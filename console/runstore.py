"""Read-only data layer of the console: run directories in, plain JSON-able dicts out.

Nothing here writes to a run directory, imports the platform, or opens a file
other than the ones named in ``RUN_FILES``. A run directory holds:

* the platform's artifacts: ``agent_run.json``, ``agent_steps.jsonl`` (one row
  per model call), ``agent_plan.json``, ``agent_conversation.json``,
  ``agent_system_prompt.txt``; a simulator run adds ``trajectory_evaluation.json``;
* SafeLab's own event log, ``safelab_trace.jsonl`` (conditions B and C only).

Vocabulary used below:

* a *turn* is one platform call: the candidate actions the actor proposed, the
  reviewer's verdict on each, the action finally returned, then (read from the
  next call's rows) what the platform reported and how the readback changed
  the ledger;
* ``seq`` orders the pieces of a run for replay. For SafeLab runs it is the
  trace's own ``seq``; for runs without a trace it is synthesised from the
  platform's rows.

Source labels never claim a safety result. A dry run is bookkeeping; an
evaluator dimension nobody assessed stays "not assessed".
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime
from pathlib import Path

RUN_FILES = ("agent_run.json", "agent_steps.jsonl", "agent_plan.json", "agent_conversation.json",
             "agent_system_prompt.txt", "trajectory_evaluation.json", "safelab_trace.jsonl",
             "actions.jsonl", "run_meta.json")
TRACE = "safelab_trace.jsonl"
#: The simulator's own action log (start and end time of every step), when the run has one.
ACTIONS = "actions.jsonl"
STEPS = "agent_steps.jsonl"
RUN = "agent_run.json"
EVALUATION = "trajectory_evaluation.json"
META = "run_meta.json"
MAX_DEPTH = 5
TEXT_LIMIT = 4000
DECLARED_UNASSESSED = (
    '评测器能否检出“用过的枪头回到试剂瓶”未经确认，裂解任务的安全维度按未评估处理'
)
# Batch-level markers: a batch directory holding one of these is not a result set
# (runs set aside as unexecuted, or a copy superseded by a later one).
BATCH_MARKERS = ("MOVED.txt", "SUPERSEDED.txt")
METRICS = {"safety": "unsafe", "scientific_integrity": "failed", "task_completion": "achieved"}

SOURCE_LABELS = {
    "simulation": "仿真",
    "dry_run": "干跑（离线推演）",
    "unknown": "来源未知",
}
CONDITION_LABELS = {
    "A": "A 平台基线（无审查器）",
    "A′": "A′ 平台基线 + 带安全提示的 brief（无审查器）",
    "B": "B 规划+账本+反思（无审查器）",
    "C": "C 完整版（含安全审查器）",
    "script": "脚本回放（无模型）",
    "?": "条件未知",
}
#: Notes attached to the turn they happened in.
NOTE_EVENTS = ("reflect", "replan", "refusal_limit", "disagreement", "empty_reply", "call_error",
               "retry", "fault", "budget_stop")
#: Evaluator statuses: label shown, and a tone for the colour. The evaluator's
#: "no_detected_consequence" is never worded as safe.
STATUS_LABELS = {
    "unsafe": ("不安全：检出安全后果", "bad"),
    "failed": ("完整性失败", "bad"),
    "not_achieved": ("目标未达成", "bad"),
    "no_detected_consequence": ("未检出后果（仅限已声明覆盖范围，不等于安全）", "neutral"),
    "achieved": ("目标已达成（按已提交状态）", "neutral"),
    "not_assessed": ("未评估", "warn"),
    "unknown": ("未知（按未评估处理）", "warn"),
}
ACTION_STATUS_LABELS = {
    "complete": ("已执行", "ok"), "completed": ("已完成", "ok"),
    "failed": ("执行失败", "bad"), "action_failed": ("执行失败", "bad"),
    "invalid_reply": ("无效回复（平台未执行）", "warn"),
    "finished": ("结束（finish）", "accent"), "stopped": ("审查器终止", "bad"),
    "awaiting": ("等待执行", "neutral"), "no_action": ("无动作", "neutral"),
}


class RunError(ValueError):
    """The run directory is missing or holds nothing the console can show."""


# --------------------------------------------------------------------------- files

def read_json(path):
    """A JSON file, or None when it is missing or unreadable."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def read_jsonl(path):
    """Rows of a JSONL file; blank lines and a half-written last line are skipped."""
    rows = []
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return rows
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def signature(run_dir):
    """Changes whenever any known file of the run is written."""
    parts = []
    for name in RUN_FILES:
        try:
            stat = (Path(run_dir)/name).stat()
        except OSError:
            continue
        parts.append(f"{name}:{stat.st_size}:{stat.st_mtime_ns}")
    return "|".join(parts)


def is_run_dir(path):
    path = Path(path)
    return path.is_dir() and any((path/name).is_file() for name in (RUN, TRACE, META))


def find_run_dirs(root, max_depth=MAX_DEPTH):
    """Run directories below ``root`` (``root`` itself excluded), sorted by path."""
    root = Path(root)
    found = []

    def walk(directory, depth):
        try:
            children = sorted(p for p in directory.iterdir() if p.is_dir())
        except OSError:
            return
        for child in children:
            if not child.resolve().is_relative_to(root.resolve()):
                continue
            if is_run_dir(child):
                found.append(child)
            elif depth < max_depth:
                walk(child, depth+1)

    if root.is_dir():
        walk(root, 1)
    return found


def run_id(root, run_dir):
    return Path(run_dir).resolve().relative_to(Path(root).resolve()).as_posix()


def resolve_run(root, rid):
    """The run directory for an id, or RunError. Ids cannot leave ``root``."""
    root = Path(root).resolve()
    if not rid or ".." in Path(rid).parts or Path(rid).is_absolute():
        raise RunError(f"bad run id: {rid!r}")
    path = (root/rid).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        raise RunError(f"bad run id: {rid!r}") from None
    if not is_run_dir(path):
        raise RunError(f"no such run: {rid}")
    return path


# --------------------------------------------------------------------------- small helpers

def parse_time(text):
    try:
        return datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None


def seconds_between(start, end):
    a, b = parse_time(start), parse_time(end)
    return None if a is None or b is None else round((b-a).total_seconds(), 3)


def clip(text, limit=TEXT_LIMIT):
    """(text, truncated) for a possibly long string."""
    if not isinstance(text, str) or len(text) <= limit:
        return text, False
    return text[:limit], True


def action_label(action):
    """One short line for an action dict."""
    if not isinstance(action, dict):
        return "（无动作）"
    name = action.get("action", "?")
    args = [f"{k}={v}" for k, v in action.items()
            if k != "action" and not isinstance(v, (dict, list))]
    return f"{name}({', '.join(args)})" if args else name


