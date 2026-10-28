"""Check a built image's imports, non-root user, and real Streamlit health.

The application container has no external network access or host port bindings.
Only the uniquely named container created here is removed during cleanup.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
import uuid

APP_SMOKE = """
import json
import os
from pathlib import Path

import streamlit
from streamlit.testing.v1 import AppTest

from core import facade
from core.db.crypto import decrypt_payload
from core.models import CVProfile
from core.storage import LocalStorage

assert os.geteuid() != 0
root = Path('/app')
for relative in ('docs', 'tests', 'extension', '.github', 'requirements-test.txt', 'requirements-audit.txt'):
    assert not (root / relative).exists(), f'Maintenance content shipped: {relative}'
assert not list((root / 'requirements/locks').glob('test-*.txt'))
assert not list((root / 'requirements/locks').glob('audit-*.txt'))
for relative in ('LICENSE', 'assets/fonts/LICENSE.txt', 'assets/fonts/DejaVuSans.ttf', 'assets/fonts/DejaVuSans-Bold.ttf', '.streamlit/config.toml', 'alembic.ini', 'requirements/locks/runtime-py311.txt'):
    assert (root / relative).is_file(), f'Missing runtime asset: {relative}'
app = AppTest.from_file('/app/app.py', default_timeout=20).run()
assert not app.exception
assert any(title.value == 'Onboarding' for title in app.title)
app.session_state['page'] = 'pipeline'
app.run()
assert not app.exception
assert any(title.value == 'Pipeline' for title in app.title)
profile = CVProfile(name='Synthetic smoke', email='smoke@example.test', raw_text='Synthetic smoke content')
profile_id = facade.persist_cv(profile)
assert facade.load_cv(profile_id).email == profile.email
path = Path(LocalStorage().save_cv_profile(profile))
assert profile.email not in path.read_text()
assert decrypt_payload(json.loads(path.read_text()))['email'] == profile.email
key = Path(os.environ['CAREERAGENT_KEY_PATH'])
assert key.exists() and key.stat().st_mode & 0o777 == 0o600
"""

PERSISTENCE_SMOKE = """
import json
from pathlib import Path
from core import facade
from core.db.crypto import decrypt_payload

profile = facade.load_cv(1)
assert profile.email == 'smoke@example.test'
paths = list(Path('/app/careeragent_data/cv_profiles').glob('*.json'))
assert len(paths) == 1
assert decrypt_payload(json.loads(paths[0].read_text()))['email'] == profile.email
"""


def _docker(*arguments: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", *arguments],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="careeragent:check")
    args = parser.parse_args(argv)
    name = f"careeragent-check-{uuid.uuid4().hex}"
    volume = f"{name}-data"
    created = False
    volume_created = False
    try:
        volume_created = True
        _docker("volume", "create", volume)
        runtime = [
            "--network",
            "none",
            "--name",
            name,
            "--mount",
            f"type=volume,src={volume},dst=/app/careeragent_data",
            "--env",
            "DATABASE_URL=sqlite:////app/careeragent_data/careeragent.db",
            "--env",
            "CAREERAGENT_KEY_PATH=/app/careeragent_data/.careeragent_key",
            "--env",
            "CAREERAGENT_ENCRYPTION_KEY=",
            "--env",
            "STORAGE_PATH=/app/careeragent_data",
        ]
        # Record ownership before starting, so cleanup also handles a Docker
        # client timeout after the daemon has created the container.
        created = True
        # Health alone passes even when Streamlit's app script crashes. Execute
        # the screens and a write on a fresh Compose-style volume first.
        _docker("run", "--rm", *runtime, args.image, "python", "-c", APP_SMOKE)
        # A replacement container must decrypt the same file and DB record with
        # the generated key retained on the volume.
        _docker("run", "--rm", *runtime, args.image, "python", "-c", PERSISTENCE_SMOKE)
        _docker("run", "--detach", *runtime, args.image)
        for _ in range(30):
            if (
                _docker(
                    "inspect", "--format", "{{.State.Running}}", name
                ).stdout.strip()
                != "true"
            ):
                print(
                    "Application container stopped before becoming healthy.",
                    file=sys.stderr,
                )
                return 1
            try:
                result = _docker(
                    "exec",
                    name,
                    "curl",
                    "--fail",
                    "--silent",
                    "--max-time",
                    "2",
                    "http://127.0.0.1:8501/_stcore/health",
                )
                if result.stdout.strip() == "ok":
                    print(
                        "Docker screens, encrypted persistence, non-root runtime, and Streamlit health passed."
                    )
                    return 0
            except subprocess.CalledProcessError:
                pass  # Streamlit may still be starting.
            time.sleep(1)
        print("Streamlit did not become healthy within 30 probes.", file=sys.stderr)
        return 1
    except (OSError, subprocess.SubprocessError) as exc:
        # Avoid dumping arbitrary application logs or environment values.
        print(f"Docker validation failed ({type(exc).__name__}).", file=sys.stderr)
        return 1
    finally:
        if created:
            try:
                _docker("rm", "--force", name)
            except (OSError, subprocess.SubprocessError):
                print(f"Could not clean up check container {name}.", file=sys.stderr)
        if volume_created:
            try:
                _docker("volume", "rm", volume)
            except (OSError, subprocess.SubprocessError):
                print(f"Could not clean up check volume {volume}.", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
