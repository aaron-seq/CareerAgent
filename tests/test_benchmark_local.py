"""Exercise real offline operations; timing values are deliberately not gates."""

import json

import pytest

from scripts.benchmark_local import main, run_benchmark


def test_benchmark_records_real_offline_workloads_without_network(
    monkeypatch, tmp_path
):
    def unexpected_network(*args, **kwargs):
        pytest.fail("Local benchmark must not open a network connection")

    monkeypatch.setattr("socket.create_connection", unexpected_network)
    path = tmp_path / "results.json"
    assert main(["--iterations", "3", "--output", str(path)]) == 0
    report = json.loads(path.read_text())
    assert set(report["results"]) == {
        "build_cv",
        "assess_one_job",
        "render_pdf",
        "hash_match_100_jobs",
    }
    for result in report["results"].values():
        assert result["samples"] == 3
        assert (
            result["min_ms"]
            <= result["median_ms"]
            <= result["p95_ms"]
            <= result["max_ms"]
        )
        assert result["separate_python_allocation_peak_bytes"] > 0


@pytest.mark.parametrize("iterations", [0, 2, 251])
def test_benchmark_rejects_unbounded_or_insufficient_samples(iterations):
    with pytest.raises(ValueError, match="between 3 and 250"):
        run_benchmark(iterations)
