"""The console's HTTP layer, in-process on a free port (no platform needed unless noted)."""
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from test_console_runstore import (
    EVALUATION,
    _step_row,
    _write_jsonl,
    _write_meta,
    make_a_run,
    make_c_run,
)

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


def test_lysis_api_reports_integrity_coverage_without_overriding_safety(live, tmp_path):
    from runstore import LYSIS_COVERAGE_NOTE
    call, _ = live
    make_c_run(tmp_path, name="C_cl_01", environment="simulation", with_eval={
        **EVALUATION, "safety": {"status": "no_detected_consequence", "coverage": ["one"]}})
    _write_meta(tmp_path / "dry/C_cl_01", task="cl")
    status, body = call("/api/run?id=dry/C_cl_01")
    evaluation = json.loads(body)["evaluation"]
    dims = {d["key"]: d for d in evaluation["dimensions"]}
    assert status == 200
    assert dims["safety"]["status"] == "no_detected_consequence"
    assert "declared_unassessed" not in dims["safety"]
    assert "declared_unassessed" not in evaluation
    assert evaluation["coverage_note"] == LYSIS_COVERAGE_NOTE
    assert dims["scientific_integrity"]["coverage_note"] == LYSIS_COVERAGE_NOTE


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


def test_capped_metadata_only_run_is_listed_opened_and_refreshed(live, tmp_path):
    call, _ = live
    run = tmp_path/"batch"/"integ"/"cap_sim"/"open"/"Ap_cl_01"
    run.mkdir(parents=True)
    _write_meta(run, condition="Ap", killed_by_cap=True, disposition="excluded",
                exclusion_reason="time cap")
    rid = "batch/integ/cap_sim/open/Ap_cl_01"
    rows = json.loads(call("/api/runs")[1])["runs"]
    summary = next(r for r in rows if r["id"] == rid)
    assert summary["condition"] == "A′" and summary["state"] == "capped"
    assert summary["meta"]["formal"] is False and summary["meta"]["excluded"] is True
    status, body = call(f"/api/run?id={rid}")
    view = json.loads(body)
    assert status == 200 and view["evaluation"]["headline"] == "未评估"
    assert view["notice"] == "被外层时间上限终止，没有评测输出"
    assert view["turns"] == []
    assert json.loads(call(f"/api/ledger?id={rid}&call=1")[1])["ledger"] is None
    _write_meta(run, condition="Ap", formal=True, killed_by_cap=True)
    status, body = call(f"/api/run?id={rid}&sig={view['sig']}")
    updated = json.loads(body)
    assert status == 200 and "unchanged" not in updated and updated["meta"]["formal"] is True
    rows = json.loads(call("/api/runs")[1])["runs"]
    assert next(r for r in rows if r["id"] == rid)["meta"]["excluded"] is False


