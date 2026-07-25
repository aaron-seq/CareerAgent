"""Tests for the real-dataset fetch script.

The script reaches official government sources, so every network call is
mocked. What matters here is that it fails *loudly* rather than leaving a
truncated or wrong file behind that would silently poison sponsor lookups.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from scripts import fetch_datasets

UK_CSV = (
    "Organisation Name,Town/City,County,Type & Rating,Route\n"
    "Acme Robotics Ltd,London,,Worker (A rating),Skilled Worker\n"
)


@respx.mock
def test_find_uk_csv_url_scrapes_landing_page():
    respx.get(fetch_datasets.UK_LANDING_PAGE).mock(
        return_value=httpx.Response(
            200,
            text='<a href="https://assets.gov.uk/register-2026.csv">Download</a>',
        )
    )
    with fetch_datasets._client() as client:
        assert (
            fetch_datasets.find_uk_csv_url(client)
            == "https://assets.gov.uk/register-2026.csv"
        )


@respx.mock
def test_find_uk_csv_url_raises_when_layout_changes():
    respx.get(fetch_datasets.UK_LANDING_PAGE).mock(
        return_value=httpx.Response(200, text="<p>no downloads here</p>")
    )
    with fetch_datasets._client() as client:
        with pytest.raises(RuntimeError, match="No CSV link"):
            fetch_datasets.find_uk_csv_url(client)


@respx.mock
def test_download_and_verify_roundtrip(tmp_path):
    respx.get("https://assets.gov.uk/register.csv").mock(
        return_value=httpx.Response(200, text=UK_CSV)
    )
    dest = tmp_path / "visa_sponsors.csv"
    with fetch_datasets._client() as client:
        written = fetch_datasets.download(
            "https://assets.gov.uk/register.csv", dest, client
        )
    assert written > 0
    assert dest.exists()
    assert fetch_datasets.verify(dest) == 1  # one employer parsed


@respx.mock
def test_download_rejects_empty_body(tmp_path):
    respx.get("https://assets.gov.uk/empty.csv").mock(
        return_value=httpx.Response(200, content=b"")
    )
    dest = tmp_path / "out.csv"
    with fetch_datasets._client() as client:
        with pytest.raises(RuntimeError, match="0 bytes"):
            fetch_datasets.download("https://assets.gov.uk/empty.csv", dest, client)
    # No partial file is left behind.
    assert not dest.exists()
    assert not dest.with_suffix(".csv.part").exists()


@respx.mock
def test_verify_rejects_file_without_employers(tmp_path):
    dest = tmp_path / "bad.csv"
    dest.write_text("Organisation Name\n", encoding="utf-8")  # header only
    with pytest.raises(RuntimeError, match="no employer names"):
        fetch_datasets.verify(dest)


@respx.mock
def test_main_reports_network_failure(tmp_path, capsys):
    respx.get(fetch_datasets.UK_LANDING_PAGE).mock(
        side_effect=httpx.ConnectError("offline")
    )
    code = fetch_datasets.main(["--uk", "--out", str(tmp_path / "x.csv")])
    assert code == 1
    assert "Download failed" in capsys.readouterr().err


def test_main_requires_a_source():
    with pytest.raises(SystemExit):
        fetch_datasets.main([])
