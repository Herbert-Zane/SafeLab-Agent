"""Batch boundaries, primary-analysis parity and the native iframe replay controller."""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path
from urllib.parse import quote

import pytest

CONSOLE = Path(__file__).resolve().parents[1] / "console"
sys.path.insert(0, str(CONSOLE))
import runstore  # noqa: E402
import server  # noqa: E402


def write_run(root, batch="batch", *, name="A_ws_01", evaluation=True, trace=True, **updates):
    meta = dict(meta_schema=1, condition="A", task="ws", group="open", mode="sim",
                formal=True, disposition="counted", index=1, name=name,
                safelab_commit="abcdef123", platform_commit="123456789",
                started="2026-11-01T00:00:00+00:00", ended="2026-11-01T00:00:10+00:00")
    meta.update(updates)
    path = root / batch / meta["group"] / name
    path.mkdir(parents=True, exist_ok=True)
    (path / runstore.META).write_text(json.dumps(meta), encoding="utf-8")
    (path / runstore.RUN).write_text(json.dumps({"outcome": "finished_by_agent",
        "task_id": "cell_lysis" if meta["task"] == "cl" else "waste_segregation",
        "environment": {"environment": "dry_run" if meta["mode"] == "dry" else "simulation"}}),
        encoding="utf-8")
    if evaluation is not False:
        value = {"safety": {"status": "unsafe", "coverage": ["one"]},
                 "scientific_integrity": {"status": "failed", "coverage": ["one"]},
                 "task_completion": {"status": "achieved"}} if evaluation is True else evaluation
        (path / runstore.EVALUATION).write_text(json.dumps(value), encoding="utf-8")
    if trace:
        events = [{"event": "reviewed", "decision": "block"},
                  {"event": "reviewed", "decision": "rewrite"},
                  {"event": "proposed", "strategy": "rewrite"}]
        (path / runstore.TRACE).write_text("\n".join(map(json.dumps, events)), encoding="utf-8")
    return path


@pytest.fixture
def matrix(tmp_path):
    write_run(tmp_path)
    write_run(tmp_path, name="A_ws_02", index=2, evaluation={
        "safety": {"status": "no_detected_consequence", "unassessed": ["unknown"]},
        "scientific_integrity": {"status": "no_detected_consequence", "coverage": []},
        "task_completion": {"status": "novel"}})
    write_run(tmp_path, name="A_ws_03", index=3, evaluation=False, trace=False)
    write_run(tmp_path, name="A_ws_04", index=4, disposition="excluded")
    write_run(tmp_path, name="C_ws_01", condition="C", trace=False)
    write_run(tmp_path, name="C_cl_01", condition="C", task="cl", evaluation={
        "safety": {"status": "unrecognized", "coverage": ["one"]},
        "scientific_integrity": {"status": "no_detected_consequence", "coverage": ["one"]},
        "task_completion": {"status": "failed", "unassessed": ["ignored"], "coverage": []}})
    write_run(tmp_path, name="Ap_ws_explore", condition="Ap", formal=False,
              safelab_commit="changed123", outcome="cap", ended="2026-11-02T00:00:00+00:00")
    write_run(tmp_path, name="B_ws_dry", condition="B", mode="dry", formal=False)
    write_run(tmp_path, name="C_ws_dry", condition="C", mode="dry", formal=True)
    write_run(tmp_path, "other", name="B_cl_01", condition="B", task="cl", group="proc")
    return tmp_path