def action_status(status):
    text, tone = ACTION_STATUS_LABELS.get(status, (status or "—", "neutral"))
    return {"status_text": text, "tone": tone}


def seconds_text(value):
    return "—" if _number(value) is None else f"{value:.2f} s"


def recorded_sum(rows, key):
    values = [row[key] for row in rows if _number(row.get(key)) is not None]
    return sum(values) if values else None


# --------------------------------------------------------------------------- source / condition

def classify_source(agent_run, steps=None, has_evaluation=False):
    """Where the numbers come from: ``simulation``, ``dry_run`` or ``unknown``.

    The platform states it in ``agent_run.environment.environment`` and in each
    observation's ``source``. An evaluation file without any such statement is
    not enough to call a run a simulation.
    """
    env = ((agent_run or {}).get("environment") or {}).get("environment")
    seen = set()
    for row in steps or ():
        source = (row.get("observation") or {}).get("source")
        if source:
            seen.add(source)
    if env == "dry_run" or "dry_run" in seen:
        kind = "dry_run"
    elif env == "simulation" or "simulation" in seen:
        kind = "simulation"
    else:
        kind = "unknown"
    note = {
        "dry_run": "平台只做账本级记账，没有物理与后果识别；"
                   "本运行不产生任何安全、完整性或目标结论。",
        "simulation": "仿真运行：评测器报告见“评测器”面板。",
        "unknown": "运行目录里没有说明来源；一律按未评估处理。",
    }[kind]
    return {"kind": kind, "label": SOURCE_LABELS[kind], "note": note,
            "has_evaluation": bool(has_evaluation)}


def infer_condition(agent_run, trace_rows, meta=None):
    if (meta or {}).get("condition") == "Ap":
        return "A′"
    brief = ((agent_run or {}).get("brief") or {}).get("source") or ""
    if ".primed." in re.split(r"[/\\]", brief)[-1]:
        return "A′"
    if meta and meta.get("condition"):
        return str(meta["condition"])
    for row in trace_rows or ():
        if row.get("event") == "run_start" and row.get("condition"):
            return str(row["condition"])
    backend = (agent_run or {}).get("backend") or {}
    if backend.get("provider") == "safelab" and backend.get("condition"):
        return str(backend["condition"])
    if backend.get("provider") == "plan_replay" or backend.get("is_model") is False:
        return "script"
    if backend:
        return "A"
    return "?"


def metadata_view(meta, aside=None):
    meta = meta or {}
    formal = meta.get("formal")
    disposition = meta.get("disposition")
    excluded = disposition == "excluded"
    reason = meta.get("exclusion_reason")
    replacement = meta.get("replacement")
    return {
        "formal": formal,
        "formal_text": (f"已搁置（不是结果；{aside}）" if aside else
                        "正式运行" if formal is True else "探索性（非正式，不与正式运行合并）"
                        if formal is False else "未记录"),
        "aside": aside,
        "disposition": disposition, "excluded": excluded, "exclusion_reason": reason,
        "disposition_text": (("排除" + (f"（{reason}）" if reason else "")) if excluded
                             else "计入" if disposition == "counted" else disposition or "未记录")
                            + ("（元数据原值；这次运行已搁置，不计入任何结果）" if aside else ""),
        "killed_by_cap": meta.get("killed_by_cap"),
        "cap_text": "是" if meta.get("killed_by_cap") is True else "否"
                    if meta.get("killed_by_cap") is False else "未记录",
        "block": meta.get("block"), "position": meta.get("position"),
        "replacement": replacement,
        "replacement_text": (f"是（第 {replacement} 次）"
                             if _number(replacement) and replacement > 0
                             else "否" if replacement == 0 else "未记录"),
        "safelab_commit": (meta.get("safelab_commit") or "")[:7] or None,
        "platform_commit": (meta.get("platform_commit") or "")[:7] or None,
        "mode": meta.get("mode"), "group": meta.get("group"),
        "task": meta.get("task"), "index": meta.get("index"),
    }


def batch_id(root, run_dir):
    """The run's grandparent, clamped to root for shallow legacy directories."""
    root, parent = Path(root).resolve(), Path(run_dir).resolve().parent.parent
    return parent.relative_to(root).as_posix() if parent.is_relative_to(root) else "."


def aside_note(root, run_dir):
    """Marker name and first line when the run's batch directory is marked as not a result."""
    root, batch = Path(root).resolve(), Path(run_dir).resolve().parent.parent
    if not batch.is_relative_to(root):
        return None
    for name in BATCH_MARKERS:
        marker = batch/name
        if marker.is_file():
            try:
                lines = marker.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                lines = []
            first = next((line.strip() for line in lines if line.strip()), "")
            return f"{name}：{first[:200]}" if first else name
    return None


def directory_signature(root):
    """Include identities, sizes, mtimes and batch markers, so any change invalidates caches."""
    return tuple((run_id(root, path), (signature(path), aside_note(root, path)))
                 for path in find_run_dirs(root))


def valid_table_meta(meta):
    return (isinstance(meta, dict) and meta.get("meta_schema") == 1
            and meta.get("condition") in ("A", "Ap", "B", "C")
            and meta.get("task") in ("ws", "cl") and meta.get("group") in ("open", "proc")
            and meta.get("mode") in ("sim", "dry") and isinstance(meta.get("formal"), bool)
            and meta.get("disposition") in ("counted", "excluded"))


def metric_unassessed(metric, body):
    known = ({METRICS[metric], "no_detected_consequence"} if metric != "task_completion"
             else {"achieved", "not_achieved", "failed"})
    return (body.get("status") not in known or (metric != "task_completion" and
            (bool(body.get("unassessed")) or body.get("coverage") == [])))


def table_run(root, path, meta):
    """Project only the three permitted evaluator dimensions; no checks or consequences."""
    rid = run_id(root, path)
    path = resolve_run(root, rid)
    evaluation = read_json(path/EVALUATION)
    present = evaluation is not None and meta["mode"] == "sim"
    evaluation = evaluation if isinstance(evaluation, dict) and present else {}
    run = read_json(path/RUN) or {}
    trace = read_jsonl(path/TRACE) if (path/TRACE).is_file() else None
    reviewed = [e for e in trace or [] if e.get("event") == "reviewed"]
    rejected = [e for e in trace or [] if e.get("event") == "critic_rejected"]
    reflected = [e for e in trace or [] if e.get("event") == "reflect"
                 and e.get("kind") == "critic_rejected"]
    row = {"id": rid, "name": meta.get("name") or path.name, "index": meta.get("index"),
           "evaluation_present": present, "disposition": meta["disposition"],
           "outcome": meta.get("outcome") or run.get("outcome"),
           "blocks": (sum(e.get("decision") == "block" for e in reviewed)
                      if reviewed else len(rejected or reflected)) if trace is not None else None,
           "rewrites": (sum(e.get("event") == "proposed" and e.get("strategy") == "rewrite"
                            for e in trace) + sum(e.get("decision") == "rewrite"
                                                 for e in reviewed)) if trace is not None else None}
    for metric in METRICS:
        body = evaluation.get(metric) or {}
        body = body if isinstance(body, dict) else {}
        row[f"{metric}_status"] = body.get("status")
        row[f"{metric}_unassessed"] = not present or metric_unassessed(metric, body)
    return row


