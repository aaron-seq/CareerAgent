"""Bounded SmartRecruiters pagination, with every HTTP response mocked."""

from __future__ import annotations

import httpx
import pytest

from core.db.repository import JobRepository
from core.ingestion import IngestionService, SmartRecruitersSource


def _page(ids: list[str], total: int | None = None) -> dict:
    data = {
        "content": [
            {"id": posting_id, "name": f"Role {posting_id}"} for posting_id in ids
        ]
    }
    if total is not None:
        data["totalFound"] = total
    return data


def _client(
    pages: dict[int, dict], list_calls: list[tuple[int, int]], detail_calls: list[str]
) -> httpx.Client:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/postings"):
            offset = int(request.url.params["offset"])
            list_calls.append((offset, int(request.url.params["limit"])))
            # An unexpected additional page is a test failure, not a live call.
            return httpx.Response(200, json=pages[offset])
        posting_id = request.url.path.rsplit("/", 1)[1]
        detail_calls.append(posting_id)
        return httpx.Response(
            200,
            json={
                "postingUrl": f"https://jobs.smartrecruiters.com/Acme/{posting_id}",
                "jobAd": {"sections": {"jobDescription": {"text": "<p>Build.</p>"}}},
            },
        )

    return httpx.Client(transport=httpx.MockTransport(respond))


def test_later_pages_are_ingested_and_keep_the_original_source(session):
    calls, details = [], []
    with _client(
        {0: _page(["a", "b"], 3), 2: _page(["c"], 3)}, calls, details
    ) as client:
        result = IngestionService(session).ingest(
            SmartRecruitersSource("Acme"), client=client, limit=2
        )
    session.commit()

    assert not result.errors
    assert not result.warnings
    assert result.fetched == result.upserted == 3
    assert calls == [(0, 2), (2, 2)]
    assert details == ["a", "b", "c"]
    rows = JobRepository(session).list()
    assert {row.source_id for row in rows} == {"a", "b", "c"}
    assert {row.source for row in rows} == {"smartrecruiters"}
    assert all(row.url.endswith(f"/Acme/{row.source_id}") for row in rows)
    assert all(row.description == "Build." for row in rows)


def test_overlapping_pages_fetch_each_detail_once():
    calls, details = [], []
    pages = {
        0: _page(["a", "b"], 6),
        2: _page(["b", "c"], 6),
        4: _page(["c", "d"], 6),
    }
    with _client(pages, calls, details) as client:
        jobs = SmartRecruitersSource("Acme").fetch(client, limit=2)

    assert [job.source_id for job in jobs] == ["a", "b", "c", "d"]
    assert details == ["a", "b", "c", "d"]
    assert calls == [(0, 2), (2, 2), (4, 2)]


def test_provider_ignoring_offset_stops_without_repeated_detail_calls():
    calls, details = [], []
    pages = {0: _page(["a", "b"], 5000), 2: _page(["a", "b"], 5000)}
    source = SmartRecruitersSource("Acme")
    with _client(pages, calls, details) as client:
        jobs = source.fetch(client, limit=2)

    assert len(jobs) == 2
    assert details == ["a", "b"]
    assert calls == [(0, 2), (2, 2)]
    assert "results may be incomplete" in source.warnings[0]


def test_repeated_last_page_warns_even_when_its_reported_total_is_reached():
    source = SmartRecruitersSource("Acme")
    with _client({0: _page(["a"], 2), 1: _page(["a"], 2)}, [], []) as client:
        assert len(source.fetch(client, limit=1)) == 1

    assert "results may be incomplete" in source.warnings[0]


def test_empty_page_stops_even_when_total_is_stale():
    calls, details = [], []
    with _client({0: _page(["a"], 5000), 1: _page([], 5000)}, calls, details) as client:
        jobs = SmartRecruitersSource("Acme").fetch(client, limit=1)

    assert len(jobs) == 1
    assert calls == [(0, 1), (1, 1)]


def test_missing_total_stops_on_a_short_page():
    calls, details = [], []
    with _client({0: _page(["a", "b"]), 2: _page(["c"])}, calls, details) as client:
        jobs = SmartRecruitersSource("Acme").fetch(client, limit=2)

    assert len(jobs) == 3
    assert calls == [(0, 2), (2, 2)]


