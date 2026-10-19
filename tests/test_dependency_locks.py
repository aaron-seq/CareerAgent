"""Offline guard against stale manifests and incomplete generated hash locks."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[1]
LOCKS = ROOT / "requirements" / "locks"
TARGETS = ("311", "312", "313")


def _manifest(path: Path) -> list[Requirement]:
    requirements: list[Requirement] = []
    for line in path.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line.startswith("-r "):
            requirements.extend(_manifest(path.parent / line[3:].strip()))
        elif line:
            requirements.append(Requirement(line))
    return requirements


def _lock(path: Path) -> dict[str, Requirement]:
    result: dict[str, Requirement] = {}
    text = path.read_text().replace("\\\n", " ")
    for line in text.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        requirement, *hashes = line.split("--hash=")
        parsed = Requirement(requirement.strip())
        assert parsed.url is None and not parsed.extras
        specs = list(parsed.specifier)
        assert len(specs) == 1 and specs[0].operator == "=="
        assert "*" not in specs[0].version
        assert hashes and all(
            re.fullmatch(r"sha256:[a-f0-9]{64}", digest.strip()) for digest in hashes
        ), f"Missing or malformed distribution hash: {parsed.name}"
        name = canonicalize_name(parsed.name)
        assert name not in result
        result[name] = parsed
    assert result
    return result


@pytest.mark.parametrize("target", TARGETS)
@pytest.mark.parametrize(
    "kind,source", [("runtime", "requirements.txt"), ("test", "requirements-test.txt")]
)
def test_linux_hash_lock_covers_source_manifest(target, kind, source):
    path = LOCKS / f"{kind}-py{target}.txt"
    header = path.read_text().splitlines()[1]
    version = f"{target[0]}.{target[1:]}"
    assert f"--python-version {version}" in header
    assert "--python-platform x86_64-manylinux_2_28" in header
    locked = _lock(path)
    environment = {
        **default_environment(),
        "python_version": version,
        "python_full_version": version + ".0",
        "platform_python_implementation": "CPython",
        "sys_platform": "linux",
        "platform_machine": "x86_64",
    }
    for requirement in _manifest(ROOT / source):
        if requirement.marker and not requirement.marker.evaluate(environment):
            continue
        name = canonicalize_name(requirement.name)
        assert name in locked, f"Refresh {path.name}: missing {name}"
        version_pin = next(iter(locked[name].specifier)).version
        assert requirement.specifier.contains(version_pin), (
            f"Refresh {path.name}: {name}=={version_pin} violates {requirement}"
        )


@pytest.mark.parametrize("target", TARGETS)
def test_test_lock_uses_the_same_runtime_versions(target):
    runtime = _lock(LOCKS / f"runtime-py{target}.txt")
    tests = _lock(LOCKS / f"test-py{target}.txt")
    for name, requirement in runtime.items():
        assert name in tests and tests[name].specifier == requirement.specifier


def test_isolated_audit_tool_is_hash_locked():
    locked = _lock(LOCKS / "audit-py311.txt")
    for requirement in _manifest(ROOT / "requirements-audit.txt"):
        version_pin = next(
            iter(locked[canonicalize_name(requirement.name)].specifier)
        ).version
        assert requirement.specifier.contains(version_pin)
