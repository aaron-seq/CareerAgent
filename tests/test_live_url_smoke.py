"""The opt-in live smoke harness itself is tested only with mocked HTTP."""

from __future__ import annotations

import gzip
import json

import httpx
import pytest

from core.ingestion.ats import GreenhouseSource, SmartRecruitersSource
from scripts import live_url_smoke as smoke


def _board(**overrides):
    item = {
        "id": 123,
        "title": "Engineer",
        "content": "<p>Build useful Python software.</p>",
        "absolute_url": "https://boards.greenhouse.io/example/jobs/123",
    }
    item.update(overrides)
    return {"jobs": [item]}


def _case():
    return smoke.SmokeCase("greenhouse", lambda: GreenhouseSource("example", "Example"))


def test_opt_in_is_required_before_any_network(monkeypatch, tmp_path):
    def forbidden_client():
        pytest.fail("No client may be constructed without --live")

    monkeypatch.setattr(smoke, "RecordingClient", forbidden_client)
    with pytest.raises(SystemExit) as exc:
        smoke.main(["--output", str(tmp_path / "report.json")])
    assert exc.value.code == 2
    assert not (tmp_path / "report.json").exists()


def test_records_all_checks_and_public_url_without_persisting_content():
    def respond(request):
        assert request.headers["user-agent"].startswith("CareerAgent/")
        assert request.extensions["timeout"]["read"] == smoke.REQUEST_TIMEOUT
        return httpx.Response(200, json=_board())

    with smoke.RecordingClient(transport=httpx.MockTransport(respond)) as client:
        result = smoke.run_case(_case(), client)
    assert result["status"] == "passed"
    assert result["parsed_count"] == 1
    assert all(
        check == {"passed": 1, "failed": 0} for check in result["checks"].values()
    )
    observation = result["requests"][0]
    assert observation["url"] == (
        "https://boards-api.greenhouse.io/v1/boards/example/jobs?content=true"
    )
    assert observation["http_status"] == 200
    assert observation["decoded_bytes"] > 0
    assert observation["started_at"] <= observation["finished_at"]
    assert "Build useful" not in json.dumps(result)


@pytest.mark.parametrize(
    ("payload", "expected", "failed_check"),
    [
        ({"jobs": []}, "empty", None),
        (_board(content=""), "failed", "description"),
        (_board(title=" "), "failed", "title"),
        (_board(absolute_url=""), "failed", "original_url"),
        (_board(id=None), "failed", "source_id"),
    ],
)
def test_empty_and_incomplete_results_are_never_passes(payload, expected, failed_check):
    with smoke.RecordingClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    ) as client:
        result = smoke.run_case(_case(), client)
    assert result["status"] == expected
    if failed_check:
        assert result["checks"][failed_check]["failed"] == 1


@pytest.mark.parametrize(
    ("status", "expected"),
    [(403, "blocked"), (429, "blocked"), (404, "failed"), (500, "failed")],
)
def test_records_http_denials_and_server_errors(status, expected):
    with smoke.RecordingClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(status))
    ) as client:
        result = smoke.run_case(_case(), client)
    assert result["status"] == expected
    assert result["parsed_count"] == 0
    assert result["requests"][0]["http_status"] == status
    assert result["error_type"] == "HTTPStatusError"


def test_network_failure_is_reported_separately_from_adapter_failure():
    def timeout(request):
        raise httpx.ConnectTimeout(
            "proxy credentials must not be copied", request=request
        )

    with smoke.RecordingClient(transport=httpx.MockTransport(timeout)) as client:
        result = smoke.run_case(_case(), client)
    assert result["status"] == "blocked"
    assert result["requests"][0]["error_type"] == "ConnectTimeout"
    assert result["requests"][0]["http_status"] is None
    assert "proxy credentials" not in json.dumps(result)


def test_response_size_is_bounded(monkeypatch):
    monkeypatch.setattr(smoke, "MAX_RESPONSE_BYTES", 10)
    with smoke.RecordingClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=b"x" * 11)
        )
    ) as client:
        result = smoke.run_case(_case(), client)
    assert result["status"] == "failed"
    assert result["error_type"] == "SmokeBudgetError"
    assert result["requests"][0]["decoded_bytes"] == 11


