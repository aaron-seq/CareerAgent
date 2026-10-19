"""Measure bounded offline CV operations with synthetic inputs only.

Run ``python -m scripts.benchmark_local --output /tmp/careeragent-benchmark.json``.
Timings describe this process/machine, not production throughput or a speedup.
Allocation peaks are separate tracemalloc observations, not total process RSS.
"""

from __future__ import annotations

import argparse
import json
import math
import platform
import statistics
import time
import tracemalloc
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.matching.embeddings import HashingEmbedder
from core.matching.scoring import score_job
from core.models import JobPosting
from core.resume import render_pdf, to_json_resume
from core.resume.assessment import assess_resume
from core.resume.builder import build_cv_profile


def run_benchmark(iterations: int = 30) -> dict[str, Any]:
    """Run warmed latency samples and one separate allocation sample per case."""
    if not 3 <= iterations <= 250:
        raise ValueError("iterations must be between 3 and 250")
    draft = {
        "name": "Benchmark Synthetic Candidate",
        "email": "benchmark@example.test",
        "summary": "Engineer building tested data services and clear documentation.",
        "skills": ["Python", "SQL", "Docker"],
        "education": ["Synthetic computing course"],
        "projects": [
            {
                "name": "Synthetic catalogue",
                "description": "Built a searchable catalogue for library volunteers.",
                "technologies": ["Python", "SQL"],
            }
        ],
    }
    cv = build_cv_profile(draft)
    document = to_json_resume(cv)
    jobs = [
        JobPosting(
            title=f"Synthetic engineer {index}",
            company="Benchmark fixture",
            description="Build Python and SQL services with Docker and unit tests.",
            tech_stack=["Python", "SQL", "Docker", "Rust"],
        )
        for index in range(100)
    ]
    embedder = HashingEmbedder()
    cases: dict[str, Callable[[], Any]] = {
        "build_cv": lambda: build_cv_profile(draft),
        "assess_one_job": lambda: assess_resume(cv, jobs[0]),
        "render_pdf": lambda: render_pdf(document),
        "hash_match_100_jobs": lambda: [
            score_job(cv, job, embedder=embedder) for job in jobs
        ],
    }
    results = {}
    for name, operation in cases.items():
        operation()  # warm imports/caches before taking samples
        samples = []
        for _ in range(iterations):
            start = time.perf_counter_ns()
            operation()
            samples.append((time.perf_counter_ns() - start) / 1_000_000)
        samples.sort()
        tracemalloc.start()
        try:
            operation()
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        results[name] = {
            "samples": iterations,
            "median_ms": round(statistics.median(samples), 4),
            "p95_ms": round(samples[math.ceil(0.95 * len(samples)) - 1], 4),
            "min_ms": round(samples[0], 4),
            "max_ms": round(samples[-1], 4),
            "separate_python_allocation_peak_bytes": peak,
        }
    return {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "scope": "Warmed single-process offline synthetic workloads; shared machine; no speedup or hosted-load claim",
        "method": "perf_counter_ns latency without tracemalloc; nearest-rank p95; separate one-operation Python allocation peak, not process RSS",
        "candidate_data": "Synthetic only; no saved profiles, credentials or model calls",
        "results": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=30)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if not 3 <= args.iterations <= 250:
        parser.error("--iterations must be between 3 and 250")
    output = json.dumps(run_benchmark(args.iterations), indent=2) + "\n"
    if args.output:
        args.output.write_text(output, encoding="utf-8")
        print(f"Benchmark written to {args.output}")
    else:
        print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
