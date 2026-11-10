"""The console's HTTP layer, in-process on a free port (no platform needed unless noted)."""
import json
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from test_console_runstore import make_a_run, make_c_run

CONSOLE = Path(__file__).resolve().parents[1]/"console"
sys.path.insert(0, str(CONSOLE))
import server  # noqa: E402


@pytest.fixture
def live(tmp_path):
    make_c_run(tmp_path)
    make_a_run(tmp_path)
    httpd = server.make_server(tmp_path, port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"

    def call(path, body=None, headers=None):
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(base+path, data=data, headers=headers or {})
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()

    yield call, httpd
    httpd.shutdown()
    httpd.jobs.stop_all()
    httpd.server_close()


def test_the_run_list_and_a_run_come_back_as_json(live):
    call, _ = live
    status, body = call("/api/runs")
    rows = json.loads(body)["runs"]
    assert status == 200
    assert {r["id"] for r in rows} == {"dry/C_test", "pilot/A_test"}
    status, body = call("/api/run?id=dry/C_test")
    run = json.loads(body)
    assert status == 200
    assert run["turns"][0]["candidates"][0]["review"]["decision"] == "block"
    assert run["source"]["label"] == "干跑（离线推演）"


def test_an_unchanged_run_is_not_resent(live):
    call, _ = live
    run = json.loads(call("/api/run?id=dry/C_test")[1])
    status, body = call(f"/api/run?id=dry/C_test&sig={run['sig']}")
    assert (status, json.loads(body)["unchanged"]) == (200, True)


def test_ledger_step_and_bad_ids(live):
    call, _ = live
    status, body = call("/api/ledger?id=dry/C_test&call=2")
    assert status == 200
    assert json.loads(body)["ledger"]["tips"]["tip1"]["status"] == "attached"
    assert call("/api/step?id=dry/C_test&step=0")[0] == 200
    assert call("/api/step?id=dry/C_test&step=77")[0] == 404
    assert call("/api/run?id=../x")[0] == 404
    assert call("/api/run?id=dry/none")[0] == 404
    assert call("/api/ledger?id=dry/C_test")[0] == 400
    assert call("/nope")[0] == 404


def test_the_page_is_served_from_local_files_only(live):
    call, _ = live
    for path in ("/", "/app.js", "/style.css"):
        status, body = call(path)
        assert status == 200
        assert b"http://" not in body and b"https://" not in body, path


def test_the_page_is_read_only_apart_from_starting_offline_runs(live):
    call, _ = live
    json_headers = {"Content-Type": "application/json"}
    assert call("/api/run", {"x": 1}, json_headers)[0] == 404
    status, _ = call("/api/start", {"condition": "C", "task": "waste_segregation"},
                     {**json_headers, "Origin": "http://elsewhere.example"})
    assert status == 403
    assert call("/api/start", {"condition": "A", "task": "waste_segregation"},
                json_headers)[0] == 400
    assert call("/api/start", {"condition": "C", "task": "../../x"}, json_headers)[0] == 400
    assert call("/api/start", {"condition": "C"}, json_headers)[0] == 400


def _agent_file(tmp_path, backend):
    path = tmp_path/"agent.json"
    path.write_text(json.dumps({"backend": backend}), encoding="utf-8")
    return path


def test_only_offline_configs_may_be_started(tmp_path):
    offline = {"provider": "safelab", "condition": "C",
               "roles": {"actor": {"provider": "plan_replay"}}, "critic": {"mode": "rules"}}
    assert server.offline_agent_problem(_agent_file(tmp_path, offline)) is None
    paid_role = {**offline, "roles": {"actor": {"provider": "openai_compatible"}}}
    assert "not plan_replay" in server.offline_agent_problem(_agent_file(tmp_path, paid_role))
    llm_critic = {**offline, "critic": {"mode": "dual"}}
    assert "rules-only" in server.offline_agent_problem(_agent_file(tmp_path, llm_critic))
    keyed = {**offline, "roles": {"actor": {"provider": "plan_replay", "api_key_env": "K"}}}
    assert "api_key" in server.offline_agent_problem(_agent_file(tmp_path, keyed))
    assert "provider is not safelab" in server.offline_agent_problem(
        _agent_file(tmp_path, {"provider": "openai_compatible"}))
    assert server.offline_agent_problem(tmp_path/"missing.json").startswith("cannot read")


def test_the_shipped_start_configs_are_offline():
    for rel in server.START_AGENTS.values():
        assert server.offline_agent_problem(server.REPO/rel) is None, rel


def test_an_offline_run_can_be_started_and_read(bench, tmp_path, monkeypatch):
    monkeypatch.setenv(server.BENCH_ENV, str(bench))
    jobs = server.Jobs(tmp_path)
    job = jobs.start("C", "waste_segregation")
    try:
        deadline = time.time()+120
        while jobs.list()[-1]["state"] == "running" and time.time() < deadline:
            time.sleep(0.5)
        view = jobs.list()[-1]
        assert view["state"] == "done", view["log_tail"]
        from runstore import load_run
        run = load_run(tmp_path, job["run_id"])
        assert run["condition"] == "C"
        assert run["source"]["kind"] == "dry_run"
        assert run["evaluation"]["state"] == "absent"
    finally:
        jobs.stop_all()
