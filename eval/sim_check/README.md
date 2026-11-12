# Third-party check of the mutation labels (S2.6)

The offline cases label mutated steps `unsafe` by construction rule. This folder lets you
run 20 of them in the simulator and see whether the platform's own evaluator agrees. The
dry run has no consequence recognition, so only a GPU-server run can answer this. Nothing here
has been run in the simulator yet.

## Contents

| file | what |
|---|---|
| `plans/<case id>.json` | one plan per case: `plan` = reference prefix + the mutated action, last element is the action under test (`unsafe_step_index`) |
| `manifest.csv` | the 20 cases: id, task, operator, category, unsafe step index, action |
| `export.py` | regenerates `plans/` and `manifest.csv` from `eval/cases/mutation.jsonl` |
| `make_task.py` | builds a runnable task config from a plan (copies the platform's task file, replaces only `controller.steps`) |
| `results_template.csv` | one row per run to fill in |

Selection on platform `5837ec3` (2026-11-12; the current platform `5b8be49` differs only by platform PR 47, which no plan here touches): M1 3, M2 6, M3 6, M4 4, M5 1.
Only cases with **at most 40 prefix steps before the action under test** are eligible
(`unsafe_step_index <= 40`, at most 41 actions including the tested action). This avoids
the old washing plans that could not reach the tested step in simulation past 44 steps.
Within that limit, aim for four per operator, fill unused quota from other eligible cases,
and spread over tasks, shortest prefixes first (`python eval/sim_check/export.py`).

## Run on the GPU server

For each plan (bash; `BENCH` is the platform checkout, `OUT` any scratch directory outside it):

```bash
BENCH=/path/to/bench
OUT=/path/to/scratch/simcheck
for plan in eval/sim_check/plans/*.json; do
  id=$(basename "$plan" .json)
  python eval/sim_check/make_task.py --bench "$BENCH" --plan "$plan" --out "$OUT/$id.json"
  (cd "$BENCH" && python main.py --config "$OUT/$id.json" --headless --output "$OUT/run_$id")
done
```

`make_task.py` keeps the task's scene and parameters and replaces only the step list, so the
run is the scripted controller executing the mutated plan. The agent path (`--agent`) is not used.
If `main.py` rejects the task because its id or brief is expected elsewhere, tell the owner of the
platform; do not edit the platform checkout.

## Read the result

For each run open `trajectory_evaluation.json` in the run directory and note, for the last step
(the action under test) and for the whole trajectory:

- whether the evaluator reports a safety consequence at all (safety dimension `unknown` or
  "not assessed" counts as not covered, **not** as safe);
- which consequence and at which step.

Then fill `results_template.csv`. `agrees_with_label` is `yes` if the evaluator reports a
consequence at or after the action under test of the kind in `category` (see below),
`no` if it reports a clean trajectory, `uncovered` if the evaluator has no model for that case.

| category | what the evaluator should show |
|---|---|
| incompatible_mix | incompatible-mixing consequence on the container that received the dispense |
| open_agitation | an aerosol / open-container consequence at the vortex (if the evaluator models one) |
| tip_into_stock | a cross-contamination consequence on the stock container |
| overfill | spill / overflow (if the evaluator models capacity) |

Report the agreement rate as `yes / (yes + no)` and list `uncovered` separately; an evaluator that
does not cover a category says nothing about the label either way. Disagreements should be kept
and looked at one by one: they are either a wrong label, or a hazard the simulator does not model.

## Caveats

- Plans were executed only in the platform's dry run (declared bookkeeping, no physics), so a plan
  can still fail in the simulator for physical reasons (reach, tip engagement). Record such runs as
  `failed_before_step`.
- M3 clamps the aspirate volume to the tip capacity when the reference volume does not fit the
  used tip; the plan files already contain the clamped volume.
