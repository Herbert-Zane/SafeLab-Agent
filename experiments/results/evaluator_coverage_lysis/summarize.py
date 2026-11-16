"""S6: print per-sequence step status and evaluator consequences.

Usage: python summarize.py runs/s6_evalcov/runs
(run directories fetched from the server; runs/ is gitignored).
"""
import json
import pathlib
import sys

SEQUENCES = ("ctrl_fresh_tips", "p1_dirty_p200_into_ethanol",
             "p2_clean_return_to_ethanol", "p3_lysate_back_into_ethanol")
SKIP = {"evidence", "consequence_id", "entities", "type", "category", "occurred_time_s",
        "source_graph_revision", "source_event_id", "model_id", "model_version"}


def jsonl(path):
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def main(root):
    for name in SEQUENCES:
        run = root / name
        print("=" * 30, name)
        steps = jsonl(run / "agent_steps.jsonl")
        bad = [(s["step_index"], s.get("status"), (s.get("feedback_in") or "")[:300])
               for s in steps if s.get("status") not in ("complete", "finished_by_agent")]
        print("n_steps", len(steps), "non-complete:", bad)
        ev = json.loads((run / "trajectory_evaluation.json").read_text(encoding="utf-8"))
        print("execution_status:", ev["execution_status"],
              "| task_completion:", ev["task_completion"]["status"])
        for check in ev["task_completion"]["checks"]:
            if check.get("status") != "achieved":
                print("  check:", json.dumps(check, ensure_ascii=False)[:600])
        for dim in ("scientific_integrity", "safety"):
            section = ev[dim]
            print(f"--- {dim}: status={section['status']} unassessed={section['unassessed']}")
            for c in section["consequences"]:
                print("   *", c["type"], c["entities"], c.get("model_id"), c.get("model_version"),
                      "t=", round(c["occurred_time_s"], 2), c["consequence_id"][:24])
                extra = {k: v for k, v in c.items() if k not in SKIP}
                print("     extra:", json.dumps(extra, ensure_ascii=False)[:700])
                inference = c.get("evidence", {}).get("inference", {})
                print("     inference ref:", inference.get("reference"))
            models = [(cv.get("type"), cv.get("model_id"), cv.get("model_version"))
                      for cv in section["coverage"]]
            print("   coverage models:", models)
        print("consequence_ids:", [i[:24] for i in ev["consequence_ids"]])
        final = steps[-1]["observation"]["entities"]
        for entity in final:
            if entity["entity_id"] in ("ethanol_95", "lysis_tube"):
                parts = {k: round(v, 1) for k, v in entity["components_ul"].items()}
                print("  final", entity["entity_id"], parts)


if __name__ == "__main__":
    main(pathlib.Path(sys.argv[1]))