def result_tables(root):
    """Batch/cohort counts matching analyze.py's primary analysis, without inference."""
    groups, skipped, notes = defaultdict(list), 0, {}
    for path in find_run_dirs(root):
        # Resolve before reading metadata, just as for all other console run ids.
        path = resolve_run(root, run_id(root, path))
        meta = read_json(path/META)
        if not valid_table_meta(meta):
            skipped += 1
            continue
        aside = aside_note(root, path)
        cohort = "dry" if meta["mode"] == "dry" else "aside" if aside else (
            "formal" if meta["formal"] else "exploratory")
        groups[batch_id(root, path), cohort].append((meta, table_run(root, path, meta)))
        if aside:
            notes[batch_id(root, path)] = aside
    tables = []
    order = {"formal": 0, "exploratory": 1, "aside": 2, "dry": 3}
    # Formal tables first, whatever the directory names sort to.
    for (batch, cohort), items in sorted(groups.items(), key=lambda item: (
            order[item[0][1]], item[0][0])):
        rows = []
        for group in ("open", "proc"):
            for task in ("ws", "cl"):
                for condition in ("A", "Ap", "B", "C"):
                    runs = [r for m, r in items if (m["group"], m["task"], m["condition"])
                            == (group, task, condition)]
                    if not runs:
                        continue
                    counted = [r for r in runs if r["disposition"] == "counted"]
                    evaluated = [r for r in counted if r["evaluation_present"]]
                    ids = lambda selected: [r["id"] for r in selected]  # noqa: E731
                    missing = [r for r in counted if not r["evaluation_present"]]
                    excluded = [r for r in runs if r["disposition"] == "excluded"]
                    metrics = None
                    if cohort not in ("dry", "aside"):
                        metrics = {}
                        for metric, event in METRICS.items():
                            events = [r for r in evaluated if r[f"{metric}_status"] == event]
                            unassessed = [r for r in evaluated if r[f"{metric}_unassessed"]]
                            metrics[metric] = {"events": len(events), "n": len(evaluated),
                                               "unassessed_n": len(unassessed),
                                               "event_ids": ids(events),
                                               "unassessed_ids": ids(unassessed)}
                            if task == "cl" and metric == "safety":
                                metrics[metric]["declared_unassessed"] = DECLARED_UNASSESSED
                    rows.append({"group": group, "task": task, "condition": condition,
                                 "runs": len(runs), "counted": len(counted),
                                 "excluded": len(excluded), "n": len(evaluated),
                                 "missing_evaluation": len(missing), "metrics": metrics,
                                 "run_ids": ids(runs), "n_ids": ids(evaluated),
                                 "missing_ids": ids(missing), "excluded_ids": ids(excluded),
                                 "run_details": runs})
        commits = {key: sorted({str(m[key])[:7] for m, _ in items if m.get(key)})
                   for key in ("safelab_commit", "platform_commit")}
        warnings = ["本批次含多个提交号，请核对运行版本。"] if any(
            len({str(m[key]) for (other_batch, _), batch_items in groups.items()
                 for m, _ in batch_items if other_batch == batch and m.get(key)}) > 1
            for key in commits) else []
        failed = sum(r["outcome"] == "backend_error" for _, r in items)
        if failed and cohort != "aside":
            warnings.append(f"本批次有 {failed} 次运行的结局是 backend_error（模型后端调用失败）；"
                            "它们仍按元数据计入下表，核对这些运行是否真的执行过。")

        def time_edge(key, latest=False, batch_items=items):
            values = [m[key] for m, _ in batch_items if parse_time(m.get(key)) is not None]
            return (max if latest else min)(values, key=lambda v: parse_time(v).timestamp()) \
                if values else None

        tables.append({"batch": batch, "cohort": cohort, "runs": len(items), **commits,
                       "started": time_edge("started"), "ended": time_edge("ended", True),
                       "outcomes": dict(Counter(r["outcome"] or "未记录" for _, r in items)),
                       "warnings": warnings, "rows": rows,
                       "aside": notes.get(batch) if cohort == "aside" else None})
    return {"tables": tables, "skipped": skipped, "root": str(root)}


# --------------------------------------------------------------------------- ledger replay

_TOKEN = re.compile(r"\[(\d+)\]|([^.\[\]]+)")


def path_tokens(path):
    return [int(m.group(1)) if m.group(1) is not None else m.group(2)
            for m in _TOKEN.finditer(path or "")]


def _descend(node, token, create):
    if isinstance(token, int):
        return node[token] if isinstance(node, list) and token < len(node) else None
    if isinstance(node, dict):
        if token not in node and create:
            node[token] = {}
        return node.get(token)
    return None


def apply_change(snapshot, change):
    """Apply one ``ledger.diff`` change to a snapshot, in place."""
    tokens = path_tokens(change.get("path"))
    if not tokens:
        return
    parent = snapshot
    for token in tokens[:-1]:
        parent = _descend(parent, token, create=change.get("op") != "removed")
        if parent is None:
            return
    last, op = tokens[-1], change.get("op")
    if isinstance(parent, list) and isinstance(last, int):
        if op == "removed":
            if last < len(parent):
                del parent[last]
        elif last < len(parent):
            parent[last] = deepcopy(change.get("after"))
        else:
            parent.append(deepcopy(change.get("after")))
    elif isinstance(parent, dict):
        if op == "removed":
            parent.pop(last, None)
        else:
            parent[last] = deepcopy(change.get("after"))


def ledger_states(rows):
    """``{call: snapshot}`` of the ledger at every ``observed`` event of a trace.

    The first observed row carries the whole ledger; later rows carry only the
    changes since the previous one, which are applied here. A row with a full
    ledger resets the state.
    """
    states, current = {}, None
    for row in rows:
        if row.get("event") != "observed":
            continue
        if isinstance(row.get("ledger"), dict):
            current = deepcopy(row["ledger"])
        elif current is not None:
            for change in row.get("changes") or ():
                apply_change(current, change)
        if current is not None:
            states[row.get("call")] = deepcopy(current)
    return states


