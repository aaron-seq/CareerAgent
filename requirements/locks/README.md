# Reviewed dependency graphs

The application requires Python **3.11+**. CI tests CPython 3.11, 3.12 and 3.13
on Linux x86_64. These are separate resolutions for those interpreter minors,
compiled for `x86_64-manylinux_2_28`; they are **not universal platform locks**.
Docker and the daily digest use the Python 3.11 runtime graph. A test graph
includes its identical runtime versions plus test/lint/type tools. The isolated
security scanner has a separate Python 3.11 graph.

Install in a fresh virtual environment, selecting its interpreter minor:

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install --require-hashes --only-binary=:all: \
  -r requirements/locks/test-py311.txt
```

Use `runtime-py311.txt` for an application-only installation. Substitute `312`
or `313` for the corresponding supported Python minor. Other operating systems
or architectures should resolve the source manifests and validate their own
graph; these files do not attest to those targets. Source installation remains
available with `python -m pip install -r requirements-test.txt` but intentionally
resolves current versions instead of reproducing this tested environment.

All direct and transitive versions are exact, with SHA-256 distribution hashes.
CI/Docker require those hashes and wheels, so a missing pin, changed artifact or
source-only build fails the installation. Python images, interpreters and OS
packages are outside these Python locks. Hashes do not establish publisher trust
or prove that an allowed release is safe.

## Refresh

Generation was tested with **uv 0.12.23**, used only as a development tool; pip
consumes the generated files without uv. Install that version in a separate
virtual environment if needed (`python -m pip install uv==0.12.23`). From the
repository root:

```bash
for minor in 3.11 3.12 3.13; do
  target="${minor//./}"
  uv pip compile requirements.txt --python-version "$minor" \
    --python-platform x86_64-manylinux_2_28 --only-binary=:all: \
    --generate-hashes --no-annotate \
    -o "requirements/locks/runtime-py${target}.txt"
  uv pip compile requirements-test.txt \
    -c "requirements/locks/runtime-py${target}.txt" \
    --python-version "$minor" --python-platform x86_64-manylinux_2_28 \
    --only-binary=:all: --generate-hashes --no-annotate \
    -o "requirements/locks/test-py${target}.txt"
done
uv pip compile requirements-audit.txt --python-version 3.11 \
  --python-platform x86_64-manylinux_2_28 --only-binary=:all: \
  --generate-hashes --no-annotate -o requirements/locks/audit-py311.txt
```

Existing output files are version preferences, so this refresh retains valid
pins. For a reviewed upgrade, append `--upgrade-package PACKAGE` to the runtime
compile command for each minor, then regenerate test graphs. Update an exact
source pin first when changing a test/tool dependency. Use `--upgrade` only for
an explicitly reviewed full refresh. Review the diff, install each graph in a
fresh environment, run `python -m scripts.check` and Docker smoke, and audit all
three resolved graphs before committing. The offline dependency-lock tests
reject missing hashes, source requirements that a lock no longer satisfies, or
runtime/test version differences.

## Coverage tooling

The test graphs include pytest-cov 7.1.0. Its 7.x migration delegates child-process
measurement to coverage.py; `pyproject.toml` enables the supported `subprocess`
patch so process-restart persistence tests keep contributing coverage. Refresh
the source pin and all three test locks together. Keep the runtime graphs
unchanged for a test-tool-only upgrade and compare coverage after migration.

## Advisory and upstream checks

CI audits each resolved test graph against the real PyPI advisory feed, with the
scanner running on Python 3.11. The resolved files encode each target's package
versions, so auditing does not re-resolve them against the scanner's interpreter.
It preserves JSON reports and fails on findings or collection/feed errors.
There are no ignored advisory IDs. To repeat the same audit locally:

```bash
python3.11 -m venv /tmp/careeragent-audit
/tmp/careeragent-audit/bin/python -m pip install --require-hashes \
  --only-binary=:all: -r requirements/locks/audit-py311.txt
for target in 311 312 313; do
  /tmp/careeragent-audit/bin/python -m pip_audit --strict \
    --vulnerability-service pypi --disable-pip --require-hashes \
    -r "requirements/locks/test-py${target}.txt" \
    --format json --output "/tmp/careeragent-audit-py${target}.json"
done
```

Weekly/manual CI also installs from the **unconstrained source manifests** and
runs the suite on all three supported minors, preserving the resolved versions.
A failure reports upstream drift without changing committed locks. Dependabot
monitors source requirements and immutable Action references; its manifest PRs
still require a reviewed lock refresh. Automatic regeneration of these custom
compiled files is not assumed.

## Security-driven compatibility change

The [2026-10-28 refresh](https://github.com/aaron-seq/CareerAgent/issues/87)
updates certifi to 2026.10.19, pypdf to 6.21.3 and Pillow to 13.0.0. Streamlit
1.66.1 is the compatibility bridge: its published metadata permits Pillow 13.
All unrelated pins and hashes stay unchanged. The unused Ollama Python SDK is
removed; `core/llm.py` uses HTTP and still requires the separate Ollama runtime
for local inference. No scanner suppressions or CI gates were relaxed.
See [Pillow release notes](https://pillow.readthedocs.io/en/stable/releasenotes/13.0.0.html),
[pypdf release notes](https://github.com/py-pdf/pypdf/releases/tag/6.21.3),
[Streamlit metadata](https://pypi.org/pypi/streamlit/1.66.1/json), and the
[PSF certifi notice](https://mail.python.org/archives/list/security-announce@python.org/thread/LSEJ6DOJPIHHNNRS43GROPIH2EPJRUDS/).

The 2026-10-17 audit found two affected installed packages: Pillow 11.3.0 and
pytest 7.4.3. The feed contained duplicate entries, so its 37-entry count is not
37 distinct confirmed flaws. Pillow's fixes require 12.3.0 and pytest's temporary
directory fix requires 9.0.3; both require Python >=3.10. Python 3.9 had additional
unfixed compatible dependencies. The approved runtime floor is 3.11, with
3.11–3.13 covered by fresh installs and CI. This changes interpreter support,
not the database format or encryption-key format.

Official references checked:

- [pip secure installs](https://pip.pypa.io/en/stable/topics/secure-installs/)
- [uv requirements compilation](https://docs.astral.sh/uv/pip/compile/)
- [pip-audit and supported advisory feeds](https://github.com/pypa/pip-audit)
- [Pillow 12.3 security release notes](https://github.com/python-pillow/Pillow/blob/12.3.0/docs/releasenotes/12.3.0.rst)
- [pytest 9.0.3 security fix](https://github.com/pytest-dev/pytest/blob/9.0.3/doc/en/changelog.rst)
- [Python 3.9 lifecycle](https://peps.python.org/pep-0596/) and
  [Python 3.10 lifecycle](https://peps.python.org/pep-0619/)

Some rendered documentation sites returned proxy 403 during validation; their
upstream maintained GitHub documentation sources were read instead.
