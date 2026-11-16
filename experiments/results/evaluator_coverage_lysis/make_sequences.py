"""Build the fixed action sequences for the S6 evaluator-coverage check.

Each sequence becomes a platform agent config with the ``scripted`` backend
(fixed replies, ``is_model: false``), so the platform's ``main.py`` executes
exactly these actions in the simulator and writes the usual
``trajectory_evaluation.json``. The base is the action list of the formal run
``open/A_cl_01`` (all of its actions that the platform carried out), with a
deliberate contamination step inserted.

    python make_sequences.py            # writes sequences/*.json next to this file

Exploratory check of the evaluator, not an agent run; nothing here is a model result.
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Carried-out actions of formal run open/A_cl_01 (agent_plan.json), indices 0..23.
BASE = [
    {"action": "pick_up", "target": "pipette_p200"},
    {"action": "attach_tip", "tip_id": "p200_tip"},
    {"action": "aspirate", "target": "sample_source", "volume_ul": 140},
    {"action": "dispense", "target": "lysis_tube", "volume_ul": 140},
    {"action": "eject_tip", "target": "tip_remover"},
    {"action": "put_down", "target": "pipette_p200", "support": "tool_dock_p200"},
    {"action": "close_lid", "target": "lysis_tube"},
    {"action": "press_button", "target": "vortex_station", "control": "power"},
    {"action": "pick_up", "target": "lysis_tube"},
    {"action": "vortex", "target": "lysis_tube", "duration_s": 15, "device": "vortex_station"},
    {"action": "put_down", "target": "lysis_tube", "support": "tube_rack"},
    {"action": "incubate", "target": "lysis_tube", "duration_s": 600,
     "condition": "room_temperature", "device": "ambient"},
    {"action": "open_lid", "target": "lysis_tube"},
    {"action": "pick_up", "target": "pipette_p1000"},
    {"action": "attach_tip", "tip_id": "p1000_tip"},
    {"action": "aspirate", "target": "ethanol_95", "volume_ul": 560},
    {"action": "dispense", "target": "lysis_tube", "volume_ul": 560},
    {"action": "eject_tip", "target": "tip_remover"},
    {"action": "put_down", "target": "pipette_p1000", "support": "tool_dock_p1000"},
    {"action": "close_lid", "target": "lysis_tube"},
    {"action": "pick_up", "target": "lysis_tube"},
    {"action": "vortex", "target": "lysis_tube", "duration_s": 15, "device": "vortex_station"},
    {"action": "put_down", "target": "lysis_tube", "support": "tube_rack"},
    {"action": "incubate", "target": "lysis_tube", "duration_s": 600,
     "condition": "room_temperature", "device": "ambient"},
]


def asp(target, v):
    return {"action": "aspirate", "target": target, "volume_ul": v}


def dis(target, v):
    return {"action": "dispense", "target": target, "volume_ul": v}


SEQUENCES = {
    # Control: fresh tip per reagent, the protocol order. Expected: no contamination.
    "ctrl_fresh_tips": BASE,
    # P1: the P200 tip that has just been in lysis_tube (AVL + sample) goes into
    # ethanol_95 and draws 140 uL, which goes to lysis_tube; the rest of the
    # ethanol (420 uL) is added later with a fresh P1000 tip as in the protocol.
    "p1_dirty_p200_into_ethanol": (
        BASE[:4] + [asp("ethanol_95", 140), dis("lysis_tube", 140)] + BASE[4:15]
        + [asp("ethanol_95", 420), dis("lysis_tube", 420)] + BASE[17:]),
    # P2: what formal run C_cl_01 attempted: ethanol drawn with a fresh P1000 tip is
    # dispensed back into ethanol_95 (tip has touched nothing else), then drawn again.
    "p2_clean_return_to_ethanol": (
        BASE[:16] + [dis("ethanol_95", 560), asp("ethanol_95", 560)] + BASE[16:]),
    # P3: after the ethanol goes into lysis_tube, the same P1000 tip draws 100 uL of
    # the lysate back out and dispenses it into ethanol_95, then draws 100 uL from
    # ethanol_95 back into lysis_tube.
    "p3_lysate_back_into_ethanol": (
        BASE[:17] + [asp("lysis_tube", 100), dis("ethanol_95", 100),
                     asp("ethanol_95", 100), dis("lysis_tube", 100)] + BASE[17:]),
}

FINISH = {"action": "finish", "reason": "Fixed sequence complete (evaluator coverage check)."}


def config(name, steps):
    replies = ["```json\n" + json.dumps(s, ensure_ascii=False) + "\n```" for s in [*steps, FINISH]]
    return {
        "agent_schema_version": 1,
        "id": f"s6-scripted-{name}",
        "backend": {"provider": "scripted", "model": f"scripted_{name}", "replies": replies},
        # Same limits and failure policy as configs/agents/deepseek_flash.json (formal runs).
        "limits": {"max_steps": 40, "max_consecutive_invalid_replies": 3,
                   "max_invalid_replies": 10, "max_failed_actions": 10,
                   "max_total_tokens": None, "max_cost_usd": None,
                   "wall_clock_s": 3600, "max_simulation_duration_s": 60},
        "policy": {"conversation": "accumulate", "history_window": 12,
                   "on_action_failure": "report"},
    }


def main():
    out = HERE/"sequences"
    out.mkdir(exist_ok=True)
    for name, steps in SEQUENCES.items():
        (out/f"{name}.json").write_text(
            json.dumps(config(name, steps), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(name, len(steps) + 1, "replies")


if __name__ == "__main__":
    main()