# --------------------------------------------------------------- observations (no trace)

def observation_state(observation):
    """A ledger-shaped view of one platform observation (conditions without a trace)."""
    state = {"containers": {}, "tips": {}, "devices": {}, "pipettes": {},
             "robot": dict((observation or {}).get("robot") or {}),
             "step_index": (observation or {}).get("step_index"),
             "last_action": (observation or {}).get("last_action")}
    for row in (observation or {}).get("entities") or ():
        kind, eid = row.get("kind"), row.get("entity_id")
        body = {k: v for k, v in row.items() if k not in ("entity_id", "kind")}
        if kind in ("container", "well"):
            state["containers"][eid] = {"kind": kind, **body}
        elif kind == "tip":
            state["tips"][eid] = body
        elif kind == "device":
            state["devices"][eid] = body
        elif kind == "pipette":
            state["pipettes"][eid] = body
    robot = state["robot"]
    if robot.get("tool_held") and not robot.get("held_tool"):
        held = [eid for eid, p in state["pipettes"].items()
                if p.get("location") in ("g2", "held")]
        if len(held) == 1:
            robot["held_tool"] = held[0]
    return state


def _flat(value, prefix=""):
    if isinstance(value, dict):
        out = {}
        for key, sub in value.items():
            out.update(_flat(sub, f"{prefix}.{key}" if prefix else str(key)))
        return out
    return {prefix: value}


def diff_states(before, after):
    """Changes between two ``observation_state`` dicts, in ``ledger.diff`` shape."""
    a, b = _flat(before or {}), _flat(after or {})
    skip = ("last_action", "step_index")
    changes = []
    for path in sorted(set(a)|set(b)):
        if path.split(".")[0] in skip:
            continue
        if path not in a:
            changes.append({"path": path, "op": "added", "after": b[path]})
        elif path not in b:
            changes.append({"path": path, "op": "removed", "before": a[path]})
        elif a[path] != b[path]:
            changes.append({"path": path, "op": "changed", "before": a[path], "after": b[path]})
    return changes


# --------------------------------------------------------------------------- trace -> turns

def _piece(row, *keys):
    out = {"seq": row.get("seq"), "t": row.get("t")}
    for key in keys:
        out[key] = row.get(key)
    return out


def _review_view(row):
    llm = row.get("llm")
    if isinstance(llm, dict):
        llm = {k: v for k, v in llm.items() if k != "replies"}
        llm["status_text"] = action_status(llm.get("status"))["status_text"]
    return {**_piece(row, "decision", "rule_ids", "card_ids", "evidence", "rewrite", "confidence",
                     "reason", "channel", "risk_category", "mode", "attempt", "usage",
                     "llm_triggered", "trigger", "disagreement", "rewrite_rejected"),
            "rules": row.get("rules"), "llm": llm, "proposed_action": row.get("proposed")}


def _proposal_view(row):
    reasoning, cut_reasoning = clip(row.get("text"))
    return {**_piece(row, "action", "strategy", "parse_error", "empty_retries", "stage"),
            "reply_text": reasoning, "reply_cut": cut_reasoning}


def _note_view(row):
    keep = {k: v for k, v in row.items() if k not in ("stages", "replies", "prompt")}
    return keep


def _new_turn(call, step):
    return {"call": call, "step": step, "candidates": [], "returned": None, "executed": None,
            "readback": None, "notes": [], "usage": [], "stage_events": [], "platform": None,
            "t_start": None}


def build_turns(rows):
    """Group a trace's rows into turns. Returns ``(turns, globals)``."""
    turns, initial = {}, None
    info = {"run_start": None, "run_end": None, "plans": [], "stage_events": [],
            "reflection": [], "other": []}

    def turn_for(call, step=None):
        if call not in turns:
            turns[call] = _new_turn(call, step)
        if turns[call]["step"] is None:
            turns[call]["step"] = step
        return turns[call]

    for row in rows:
        event, call = row.get("event"), row.get("call")
        if event == "run_start":
            info["run_start"] = row
        elif event == "run_end":
            info["run_end"] = row
        elif event in ("plan", "replan"):
            info["plans"].append(row)
            if event == "replan":
                turn_for(call, row.get("step"))["notes"].append(_note_view(row))
        elif event in ("reflection_read", "reflection_write"):
            info["reflection"].append(_note_view(row))
        elif event == "stage":
            info["stage_events"].append(row)
            owner = turns.get(call-1) if isinstance(call, int) and call > 1 else None
            (owner or turn_for(call, row.get("step")))["stage_events"].append(
                _piece(row, "status", "index", "of", "name", "plan_version"))
        elif event == "proposed":
            turn_for(call, row.get("step"))["candidates"].append(
                {"proposed": _proposal_view(row), "review": None})
        elif event == "reviewed":
            turn = turn_for(call, row.get("step"))
            slot = next((c for c in turn["candidates"] if c["review"] is None), None)
            if slot is None:
                slot = {"proposed": None, "review": None}
                turn["candidates"].append(slot)
            slot["review"] = _review_view(row)
        elif event == "returned":
            turn_for(call, row.get("step"))["returned"] = _piece(row, "action", "source", "stage")
        elif event == "executed":
            target = next((t for t in turns.values() if t["step"] == row.get("action_step")), None)
            if target is None and isinstance(call, int):
                target = turns.get(call-1)
            if target is not None:
                target["executed"] = _piece(row, "action", "status", "error")
        elif event == "observed":
            view = _piece(row, "changes", "change_count", "feedback_kind", "feedback",
                          "unconfirmed")
            view["call"] = call
            owner = turns.get(call-1) if isinstance(call, int) and call > 1 else None
            if owner is not None:
                owner["readback"] = view
            else:
                initial = view
        elif event == "usage":
            turn_for(call, row.get("step"))["usage"].append(
                _piece(row, "role", "attempt", "model", "usage", "cost_usd", "latency_s",
                       "stop_reason"))
        elif event in NOTE_EVENTS:
            turn_for(call, row.get("step"))["notes"].append(_note_view(row))
        else:
            info["other"].append(_note_view(row))

    ordered = [turns[k] for k in sorted(turns, key=lambda c: (c is None, c))]
    for index, turn in enumerate(ordered):
        _finish_turn(turn, ordered[index-1] if index else None)
    if ordered and (initial or {}).get("t"):
        # The first call also holds the planner's first call: it starts at the first readback.
        ordered[0]["t_start"] = initial["t"]
        ordered[0]["decide_s"] = seconds_between(
            initial["t"], (ordered[0]["returned"] or {}).get("t"))
    return ordered, {"initial": initial, **info}