def test_batch_cohort_counts_ids_and_per_run_projection(matrix):
    data = runstore.result_tables(matrix)
    tables = {(t["batch"], t["cohort"]): t for t in data["tables"]}
    assert data["skipped"] == 0
    assert set(tables) == {("batch", "formal"), ("batch", "exploratory"),
                           ("batch", "dry"), ("other", "formal")}
    table = tables["batch", "formal"]
    assert table["runs"] == 6
    # The batch warning also covers different versions in its other cohorts.
    assert len(table["warnings"]) == 1
    assert [(r["group"], r["task"], r["condition"]) for r in table["rows"]] == [
        ("open", "ws", "A"), ("open", "ws", "C"), ("open", "cl", "C")]
    row = table["rows"][0]
    assert [row[k] for k in ("runs", "counted", "excluded", "n", "missing_evaluation")] == [
        4, 3, 1, 2, 1]
    for metric in runstore.METRICS:
        value = row["metrics"][metric]
        assert [value[k] for k in ("events", "n", "unassessed_n")] == [1, 2, 1]
        assert value["event_ids"] == ["batch/open/A_ws_01"]
        assert value["unassessed_ids"] == ["batch/open/A_ws_02"]
    assert row["n_ids"] == ["batch/open/A_ws_01", "batch/open/A_ws_02"]
    assert row["missing_ids"] == ["batch/open/A_ws_03"]
    assert row["excluded_ids"] == ["batch/open/A_ws_04"]
    assert row["run_ids"] == [f"batch/open/A_ws_0{i}" for i in range(1, 5)]
    first = row["run_details"][0]
    assert (first["blocks"], first["rewrites"]) == (1, 2)
    assert first["outcome"] == "finished_by_agent"
    assert row["run_details"][2]["blocks"] is None
    assert table["rows"][-1]["metrics"]["safety"]["declared_unassessed"] == (
        runstore.DECLARED_UNASSESSED)
    assert table["rows"][-1]["metrics"]["task_completion"]["unassessed_n"] == 0
    assert all(r["metrics"] is None and r["n"] == 0 for r in tables["batch", "dry"]["rows"])
    assert tables["other", "formal"]["runs"] == 1


@pytest.mark.parametrize("field,value", [
    ("meta_schema", 2), ("condition", "D"), ("task", "other"), ("group", "other"),
    ("mode", "real"), ("formal", 1), ("disposition", "unknown"),
])
def test_invalid_metadata_is_skipped(tmp_path, field, value):
    write_run(tmp_path, **{field: value})
    assert runstore.result_tables(tmp_path)["skipped"] == 1
    assert runstore.result_tables(tmp_path)["tables"] == []


def test_missing_malformed_metadata_and_shallow_batch(tmp_path):
    path = write_run(tmp_path)
    (path / runstore.META).unlink()
    other = write_run(tmp_path, name="C_bad")
    (other / runstore.META).write_text("{", encoding="utf-8")
    assert runstore.result_tables(tmp_path)["skipped"] == 2
    (other / runstore.META).write_text("[]", encoding="utf-8")
    assert runstore.result_tables(tmp_path)["skipped"] == 2
    # Root itself is a valid batch id, including legacy one-level layouts.
    assert runstore.batch_id(tmp_path, tmp_path / "open" / "A_ws_01") == "."
    assert runstore.batch_id(tmp_path, tmp_path / "A_ws_01") == "."
    root_run = write_run(tmp_path, batch=".", name="B_ws_01", condition="B")
    assert runstore.result_tables(tmp_path)["tables"][0]["batch"] == "."
    assert root_run.parent.parent == tmp_path


def test_table_header_and_single_run_declared_coverage(matrix):
    write_run(matrix, name="B_ws_01", condition="B", safelab_commit="newhash123",
              started="2026-10-31T23:00:00+00:00", ended="2026-11-03T00:00:00+00:00")
    table = runstore.result_tables(matrix)["tables"][0]
    assert table["safelab_commit"] == ["abcdef1", "newhash"]
    assert table["platform_commit"] == ["1234567"]
    assert len(table["warnings"]) == 1
    assert table["started"] == "2026-10-31T23:00:00+00:00"
    assert table["ended"] == "2026-11-03T00:00:00+00:00"
    assert table["outcomes"] == {"finished_by_agent": 7}
    run = runstore.load_run(matrix, "batch/open/C_cl_01")
    safety = next(d for d in run["evaluation"]["dimensions"] if d["key"] == "safety")
    assert safety["declared_unassessed"] == runstore.DECLARED_UNASSESSED
    # Also show the advisory when metadata is the only task identification.
    path = matrix / "batch/open/C_cl_01"
    (path / runstore.RUN).unlink()
    (path / runstore.STEPS).write_text(json.dumps({"observation": {"source": "simulation"}}),
                                      encoding="utf-8")
    assert runstore.load_run(matrix, "batch/open/C_cl_01")["evaluation"][
        "declared_unassessed"] == runstore.DECLARED_UNASSESSED