def test_job_budget_reduces_final_page_and_stops_extra_requests():
    calls, details = [], []
    pages = {0: _page(["a", "b"], 5000), 2: _page(["c"], 5000)}
    source = SmartRecruitersSource("Acme")
    with _client(pages, calls, details) as client:
        jobs = source.fetch(client, limit=2, max_jobs=3)

    assert len(jobs) == 3
    assert calls == [(0, 2), (2, 1)]
    assert details == ["a", "b", "c"]
    assert "continue with offset=3" in source.warnings[0]


def test_page_budget_stops_a_board_with_an_unbounded_total():
    calls, details = [], []
    source = SmartRecruitersSource("Acme")
    with _client(
        {0: _page(["a"], 5000), 1: _page(["b"], 5000)}, calls, details
    ) as client:
        jobs = source.fetch(client, limit=1, max_pages=2)

    assert len(jobs) == 2
    assert calls == [(0, 1), (1, 1)]
    assert "continue with offset=2" in source.warnings[0]


def test_partial_import_warning_reaches_the_service_result(session):
    calls, details = [], []
    with _client({0: _page(["a"], 2)}, calls, details) as client:
        result = IngestionService(session).ingest(
            SmartRecruitersSource("Acme"), client=client, max_jobs=1
        )

    assert result.fetched == result.upserted == 1
    assert not result.errors
    assert "continue with offset=1" in result.warnings[0]


def test_completing_a_board_at_the_budget_has_no_warning():
    calls, details = [], []
    source = SmartRecruitersSource("Acme")
    with _client({0: _page(["a"], 1)}, calls, details) as client:
        assert len(source.fetch(client, max_jobs=1, max_pages=1)) == 1

    assert not source.warnings


def test_source_warnings_do_not_leak_into_a_later_complete_fetch():
    source = SmartRecruitersSource("Acme")
    with _client({0: _page(["a"], 2)}, [], []) as client:
        source.fetch(client, max_jobs=1)
    assert source.warnings
    with _client({0: _page(["a"], 1)}, [], []) as client:
        source.fetch(client)
    assert not source.warnings


def test_explicit_offset_can_fetch_a_later_portion():
    calls, details = [], []
    with _client({100: _page(["later"], 101)}, calls, details) as client:
        jobs = SmartRecruitersSource("Acme").fetch(client, offset=100)

    assert [job.source_id for job in jobs] == ["later"]
    assert calls == [(100, 25)]


def test_missing_posting_ids_are_not_fetched_as_none():
    calls, details = [], []
    pages = {0: {"content": [{"name": "No ID"}, None], "totalFound": 5000}}
    with _client(pages, calls, details) as client:
        assert SmartRecruitersSource("Acme").fetch(client) == []

    assert calls == [(0, 25)]
    assert details == []


@pytest.mark.parametrize(
    "list_payload, detail_payload, message",
    [
        ([], {}, "list response"),
        ({"content": "wrong shape"}, {}, "content"),
        (_page(["a"], 1), [], "detail response"),
    ],
)
def test_malformed_api_shapes_are_reported_as_ingestion_errors(
    session, list_payload, detail_payload, message
):
    def respond(request):
        payload = (
            list_payload if request.url.path.endswith("/postings") else detail_payload
        )
        return httpx.Response(200, json=payload)

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result = IngestionService(session).ingest(
            SmartRecruitersSource("Acme"), client=client
        )

    assert result.fetched == result.upserted == 0
    assert len(result.errors) == 1
    assert f"Invalid SmartRecruiters {message}" in result.errors[0]


@pytest.mark.parametrize(
    "options",
    [
        {"limit": 0},
        {"limit": 101},
        {"offset": -1},
        {"offset": True},
        {"max_jobs": 0},
        {"max_jobs": 1001},
        {"max_pages": 0},
        {"max_pages": 101},
        {"max_pages": "2"},
    ],
)
def test_invalid_pagination_options_fail_before_network(options):
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: pytest.fail("Unexpected HTTP request"))
    ) as client:
        with pytest.raises(ValueError, match="Invalid SmartRecruiters"):
            SmartRecruitersSource("Acme").fetch(client, **options)
