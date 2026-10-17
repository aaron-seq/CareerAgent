"""Pure presentation helpers (ported from the ui-integration-followup branch)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core.presentation import (
    GHOST_RISK_THRESHOLD,
    format_relative_date,
    format_salary,
    job_chips,
    match_quality,
    risk_notes,
    truncate,
)


@pytest.mark.parametrize(
    "args,expected",
    [
        ((120000, 150000, "USD"), "$120k–150k"),
        ((60000, None, "GBP"), "£60k"),
        ((90000, 90000, "EUR"), "€90k"),
        ((85500, None, "USD"), "$85,500"),
        ((100000, 120000, None), "100k–120k"),
        ((None, None, "USD"), None),
    ],
)
def test_format_salary(args, expected):
    assert format_salary(*args) == expected


def test_format_salary_handles_unknown_currency_code():
    assert format_salary(50000, None, "SEK") == "SEK 50k"


@pytest.mark.parametrize(
    "days,expected",
    [
        (0, "today"),
        (1, "yesterday"),
        (3, "3 days ago"),
        (10, "1 week ago"),
        (20, "2 weeks ago"),
        (45, "1 month ago"),
        (90, "3 months ago"),
    ],
)
def test_format_relative_date(days, expected):
    now = datetime(2026, 6, 1)
    assert format_relative_date(now - timedelta(days=days), now=now) == expected


def test_format_relative_date_handles_none_and_future():
    now = datetime(2026, 6, 1)
    assert format_relative_date(None) is None
    assert format_relative_date(now + timedelta(days=2), now=now) == "just posted"


@pytest.mark.parametrize(
    "score,word,tone",
    [
        (92, "Strong match", "good"),
        (60, "Good match", "good"),
        (40, "Fair match", "warn"),
        (10, "Weak match", "bad"),
        (None, "Unscored", "neutral"),
    ],
)
def test_match_quality_words_the_score(score, word, tone):
    assert match_quality(score) == (word, tone)


def test_truncate_cuts_on_a_word_boundary():
    text = "The quick brown fox jumps over the lazy dog"
    result = truncate(text, limit=20)
    assert result.endswith("…")
    assert len(result) <= 21
    assert not result[:-1].endswith(" ")


def test_truncate_leaves_short_text_alone():
    assert truncate("short", limit=50) == "short"
    assert truncate(None) == ""


# --------------------------------------------------------------------------- #
# Job cards
# --------------------------------------------------------------------------- #


def test_job_chips_prioritise_the_useful_facts():
    now = datetime(2026, 6, 1)
    chips = job_chips(
        {
            "remote": True,
            "location": "London",
            "salary_min": 90000,
            "salary_max": 110000,
            "salary_currency": "GBP",
            "date_posted": now - timedelta(days=2),
            "sponsors_visa": True,
        },
        now=now,
    )
    assert chips[0] == "Remote"
    assert "£90k–110k" in chips
    assert "Posted 2 days ago" in chips
    assert "Visa sponsor" in chips


def test_job_chips_omit_missing_data_rather_than_showing_blanks():
    assert job_chips({}) == []
    chips = job_chips({"location": "Berlin"})
    assert chips == ["Berlin"]


def test_risk_notes_flag_ghost_jobs_and_layoffs():
    notes = risk_notes({"ghost_score": 0.8, "had_layoffs": True})
    assert any("ghost" in n.lower() for n in notes)
    assert any("layoff" in n.lower() for n in notes)


def test_risk_notes_stay_quiet_for_healthy_postings():
    assert risk_notes({"ghost_score": 0.1, "had_layoffs": False}) == []
    # Unknown layoff data must not produce a warning.
    assert risk_notes({"ghost_score": None, "had_layoffs": None}) == []


def test_format_relative_date_accepts_iso_strings_and_aware_datetimes():
    now = datetime(2026, 6, 1, 12)
    assert format_relative_date("2026-05-29T12:00:00", now=now) == "3 days ago"
    aware = datetime(2026, 5, 31, 12, tzinfo=timezone.utc)
    assert format_relative_date(aware, now=now) == "yesterday"
    # Aware "now" against a naive stored value (both conventions coexist).
    aware_now = now.replace(tzinfo=timezone.utc)
    assert format_relative_date(now - timedelta(days=1), now=aware_now) == "yesterday"


def test_format_relative_date_never_guesses_on_garbage():
    assert format_relative_date("last Tuesday") is None
    assert format_relative_date("") is None


def test_job_chips_take_the_facade_card_shape():
    # top_jobs() cards carry date_posted as an ISO string.
    chips = job_chips(
        {"date_posted": "2026-05-25T00:00:00", "sponsors_visa": None},
        now=datetime(2026, 6, 1),
    )
    assert chips == ["Posted 1 week ago"]


def test_ghost_threshold_matches_the_pipeline_filter():
    assert risk_notes({"ghost_score": GHOST_RISK_THRESHOLD}) == []
    assert risk_notes({"ghost_score": GHOST_RISK_THRESHOLD + 0.01})
