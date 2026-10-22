"""Verify the running backend over real HTTP.

This is the *real backend* check: a real uvicorn server, real HTTP requests,
the real adapters. It is deliberately separate from the pytest suite, which
uses the ASGI test client.

Usage::

    python scripts/verify_backend.py            # starts a server, checks it, stops it
    python scripts/verify_backend.py --url http://127.0.0.1:8000   # use a running one
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sidekick.api.app import create_app  # noqa: E402
from sidekick.bootstrap import build_engine  # noqa: E402


class Checker:
    def __init__(self) -> None:
        self.failures: list[str] = []
        self.passed = 0

    def check(self, name: str, condition: bool, detail: str = "") -> None:
        if condition:
            self.passed += 1
            print(f"  ok   {name}")
        else:
            self.failures.append(f"{name}{(' - ' + detail) if detail else ''}")
            print(f"  FAIL {name} {detail}")


def request(
    base: str,
    path: str,
    payload: dict | None = None,
    session: str = "verify",
    method: str | None = None,
) -> tuple[int, dict]:
    url = f"{base}{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method or ("POST" if data else "GET"))
    req.add_header("Content-Type", "application/json")
    req.add_header("X-Sidekick-Session-Id", session)
    try:
        with urllib.request.urlopen(req, timeout=180) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            return exc.code, json.loads(body)
        except json.JSONDecodeError:
            return exc.code, {"raw": body}


def run(base: str) -> Checker:
    checker = Checker()
    print(f"verifying {base}")

    status, health = request(base, "/healthz")
    checker.check("healthz answers", status == 200, str(status))
    checker.check(
        "healthz reports the model truthfully",
        "provider" in health.get("model", {}) and "fallback_used" in health.get("model", {}),
    )

    status, capabilities = request(base, "/api/v1/capabilities")
    checker.check("capabilities answer", status == 200, str(status))
    states = {item["id"]: item["state"] for item in capabilities.get("capabilities", [])}
    checker.check("a server capability is live", states.get("note.write") == "live", str(states))
    client_states = {
        item["id"]: item["state"] for item in capabilities.get("client_capabilities", [])
    }
    checker.check(
        "a client capability is reported as client",
        client_states.get("media.play") == "client",
        str(client_states),
    )
    checker.check(
        "the server states stay inside the vocabulary the browser renders",
        set(states.values())
        <= {"live", "simulated", "unavailable", "unconfigured", "disconnected"},
        str(set(states.values())),
    )
    checker.check(
        "an unimplemented capability is not live",
        all(state != "live" for name, state in states.items() if name.startswith("future.")),
    )

    status, body = request(
        base,
        "/api/v1/requests",
        {"request_id": "v1", "session_id": "verify", "utterance": "open youtube"},
    )
    checker.check("an ordinary request is answered", status == 200, str(status))
    checker.check(
        "an ordinary request reaches a capability",
        body.get("action_plan") and body["action_plan"][0]["tool"] == "media.open",
        json.dumps(body.get("action_plan"))[:120],
    )
    checker.check(
        "the response reports the decision source",
        body.get("decision_model", {}).get("source") in ("model", "rule"),
    )

    status, body = request(
        base,
        "/api/v1/requests",
        {"request_id": "v2", "session_id": "verify", "utterance": "order me a pizza"},
    )
    checker.check(
        "an unsupported request is refused",
        body.get("status") == "needs_clarification",
        str(body.get("status")),
    )
    checker.check(
        "an unsupported request runs nothing",
        all(a["tool"] == "unresolved" for a in body.get("action_plan", [])),
    )
    checker.check(
        "the refusal names the limitation",
        "do not have a capability" in (body.get("clarification") or {}).get("question", ""),
    )

    status, body = request(
        base,
        "/api/v1/requests",
        {"request_id": "v3", "session_id": "verify", "utterance": "No, I meant Spotify, not YouTube"},
    )
    checker.check(
        "a correction keeps the corrected intent",
        body.get("action_plan")
        and body["action_plan"][0].get("arguments", {}).get("destination") == "spotify",
        json.dumps(body.get("action_plan"))[:140],
    )

    status, body = request(
        base,
        "/api/v1/requests",
        {"request_id": "v4", "session_id": "verify", "utterance": "What can you actually do?"},
    )
    inventory = (body.get("action_plan") or [{}])[0].get("result", {}).get("capabilities", [])
    checker.check(
        "capability discovery answers with the inventory",
        bool(inventory) and any(item["id"] == "note.write" for item in inventory),
    )
    checker.check(
        "capability discovery separates the server from the client",
        any(item["state"] == "client" for item in inventory)
        and any(item["state"] == "live" for item in inventory),
    )

    status, body = request(
        base,
        "/api/v1/requests",
        {"request_id": "v5", "session_id": "verify", "utterance": "play some relaxing music"},
    )
    action = (body.get("action_plan") or [{}])[0]
    checker.check(
        "a client capability waits for the client",
        action.get("state") == "pending"
        and (action.get("result") or {}).get("status") == "awaiting_client",
        json.dumps(action)[:140],
    )

    if action.get("action_id"):
        status, body = request(
            base,
            f"/v1/actions/{action['action_id']}/complete",
            {"session_id": "verify", "status": "succeeded", "result": {"client": "reported"}},
        )
        checker.check("the client report is recorded", status == 200, str(status))
        checker.check(
            "the recorded result is the client's",
            (body.get("action") or {}).get("result") == {"client": "reported"},
        )

    status, body = request(
        base,
        "/api/v1/requests",
        {"request_id": "v6", "session_id": "verify", "utterance": "delete everything"},
    )
    checker.check("a request without a capability is refused", status == 200, str(status))

    return checker


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=None, help="a running backend (default: start one)")
    parser.add_argument("--port", type=int, default=8127)
    args = parser.parse_args()

    server = None
    base = args.url
    if base is None:
        import uvicorn

        engine = build_engine()
        config = uvicorn.Config(create_app(engine), host="127.0.0.1", port=args.port, log_level="error")
        server = uvicorn.Server(config)
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{args.port}"
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                urllib.request.urlopen(f"{base}/healthz", timeout=2).read()
                break
            except Exception:
                time.sleep(0.2)

    try:
        checker = run(base)
    finally:
        if server is not None:
            server.should_exit = True
            time.sleep(0.5)

    print()
    print(f"checks passed : {checker.passed}")
    print(f"checks failed : {len(checker.failures)}")
    for failure in checker.failures:
        print(f"  - {failure}")
    return 1 if checker.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