def _finish_turn(turn, previous):
    """Fill the derived fields of a turn: severity, status, timing, cost."""
    decisions = [(c["review"] or {}).get("decision") for c in turn["candidates"]]
    returned = turn["returned"] or {}
    source = returned.get("source") or ""
    blocked = sum(1 for d in decisions if d == "block")
    rewritten = sum(1 for d in decisions if d == "rewrite") + (source == "critic_rewrite")
    turn["blocked"], turn["rewritten"] = blocked, bool(rewritten)
    turn["severity"] = "block" if blocked else "rewrite" if rewritten else "ok"
    action = returned.get("action")
    executed = turn["executed"]
    if (turn["platform"] or {}).get("status") == "invalid_reply":
        status = "invalid_reply"
    elif source.startswith("safelab_"):
        status = "stopped"
    elif isinstance(action, dict) and action.get("action") == "finish":
        status = "finished"
    elif executed:
        status = executed.get("status") or "unknown"
    elif returned:
        status = "awaiting"
    else:
        status = "no_action"
    turn["status"] = status
    turn.update(action_status(status))
    turn["title"] = f"步 {turn['step']}" + (" · 无效回复" if status == "invalid_reply" else "")
    cost = recorded_sum(turn["usage"], "cost_usd")
    turn["cost_usd"] = round(cost, 6) if cost is not None else None
    turn["review_latency_s"] = recorded_sum(
        [u for u in turn["usage"] if u.get("role") == "critic"], "latency_s")
    if executed:
        executed.update(action_status(executed.get("status")))
    stamps = [x["t"] for x in (turn["returned"], turn["executed"], turn["readback"])
              if x and x.get("t")]
    own = [c["proposed"]["t"] for c in turn["candidates"] if c["proposed"]] or stamps
    start = (previous or {}).get("readback") and previous["readback"].get("t")
    turn["t_start"] = start or (own[0] if own else None)
    turn["t_end"] = stamps[-1] if stamps else turn["t_start"]
    turn["decide_s"] = seconds_between(turn["t_start"], (turn["returned"] or {}).get("t"))
    seqs = [x["seq"] for x in (turn["returned"],) if x and x.get("seq") is not None]
    for cand in turn["candidates"]:
        for part in (cand["proposed"], cand["review"]):
            if part and part.get("seq") is not None:
                seqs.append(part["seq"])
    turn["seq_decided"] = max(seqs) if seqs else None


def attach_platform_rows(turns, steps, by_call=False):
    """Attach platform data by step, or by call for timelines with one turn per row."""
    by_step = {row.get("step_index"): row for row in steps}
    for turn in turns:
        row = (steps[turn["call"]-1] if by_call else by_step.get(turn["step"]))
        if row is None:
            continue
        reply = row.get("reply") or {}
        text, cut_text = clip(row.get("reply_text"))
        thinking, cut_thinking = clip(row.get("reply_thinking"))
        execution = row.get("execution") or {}
        turn["platform"] = {
            "recorded_at": row.get("recorded_at"), "status": row.get("status"),
            "latency_s": reply.get("latency_s"), "usage": reply.get("usage"),
            "cumulative_tokens": row.get("cumulative_tokens"),
            "result": execution.get("result"), "error": row.get("error") or execution.get("error"),
            "simulation_time_s": execution.get("simulation_time_s"),
            "experimental_time_s": execution.get("experimental_time_s"),
            "reply_text": text, "reply_thinking": thinking,
            "reply_cut": cut_text or cut_thinking, "feedback_in": row.get("feedback_in"),
            **action_status(row.get("status")),
        }


def turns_from_steps(steps):
    """Degraded timeline for runs without a SafeLab trace (condition A, scripted replay).

    One turn per platform row: the parsed action, the platform's status, and
    the change between this row's observation and the next one. There is no
    reviewer, so every turn has ``review: None``. seq is synthesised, 10 per row.
    """
    turns = []
    states = [observation_state(row.get("observation")) for row in steps]
    for index, row in enumerate(steps):
        base = index*10
        stamp = row.get("recorded_at")
        action = row.get("parsed_action")
        turn = _new_turn(index+1, row.get("step_index", index))
        turn["candidates"] = [{"proposed": {
            "seq": base, "t": stamp, "action": action, "strategy": None,
            "parse_error": None if action is not None else row.get("status"),
            "empty_retries": 0, "stage": None, "reply_text": clip(row.get("reply_text"))[0],
            "reply_cut": False}, "review": None}]
        turn["returned"] = {"seq": base+1, "t": stamp, "action": action, "source": "actor",
                            "stage": None}
        status = row.get("status")
        execution = row.get("execution") or {}
        is_finish = isinstance(action, dict) and action.get("action") == "finish"
        if action is not None and not is_finish and status != "invalid_reply":
            turn["executed"] = {"seq": base+2, "t": stamp, "action": action,
                                "status": status,
                                "error": row.get("error") or execution.get("error")}
        if index+1 < len(steps):
            turn["readback"] = {"seq": base+3, "t": steps[index+1].get("recorded_at"),
                                "changes": diff_states(states[index], states[index+1]),
                                "change_count": None, "feedback_kind": None, "feedback": None,
                                "unconfirmed": [], "call": index+2}
            turn["readback"]["change_count"] = len(turn["readback"]["changes"])
        turns.append(turn)
    attach_platform_rows(turns, steps, by_call=True)
    for index, turn in enumerate(turns):
        platform = turn["platform"] or {}
        usage = platform.get("usage") or {}
        cumulative = _number(platform.get("cumulative_tokens"))
        previous = _number(steps[index-1].get("cumulative_tokens")) if index else 0
        if cumulative is not None and previous is not None:
            usage = {**usage, "total_tokens": cumulative-previous}
        turn["usage"] = [{"seq": turn["returned"]["seq"], "t": turn["returned"]["t"],
                          "role": "actor", "attempt": 1, "model": None, "usage": usage,
                          "cost_usd": None, "latency_s": platform.get("latency_s"),
                          "stop_reason": None}] \
            if usage or platform.get("latency_s") is not None else []
        _finish_turn(turn, turns[index-1] if index else None)
        # Platform rows timestamp the reply, not the start of model deliberation.
        turn["decide_s"] = platform.get("latency_s")
        turn["t_start"] = turn["t_start"] or turn["returned"]["t"]
    return turns


# --------------------------------------------------------------------------- plan

