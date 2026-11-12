# Renamed task variants (snapshot)

Output of `eval/variants/make_renamed.py`, copied here from `runs/variants/` on 2026-11-12.

- **Provenance.** Every file is a copy of one of the platform's own task configs or agent
  briefs (BSLBench, commit `5837ec3`) with entity ids replaced by neutral ones. The scenes,
  criteria, goals and everything else in them are the platform author's work, not SafeLab's,
  and are not claimed as such.
- **Permission.** Kept in this private repository as test data with the platform author's
  agreement (given 2026-11-11). They are run through the platform's `main.py --config` /
  `run_agent.py --config`; no platform code is changed or copied.
- **Not read by the agent.** A task config holds the evaluator's criteria and goals. SafeLab's
  agent and reviewer never open these files; the platform reads them and hands the agent an
  observation that `assert_no_evaluator_state` has checked.
- **Regenerating.** `python eval/variants/make_renamed.py` writes a fresh set to
  `runs/variants/` (git-ignored), which is what the robustness suite and the tests read. This
  folder is the fixed copy to cite; if the platform commit changes, regenerate and replace it.

`mappings/` gives old id -> new id for each task and its fault variants.
The missing-item variants (`eval/robustness/make_missing.py`) are not covered by the agreement
and stay out of the repository.
