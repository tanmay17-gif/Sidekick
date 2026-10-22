"""Check that the core and the other agents agree on contract v1.

The team works on four PCs, so drift is a real risk: the core, the execution
service (Agent 2) and the browser client (Agent 3) each have their own copy of
the contract. This script reads the *actual* contract definitions from the
other branches and compares them with what the core produces.

It is a verification tool, not a test: it needs the other branches to be
fetched, so it is not part of the CI suite. The same expectations are frozen
in ``tests/test_contract_compat.py`` so CI catches drift without the branches.

Usage::

    git fetch origin --prune
    python scripts/check_contract_compat.py
    python scripts/check_contract_compat.py --agent2-branch agent2/execution-foundation
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sidekick.core.schemas import (  # noqa: E402
    Action,
    ActionError,
    ActionStatus,
    Clarification,
    DecisionModelInfo,
    Event,
    IntentInfo,
    SidekickRequest,
    SidekickResponse,
)

GIT = "git"


def git_show(ref: str, path: str) -> str:
    proc = subprocess.run(
        [GIT, "show", f"{ref}:{path}"],
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout


# --------------------------------------------------------------------------
# Extraction helpers
# --------------------------------------------------------------------------

_TS_INTERFACE_RE = re.compile(
    r"export interface (?P<name>\w+)[^{]*\{(?P<body>.*?)\n\}", re.DOTALL
)
_TS_FIELD_RE = re.compile(r"^\s{2}(?P<name>[A-Za-z_]\w*)\??\s*:", re.MULTILINE)
_PY_LIST_RE = re.compile(r"^ACTION_STATES[^=]*=\s*\[(?P<body>.*?)\]", re.DOTALL | re.MULTILINE)
_PY_STRING_RE = re.compile(r'"([^"]+)"')


def ts_interface_fields(source: str, name: str) -> set[str]:
    """The field names of a TypeScript interface."""
    for match in _TS_INTERFACE_RE.finditer(source):
        if match.group("name") != name:
            continue
        body = match.group("body")
        fields = {m.group("name") for m in _TS_FIELD_RE.finditer(body)}
        # Index signatures are not real fields.
        return {f for f in fields if f != "key"}
    return set()


def py_action_states(source: str) -> set[str]:
    """The action state vocabulary the execution service implements.

    The list may be written with bare constant names (``[PENDING, ...]``), so
    the constants are resolved first.
    """
    constants = dict(re.findall(r"^([A-Z_]+)\s*=\s*[\"']([^\"']+)[\"']", source, re.MULTILINE))
    match = _PY_LIST_RE.search(source)
    if not match:
        return set()
    states: set[str] = set()
    for item in match.group("body").split(","):
        item = item.strip()
        if not item:
            continue
        if item.startswith(('"', "'")):
            states.add(item.strip("\"'"))
        elif item in constants:
            states.add(constants[item])
    return states


def py_from_dict_keys(source: str, class_name: str) -> set[str]:
    """The keys ``from_dict`` of a dataclass reads."""
    pattern = re.compile(
        rf"class {class_name}\b.*?def from_dict\(.*?\).*?(?=\n    @|\n    def |\nclass |\Z)",
        re.DOTALL,
    )
    match = pattern.search(source)
    if not match:
        return set()
    return set(re.findall(r"raw\.get\(\s*[\"']([^\"']+)[\"']", match.group(0)))


def model_field_names(model: Any) -> set[str]:
    """The field names a pydantic model exposes.

    ``model_fields`` does not include *computed* fields, but a computed field
    is part of the serialised payload just like any other. The core's
    ``Event.ts`` is one: the browser reads it, so the check must see it.
    """
    names = set(model.model_fields)
    computed = getattr(model, "model_computed_fields", None)
    if computed:
        names |= set(computed)
    return names


# --------------------------------------------------------------------------
# Comparison
# --------------------------------------------------------------------------


class Report:
    def __init__(self) -> None:
        self.problems: list[str] = []
        self.checks = 0

    def require(self, condition: bool, message: str) -> None:
        self.checks += 1
        if not condition:
            self.problems.append(message)

    def report(self) -> int:
        if not self.problems:
            print(f"contract compatibility: OK ({self.checks} checks)")
            return 0
        print(f"contract compatibility: {len(self.problems)} problem(s)")
        for problem in self.problems:
            print(f"  - {problem}")
        return 1


def check_execution_service(source: str, report: Report) -> None:
    """The execution service (Agent 2) must be able to read our actions."""
    states = py_action_states(source)
    mine = {state.value for state in ActionStatus}
    report.require(
        states == mine,
        f"action state vocabulary differs: execution service {sorted(states)} vs core {sorted(mine)}",
    )

    keys = py_from_dict_keys(source, "Action")
    mine_fields = model_field_names(Action)
    missing = keys - mine_fields
    report.require(
        not missing,
        f"the execution service reads action fields the core does not provide: {sorted(missing)}",
    )

    error_keys = py_from_dict_keys(source, "ActionError")
    mine_error = model_field_names(ActionError)
    missing_error = error_keys - mine_error
    report.require(
        not missing_error,
        f"the execution service reads error fields the core does not provide: {sorted(missing_error)}",
    )


def check_browser_client(source: str, report: Report) -> None:
    """The browser client (Agent 3) must be able to read our responses."""
    request_fields = ts_interface_fields(source, "SidekickRequest")
    mine_request = model_field_names(SidekickRequest)
    missing = request_fields - mine_request
    report.require(
        not missing,
        f"the browser client sends request fields the core rejects: {sorted(missing)}",
    )

    response_fields = ts_interface_fields(source, "SidekickResponse")
    mine_response = model_field_names(SidekickResponse)
    missing = response_fields - mine_response
    report.require(
        not missing,
        f"the browser client reads response fields the core does not provide: {sorted(missing)}",
    )

    action_fields = ts_interface_fields(source, "Action")
    mine_action = model_field_names(Action)
    missing = action_fields - mine_action
    report.require(
        not missing,
        f"the browser client reads action fields the core does not provide: {sorted(missing)}",
    )

    intent_fields = ts_interface_fields(source, "Intent")
    missing = intent_fields - model_field_names(IntentInfo)
    report.require(
        not missing,
        f"the browser client reads intent fields the core does not provide: {sorted(missing)}",
    )

    model_fields = ts_interface_fields(source, "DecisionModel")
    missing = model_fields - model_field_names(DecisionModelInfo)
    report.require(
        not missing,
        f"the browser client reads decision model fields the core does not provide: {sorted(missing)}",
    )

    clarification_fields = ts_interface_fields(source, "Clarification")
    missing = clarification_fields - model_field_names(Clarification)
    report.require(
        not missing,
        f"the browser client reads clarification fields the core does not provide: {sorted(missing)}",
    )

    event_fields = ts_interface_fields(source, "ProgressEvent")
    missing = event_fields - model_field_names(Event)
    report.require(
        not missing,
        f"the browser client reads event fields the core does not provide: {sorted(missing)}",
    )

    # The browser client must be able to parse our action states.
    states_match = re.search(
        r"export type ActionState\s*=\s*(.*?);", source, re.DOTALL
    )
    if states_match:
        client_states = set(_PY_STRING_RE.findall(states_match.group(1)))
        mine_states = {state.value for state in ActionStatus}
        extra = client_states - mine_states
        report.require(
            not extra,
            f"the browser client expects action states the core never produces: {sorted(extra)}",
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent2-branch", default="origin/agent2/execution-foundation")
    parser.add_argument("--agent3-branch", default="origin/agent3/voice-experience")
    args = parser.parse_args()

    report = Report()

    try:
        execution_source = git_show(args.agent2_branch, "sidekick_execution/contracts.py")
    except subprocess.CalledProcessError:
        print(
            f"could not read sidekick_execution/contracts.py from {args.agent2_branch}; "
            "run 'git fetch origin --prune' first",
            file=sys.stderr,
        )
        return 2
    check_execution_service(execution_source, report)

    try:
        browser_source = git_show(args.agent3_branch, "web/src/lib/api/types.ts")
    except subprocess.CalledProcessError:
        print(
            f"could not read web/src/lib/api/types.ts from {args.agent3_branch}; "
            "run 'git fetch origin --prune' first",
            file=sys.stderr,
        )
        return 2
    check_browser_client(browser_source, report)

    return report.report()


if __name__ == "__main__":
    raise SystemExit(main())