def test_compressed_payload_is_decoded_once():
    compressed = gzip.compress(json.dumps(_board()).encode())
    with smoke.RecordingClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, content=compressed, headers={"content-encoding": "gzip"}
            )
        )
    ) as client:
        result = smoke.run_case(_case(), client)
    assert result["status"] == "passed"


def test_request_budget_blocks_extra_requests():
    calls = []

    def respond(request):
        calls.append(request.url)
        return httpx.Response(200, json={})

    with smoke.RecordingClient(transport=httpx.MockTransport(respond)) as client:
        for _ in range(smoke.MAX_REQUESTS):
            client.get("https://api.example.test/jobs")
        with pytest.raises(smoke.SmokeBudgetError):
            client.get("https://api.example.test/jobs")
    assert len(calls) == smoke.MAX_REQUESTS


def test_swallowed_smartrecruiters_detail_denial_remains_blocked():
    def respond(request):
        if request.url.path.endswith("/123"):
            return httpx.Response(403)
        return httpx.Response(
            200, json={"content": [{"id": "123", "name": "Engineer"}], "totalFound": 1}
        )

    case = smoke.SmokeCase(
        "smartrecruiters",
        lambda: SmartRecruitersSource("Visa"),
        {"limit": 2, "max_jobs": 2, "max_pages": 1},
    )
    with smoke.RecordingClient(transport=httpx.MockTransport(respond)) as client:
        result = smoke.run_case(case, client)
    assert result["status"] == "blocked"
    assert result["parsed_count"] == 1
    assert result["checks"]["description"]["failed"] == 1
    assert [request["http_status"] for request in result["requests"]] == [200, 403]


def test_cli_writes_report_and_returns_nonzero_for_empty(monkeypatch, tmp_path):
    client_class = smoke.RecordingClient
    monkeypatch.setattr(
        smoke,
        "RecordingClient",
        lambda: client_class(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={"jobs": []})
            )
        ),
    )
    output = tmp_path / "reports" / "live.json"
    assert (
        smoke.main(["--live", "--sources", "greenhouse", "--output", str(output)]) == 1
    )
    report = json.loads(output.read_text())
    assert report["summary"] == {"empty": 1}
    assert report["results"][0]["source"] == "greenhouse"
    assert report["limits"]["requests_per_source"] == 3


@pytest.mark.parametrize("source", ["greenhouse", "lever", "ashby", "smartrecruiters"])
def test_careers_urls_route_locally_before_mocked_api_fetch(source, monkeypatch):
    case = next(case for case in smoke.CASES if case.source == source)
    calls = []
    original_detect = smoke.detect

    def recording_detect(url):
        calls.append(url)
        return original_detect(url)

    def respond(request):
        assert calls == [case.careers_url]
        assert str(request.url) != case.careers_url
        # An empty mock is sufficient here: this checks local routing order,
        # while the adapter's content assertions are covered separately.
        payload = [] if source == "lever" else {"jobs": [], "content": []}
        return httpx.Response(200, json=payload)

    monkeypatch.setattr(smoke, "detect", recording_detect)
    with smoke.RecordingClient(transport=httpx.MockTransport(respond)) as client:
        result = smoke.run_case(case, client)
    assert result["status"] == "empty"
    assert result["careers_url"] == case.careers_url
    assert result["careers_url_detection"]["passed"] is True
    assert result["careers_url_detection"]["detected_source"] == source
    assert result["careers_url_detection"]["detected_slug"] == case.board_slug
    assert "HTTP not tested" in result["careers_url_detection"]["method"]
    assert len(result["requests"]) == 1


def test_mismatched_careers_url_stops_before_any_network_request():
    def forbidden_request(request):
        pytest.fail("A mismatched careers URL must not reach the API")

    case = smoke.SmokeCase(
        "greenhouse",
        lambda: GreenhouseSource("stripe"),
        careers_url="https://jobs.lever.co/palantir",
        board_slug="stripe",
    )
    with smoke.RecordingClient(
        transport=httpx.MockTransport(forbidden_request)
    ) as client:
        result = smoke.run_case(case, client)
    assert result["status"] == "failed"
    assert result["careers_url_detection"]["passed"] is False
    assert result["requests"] == []
