"""The event log (no platform needed)."""
import pytest

from safelab import trace


def test_rows_are_numbered_bound_to_call_and_step_and_written_as_they_happen(tmp_path):
    log = trace.TraceLog(tmp_path/"run"/trace.FILENAME)
    log.bind(call=1, step=0)
    log.emit("observed", change_count=3)
    log.bind(call=2, step=1)
    log.emit("proposed", action={"action": "finish"})
    rows = trace.read(tmp_path/"run"/trace.FILENAME)
    assert [(r["seq"], r["event"], r["call"], r["step"]) for r in rows] == [
        (0, "observed", 1, 0), (1, "proposed", 2, 1)]
    assert rows == log.events
    assert rows[0]["t"].endswith("+00:00")


def test_a_new_log_starts_the_file_empty(tmp_path):
    path = tmp_path/trace.FILENAME
    trace.TraceLog(path).emit("run_start")
    trace.TraceLog(path)
    assert trace.read(path) == []


def test_unknown_events_are_refused():
    with pytest.raises(ValueError, match="Unknown trace event"):
        trace.TraceLog().emit("thought")


def test_the_run_directory_comes_from_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv(trace.RUN_DIR_ENV, str(tmp_path))
    assert trace.TraceLog.for_run().path == tmp_path/trace.FILENAME
    monkeypatch.delenv(trace.RUN_DIR_ENV)
    assert trace.TraceLog.for_run().path is None


def _chain(*calls):
    log = trace.TraceLog()
    for number, events in enumerate(calls, 1):
        log.bind(call=number, step=number-1)
        for event, action in events:
            log.emit(event, action=action)
    return log.events


def test_chain_gaps_finds_a_returned_action_without_its_readback():
    act = {"action": "open_lid", "target": "t"}
    complete = _chain([("proposed", act), ("returned", act)],
                      [("executed", act), ("observed", None), ("returned", {"action": "finish"})])
    assert trace.chain_gaps(complete) == []
    broken = _chain([("returned", act)], [("observed", None), ("returned", act)],
                    [("executed", act), ("observed", None)])
    assert trace.chain_gaps(broken) == [{"call": 1, "step": 0, "missing": ["executed"]}]