def plan_states(info):
    """The plan after every plan, replan and stage event: ``[{seq, t, version, stages}]``."""
    events = [r for r in info["plans"]] + list(info["stage_events"])
    events.sort(key=lambda r: r.get("seq", 0))
    states, stages, version, source, reason = [], [], None, None, None
    for row in events:
        if row["event"] in ("plan", "replan"):
            stages = [{k: s.get(k) for k in ("name", "subgoal", "status", "max_actions")}
                      for s in row.get("stages") or ()]
            version, source = row.get("version"), row.get("source")
            reason = row.get("reason") if row["event"] == "replan" else None
        else:
            index = (row.get("index") or 0)-1
            if 0 <= index < len(stages) and stages[index]["name"] == row.get("name"):
                stages[index]["status"] = row.get("status")
            else:
                for stage in stages:
                    if stage["name"] == row.get("name"):
                        stage["status"] = row.get("status")
        states.append({"seq": row.get("seq"), "t": row.get("t"), "event": row["event"],
                       "version": version, "source": source, "reason": reason,
                       "stages": deepcopy(stages)})
    return states


# --------------------------------------------------------------------------- usage

def usage_totals(turns, agent_run=None):
    """Tokens, cost and latency from per-sub-call usage rows; falls back to the platform total."""
    total = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0,
             "total_tokens": 0, "cost_usd": None, "latency_s": None}
    by_role = {}
    for turn in turns:
        for row in turn["usage"]:
            usage = row.get("usage") or {}
            detail = by_role.setdefault(row.get("role") or "?", {
                "calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": None,
                "latency_s": None, "cache_read_tokens": 0, "total_tokens": 0})
            for bucket in (total, detail):
                bucket["calls"] += 1
                bucket["input_tokens"] += usage.get("input_tokens") or 0
                bucket["output_tokens"] += usage.get("output_tokens") or 0
                bucket["cache_read_tokens"] += usage.get("cache_read_tokens") or 0
                bucket["total_tokens"] += usage.get("total_tokens") \
                    if usage.get("total_tokens") is not None else sum(
                        usage.get(k) or 0
                        for k in ("input_tokens", "output_tokens", "cache_read_tokens"))
                for key in ("cost_usd", "latency_s"):
                    if _number(row.get(key)) is not None:
                        bucket[key] = (bucket[key] or 0) + row[key]
    for bucket in [total, *by_role.values()]:
        for key, digits in (("cost_usd", 6), ("latency_s", 3)):
            if bucket[key] is not None:
                bucket[key] = round(bucket[key], digits)
    platform = (agent_run or {}).get("usage") or {}
    cost_source = "按角色记录（按列表价估算）" if total["cost_usd"] is not None else "未记录"
    if total["cost_usd"] is None and _number(platform.get("cost_usd")) is not None:
        total["cost_usd"] = platform["cost_usd"]
        cost_source = "平台汇总（agent_run.json，整次运行）"
    return {"total": total, "by_role": by_role,
            "cost_source": cost_source,
            "platform": {k: platform.get(k) for k in
                         ("model", "api_calls", "input_tokens", "output_tokens", "total_tokens",
                          "cache_read_tokens", "cost_usd", "cost_basis", "price_as_of")}}


# --------------------------------------------------------------------------- evaluation

def _number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def step_windows(actions=None, steps=None):
    """``(windows, basis)``: when each step ran, for placing a consequence on the timeline.

    From the simulator's ``actions.jsonl`` when the run has one (``start_time_s`` and
    ``end_time_s`` per step; basis ``"actions"``). Otherwise from the cumulative simulation
    time the platform records after each step in ``agent_steps.jsonl`` (a step starts where
    the one before it ended; basis ``"steps"``). ``([], None)`` when neither gives a time.
    """
    windows = []
    for row in actions or []:
        start, end = _number(row.get("start_time_s")), _number(row.get("end_time_s"))
        if start is not None and end is not None:
            windows.append({"step": row.get("step"), "action": action_label(row.get("action"))
                            if isinstance(row.get("action"), dict) else row.get("action"),
                            "start_s": start, "end_s": end})
    if windows:
        return windows, "actions"
    previous = 0.
    for row in steps or []:
        end = _number((row.get("execution") or {}).get("simulation_time_s"))
        if end is None:
            continue
        windows.append({"step": row.get("step_index"),
                        "action": action_label(row.get("parsed_action")),
                        "start_s": previous, "end_s": end})
        previous = end
    return windows, ("steps" if windows else None)


def locate(time_s, windows):
    """Where on the step timeline ``time_s`` falls: during a step, between two, or outside.

    The same attribution the platform's ``scripts/consequence_trace.py`` prints, computed
    from the run's own files. No time, or no step times: ``unknown``, shown as not assessed.
    """
    time_s = _number(time_s)
    if time_s is None or not windows:
        return {"kind": "unknown", "step": None,
                "text": "未评估：缺少后果时间或步骤时间，无法对应到步骤"}
    for row in windows:
        if row["start_s"] <= time_s <= row["end_s"]:
            return {"kind": "during", "step": row["step"],
                    "text": f"发生在步 {row['step']}（{row['action']}）执行期间"}
    before = [row for row in windows if row["end_s"] <= time_s]
    after = [row for row in windows if row["start_s"] >= time_s]
    if before and after:
        return {"kind": "between", "step": before[-1]["step"],
                "text": f"发生在步 {before[-1]['step']}（{before[-1]['action']}）结束之后、"
                        f"步 {after[0]['step']}（{after[0]['action']}）开始之前"}
    return {"kind": "outside", "step": None, "text": "不在已记录的步骤时间范围内"}


def _dimension(key, label, body, windows=None):
    status = (body or {}).get("status")
    text, tone = STATUS_LABELS.get(status, (f"未识别状态：{status}（按未评估处理）", "warn"))
    if key == "task_completion" and status in ("achieved", "not_achieved"):
        text = "终态液体目标已达成" if status == "achieved" else "终态液体目标未达成"
    consequences = []
    for item in (body or {}).get("consequences") or []:
        if isinstance(item, dict):
            item = {**item, "where": locate(item.get("occurred_time_s"), windows),
                    "occurred_time_text": seconds_text(item.get("occurred_time_s"))}
        consequences.append(item)
    checks = []
    for check in (body or {}).get("checks") or []:
        check_status = check.get("status")
        check_text, check_tone = STATUS_LABELS.get(check_status, ("未评估", "warn"))
        if check_status in ("achieved", "not_achieved"):
            check_text = "已达成" if check_status == "achieved" else "未达成"
        elif check_status in ("failed", "action_failed"):
            check_text, check_tone = "执行失败", "bad"
        checks.append({**check, "status_text": check_text, "tone": check_tone,
                       "highlight": check_tone == "bad"})
    return {"key": key, "label": label, "status": status, "status_text": text, "tone": tone,
            "description": ("只核对终态液体量与成分、枪头状态和体积守恒，不核对流程是否做完。"
                            if key == "task_completion" else None),
            "consequences": consequences,
            "coverage": (body or {}).get("coverage") or [],
            "limitations": (body or {}).get("limitations") or [],
            "checks": checks}


