"""Operational commands fail visibly without sending real notifications."""

from __future__ import annotations

import subprocess

import httpx
import pytest
from sqlalchemy.exc import OperationalError

from scripts import check, send_digest, smoke_docker


@pytest.fixture
def delivery_env(monkeypatch):
    for key in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "DISCORD_WEBHOOK_URL"):
        monkeypatch.delenv(key, raising=False)


def test_default_checks_cover_types_python_format_and_extension(monkeypatch):
    calls = []
    monkeypatch.setattr(
        check,
        "_run",
        lambda command, cwd=check.ROOT: calls.append((command, cwd)) or True,
    )
    assert check.main([]) == 0
    assert [command[1:3] for command, _ in calls[:4]] == [
        ["-m", "ruff"],
        ["-m", "ruff"],
        ["-m", "mypy"],
        ["-m", "pytest"],
    ]
    assert calls[-1] == (["node", "--test"], check.ROOT / "extension")
    assert not any("docker" in command for command, _ in calls)


def test_type_errors_fail_the_shared_check(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(
        check, "_run", lambda command, cwd=check.ROOT: calls.append(command) or False
    )
    assert check.main(["type"]) == 1
    assert calls == [[check.sys.executable, "-m", "mypy", "."]]
    assert "Checks failed: type" in capsys.readouterr().err


def test_lint_failure_still_runs_format(monkeypatch, capsys):
    results = iter((False, True))
    calls = []

    def run(command, cwd=check.ROOT):
        calls.append(command)
        return next(results)

    monkeypatch.setattr(check, "_run", run)
    assert check.main(["lint"]) == 1
    assert len(calls) == 2
    assert "Checks failed: lint" in capsys.readouterr().err


def test_missing_command_reports_which_tool(monkeypatch, capsys):
    def missing(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(check.subprocess, "run", missing)
    assert check._run(["node", "--test"]) is False
    assert "Required command not found: node" in capsys.readouterr().err


def test_docker_failure_does_not_attempt_start(monkeypatch):
    calls = []
    monkeypatch.setattr(
        check, "_run", lambda command, cwd=check.ROOT: calls.append(command) or False
    )
    assert check.main(["docker"]) == 1
    assert len(calls) == 1
    assert calls[0][:2] == ["docker", "build"]


def test_docker_check_accepts_ca_as_one_argument(monkeypatch, tmp_path):
    bundle = tmp_path / "trusted bundle.pem"
    bundle.write_text("synthetic test CA")
    calls = []
    monkeypatch.setattr(
        check, "_run", lambda command, cwd=check.ROOT: calls.append(command) or True
    )
    assert check.main(["docker", "--docker-ca-bundle", str(bundle)]) == 0
    assert f"id=pip_ca_bundle,src={bundle}" in calls[0]
    assert "scripts.smoke_docker" in calls[1]


def test_unknown_check_fails_before_running(monkeypatch):
    monkeypatch.setattr(check, "_run", lambda *args: pytest.fail("unexpected command"))
    with pytest.raises(SystemExit) as exc:
        check.main(["typo"])
    assert exc.value.code == 2


def test_docker_smoke_cleans_up_only_its_container(monkeypatch):
    calls = []

    def docker(*args):
        calls.append(args)
        stdout = "true" if args[0] == "inspect" else "ok"
        return subprocess.CompletedProcess(args, 0, stdout=stdout)

    monkeypatch.setattr(smoke_docker, "_docker", docker)
    assert smoke_docker.main(["--image", "synthetic:check"]) == 0
    app_call = next(call for call in calls if smoke_docker.APP_SMOKE in call)
    name = app_call[app_call.index("--name") + 1]
    volume = calls[0][-1]
    assert name.startswith("careeragent-check-")
    assert calls[-2] == ("rm", "--force", name)
    assert calls[-1] == ("volume", "rm", volume)
    assert any(smoke_docker.PERSISTENCE_SMOKE in call for call in calls)
    for call in calls:
        if call[0] == "run":
            assert "--network" in call and "none" in call
            assert f"type=volume,src={volume},dst=/app/careeragent_data" in call
            assert "CAREERAGENT_ENCRYPTION_KEY=" in call


def test_docker_smoke_cleans_up_after_start_timeout(monkeypatch):
    calls = []

    def docker(*args):
        calls.append(args)
        if "--detach" in args:
            raise subprocess.TimeoutExpired("docker", 30)
        return subprocess.CompletedProcess(args, 0, stdout="")

    monkeypatch.setattr(smoke_docker, "_docker", docker)
    assert smoke_docker.main([]) == 1
    assert calls[-2][:2] == ("rm", "--force")
    assert calls[-1][:2] == ("volume", "rm")


def test_docker_smoke_cleans_up_when_app_screen_crashes(monkeypatch):
    calls = []

    def docker(*args):
        calls.append(args)
        if smoke_docker.APP_SMOKE in args:
            raise subprocess.CalledProcessError(1, "docker")
        return subprocess.CompletedProcess(args, 0, stdout="")

    monkeypatch.setattr(smoke_docker, "_docker", docker)
    assert smoke_docker.main([]) == 1
    assert not any("--detach" in call for call in calls)
    assert calls[-2][:2] == ("rm", "--force")
    assert calls[-1][:2] == ("volume", "rm")


def test_docker_smoke_reports_early_exit(monkeypatch, capsys):
    def docker(*args):
        return subprocess.CompletedProcess(args, 0, stdout="false")

    monkeypatch.setattr(smoke_docker, "_docker", docker)
    assert smoke_docker.main([]) == 1
    assert "stopped before becoming healthy" in capsys.readouterr().err


def test_digest_dry_run_never_opens_delivery_client(
    temp_db, delivery_env, monkeypatch, capsys
):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "synthetic-token")
    monkeypatch.setattr(
        send_digest.httpx, "Client", lambda: pytest.fail("delivery attempted")
    )
    assert send_digest.main(["--dry-run"]) == 0
    assert "No new matching jobs" in capsys.readouterr().out


def test_digest_rejects_partial_telegram_before_database(
    delivery_env, monkeypatch, capsys
):
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "synthetic-chat")
    monkeypatch.setattr(send_digest, "init_db", lambda: pytest.fail("database opened"))
    assert send_digest.main([]) == 1
    assert (
        "requires both TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID"
        in capsys.readouterr().err
    )


