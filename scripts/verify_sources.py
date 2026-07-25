"""
Hit every configured job source for real and report what actually works.

The adapters are written against each provider's **documentation**. This script
is how you confirm that documentation matches reality: it makes one small live
request per source, runs the real payload through our parser, and prints a
table of what came back.

    python -m scripts.verify_sources                 # keyless sources only
    python -m scripts.verify_sources --all           # include keyed sources
    python -m scripts.verify_sources --source jobicy

Nothing is written to the database -- this is a read-only probe. Exit code is
non-zero if any attempted source failed, so it can gate CI on a connected
runner.
"""

from __future__ import annotations

import argparse
import os
import sys
import traceback
from dataclasses import dataclass
from typing import Optional

import httpx

from core.ingestion import (
    AdzunaSource,
    ArbeitnowSource,
    AshbySource,
    GreenhouseSource,
    HimalayasSource,
    JobicySource,
    LeverSource,
    RemoteOKSource,
    RemotiveSource,
    TheMuseSource,
)

# name -> (factory, fetch kwargs, needs_key)
KEYLESS = {
    "arbeitnow": (ArbeitnowSource, {"page": 1}, False),
    "himalayas": (HimalayasSource, {"limit": 5}, False),
    "jobicy": (JobicySource, {"count": 5}, False),
    "remoteok": (RemoteOKSource, {}, False),
    "remotive": (RemotiveSource, {}, False),
    # Public ATS boards: no key, but tied to a specific company.
    "greenhouse": (lambda: GreenhouseSource("gitlab", "GitLab"), {}, False),
    "lever": (lambda: LeverSource("netflix", "Netflix"), {}, False),
    "ashby": (lambda: AshbySource("ramp", "Ramp"), {}, False),
}


def _keyed_sources() -> dict:
    sources = {}
    muse_key = os.environ.get("THEMUSE_API_KEY")
    sources["themuse"] = (lambda: TheMuseSource(api_key=muse_key), {"page": 0}, False)
    app_id = os.environ.get("ADZUNA_APP_ID")
    app_key = os.environ.get("ADZUNA_APP_KEY")
    if app_id and app_key:
        sources["adzuna"] = (
            lambda: AdzunaSource(app_id, app_key),
            {"what": "engineer", "results_per_page": 5},
            True,
        )
    return sources


@dataclass
class Result:
    name: str
    ok: bool
    count: int = 0
    sample: str = ""
    error: Optional[str] = None
    with_salary: int = 0
    with_date: int = 0


def probe(name: str, factory, kwargs, client: httpx.Client) -> Result:
    try:
        source = factory()
        jobs = source.fetch(client, **kwargs)
    except httpx.HTTPStatusError as exc:
        return Result(name, False, error=f"HTTP {exc.response.status_code}")
    except httpx.HTTPError as exc:
        return Result(name, False, error=f"network: {type(exc).__name__}: {exc}")
    except Exception as exc:  # parser bug or unexpected shape
        return Result(name, False, error=f"parse: {type(exc).__name__}: {exc}")

    if not jobs:
        return Result(name, False, error="reachable but returned 0 jobs")

    first = jobs[0]
    sample = f"{first.job.title} @ {first.job.company}".strip()
    if not first.job.title or not first.job.company:
        return Result(
            name,
            False,
            count=len(jobs),
            error=f"parsed {len(jobs)} rows but title/company empty - shape drift",
        )
    return Result(
        name,
        True,
        count=len(jobs),
        sample=sample[:60],
        with_salary=sum(1 for j in jobs if j.salary_min),
        with_date=sum(1 for j in jobs if j.date_posted),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true", help="include keyed sources")
    parser.add_argument("--source", help="probe a single source by name")
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args(argv)

    sources = dict(KEYLESS)
    if args.all:
        sources.update(_keyed_sources())
    if args.source:
        if args.source not in sources:
            print(
                f"Unknown source '{args.source}'. Known: {', '.join(sorted(sources))}",
                file=sys.stderr,
            )
            return 2
        sources = {args.source: sources[args.source]}

    results: list[Result] = []
    with httpx.Client(timeout=args.timeout, follow_redirects=True) as client:
        for name, (factory, kwargs, _needs_key) in sources.items():
            print(f"probing {name} ...", flush=True)
            results.append(probe(name, factory, kwargs, client))

    width = max(len(r.name) for r in results)
    print(f"\n{'SOURCE'.ljust(width)}  {'STATUS':<6} {'JOBS':>5}  DETAIL")
    print("-" * (width + 40))
    for r in sorted(results, key=lambda r: (not r.ok, r.name)):
        if r.ok:
            detail = f"{r.sample}  (salary {r.with_salary}/{r.count}, dated {r.with_date}/{r.count})"
            print(f"{r.name.ljust(width)}  {'OK':<6} {r.count:>5}  {detail}")
        else:
            print(f"{r.name.ljust(width)}  {'FAIL':<6} {r.count:>5}  {r.error}")

    failed = [r for r in results if not r.ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} sources working.")
    if failed:
        print(
            "Failing sources are either down, geo-blocked, rate-limiting this "
            "IP, or have changed their response shape. Re-run a single source "
            "with --source <name> to see the raw error.",
            file=sys.stderr,
        )
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        traceback.print_exc(limit=0)
        raise SystemExit(130) from None
