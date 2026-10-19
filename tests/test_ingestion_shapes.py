"""Public provider envelopes fail clearly; HTTP is entirely mocked."""

from __future__ import annotations

import httpx
import pytest

from core.db.repository import JobRepository
from core.ingestion import (
    AdzunaSource,
    ArbeitnowSource,
    AshbySource,
    GreenhouseSource,
    HimalayasSource,
    IngestionService,
    JobicySource,
    LeverSource,
    RecruiteeSource,
    RemoteOKSource,
    RemotiveSource,
    SmartRecruitersSource,
    TheMuseSource,
    WorkableSource,
)


@pytest.mark.parametrize(
    "source, malformed",
    [
        (GreenhouseSource("acme"), []),
        (LeverSource("acme"), {}),
        (AshbySource("acme"), []),
        (SmartRecruitersSource("acme"), []),
        (RecruiteeSource("acme"), []),
        (WorkableSource("acme"), []),
        (ArbeitnowSource(), []),
        (JobicySource(), []),
        (RemoteOKSource(), {}),
        (HimalayasSource(), []),
        (AdzunaSource("test-id", "test-key"), []),
        (TheMuseSource(), []),
        (RemotiveSource(), []),
    ],
    ids=lambda value: getattr(value, "source", None),
)
def test_wrong_provider_envelope_is_isolated_before_persistence(
    session, source, malformed
):
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=malformed)
        )
    ) as client:
        result = IngestionService(session).ingest(source, client=client)

    assert result.fetched == 0
    assert result.upserted == 0
    assert len(result.errors) == 1
    assert "Invalid" in result.errors[0]
    assert "expected" in result.errors[0]
    assert "AttributeError" not in result.errors[0]
    assert JobRepository(session).list() == []


@pytest.mark.parametrize("body", ["null", "42", '"not an envelope"'])
def test_noncontainer_json_is_rejected_without_echoing_payload(session, body):
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text=body))
    ) as client:
        result = IngestionService(session).ingest(
            GreenhouseSource("acme"), client=client
        )
    assert result.errors == [
        "greenhouse: Invalid Greenhouse response: expected an object."
    ]
    assert result.fetched == result.upserted == 0
