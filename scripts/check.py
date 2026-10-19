"""Run the repository's checks with one command, without installing a task runner.

``python -m scripts.check`` runs lint/format, mypy, Python and extension tests.
Select individual checks with ``python -m scripts.check lint test``. Docker is
opt-in: ``python -m scripts.check docker`` builds and starts the real image.
Install the development lock for your Python version and Node.js first.
No LLM or API keys are needed.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CHECKS = ("lint", "type", "test", "extension")


def _run(command: list[str], cwd: Path = ROOT) -> bool:
    print(f"\nRunning: {' '.join(command)}", flush=True)
    try:
        return subprocess.run(command, cwd=cwd, check=False).returncode == 0
    except FileNotFoundError:
        print(f"Required command not found: {command[0]}", file=sys.stderr)
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checks", nargs="*", metavar="CHECK")
    parser.add_argument(
        "--docker-ca-bundle",
        type=Path,
        help="trusted CA bundle for the Docker pip build step, if required",
    )
    args = parser.parse_args(argv)
    checks = list(dict.fromkeys(args.checks or DEFAULT_CHECKS))
    if any(check not in (*DEFAULT_CHECKS, "docker") for check in checks):
        parser.error("checks must be lint, type, test, extension, or docker")
    if args.docker_ca_bundle and not args.docker_ca_bundle.is_file():
        parser.error("--docker-ca-bundle must point to an existing file")

    commands = {
        "lint": [
            ([sys.executable, "-m", "ruff", "check", "."], ROOT),
            ([sys.executable, "-m", "ruff", "format", "--check", "."], ROOT),
        ],
        "type": [([sys.executable, "-m", "mypy", "."], ROOT)],
        "test": [
            (
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "tests/",
                    "-q",
                    "--cov=core",
                    "--cov-report=xml",
                    "--cov-report=term",
                ],
                ROOT,
            )
        ],
        "extension": [(["node", "--test"], ROOT / "extension")],
    }
    failed = []
    for check in checks:
        if check == "docker":
            image = "careeragent:check"
            build = ["docker", "build", "--tag", image]
            if args.docker_ca_bundle:
                build.extend(
                    [
                        "--secret",
                        f"id=pip_ca_bundle,src={args.docker_ca_bundle.resolve()}",
                    ]
                )
            build.append(".")
            passed = _run(build) and _run(
                [sys.executable, "-m", "scripts.smoke_docker", "--image", image]
            )
        else:
            # Run both lint and format even if one fails, so one invocation
            # reports all independent issues developers need to address.
            passed = all([_run(command, cwd) for command, cwd in commands[check]])
        if not passed:
            failed.append(check)

    if failed:
        print(f"\nChecks failed: {', '.join(failed)}", file=sys.stderr)
        return 1
    print(f"\nChecks passed: {', '.join(checks)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