def test_digest_no_channel_succeeds_without_delivery(
    temp_db, delivery_env, monkeypatch, capsys
):
    monkeypatch.setattr(
        send_digest.httpx, "Client", lambda: pytest.fail("delivery attempted")
    )
    assert send_digest.main([]) == 0
    assert "No delivery channel configured" in capsys.readouterr().err


def test_digest_database_error_hides_connection_details(
    delivery_env, monkeypatch, capsys
):
    def broken_db():
        raise OperationalError(
            "postgres://secret-password@host", None, Exception("private data")
        )

    monkeypatch.setattr(send_digest, "init_db", broken_db)
    assert send_digest.main(["--dry-run"]) == 1
    stderr = capsys.readouterr().err
    assert "DATABASE_URL" in stderr and "OperationalError" in stderr
    assert "secret-password" not in stderr and "private data" not in stderr


@pytest.mark.parametrize("invalid_url", [False, True])
def test_digest_failed_channel_returns_failure_and_other_channel_runs(
    temp_db, delivery_env, monkeypatch, capsys, invalid_url
):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "synthetic-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "synthetic-chat")
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://example.org/synthetic-webhook")
    calls = []

    def failed_telegram(*args):
        calls.append("Telegram")
        if invalid_url:
            raise httpx.InvalidURL("SYNTHETIC_PRIVATE_VALUE")
        return False

    monkeypatch.setattr(send_digest.TelegramEmitter, "send", failed_telegram)
    monkeypatch.setattr(
        send_digest.DiscordEmitter,
        "send",
        lambda *args: calls.append("Discord") or True,
    )
    assert send_digest.main([]) == 1
    assert calls == ["Telegram", "Discord"]
    captured = capsys.readouterr()
    assert "Telegram delivery failed" in captured.err
    assert "Discord digest delivered" in captured.out
    assert "SYNTHETIC_PRIVATE_VALUE" not in captured.err + captured.out


def test_digest_transport_error_hides_token(temp_db, delivery_env, monkeypatch, capsys):
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://example.org/synthetic-secret")

    def failed_send(*args):
        raise httpx.ConnectError("https://example.org/synthetic-secret")

    monkeypatch.setattr(send_digest.DiscordEmitter, "send", failed_send)
    assert send_digest.main([]) == 1
    stderr = capsys.readouterr().err
    assert "Discord delivery failed" in stderr
    assert "synthetic-secret" not in stderr


def test_digest_rejects_invalid_limit_before_database(monkeypatch):
    monkeypatch.setattr(send_digest, "init_db", lambda: pytest.fail("database opened"))
    with pytest.raises(SystemExit) as exc:
        send_digest.main(["--limit", "0", "--dry-run"])
    assert exc.value.code == 2


def test_digest_malformed_webhook_hides_secret_and_returns_failure(
    temp_db, delivery_env, monkeypatch, capsys
):
    # Exercise httpx's URL parsing, rather than mocking the emitter's exception.
    monkeypatch.setenv(
        "DISCORD_WEBHOOK_URL", "https://example.org:SYNTHETIC_WEBHOOK_TOKEN/path"
    )
    assert send_digest.main([]) == 1
    captured = capsys.readouterr()
    assert "Discord delivery failed" in captured.err
    assert "SYNTHETIC_WEBHOOK_TOKEN" not in captured.err + captured.out