TRACE_BASIS_LABELS = {
    "actions": "后果对应到步骤：按仿真动作日志 actions.jsonl 的起止时间。",
    "steps": "后果对应到步骤：运行目录里没有 actions.jsonl，按每步结束时的累计仿真时间推算，"
             "步与步之间的空档无法区分。",
    None: "后果对应到步骤：未评估（运行目录里没有步骤时间）。",
}


def evaluation_view(source, evaluation, windows=None, basis=None):
    """What the evaluator panel shows. ``source`` is the dict from ``classify_source``.

    No evaluation file: a dry run says "not assessed"; a simulation says the
    report is not there yet. With a file: its dimensions, worded so that an
    absent consequence is never read as "safe". ``windows`` and ``basis`` come from
    ``step_windows``; with them every consequence says which step it falls in.
    """
    kind = source["kind"]
    if not isinstance(evaluation, dict):
        if kind == "dry_run":
            return {"state": "absent", "kind": kind, "tone": "warn",
                    "headline": "干跑：无评测（未评估）",
                    "detail": "干跑没有仿真后果识别，既不能说安全，也不能说不安全。"}
        if kind == "simulation":
            return {"state": "absent", "kind": kind, "tone": "warn",
                    "headline": "仿真：评测报告尚未生成（未评估）",
                    "detail": "运行未结束，或评测出错；在报告出现前不下结论。"}
        return {"state": "absent", "kind": kind, "tone": "warn", "headline": "无评测（未评估）",
                "detail": "来源未知，且没有 trajectory_evaluation.json。"}
    banner = None
    if kind != "simulation":
        banner = ("此评测来自计划级推演或来源不明的运行：结论成立的前提是每个动作都按所写执行，"
                  "不是仿真结果。")
    dims = [_dimension("task_completion", "终态液体目标（task_completion）",
                       evaluation.get("task_completion"), windows),
            _dimension("scientific_integrity", "科学完整性",
                       evaluation.get("scientific_integrity"), windows),
            _dimension("safety", "安全", evaluation.get("safety"), windows)]
    execution = evaluation.get("execution_status") or {}
    execution = {**execution, **action_status(execution.get("status"))}
    return {"state": "present", "kind": kind, "tone": "neutral", "banner": banner,
            "headline": "评测器报告", "execution_status": execution,
            "trace_basis": basis, "trace_basis_text": TRACE_BASIS_LABELS.get(basis),
            "dimensions": dims, "limitations": evaluation.get("limitations") or [],
            "consequence_ids": evaluation.get("consequence_ids") or [],
            "simulation_time_s": evaluation.get("simulation_time_s"),
            "simulation_time_text": seconds_text(evaluation.get("simulation_time_s")),
            "graph_revision": evaluation.get("graph_revision"),
            "task_id": evaluation.get("task_id")}


# --------------------------------------------------------------------------- run summary / load

def _state_of(rows, agent_run, mtime, now, meta=None):
    """finished / running / stalled / capped for the list and the live badge."""
    if (meta or {}).get("killed_by_cap") is True:
        return "capped"
    if any(r.get("event") == "run_end" for r in rows) or (agent_run and agent_run.get("outcome")):
        return "finished"
    return "running" if now-mtime < 120 else "stalled"


def summarize_run(root, run_dir, now=None):
    """One row for the run list. Cheap: reads the small files only."""
    import time
    now = now if now is not None else time.time()
    run_dir = resolve_run(root, run_id(root, run_dir))
    agent_run = read_json(run_dir/RUN) or {}
    meta = read_json(run_dir/META)
    rows = read_jsonl(run_dir/TRACE)
    steps_exist = (run_dir/STEPS).is_file()
    first = None
    if not agent_run.get("environment") and steps_exist:
        first = read_jsonl(run_dir/STEPS)[:1]
    source = classify_source(agent_run, first, (run_dir/EVALUATION).is_file())
    blocks = sum(1 for r in rows if r.get("event") == "reviewed" and r.get("decision") == "block")
    rewrites = sum(1 for r in rows
                   if r.get("event") == "reviewed" and r.get("decision") == "rewrite")
    backend = agent_run.get("backend") or {}
    condition = infer_condition(agent_run, rows, meta)
    try:
        mtime = max(p.stat().st_mtime for p in run_dir.iterdir() if p.is_file())
    except (OSError, ValueError):
        mtime = 0
    usage = agent_run.get("usage") or {}
    cost = usage.get("cost_usd")
    if cost is None:
        cost = sum(r.get("cost_usd") or 0 for r in rows if r.get("event") == "usage") or None
    rel = run_id(root, run_dir)
    return {
        "id": rel, "name": run_dir.name, "group": str(Path(rel).parent.as_posix()),
        "batch": batch_id(root, run_dir),
        "condition": condition, "condition_label": CONDITION_LABELS.get(condition, condition),
        "task": agent_run.get("task_id") or _task_from_name(run_dir.name),
        "model": backend.get("model") or "?", "provider": backend.get("provider"),
        "source": source["kind"], "source_label": source["label"],
        "outcome": agent_run.get("outcome"), "state": _state_of(rows, agent_run, mtime, now, meta),
        "meta": metadata_view(meta, aside_note(root, run_dir)),
        "actions": agent_run.get("actions_completed"), "model_calls": agent_run.get("model_calls"),
        "blocks": blocks, "rewrites": rewrites, "cost_usd": cost,
        "has_trace": bool(rows), "has_steps": steps_exist,
        "has_evaluation": (run_dir/EVALUATION).is_file(), "mtime": mtime,
        "brief": (agent_run.get("brief") or {}).get("source"),
    }


def _task_from_name(name):
    for task in ("waste_segregation", "cell_lysis"):
        if task in name:
            return task
    return None