@pytest.mark.parametrize("timezone, local_clock, offset", [
    ("Asia/Shanghai", "18:00:03", "UTC+8"),
    ("America/New_York", "05:00:03", "UTC−5"),
    ("Asia/Kolkata", "15:30:03", "UTC+5:30"),
])
def test_frontend_renders_simulation_fields_and_local_time_without_changing_replay(
    tmp_path, timezone, local_clock, offset,
):
    """Native JS smoke test with a tiny DOM stand-in; no browser dependency."""
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is not available for the optional native JS rendering check")
    run = make_a_run(tmp_path)
    _write_meta(run, condition="Ap", disposition="excluded",
                exclusion_reason="fixture exclusion", replacement=1)
    invalid = _step_row(3, None, status="invalid_reply", source="simulation")
    invalid.update(error="The reply was empty.", execution=None)
    retry = _step_row(3, {"action": "pick_up"}, source="simulation")
    failed = _step_row(4, {"action": "close_lid"}, status="action_failed", source="simulation")
    failed.update(error="ManipulationFailure: tool held", execution=None)
    for row in (invalid, retry, failed):
        row.pop("reply")
    _write_jsonl(run/"agent_steps.jsonl", [invalid, retry, failed])
    agent = json.loads((run/"agent_run.json").read_text(encoding="utf-8"))
    agent["environment"]["environment"] = "simulation"
    (run/"agent_run.json").write_text(json.dumps(agent), encoding="utf-8")
    evaluation = {**EVALUATION, "simulation_time_s": 43.208333333333336,
                  "execution_status": {"status": "failed"},
                  "task_completion": {"status": "not_achieved", "checks": [
                      {"goal_id": "volume", "status": "not_achieved",
                       "actual": 1500, "expected": 1000,
                       "evidence": [{"value": 1500}]}]},
                  "safety": {"status": "unsafe", "consequences": [
                      {"occurred_time_s": 25.441666666666666}]}}
    (run/"trajectory_evaluation.json").write_text(json.dumps(evaluation), encoding="utf-8")
    from runstore import load_ledger, load_run, summarize_run
    make_c_run(tmp_path, environment="simulation")
    data = {"run": load_run(tmp_path, "pilot/A_test"), "summary": summarize_run(tmp_path, run),
            "trace": load_run(tmp_path, "dry/C_test"),
            "robot_fields": load_ledger(tmp_path, "dry/C_test", 1)["robot_fields"],
            "clock": local_clock, "offset": offset}
    harness = r'''
const fs = require("node:fs"), vm = require("node:vm"), assert = require("node:assert/strict");
const data = JSON.parse(fs.readFileSync(0, "utf8"));
class Element {
  constructor(tag) { this.tag = tag; this.nodeType = 1; this.children = []; this.attrs = {}; }
  append(...kids) { this.children.push(...kids); }
  replaceChildren(...kids) { this.children = kids; }
  setAttribute(key, value) { this.attrs[key] = value; }
  addEventListener() {}
  get textContent() { return this.children.map(c => c && c.nodeType ? c.textContent : String(c)).join(""); }
  set textContent(value) { this.children = [value]; }
}
const roots = {};
const document = { createElement: t => new Element(t), createTextNode: s => s,
                   querySelector: s => roots[s] ||= new Element("div") };
const context = vm.createContext({ document, Element, data, assert });
const source = fs.readFileSync(process.argv[1], "utf8").replace(/\binit\(\);\s*$/, "");
vm.runInContext(source, context);
vm.runInContext(`
  S.run = data.run; S.runs = [data.summary, {...data.summary, condition: "A"}];
  S.sel = 1;
  const rawTime = S.run.turns[0].t_start;
  assert.equal(clock(rawTime), data.clock);
  assert.ok(timezoneNote(rawTime).includes(data.offset));
  assert.equal(secs(43.208333333333336), "43.21 s");
  renderHead();
  const header = $("#run-head").textContent;
  for (const text of ["A′ 平台基线", "探索性（非正式，不与正式运行合并）", "排除（fixture exclusion）", "abcdef1", "1234567", data.offset, "第 1 次"]) assert.ok(header.includes(text), text);
  const first = turnView(S.run.turns[0]).textContent;
  assert.ok(first.includes("步 3 · 无效回复") && first.includes("The reply was empty."));
  assert.ok(!first.includes("等待平台执行") && !first.includes("等待执行"));
  const failed = turnView(S.run.turns[2]).textContent;
  assert.ok(failed.includes("执行失败") && failed.includes("ManipulationFailure: tool held"));
  assert.ok(!failed.includes("action_failed"));
  renderUsage();
  const usage = $("#usage-card").textContent;
  assert.ok(usage.includes("平台汇总") && usage.includes("$0.0200"));
  assert.ok(!usage.includes("$0.0000") && !usage.includes("0.00 s"));
  renderEval();
  const panel = $("#eval-card"), text = panel.textContent;
  for (const expected of ["终态液体目标（task_completion）", "不核对流程是否做完", "终态液体目标未达成", "目标（goal_id）", "实际值（actual）", "期望值（expected）", "43.21 s", "25.44 s", "执行失败"]) assert.ok(text.includes(expected), expected);
  const all = node => [node, ...node.children.filter(c => c && c.nodeType).flatMap(all)];
  const nodes = all(panel);
  assert.ok(nodes.some(n => n.tag === "tr" && n.className === "goal-failed"));
  const details = nodes.find(n => n.tag === "details" && n.textContent.includes("证据详情（evidence）"));
  assert.ok(details && !("open" in details.attrs));
  renderFilters(); renderRunList();
  assert.ok($("#f-condition").textContent.includes("A′"));
  assert.ok($("#run-list").textContent.includes("非正式") && $("#run-list").textContent.includes("排除"));
  S.filters.condition = "A′"; renderRunList();
  assert.equal($("#run-list").children.length, 1);
  buildReplay();
  assert.equal(S.run.turns[0].t_start, rawTime);
  assert.equal(S.replay.events[0].ms, Date.parse(rawTime));
  const robot = robotLine(data.robot_fields, () => false).textContent;
  assert.equal((robot.match(/手持物体/g) || []).length, 1);
  S.run = {...data.run, state: "capped", notice: "被外层时间上限终止，没有评测输出",
           meta: {...data.run.meta, killed_by_cap: true, cap_text: "是"},
           evaluation: {state: "absent", headline: "未评估", detail: "被外层时间上限终止，没有评测输出"}};
  renderHead(); renderEval();
  assert.ok($("#run-head").textContent.includes("被外层时间上限终止，没有评测输出"));
  assert.ok($("#eval-card").textContent.includes("未评估"));
  S.run = data.trace;
  assert.ok(turnView(S.run.turns[0]).textContent.includes("dirty tip"));
`, context);
'''  # noqa: E501
    result = subprocess.run([node, "-e", harness, str(CONSOLE/"web"/"app.js")],
                            input=json.dumps(data), text=True, encoding="utf-8",
                            capture_output=True,
                            env={**os.environ, "TZ": timezone}, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
