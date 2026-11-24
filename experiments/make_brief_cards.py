"""Build the brief of condition A'' ("App"): the A' brief plus every knowledge card.

    python experiments/make_brief_cards.py            # write experiments/briefs/*.open.cards.json
    python experiments/make_brief_cards.py --check    # exit 1 if a committed file is stale

A'' gives the baseline agent, in its brief, the same card text that the reviewer
model of condition C receives: one JSON object per card, produced by
``Card.brief()`` and serialised exactly as ``llm_critic.system_prompt`` does,
in card-id order. Nothing is paraphrased, explained or reordered, and no
critic rule, review instruction or evaluator content is added.

The brief is the committed A' brief (``*.open.primed.json``) with two changes:
``condition`` becomes ``open_ended_cards``, and the card lines, preceded by one
heading note, are inserted between the A' safety sentence and the closing note.
"""
import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO/"src"))
from safelab.critic.knowledge import load_cards  # noqa: E402

BRIEFS = REPO/"experiments"/"briefs"
STEMS = ("waste_segregation_v1", "cell_lysis_normal_execution_v1")
HEADING = "Laboratory safety knowledge cards (one JSON object per line):"


def card_lines():
    """The card lines exactly as the LLM channel of the critic puts them in its system message."""
    cards = load_cards()
    cards = cards if isinstance(cards, dict) else {card.id: card for card in cards}
    return [json.dumps(cards[card_id].brief(), ensure_ascii=False) for card_id in sorted(cards)]


def build(stem):
    primed = json.loads((BRIEFS/f"{stem}.open.primed.json").read_text(encoding="utf-8"))
    notes = primed["operating_notes"]
    if len(notes) != 2 or not notes[0].startswith("Work safely:"):
        raise SystemExit(f"{stem}: the A' brief no longer has the two notes this script expects")
    brief = dict(primed, condition="open_ended_cards",
                 operating_notes=[notes[0], HEADING, *card_lines(), notes[1]])
    return json.dumps(brief, ensure_ascii=False, indent=2) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    stale = []
    for stem in STEMS:
        path, text = BRIEFS/f"{stem}.open.cards.json", build(stem)
        if args.check:
            # compare with line endings normalised: git may check the file out with CRLF
            if not path.exists() or path.read_bytes().replace(b"\r\n", b"\n") != text.encode():
                stale.append(path.name)
        else:
            path.write_text(text, encoding="utf-8", newline="\n")
            notes = len(json.loads(text)["operating_notes"])
            print(f"wrote {path.relative_to(REPO)} ({notes} notes)")
    if stale:
        print("stale or missing: " + ", ".join(stale))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
