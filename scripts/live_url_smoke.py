"""Opt-in smoke checks of public job APIs, without persisting or applying.

Run ``python -m scripts.live_url_smoke --live --output /tmp/live-results.json``.
This command performs real network reads. Ordinary pytest/CI remains mocked.
A pass checks normalized fields and source attribution, not job availability
at application time or the behavior of a browser/application submission.
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

import httpx

from core.fetching.ats_detection import detect
from core.ingestion.aggregators import RemotiveSource
from core.ingestion.ats import (
    AshbySource,
    GreenhouseSource,
    LeverSource,
    SmartRecruitersSource,
)
from core.ingestion.base import FetchedJob, JobSource
from core.ingestion.boards import ArbeitnowSource, HimalayasSource, JobicySource

MAX_REQUESTS = 3
MAX_RESPONSE_BYTES = 12 * 1024 * 1024
REQUEST_TIMEOUT = 15.0
BLOCKED_STATUSES = {401, 403, 407, 429, 451}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class SmokeCase:
    source: str
    factory: Callable[[], JobSource]
    params: dict = field(default_factory=dict)
    careers_url: str | None = None
    board_slug: str | None = None


CASES = (
    SmokeCase(
        "greenhouse",
        lambda: GreenhouseSource("stripe", "Stripe"),
        careers_url="https://boards.greenhouse.io/stripe",
        board_slug="stripe",
    ),
    SmokeCase(
        "lever",
        lambda: LeverSource("palantir", "Palantir"),
        careers_url="https://jobs.lever.co/palantir",
        board_slug="palantir",
    ),
    SmokeCase(
        "ashby",
        lambda: AshbySource("ramp", "Ramp"),
        careers_url="https://jobs.ashbyhq.com/ramp",
        board_slug="ramp",
    ),
    SmokeCase(
        "smartrecruiters",
        lambda: SmartRecruitersSource("Ubisoft2", "Ubisoft"),
        {"limit": 2, "max_jobs": 2, "max_pages": 1},
        careers_url="https://careers.smartrecruiters.com/Ubisoft2",
        board_slug="Ubisoft2",
    ),
    SmokeCase("remotive", RemotiveSource, {"search": "python"}),
    SmokeCase("arbeitnow", ArbeitnowSource),
    SmokeCase("jobicy", JobicySource, {"count": 5}),
    SmokeCase("himalayas", HimalayasSource, {"limit": 5}),
)


class SmokeBudgetError(RuntimeError):
    """The requested live operation exceeded the smoke-test budget."""


class RecordingClient(httpx.Client):
    """Record and bound the existing adapters' GET requests.

    httpx retains its normal TLS verification and environment proxy behavior.
    Streaming prevents a surprisingly large provider response from consuming
    unbounded memory. Only fixed API endpoints are selected by this command;
    returned application links are checked as strings, never followed.
    """

    def __init__(self, **kwargs):
        super().__init__(follow_redirects=False, **kwargs)
        self.observations: list[dict] = []

    def get(self, url: str, **kwargs) -> httpx.Response:
        if len(self.observations) >= MAX_REQUESTS:
            raise SmokeBudgetError("Source exceeded the three-request budget")
        kwargs["timeout"] = REQUEST_TIMEOUT
        kwargs["follow_redirects"] = False
        request = self.build_request(
            "GET",
            url,
            **{
                key: value for key, value in kwargs.items() if key != "follow_redirects"
            },
        )
        observation = {
            "url": str(request.url),
            "started_at": _utc_now(),
            "http_status": None,
            "decoded_bytes": 0,
        }
        self.observations.append(observation)
        started = time.monotonic()
        try:
            # send(stream=True) uses the timeout attached by build_request.
            with closing(
                self.send(request, stream=True, follow_redirects=False)
            ) as response:
                observation["http_status"] = response.status_code
                chunks = []
                for chunk in response.iter_bytes():
                    observation["decoded_bytes"] += len(chunk)
                    if observation["decoded_bytes"] > MAX_RESPONSE_BYTES:
                        raise SmokeBudgetError("Response exceeded the 12 MiB budget")
                    chunks.append(chunk)
                # iter_bytes already decoded compression; do not decode twice
                # when the adapter subsequently asks this response for JSON.
                headers = {
                    key: value
                    for key, value in response.headers.items()
                    if key.lower() not in {"content-encoding", "content-length"}
                }
                return httpx.Response(
                    response.status_code,
                    headers=headers,
                    content=b"".join(chunks),
                    request=request,
                )
        except (httpx.HTTPError, SmokeBudgetError) as exc:
            observation["error_type"] = type(exc).__name__
            raise
        finally:
            observation["finished_at"] = _utc_now()
            observation["duration_seconds"] = round(time.monotonic() - started, 3)


def validate_jobs(jobs: list[FetchedJob], source: str) -> dict[str, dict[str, int]]:
    """Check every returned row, keeping job descriptions out of artifacts."""
    checks = {
        name: {"passed": 0, "failed": 0}
        for name in (
            "title",
            "company",
            "description",
            "original_url",
            "source_id",
            "source",
        )
    }
    for fetched in jobs:
        url = urlsplit(str(fetched.job.url or ""))
        valid = {
            "title": bool(fetched.job.title.strip()),
            "company": bool(fetched.job.company.strip()),
            "description": bool(fetched.job.description.strip()),
            "original_url": url.scheme in {"http", "https"} and bool(url.hostname),
            "source_id": str(fetched.source_id or "").strip().lower()
            not in {"", "none", "null"},
            "source": fetched.source == source,
        }
        for name, passed in valid.items():
            checks[name]["passed" if passed else "failed"] += 1
    return checks


def careers_url_check(case: SmokeCase) -> dict | None:
    """Check local routing only; this never fetches a careers/application page."""
    if case.careers_url is None:
        return None
    match = detect(case.careers_url)
    return {
        "method": "Local ATS URL signature; careers/application page HTTP not tested",
        "expected_source": case.source,
        "expected_slug": case.board_slug,
        "detected_source": match.ats_type if match else None,
        "detected_slug": match.slug if match else None,
        "passed": bool(
            match and match.ats_type == case.source and match.slug == case.board_slug
        ),
    }


def run_case(case: SmokeCase, client: RecordingClient) -> dict:
    """Run one provider, preserving partial HTTP evidence even on failure."""
    result = {
        "source": case.source,
        "started_at": _utc_now(),
        "status": "failed",
        "parsed_count": 0,
        "checks": {},
        "requests": client.observations,
        "careers_url": case.careers_url,
        "careers_url_detection": None,
    }
    started = time.monotonic()
    try:
        result["careers_url_detection"] = careers_url_check(case)
        if (
            result["careers_url_detection"] is not None
            and not result["careers_url_detection"]["passed"]
        ):
            raise ValueError("Careers URL does not match the configured source/board")
        adapter = case.factory()
        jobs = adapter.fetch(client, **case.params)
        result["parsed_count"] = len(jobs)
        result["checks"] = validate_jobs(jobs, case.source)
        result["warnings"] = getattr(adapter, "warnings", [])
        failed_checks = any(item["failed"] for item in result["checks"].values())
        result["status"] = (
            "empty" if not jobs else "failed" if failed_checks else "passed"
        )
    except httpx.HTTPStatusError as exc:
        result["error_type"] = type(exc).__name__
        result["error"] = f"Public API returned HTTP {exc.response.status_code}"
    except httpx.RequestError as exc:
        result["status"] = "blocked"
        result["error_type"] = type(exc).__name__
        result["error"] = "Network request failed; live adapter behavior is unverified"
    except (ValueError, TypeError, KeyError, AttributeError, SmokeBudgetError) as exc:
        result["error_type"] = type(exc).__name__
        result["error"] = (
            "Adapter parsing or smoke budget failed; inspect the recorded checks"
        )
    # Some adapters deliberately swallow failed detail requests. Such requests
    # still prevent a complete pass even when enough fields survived to parse.
    statuses = [item["http_status"] for item in client.observations]
    if any(status in BLOCKED_STATUSES for status in statuses):
        result["status"] = "blocked"
    elif any(status is not None and not 200 <= status < 300 for status in statuses):
        result["status"] = "failed"
    elif any(item.get("error_type") for item in client.observations):
        if result["status"] in {"passed", "empty"}:
            result["status"] = "failed"
    result["finished_at"] = _utc_now()
    result["duration_seconds"] = round(time.monotonic() - started, 3)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live", action="store_true", help="explicitly permit public API reads"
    )
    parser.add_argument("--sources", nargs="+", choices=[case.source for case in CASES])
    parser.add_argument(
        "--output", type=Path, default=Path("careeragent_data/live-url-results.json")
    )
    args = parser.parse_args(argv)
    if not args.live:
        parser.error("--live is required; this command contacts real public APIs")
    started_at = _utc_now()
    results = []
    for case in CASES:
        if args.sources and case.source not in args.sources:
            continue
        with RecordingClient() as client:
            result = run_case(case, client)
        results.append(result)
        print(
            f"{case.source}: {result['status']} ({result['parsed_count']} parsed)",
            flush=True,
        )
    report = {
        "started_at": started_at,
        "finished_at": _utc_now(),
        "scope": "Read-only public APIs; no persistence, models, outreach or applications",
        "limits": {
            "requests_per_source": MAX_REQUESTS,
            "timeout_seconds": REQUEST_TIMEOUT,
            "decoded_bytes_per_response": MAX_RESPONSE_BYTES,
        },
        "summary": dict(Counter(result["status"] for result in results)),
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Report: {args.output}")
    return 0 if all(result["status"] == "passed" for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