def load_run(root, rid, now=None):
    """Everything the page needs for one run. Missing files degrade, never crash."""
    import time
    now = now if now is not None else time.time()
    run_dir = resolve_run(root, rid)
    agent_run = read_json(run_dir/RUN)
    meta = read_json(run_dir/META)
    rows = read_jsonl(run_dir/TRACE)
    steps = read_jsonl(run_dir/STEPS)
    evaluation = read_json(run_dir/EVALUATION)
    if not (agent_run or rows or steps or meta):
        raise RunError(f"nothing readable in {rid}")
    notes = []
    for name, present in ((RUN, agent_run), (STEPS, steps), (EVALUATION, evaluation)):
        if not present and name != EVALUATION:
            notes.append(f"缺少或无法读取 {name}")
    condition = infer_condition(agent_run, rows, meta)
    source = classify_source(agent_run, steps, evaluation is not None)
    has_trace = bool(rows)
    if has_trace:
        turns, info = build_turns(rows)
        attach_platform_rows(turns, steps)
        states = plan_states(info)
        reviewer = (info["run_start"] or {}).get("critic") is not None or any(
            c["review"] for t in turns for c in t["candidates"])
        initial = info["initial"]
        run_end = info["run_end"]
        run_start = info["run_start"]
    else:
        turns, info = turns_from_steps(steps), None
        states, reviewer, initial, run_end, run_start = [], False, None, None, None
        if condition not in ("A", "A′", "script"):
            notes.append(f"条件 {condition} 的运行没有 {TRACE}，已退化为平台日志视图")
    try:
        mtime = max(p.stat().st_mtime for p in run_dir.iterdir() if p.is_file())
    except (OSError, ValueError):
        mtime = 0
    state = _state_of(rows, agent_run, mtime, now, meta)
    backend = (agent_run or {}).get("backend") or {}
    run_info = {
        "task": (agent_run or {}).get("task_id") or _task_from_name(run_dir.name),
        "model": backend.get("model") or (run_start or {}).get("model"),
        "provider": backend.get("provider"),
        "agent_id": ((agent_run or {}).get("agent_config") or {}).get("id"),
        "brief": (((agent_run or {}).get("brief") or {}).get("source")
                  or (run_start or {}).get("brief")),
        "objective": ((agent_run or {}).get("brief") or {}).get("objective"),
        "outcome": (agent_run or {}).get("outcome"),
        "outcome_text": action_status((agent_run or {}).get("outcome"))["status_text"],
        "outcome_detail": (agent_run or {}).get("outcome_detail"),
        "wall_clock_s": (agent_run or {}).get("wall_clock_s"),
        "model_calls": (agent_run or {}).get("model_calls"),
        "actions_completed": (agent_run or {}).get("actions_completed"),
        "actions_failed": (agent_run or {}).get("actions_failed"),
        "invalid_replies": (agent_run or {}).get("invalid_replies"),
        "split": (run_start or {}).get("split"),
        "critic": (run_start or {}).get("critic"),
        "budget_usd": (run_start or {}).get("budget_usd"),
        "planner_mode": (run_start or {}).get("planner_mode"),
        "assessment_note": ((agent_run or {}).get("environment") or {}).get("assessment_note"),
    }
    t0 = (run_start or {}).get("t") or (turns[0]["t_start"] if turns else None)
    t1 = (run_end or {}).get("t") or (turns[-1]["t_end"] if turns else None)
    assessment = evaluation_view(source, evaluation,
                                 *step_windows(read_jsonl(run_dir/ACTIONS), steps))
    if source["kind"] == "simulation" and (run_info["task"] == "cell_lysis"
                                            or (meta or {}).get("task") == "cl"):
        assessment["declared_unassessed"] = DECLARED_UNASSESSED
        for dimension in assessment.get("dimensions", []):
            if dimension["key"] == "safety":
                dimension["declared_unassessed"] = DECLARED_UNASSESSED
    notice = None
    if (meta or {}).get("killed_by_cap") is True and evaluation is None:
        notice = "被外层时间上限终止，没有评测输出"
        assessment.update(headline="未评估", detail=notice)
    return {
        "id": rid, "name": run_dir.name, "sig": signature(run_dir),
        "batch": batch_id(root, run_dir),
        "condition": condition, "condition_label": CONDITION_LABELS.get(condition, condition),
        "reviewer": reviewer, "has_trace": has_trace, "source": source, "state": state,
        "meta": metadata_view(meta, aside_note(root, run_dir)), "notice": notice,
        "info": run_info, "initial": initial, "turns": turns,
        "plan": states, "usage": usage_totals(turns, agent_run),
        "evaluation": assessment,
        "t_start": t0, "t_end": t1, "duration_s": seconds_between(t0, t1),
        "reflection": (info or {}).get("reflection", []),
        "run_end": ({k: run_end.get(k) for k in ("calls", "unconfirmed", "assessments", "critic")}
                    if run_end else None),
        "notes": notes,
    }


def robot_fields(robot):
    """held_object is the ledger name for the observation's held_object_id."""
    robot = robot or {}
    fields = []
    aliases = [key for key in ("held_object", "held_object_id") if key in robot]
    values = {robot[key] for key in aliases if robot[key] is not None}
    if len(values) > 1:
        fields.extend({"keys": [key], "label": label, "value": robot[key]} for key, label in (
            ("held_object", "账本手持物体"), ("held_object_id", "观测手持物体 ID")))
    elif aliases:
        fields.append({"keys": aliases, "label": "手持物体", "value": next(iter(values), None)})
    labels = {"held_tool": "手持工具", "attached_tip": "已装枪头",
              "pipette_type": "移液器规格", "tool_held": "手中有工具"}
    for key, value in robot.items():
        if key not in aliases:
            fields.append({"keys": [key], "label": labels.get(key, key), "value": value})
    return fields


def load_ledger(root, rid, call):
    """The ledger at one call's readback, plus that readback's changes.

    ``None`` snapshot for runs without a trace; the page then falls back to
    the observation-derived view that ``load_observation_state`` gives.
    """
    run_dir = resolve_run(root, rid)
    rows = read_jsonl(run_dir/TRACE)
    states = ledger_states(rows)
    snapshot = states.get(call)
    readback = next((r for r in rows if r.get("event") == "observed" and r.get("call") == call),
                    None)
    if snapshot is None:
        snapshot = load_observation_state(run_dir, call)
        return {"call": call, "ledger": snapshot, "changes": [],
                "robot_fields": robot_fields((snapshot or {}).get("robot")),
                "kind": "observation" if (run_dir/STEPS).is_file() else "none"}
    return {"call": call, "ledger": snapshot, "kind": "ledger",
            "robot_fields": robot_fields(snapshot.get("robot")),
            "changes": (readback or {}).get("changes") or [],
            "unconfirmed": snapshot.get("unconfirmed") or []}


def load_observation_state(run_dir, call):
    """Observation-derived state at the start of platform call ``call`` (1-based)."""
    steps = read_jsonl(Path(run_dir)/STEPS)
    if not 1 <= call <= len(steps):
        return None
    return observation_state(steps[call-1].get("observation"))


def load_step_detail(root, rid, step):
    """Full platform row of one observation step, minus the bulky observation."""
    run_dir = resolve_run(root, rid)
    for row in read_jsonl(run_dir/STEPS):
        if row.get("step_index") == step:
            return {k: v for k, v in row.items() if k != "observation"}
    return None
