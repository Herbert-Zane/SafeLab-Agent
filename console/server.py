r"""SafeLab console server: a read-only view of run directories, standard library only.

    .venv\Scripts\python.exe console\server.py --runs runs

Opens http://127.0.0.1:8765/ . Works offline: the page is plain HTML, CSS and
JS from ``console/web`` and loads nothing from the network.

The server only reads run directories. The one thing it can start is an offline
dry run through ``scripts/run_dry.py`` with one of the agent configs in
``START_AGENTS``; before starting it checks that the config has no model
provider, endpoint or API key, so a click can never spend money.
"""
from __future__ import annotations

import argparse
import atexit
import json
import os
import subprocess
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
WEB = HERE/"web"
sys.path.insert(0, str(HERE))

import runstore  # noqa: E402

#: Offline configs the page may start, by condition. Nothing that calls a model.
START_AGENTS = {"B": "configs/agents/safelab_B.json", "C": "configs/agents/safelab_C.json"}
#: Tasks the page offers (their config file must exist under the platform root).
START_TASKS = ("waste_segregation", "cell_lysis")
BENCH_ENV = "SAFELAB_BENCH_ROOT"
BENCH_DEFAULT = r"D:\科学具身仿真\Benchmark\bench"
STATIC = {"/": ("index.html", "text/html; charset=utf-8"),
          "/app.js": ("app.js", "text/javascript; charset=utf-8"),
          "/style.css": ("style.css", "text/css; charset=utf-8")}
MAX_BODY = 4096
LIVE_SECONDS = 120


# --------------------------------------------------------------------------- offline start

def bench_root():
    return Path(os.environ.get(BENCH_ENV) or BENCH_DEFAULT)


