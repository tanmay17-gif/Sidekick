"""Reproduce what Sidekick actually does with realistic requests.

This is the evidence harness behind ``docs/CAPABILITY_REALITY_AUDIT.md`` and
``docs/DECISION_FAILURES.md``. It sends real requests through the real ASGI
application and reports what the brain decided, what it executed and what the
user actually got.

**By default it has no external side effects.** The browser is stubbed, so
the report says which URL *would* have been opened without opening it. Pass
``--real-browser`` to actually open it - that is the only mode that touches
anything outside the process.

Usage::

    python scripts/reproduce_requests.py                 # deterministic fallback
    python scripts/reproduce_requests.py --model laya    # the real decision model
    python scripts/reproduce_requests.py --real-browser  # actually open the browser
    python scripts/reproduce_requests.py --json out.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from sidekick.bootstrap import build_engine  # noqa: E402
from sidekick.core.schemas import ActionStatus  # noqa: E402

#: The requests the audit is built on.
REQUESTS: list[str] = [
    "Open YouTube.",
    "Play some relaxing music.",
    "Find a good movie for tonight.",
    "Remind me to call my friend at 6 PM.",
    "Write a note saying I need to finish the hackathon.",
    "Help me debug this Python error.",
    "Fix the failing tests in my project.",
    "Search for flights to Delhi next Friday.",
    "Order dinner for me.",
    "Stop what you're doing.",
    "No, I meant Spotify, not YouTube.",
    "What can you actually do?",
    "xyzzy plugh.",
]


def describe(action: dict) -> dict:
    """What actually happened to one action."""
    error = action.get("error")
    return {
        "tool": action.get("tool"),
        "state": action.get("state"),
        "arguments": action.get("arguments"),
        "approval_required": action.get("approval_required"),
        "result": action.get("result"),
        "error_code": error.get("code") if error else None,
        "error_message": error.get("message") if error else None,
    }


def run(model: str = "rule", workspace: str | None = None, real_browser: bool = False) -> list[dict]:
    opened: list[str] = []

    if not real_browser:
        # No external side effects by default: the harness reports which URL
        # would have been opened instead of opening it.
        def fake_open(url: str, *args, **kwargs) -> bool:
            opened.append(url)
            return True

        webbrowser.open = fake_open  # type: ignore[assignment]

    engine = build_engine(prefer_model=model, workspace=workspace)
    client = TestClient(_app(engine))
    rows: list[dict] = []
    for index, utterance in enumerate(REQUESTS):
        started = time.perf_counter()
        response = client.post(
            "/api/v1/requests",
            headers={"X-Sidekick-Session-Id": "audit"},
            json={
                "request_id": f"audit-{index}",
                "session_id": "audit",
                "utterance": utterance,
                "input_source": "voice",
                "utterance_finalized": True,
            },
        )
        elapsed = (time.perf_counter() - started) * 1000.0
        body = response.json()
        rows.append(
            {
                "utterance": utterance,
                "http_status": response.status_code,
                "status": body.get("status"),
                "intent_normalized": body.get("intent", {}).get("normalized"),
                "intent_confidence": body.get("intent", {}).get("confidence"),
                "intent_source": body.get("intent", {}).get("source"),
                "decision_model": body.get("decision_model", {}),
                "risk_level": body.get("risk_level"),
                "clarification": body.get("clarification"),
                "speech": body.get("speech"),
                "message": body.get("message"),
                "actions": [describe(action) for action in body.get("action_plan", [])],
                "latency_ms": round(elapsed, 1),
            }
        )
    rows.append({"utterance": "__opened_urls__", "actions": [], "status": "info",
                 "message": ", ".join(opened) if opened else "none"})
    return rows


def _app(engine):
    from sidekick.api.app import create_app

    return create_app(engine)


def render(rows: list[dict]) -> None:
    header = (
        f"{'REQUEST':<44} {'TOOL':<18} {'STATE':<20} {'SRC':<6} "
        f"{'CONFIRM':<8} {'ERROR':<24} RESULT"
    )
    print(header)
    print("-" * len(header))
    for row in rows:
        if row.get("status") == "info":
            print(f"\nURLs the code would open (not opened): {row.get('message')}")
            continue
        actions = row["actions"] or [{}]
        for index, action in enumerate(actions):
            request = row["utterance"] if index == 0 else ""
            result = action.get("result")
            if isinstance(result, dict):
                result = json.dumps(result)[:60]
            print(
                f"{request[:43]:<44} {str(action.get('tool'))[:17]:<18} "
                f"{str(action.get('state'))[:19]:<20} "
                f"{str(row['decision_model'].get('source'))[:5]:<6} "
                f"{str(action.get('approval_required'))[:7]:<8} "
                f"{str(action.get('error_code'))[:23]:<24} "
                f"{str(result)[:60]}"
            )
        if not row["actions"]:
            print(f"{row['utterance'][:43]:<44} {'<no plan>':<18}")
        if row.get("speech"):
            print(f"{'':<44} speech: {row['speech']}")
        if row.get("clarification"):
            print(f"{'':<44} clarify: {row['clarification'].get('question')}")
        print(
            f"{'':<44} ({row['status']}, {row['latency_ms']} ms, "
            f"model={row['decision_model'].get('model')}, "
            f"fallback={row['decision_model'].get('fallback_used')})"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="rule", help="rule | laya | auto")
    parser.add_argument("--json", default=None)
    parser.add_argument(
        "--real-browser",
        action="store_true",
        help="actually open the browser (the default only reports the URL)",
    )
    args = parser.parse_args()

    rows = run(args.model, real_browser=args.real_browser)
    render(rows)

    completed = [
        row
        for row in rows
        if any(a.get("state") == ActionStatus.SUCCEEDED.value for a in row["actions"])
    ]
    failed = [
        row
        for row in rows
        if row["actions"] and not any(a.get("state") == ActionStatus.SUCCEEDED.value for a in row["actions"])
    ]
    unplanned = [row for row in rows if not row["actions"]]
    print()
    print(f"requests              : {len(rows)}")
    print(f"something succeeded   : {len(completed)}")
    print(f"nothing succeeded     : {len(failed)}")
    print(f"no plan at all        : {len(unplanned)}")

    if args.json:
        target = Path(args.json)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")
        print(f"report written to {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