def test_tables_match_analyze_primary_analysis_cell_by_cell(matrix):
    spec = importlib.util.spec_from_file_location("console_analysis_reference",
        CONSOLE.parent / "experiments/analyze.py")
    analyze = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(analyze)
    runs, _, _ = analyze.load_runs(matrix)
    for table in runstore.result_tables(matrix)["tables"]:
        cohort = "nonformal" if table["cohort"] == "exploratory" else table["cohort"]
        selected = [r for r in runs if r["cohort"] == cohort
                    and runstore.batch_id(matrix, matrix / r["directory"]) == table["batch"]]
        expected = analyze.result_tables(selected)
        assert len(expected) == len(table["rows"])
        for actual, reference in zip(table["rows"], expected, strict=True):
            for key in ("group", "task", "condition", "runs", "counted", "excluded", "n"):
                assert actual[key] == reference[key], (table["batch"], cohort, key)
            if cohort == "dry":
                assert actual["metrics"] is reference["metrics"] is None
                continue
            for metric in runstore.METRICS:
                for key in ("events", "n", "unassessed_n"):
                    assert actual["metrics"][metric][key] == reference["metrics"][metric][key]


@pytest.fixture
def api(matrix):
    httpd = server.make_server(matrix, port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    def call(path):
        with urllib.request.urlopen(f"http://127.0.0.1:{httpd.server_port}{path}") as response:
            return json.load(response)

    yield call
    httpd.shutdown()
    httpd.server_close()


def test_tables_api_cache_invalidates_edits_additions_and_removals(api, matrix, monkeypatch):
    build, builds = runstore.result_tables, []

    def counted_build(root):
        builds.append(root)
        return build(root)

    monkeypatch.setattr(runstore, "result_tables", counted_build)
    first = api("/api/tables")
    assert set(first) == {"tables", "skipped", "root"}
    assert api("/api/tables") == first and len(builds) == 1
    path = matrix / "batch/open/A_ws_01/trajectory_evaluation.json"
    path.write_text("{}", encoding="utf-8")
    assert api("/api/tables") != first and len(builds) == 2
    new = write_run(matrix, name="B_ws_new", condition="B")
    api("/api/tables")
    assert len(builds) == 3
    (new / runstore.META).unlink()
    api("/api/tables")
    assert len(builds) == 4
    # Query strings cannot select an arbitrary filesystem root.
    assert api("/api/tables?id=" + quote("../../private")) == api("/api/tables")


def test_table_reads_are_allowlisted_and_run_ids_are_resolved(matrix, monkeypatch):
    original_read, original_resolve = Path.read_text, runstore.resolve_run
    resolved = set()

    def read(path, *args, **kwargs):
        if path.is_relative_to(matrix):
            assert path.name in runstore.RUN_FILES + runstore.BATCH_MARKERS
        return original_read(path, *args, **kwargs)

    def resolve(root, rid):
        resolved.add(rid)
        return original_resolve(root, rid)

    monkeypatch.setattr(Path, "read_text", read)
    monkeypatch.setattr(runstore, "resolve_run", resolve)
    data = runstore.result_tables(matrix)
    assert {rid for t in data["tables"] for r in t["rows"] for rid in r["run_ids"]} <= resolved
    for invalid in ("../private", "/private", "batch/../../private"):
        with pytest.raises(runstore.RunError):
            runstore.resolve_run(matrix, invalid)


def test_symlinks_outside_root_are_not_discovered(tmp_path):
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    write_run(outside)
    try:
        (root / "escape").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Directory symlinks are unavailable")
    assert runstore.find_run_dirs(root) == []
    assert runstore.result_tables(root)["tables"] == []


def test_real_formal_and_aside_counts():
    root = CONSOLE.parent / "runs/formal_s52d09cf_full"
    if not root.is_dir():
        pytest.skip("Formal run artifacts are unavailable")
    tables = {(t["batch"], t["cohort"]): t for t in runstore.result_tables(root)["tables"]}
    formal = tables["formal", "formal"]
    assert formal["runs"] == 110 and len(formal["rows"]) == 14
    expected = {
        ("open", "ws"): [(10, 10, 0), (0, 4, 0), (10, 10, 0), (0, 0, 0)],
        ("open", "cl"): [(0, 0, 9), (0, 0, 10), (0, 0, 6), (0, 0, 6)],
        ("proc", "ws"): [(0, 0, 5)] * 3,
        ("proc", "cl"): [(0, 0, 4), (0, 1, 4), (0, 0, 5)],
    }
    for (group, task), values in expected.items():
        rows = [r for r in formal["rows"] if r["group"] == group and r["task"] == task]
        for row, events in zip(rows, values, strict=True):
            n = 10 if group == "open" else 5
            assert row["runs"] == row["n"] == n and row["missing_evaluation"] == 0
            assert tuple(row["metrics"][m]["events"] for m in runstore.METRICS) == events
            assert all(row["metrics"][m]["n"] == n for m in runstore.METRICS)
    # The 90 runs set aside under preregistration amendment 5 carry formal/counted
    # metadata and evaluator files for empty trajectories; MOVED.txt in their batch
    # directory keeps them out of the formal cohort and out of any count.
    assert ("formal_402_aside", "formal") not in tables
    aside = tables["formal_402_aside", "aside"]
    assert aside["runs"] == 90 and aside["aside"].startswith("MOVED.txt：402")
    assert all(r["metrics"] is None for r in aside["rows"])
    assert sum(r["runs"] for r in aside["rows"]) == 90
    assert aside["outcomes"] == {"backend_error": 90}


def test_marked_batch_is_set_aside_not_formal(api, tmp_path, matrix):
    write_run(matrix, "kept", name="A_ws_01", outcome="backend_error")
    path = write_run(matrix, "moved", name="A_ws_01", outcome="backend_error")
    first = api("/api/tables")
    assert {t["cohort"] for t in first["tables"] if t["batch"] == "moved"} == {"formal"}
    kept = next(t for t in first["tables"] if t["batch"] == "kept")
    assert kept["aside"] is None and any("backend_error" in w for w in kept["warnings"])
    assert runstore.summarize_run(matrix, path)["meta"]["aside"] is None

    (matrix / "moved/SUPERSEDED.txt").write_text(
        "\n".join(["", "旧备份，已被取代", "第二行"]), encoding="utf-8")
    second = api("/api/tables")  # the marker alone must invalidate the cached tables
    moved = [t for t in second["tables"] if t["batch"] == "moved"]
    assert [t["cohort"] for t in moved] == ["aside"]
    assert moved[0]["aside"] == "SUPERSEDED.txt：旧备份，已被取代" and moved[0]["warnings"] == []
    assert all(r["metrics"] is None and r["run_ids"] for r in moved[0]["rows"])
    for view in (runstore.summarize_run(matrix, path),
                 runstore.load_run(matrix, runstore.run_id(matrix, path))):
        assert view["meta"]["aside"] == moved[0]["aside"]
        assert view["meta"]["formal"] is True and "已搁置" in view["meta"]["formal_text"]
    # Other batches are untouched, and an empty marker still sets the batch aside.
    assert next(t for t in second["tables"] if t["batch"] == "kept")["cohort"] == "formal"
    (matrix / "moved/SUPERSEDED.txt").write_text("", encoding="utf-8")
    assert runstore.aside_note(matrix, path) == "SUPERSEDED.txt"


def test_native_tables_and_replay_controller(matrix):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is unavailable")
    harness = r'''
const fs = require("node:fs"), vm = require("node:vm"), assert = require("node:assert/strict");
const data = JSON.parse(fs.readFileSync(0, "utf8"));
class Element {
  constructor(tag) { this.tag = tag; this.nodeType = 1; this.children = []; this.attrs = {}; this.listeners = {}; this.classList = {add(){}, toggle(){}}; }
  append(...kids) { this.children.push(...kids); }
  replaceChildren(...kids) { this.children = kids; }
  setAttribute(key, value) { this.attrs[key] = value; }
  addEventListener(key, value) { this.listeners[key] = value; }
  get textContent() { return this.children.map(c => c?.nodeType ? c.textContent : String(c)).join(""); }
  set textContent(value) { this.children = [value]; }
}
const roots = {};
const document = {createElement: t => new Element(t), createTextNode: s => s,
  body: new Element("body"), querySelector: s => roots[s] ||= new Element("div")};
const history = {pushState(_state, _unused, url) { this.url = url; }};
const context = vm.createContext({document, Element, data, assert, history, URLSearchParams,
  location: {search: ""}, setTimeout, clearTimeout, clearInterval, performance, window: {}});
vm.runInContext(fs.readFileSync(process.argv[1], "utf8").replace(/\binit\(\);\s*$/, ""), context);
vm.runInContext(`
const all = node => [node, ...node.children.filter(c => c?.nodeType).flatMap(all)];
S.tables = data; S.view = "tables"; renderTables();
const panel = $("#tables-view"), text = panel.textContent;
for (const word of ["正式运行", "探索性（非正式）", "干跑", "未预注册", "不与正式运行合并报告", "不等于安全", "未经确认", "干跑不给评测结论（未评估）"]) assert.ok(text.includes(word), word);
for (const cls of ["b-formal", "b-exploratory", "b-dry"]) assert.ok(all(panel).some(n => n.className?.includes(cls)));
assert.ok(all(panel).some(n => n.tag === "button" && n.textContent === "0"));
const table = data.tables.find(t => t.batch === "batch" && t.cohort === "formal");
const row = table.rows[0];
const cell = tableMetric(table, table.rows.find(r => r.task === "cl"), "safety");
assert.ok(cell.textContent.startsWith("未评估") && cell.textContent.includes("检出 0/1"));
const button = tableMetric(table, row, "safety").children[0];
button.listeners.click();
assert.ok(history.url.startsWith("/?view=tables&batch=batch&sel="));
assert.deepEqual(JSON.parse(new URLSearchParams(history.url.split("?")[1]).get("sel")), JSON.parse(JSON.stringify(S.tableSelection)));
const drill = drillPanel(table);
assert.ok(drill.textContent.includes("危险后果：1 / 2") && drill.textContent.includes("A_ws_02"));
assert.ok(!drill.textContent.includes("A_ws_03"));
const links = all(drill).filter(n => n.tag === "a");
const peer = links.find(n => n.textContent.includes("并排 C"));
assert.ok(peer && peer.attrs.href.startsWith("/?left=batch%2Fopen%2FA_ws_01&right=batch%2Fopen%2FC_ws_01"));
assert.ok(links.find(n => n.textContent === "打开").attrs.href.includes("&sel="));
assert.equal(tableReturnLink().attrs.href, history.url);
assert.ok(all(drill).some(n => n.tag === "tr" && n.className === "goal-failed"));
selectTableCell(table, row, "missing"); assert.ok(drillPanel(table).textContent.includes("A_ws_03"));
selectTableCell(table, row, "excluded"); assert.ok(drillPanel(table).textContent.includes("A_ws_04"));
selectTableCell(table, row, "unassessed:safety"); assert.ok(drillPanel(table).textContent.includes("A_ws_02"));
assert.equal(shortStatus({...row.run_details[0], safety_status: "no_detected_consequence"}, "safety", "ws"), "未检出");
assert.equal(shortStatus(row.run_details[0], "safety", "cl"), "未评估");

assert.deepEqual(Array.from(replayOffsets([{ms: 1000}, {ms: 1500}, {ms: 10000}, {ms: 10100}], false)), [0, 500, 9000, 9100]);
assert.deepEqual(Array.from(replayOffsets([{ms: 1000}, {ms: 1500}, {ms: 10000}, {ms: 10100}], true)), [0, 500, 2500, 2600]);
assert.equal(eventIndexAt([0, 500, 500, 1000], 500), 2);
assert.equal(eventIndexAt([0, 500], -1), -1);
assert.deepEqual(Array.from(mergedOffsets([[0, 10], [0, 5, 20]])), [0, 5, 10, 20]);
assert.equal(adjacentOffset([0, 5, 10], 5, 1), 10);
assert.equal(adjacentOffset([0, 5, 10], 5, -1), 0);
const turn = (seqs) => ({candidates: [], returned: {seq: seqs[0]}, readback: {seq: seqs[1]}, notes: [], stage_events: [], usage: []});
const ends = turnEndIndices([turn([1, 3]), turn([4, 7])], [0, 1, 2, 3, 4, 7, 8].map(seq => ({seq})));
assert.deepEqual(Array.from(ends), [3, 6]);
assert.equal(stepEventIndex(ends, 0, 7), -1);
assert.equal(stepEventIndex(ends, 1, 7), 3);
assert.equal(stepEventIndex(ends, 99, 7), 6);
const info = {source: {kind: "simulation"}, meta: {task: "ws", group: "open", formal: true, mode: "sim"}, batch: "one"};
assert.equal(comparisonWarnings([info, info]).length, 0);
const mismatch = comparisonWarnings([info, {...info, batch: "two", meta: {...info.meta, formal: false, task: "cl", group: "proc"}}]).join("");
for (const word of ["任务", "brief 组", "批次", "性质：正式运行 / 探索性（非正式）", "只供查看，不能当作同批对照"]) assert.ok(mismatch.includes(word));
assert.ok(comparisonWarnings([{...info, source: {kind: "dry_run"}}]).join("").includes("不是仿真结果"));
const sought = [];
const verdict = () => [{label: "安全", text: "检出危险后果", tone: "bad"}];
C.sides = [{api: {seekEvent: i => sought.push(i), verdict}, offsets: [0, 500], ends: [1], ended: new Element("span"), verdict: new Element("div")}, {api: null}];
C.position = 500; C.align = "time"; applyCompare();
assert.equal(sought[0], 1); assert.equal(C.sides[0].ended.textContent, "已到结尾");
// The verdict is shown beside a side only once that side has reached its end.
assert.ok(C.sides[0].verdict.textContent.includes("已完成 1 / 1 步") && C.sides[0].verdict.textContent.includes("安全：检出危险后果"));
C.position = 0; C.align = "step"; applyCompare(); assert.equal(sought[1], -1);
assert.ok(C.sides[0].verdict.textContent.includes("已完成 0 / 1 步") && !C.sides[0].verdict.textContent.includes("检出危险后果"));
assert.ok(C.sides[0].verdict.textContent.includes("到结尾后显示"));
const dims = [{key: "task_completion", label: "终态液体目标（task_completion）", status: "not_achieved", status_text: "终态液体目标未达成", tone: "bad"},
  {key: "safety", label: "安全", status: "no_detected_consequence", status_text: "未检出后果（仅限已声明覆盖范围，不等于安全）", tone: "neutral"}];
const simRun = {source: {kind: "simulation"}, meta: {}, evaluation: {state: "present", dimensions: dims}};
assert.deepEqual(embedVerdict(simRun).map(v => v.label + "：" + v.text), ["终态液体目标：未达成", "安全：未检出后果"]);
assert.ok(embedVerdict(simRun)[1].title.includes("不等于安全"));
assert.equal(embedVerdict({...simRun, evaluation: {state: "present", dimensions: [{...dims[1], status: "unsafe", status_text: "不安全", tone: "bad"}]}})[0].text, "检出危险后果");
assert.equal(embedVerdict({...simRun, meta: {aside: "MOVED.txt"}})[0].text, "未评估（已搁置的运行，不是结果）");
assert.equal(C.align, "step");  // default: step k beside step k
assert.equal(embedVerdict({...simRun, evaluation: {state: "present", dimensions: [{...dims[1], declared_unassessed: "未经确认"}]}})[0].text, "未评估");
assert.equal(embedVerdict({...simRun, evaluation: {state: "absent"}})[0].text, "未评估（没有评测输出）");
assert.equal(embedVerdict({...simRun, source: {kind: "dry_run"}})[0].text, "未评估（不是仿真结果）");
// The baseline is on the left whichever row the link was opened from.
assert.ok(orderedCompareURL({id: "x/C_ws_03", condition: "C"}, {id: "x/A_ws_03", condition: "A"}).startsWith("/?left=x%2FA_ws_03&right=x%2FC_ws_03"));
assert.ok(orderedCompareURL({id: "x/A_ws_03", condition: "A"}, {id: "x/C_ws_03", condition: "C"}).startsWith("/?left=x%2FA_ws_03&right=x%2FC_ws_03"));
// Set-aside batches: their own label, no counts, no per-run verdicts.
assert.equal(formalCohort({aside: "MOVED.txt：402", formal: true}), "aside");
assert.equal(cohortBadge("aside").textContent, "已搁置（不是结果）");
assert.equal(tableMetric({cohort: "aside", batch: "b"}, {metrics: null}, "safety").textContent, "已搁置，不计数（未评估）");
assert.equal(shortStatus({...row.run_details[0], safety_status: "unsafe"}, "safety", "ws", "aside"), "未评估");
S.tables = {skipped: 0, tables: [{batch: "old", cohort: "aside", aside: "MOVED.txt：402", runs: 1, warnings: [], outcomes: {backend_error: 1}, rows: [{group: "open", task: "ws", condition: "A", n: 0, missing_evaluation: 0, excluded: 0, metrics: null, run_ids: [], run_details: []}]}]};
renderTables();
for (const word of ["已搁置的运行，不是结果", "MOVED.txt：402", "不与正式运行合并"]) assert.ok($("#tables-view").textContent.includes(word), word);
assert.ok(!$("#tables-view").textContent.includes("规则同 experiments/analyze.py"));
S.tables = data;
// One failed side must not disable the other side's shared controls.
S.view = "compare"; showCompare("missing/run", "working/run");
const failed = C.sides[0], working = C.sides[1];
failed.iframe.contentWindow = {SafeLabEmbed: {error: "no such run"}};
failed.iframe.listeners.load();
assert.equal(failed.iframe.hidden, true);
working.iframe.contentWindow = {SafeLabEmbed: {ready: true, info: () => ({...info, name: "working", condition: "C"}), offsets: () => [0, 500], turnEnds: () => [1], seekEvent: i => sought.push(i), verdict}};
working.iframe.listeners.load();
C.position = 500; C.align = "time"; applyCompare();
assert.equal(sought.at(-1), 1); assert.equal(working.ended.textContent, "已到结尾");
assert.ok($("#top-note").textContent.includes("右侧原始来源"));
const range = all($("#compare-controls")).find(n => n.attrs.id === "compare-progress");
const controls = $("#compare-controls").children[0];
range.listeners.input({target: {value: "0"}});
assert.equal($("#compare-controls").children[0], controls);
assert.equal(C.position, 0);
renderTop(); assert.ok($("#top-source").textContent.includes("数据来源：录像回放（并排）"));
`, context);
'''  # noqa: E501
    result = subprocess.run([node, "-e", harness, str(CONSOLE / "web/app.js")],
        input=json.dumps(runstore.result_tables(matrix)), encoding="utf-8", text=True,
        capture_output=True, timeout=20, env=os.environ.copy())
    assert result.returncode == 0, result.stdout + result.stderr
