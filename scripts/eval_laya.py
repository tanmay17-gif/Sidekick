"""Evaluate the real Laya decision model against a small labelled set.

This script is the evidence that the model is really doing the work: it
reports per-utterance accuracy for the tool and the destination, plus the
latency of the model on this machine.

Usage::

    python scripts/eval_laya.py                 # both checkpoints
    python scripts/eval_laya.py --checkpoint english
    python scripts/eval_laya.py --json out.json

The labelled set is intentionally small and written against the *capability
catalog* rather than against demo sentences, so it measures "does the model
pick the right capability" and not "does the model memorise a script".
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sidekick.bootstrap import build_registry  # noqa: E402
from sidekick.core.decisions.laya_model import LayaDecisionModel  # noqa: E402
from sidekick.core.parsing import CONTROL_INTENT_DESCRIPTIONS  # noqa: E402

# (utterance, expected tool, expected destination)
CASES: list[tuple[str, str, str | None]] = [
    ("open spotify", "media.open", "spotify"),
    ("launch youtube for me", "media.open", "youtube"),
    ("open netflix", "media.open", "netflix"),
    ("write a note that the milk is out", "note.write", None),
    ("take a note about the meeting", "note.write", None),
    ("set a timer for 5 minutes", "timer.set", None),
    ("start a timer for 90 seconds", "timer.set", None),
    ("cancel that", "control.cancel", None),
    ("stop what you are doing", "control.cancel", None),
    ("pause", "control.pause", None),
    ("resume", "control.resume", None),
    ("what is pending?", "control.status", None),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", default=None, help="english | multilingual | typed-decisions")
    parser.add_argument("--json", default=None, help="write the report as JSON")
    parser.add_argument("--device", default=None)
    parser.add_argument(
        "--with-controls",
        action="store_true",
        help="also offer the control intents in the action question",
    )
    args = parser.parse_args()

    registry = build_registry()
    model = LayaDecisionModel(device=args.device, checkpoint=args.checkpoint)
    if not model.available:
        print("the 'laya' package is not installed - nothing to evaluate", file=sys.stderr)
        return 2

    questions = model.build_questions(registry.catalog)
    if args.with_controls:
        criteria = dict(questions["action"]["criteria"])
        criteria.update(CONTROL_INTENT_DESCRIPTIONS)
        questions["action"]["criteria"] = criteria
    router = model._ensure_router()  # noqa: SLF001 - evaluation needs the raw router

    tool_hits = 0
    destination_hits = 0
    destination_cases = 0
    below_floor = 0
    latencies: list[float] = []
    rows: list[dict[str, object]] = []

    #: The engine falls back to the deterministic matcher below this
    #: confidence, so a "miss" above the floor is a real miss.
    FLOOR = 0.35

    for utterance, expected_tool, expected_destination in CASES:
        started = time.perf_counter()
        if args.checkpoint:
            result = router.predict(utterance, questions, model=args.checkpoint)
        else:
            result = router.predict(utterance, questions)
        elapsed = (time.perf_counter() - started) * 1000.0
        latencies.append(elapsed)

        answers = result.get("answers", {})
        action = answers.get("action", {})
        destination = answers.get("destination", {})
        got_tool = action.get("choice")
        got_destination = destination.get("choice")
        tool_confidence = float(action.get("answer_confidence") or 0.0)
        destination_confidence = float(destination.get("answer_confidence") or 0.0)

        tool_ok = got_tool == expected_tool
        tool_hits += int(tool_ok)
        if not tool_ok and tool_confidence < FLOOR:
            below_floor += 1
        destination_ok = True
        if expected_destination is not None:
            destination_cases += 1
            destination_ok = got_destination == expected_destination
            destination_hits += int(destination_ok)

        rows.append(
            {
                "utterance": utterance,
                "expected_tool": expected_tool,
                "got_tool": got_tool,
                "tool_ok": tool_ok,
                "tool_confidence": tool_confidence,
                "expected_destination": expected_destination,
                "got_destination": got_destination,
                "destination_ok": destination_ok,
                "destination_confidence": destination_confidence,
                "latency_ms": round(elapsed, 1),
            }
        )
        flag = "ok " if tool_ok else "MISS"
        print(
            f"{flag} {utterance!r:45} tool={got_tool!s:15} p={tool_confidence:.3f} "
            f"dest={got_destination!s:12} p={destination_confidence:.3f} {elapsed:7.1f} ms"
        )

    report = {
        "checkpoint": args.checkpoint or "auto",
        "cases": len(CASES),
        "tool_accuracy": tool_hits / len(CASES),
        "tool_accuracy_above_floor": (tool_hits + below_floor) / len(CASES),
        "below_confidence_floor": below_floor,
        "destination_accuracy": (destination_hits / destination_cases) if destination_cases else None,
        "destination_cases": destination_cases,
        "latency_ms_mean": round(statistics.mean(latencies), 1),
        "latency_ms_max": round(max(latencies), 1),
        "control_intents": sorted(CONTROL_INTENT_DESCRIPTIONS),
        "rows": rows,
    }
    print()
    print(f"tool accuracy      : {report['tool_accuracy']:.0%}")
    print(f"tool accuracy with the deterministic fallback: {report['tool_accuracy_above_floor']:.0%}")
    if report["destination_accuracy"] is not None:
        print(f"destination accuracy: {report['destination_accuracy']:.0%}")
    print(f"latency mean / max : {report['latency_ms_mean']} ms / {report['latency_ms_max']} ms")

    if args.json:
        target = Path(args.json)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"report written to {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
