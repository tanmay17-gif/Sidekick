"""Check that the built distribution contains everything the project needs.

The repository ships **two** Python distributions in one project:

- ``sidekick`` - the core brain (Agent 1)
- ``sidekick_execution`` - the execution service (Agent 2)

and two console entry points, ``sidekick`` and ``sidekick-execution``.

This script builds a wheel from a copy of the tree and verifies the result, so
a future edit to ``pyproject.toml`` cannot silently drop the execution
service.

Usage::

    python scripts/check_packaging.py            # check the configuration only
    python scripts/check_packaging.py --build    # also build and inspect a wheel
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]

#: The packages the distribution must contain.
REQUIRED_PACKAGES = ("sidekick", "sidekick_execution")

#: The console entry points the distribution must declare.
REQUIRED_SCRIPTS = {
    "sidekick": "sidekick.api.app:main",
    "sidekick-execution": "sidekick_execution.__main__:main",
}

#: The dependencies the core needs at runtime.
REQUIRED_DEPENDENCIES = ("fastapi", "uvicorn", "pydantic")

#: The extras the project publishes.
REQUIRED_EXTRAS = ("laya", "dev", "aws")

#: A stand-in for the execution service, used when it is not in the tree.
SYNTHETIC_EXECUTION_PACKAGE = {
    "sidekick_execution/__init__.py": '"""stand-in for the execution service."""\n',
    "sidekick_execution/__main__.py": 'def main() -> None:\n    """stand-in."""\n',
}


def read_config() -> dict:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)


def check_configuration() -> list[str]:
    """The static checks. They do not need a build."""
    problems: list[str] = []
    config = read_config()
    project = config.get("project", {})

    scripts = project.get("scripts", {})
    for name, target in REQUIRED_SCRIPTS.items():
        if scripts.get(name) != target:
            problems.append(
                f"the console script '{name}' should point at '{target}', "
                f"found '{scripts.get(name)}'"
            )

    dependencies = {
        item.split(">")[0].split("=")[0].split("[")[0].strip().lower()
        for item in project.get("dependencies", [])
    }
    for dependency in REQUIRED_DEPENDENCIES:
        if dependency not in dependencies:
            problems.append(f"the dependency '{dependency}' is missing")

    extras = project.get("optional-dependencies", {})
    for extra in REQUIRED_EXTRAS:
        if extra not in extras:
            problems.append(f"the extra '{extra}' is missing")

    include = (
        config.get("tool", {})
        .get("setuptools", {})
        .get("packages", {})
        .get("find", {})
        .get("include", [])
    )
    if not include:
        problems.append("no package glob is configured")
    else:
        for package in REQUIRED_PACKAGES:
            if not any(
                package == pattern or pattern.rstrip("*") == package[: len(pattern.rstrip("*"))]
                for pattern in include
            ):
                problems.append(
                    f"the package '{package}' is not covered by the glob {include}"
                )
    return problems


def build_and_inspect() -> list[str]:
    """Build a wheel and check what is inside it."""
    problems: list[str] = []
    with tempfile.TemporaryDirectory() as raw:
        temp = Path(raw)
        tree = temp / "tree"
        tree.mkdir()

        shutil.copytree(ROOT / "sidekick", tree / "sidekick")
        for name in ("pyproject.toml", "README.md"):
            source = ROOT / name
            if source.exists():
                shutil.copy2(source, tree / name)

        # The execution service may not be in this branch (it is Agent 2's);
        # a stand-in proves the packaging would include it.
        execution = tree / "sidekick_execution"
        if not execution.exists():
            for relative, content in SYNTHETIC_EXECUTION_PACKAGE.items():
                target = tree / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "wheel",
                "--no-deps",
                "--no-build-isolation",
                "--wheel-dir",
                str(temp / "dist"),
                str(tree),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return [f"the build failed:\n{result.stdout[-2000:]}\n{result.stderr[-2000:]}"]

        wheels = list((temp / "dist").glob("*.whl"))
        if not wheels:
            return ["the build produced no wheel"]
        with zipfile.ZipFile(wheels[0]) as archive:
            names = archive.namelist()
            top_level = {name.split("/")[0] for name in names}
            for package in REQUIRED_PACKAGES:
                if package not in top_level:
                    problems.append(
                        f"the wheel does not contain '{package}' "
                        f"(it has: {sorted(top_level)})"
                    )
            entry_points = [
                name for name in names if name.endswith("entry_points.txt")
            ]
            if not entry_points:
                problems.append("the wheel has no entry points")
            else:
                content = archive.read(entry_points[0]).decode("utf-8")
                for name in REQUIRED_SCRIPTS:
                    if f"{name} =" not in content:
                        problems.append(f"the wheel has no console script '{name}'")
            if not any(name.startswith("sidekick/api/static/") for name in names):
                problems.append("the wheel does not contain the static slice page")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--build",
        action="store_true",
        help="also build a wheel and inspect its contents",
    )
    args = parser.parse_args()

    problems = check_configuration()
    if args.build:
        problems += build_and_inspect()

    if problems:
        print(f"packaging: {len(problems)} problem(s)")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("packaging: OK" + (" (configuration and wheel contents)" if args.build else " (configuration)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