def offline_agent_problem(path):
    """Why a SafeLab agent config may not be started from the page, or None.

    Allowed: every role is ``plan_replay``, the critic (if any) is rules-only,
    and the file names no endpoint or API key.
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
        config = json.loads(text)
    except (OSError, ValueError) as error:
        return f"cannot read {Path(path).name}: {error}"
    backend = config.get("backend") or {}
    if backend.get("provider") != "safelab":
        return "provider is not safelab"
    for marker in ("api_key", "base_url", "api_base"):
        if marker in text:
            return f"config mentions {marker}"
    roles = backend.get("roles") or {}
    if not roles:
        return "no roles declared"
    for name, role in roles.items():
        if (role or {}).get("provider") != "plan_replay":
            return f"role {name} is not plan_replay"
    if (backend.get("critic") or {}).get("mode", "rules") != "rules":
        return "critic is not rules-only"
    return None


def start_options():
    root = bench_root()
    agents = []
    for condition, rel in START_AGENTS.items():
        problem = offline_agent_problem(REPO/rel)
        agents.append({"condition": condition, "config": rel, "ok": problem is None,
                       "problem": problem})
    tasks = [{"name": name, "ok": (root/"configs"/"tasks"/f"{name}.json").is_file()}
             for name in START_TASKS]
    return {"agents": agents, "tasks": tasks, "bench_root_exists": root.is_dir(),
            "note": "只开放不调用模型的离线配置；产物写入 runs/dry/。"}


class Jobs:
    """Subprocesses started from the page. Killed when the server exits."""

    def __init__(self, runs_root):
        self.runs_root = Path(runs_root)
        self.items = {}
        self.lock = threading.Lock()
        atexit.register(self.stop_all)

    def start(self, condition, task):
        if condition not in START_AGENTS:
            raise ValueError("condition is not startable")
        if task not in START_TASKS:
            raise ValueError("task is not startable")
        agent = REPO/START_AGENTS[condition]
        problem = offline_agent_problem(agent)
        if problem:
            raise ValueError(f"refused: {problem}")
        if not (bench_root()/"configs"/"tasks"/f"{task}.json").is_file():
            raise ValueError(f"platform task config not found under {bench_root()}")
        stamp = time.strftime("%Y%m%d-%H%M%S")
        name = f"{condition}_{task}_console_{stamp}"
        out_dir = self.runs_root/"dry"/name
        log = self.runs_root/"dry"/f"{name}.log"
        out_dir.parent.mkdir(parents=True, exist_ok=True)
        command = [sys.executable, str(REPO/"scripts"/"run_dry.py"), "--condition", condition,
                   "--agent", str(agent), "--config", f"configs/tasks/{task}.json",
                   "--output", str(out_dir)]
        with log.open("wb") as stream:
            process = subprocess.Popen(command, cwd=str(REPO), stdout=stream,
                                       stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
        job = {"id": name, "pid": process.pid, "condition": condition, "task": task,
               "started": stamp, "log": log, "process": process,
               "run_id": f"dry/{name}"}
        with self.lock:
            self.items[name] = job
        return self.view(job)

    @staticmethod
    def view(job):
        code = job["process"].poll()
        try:
            tail = job["log"].read_text(encoding="utf-8", errors="replace").splitlines()[-12:]
        except OSError:
            tail = []
        return {"id": job["id"], "condition": job["condition"], "task": job["task"],
                "started": job["started"], "run_id": job["run_id"],
                "state": "running" if code is None else ("done" if code == 0 else "failed"),
                "exit_code": code, "log_tail": tail}

    def list(self):
        with self.lock:
            return [self.view(job) for job in self.items.values()]

    def stop_all(self):
        with self.lock:
            for job in self.items.values():
                if job["process"].poll() is None:
                    job["process"].terminate()


# --------------------------------------------------------------------------- http

class Cache:
    """Parsed runs and list rows, keyed by file signature; keeps the last few."""

    def __init__(self, size=12):
        self.size, self.items, self.lock = size, {}, threading.Lock()

    def get(self, key, build):
        with self.lock:
            if key in self.items:
                return self.items[key]
        value = build()
        with self.lock:
            self.items[key] = value
            while len(self.items) > self.size*8:
                self.items.pop(next(iter(self.items)))
        return value


def make_handler(runs_root, jobs):
    cache = Cache()

    class Handler(BaseHTTPRequestHandler):
        server_version = "SafeLabConsole"

        def log_message(self, fmt, *args):  # keep the terminal quiet
            return

        # ---- plumbing
        def _send(self, status, body, content_type):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, payload, status=HTTPStatus.OK):
            body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
            self._send(status, body, "application/json; charset=utf-8")

        def _error(self, status, message):
            self._json({"error": message}, status)

        # ---- GET
        def do_GET(self):  # noqa: N802
            url = urlparse(self.path)
            query = {k: v[0] for k, v in parse_qs(url.query).items()}
            if url.path in STATIC:
                name, content_type = STATIC[url.path]
                try:
                    return self._send(HTTPStatus.OK, (WEB/name).read_bytes(), content_type)
                except OSError:
                    return self._error(HTTPStatus.NOT_FOUND, f"missing web file {name}")
            routes = {"/api/health": self._health, "/api/runs": self._runs, "/api/run": self._run,
                      "/api/ledger": self._ledger, "/api/step": self._step,
                      "/api/options": self._options, "/api/jobs": self._jobs}
            handler = routes.get(url.path)
            if handler is None:
                return self._error(HTTPStatus.NOT_FOUND, "not found")
            try:
                return handler(query)
            except runstore.RunError as error:
                return self._error(HTTPStatus.NOT_FOUND, str(error))
            except (ValueError, KeyError) as error:
                return self._error(HTTPStatus.BAD_REQUEST, str(error))

        def _health(self, query):
            self._json({"ok": True, "runs": str(runs_root), "time": time.time(),
                        "bench_root_exists": bench_root().is_dir()})

        def _runs(self, query):
            rows = []
            for run_dir in runstore.find_run_dirs(runs_root):
                key = ("summary", str(run_dir), runstore.signature(run_dir),
                       int(time.time()//30))
                rows.append(cache.get(key, lambda d=run_dir: runstore.summarize_run(runs_root, d)))
            rows.sort(key=lambda r: r["mtime"], reverse=True)
            self._json({"runs": rows, "root": str(runs_root)})

        def _run(self, query):
            rid = query.get("id", "")
            run_dir = runstore.resolve_run(runs_root, rid)
            sig = runstore.signature(run_dir)
            if query.get("sig") == sig:
                return self._json({"unchanged": True, "sig": sig})
            key = ("run", rid, sig, int(time.time()//LIVE_SECONDS))
            self._json(cache.get(key, lambda: runstore.load_run(runs_root, rid)))

        def _ledger(self, query):
            self._json(runstore.load_ledger(runs_root, query.get("id", ""), int(query["call"])))

        def _step(self, query):
            detail = runstore.load_step_detail(runs_root, query.get("id", ""), int(query["step"]))
            if detail is None:
                return self._error(HTTPStatus.NOT_FOUND, "no such step")
            self._json(detail)

        def _options(self, query):
            self._json(start_options())

        def _jobs(self, query):
            self._json({"jobs": jobs.list()})

        # ---- POST
        def do_POST(self):  # noqa: N802
            url = urlparse(self.path)
            if url.path != "/api/start":
                return self._error(HTTPStatus.NOT_FOUND, "not found")
            origin = self.headers.get("Origin")
            if origin and urlparse(origin).netloc != self.headers.get("Host"):
                return self._error(HTTPStatus.FORBIDDEN, "cross-origin request refused")
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if not 0 < length <= MAX_BODY:
                    raise ValueError("bad body size")
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                job = jobs.start(str(body.get("condition")), str(body.get("task")))
            except (ValueError, OSError) as error:
                return self._error(HTTPStatus.BAD_REQUEST, str(error))
            self._json(job, HTTPStatus.ACCEPTED)

    return Handler


def make_server(runs_root, host="127.0.0.1", port=8765):
    runs_root = Path(runs_root).resolve()
    jobs = Jobs(runs_root)
    server = ThreadingHTTPServer((host, port), make_handler(runs_root, jobs))
    server.daemon_threads = True
    server.jobs = jobs
    return server


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--runs", type=Path, default=REPO/"runs",
                        help="Folder holding run directories")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    if not args.runs.is_dir():
        parser.error(f"runs folder not found: {args.runs}")
    server = make_server(args.runs, args.host, args.port)
    print(f"SafeLab console: http://{args.host}:{server.server_address[1]}/"
          f"  (runs: {args.runs.resolve()})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.jobs.stop_all()
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
