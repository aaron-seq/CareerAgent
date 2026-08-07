"""Presentation helpers: the formatting and copy decisions the UI renders."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from core.presentation import (
    CORE_STEPS,
    STEPS,
    build_steps,
    empty_state,
    format_relative_date,
    format_salary,
    job_chips,
    match_quality,
    next_step,
    risk_notes,
    truncate,
)

# --------------------------------------------------------------------------- #
# Guided flow
# --------------------------------------------------------------------------- #


def test_steps_are_numbered_and_flag_the_current_page():
    steps = build_steps(current_page="discovery")
    assert [s.index for s in steps] == list(range(1, len(STEPS) + 1))
    current = [s for s in steps if s.current]
    assert len(current) == 1 and current[0].key == "discovery"


def test_finished_steps_show_a_tick_not_a_number():
    steps = build_steps("discovery", has_profile=True)
    profile_step = next(s for s in steps if s.key == "onboarding")
    assert profile_step.done is True
    assert profile_step.display.startswith("✓")

    jobs_step = next(s for s in steps if s.key == "discovery")
    assert jobs_step.display.startswith("2")


def test_optional_steps_are_labelled():
    steps = build_steps("onboarding")
    contacts = next(s for s in steps if s.key == "contacts")
    assert contacts.is_core is False
    assert "(optional)" in contacts.display
    profile = next(s for s in steps if s.key == "onboarding")
    assert "(optional)" not in profile.display


def test_next_step_walks_the_core_path_in_order():
    fresh = build_steps("onboarding")
    assert next_step(fresh).key == "onboarding"

    with_profile = build_steps("discovery", has_profile=True)
    assert next_step(with_profile).key == "discovery"

    with_jobs = build_steps("pipeline", has_profile=True, has_jobs=True)
    assert next_step(with_jobs).key == "pipeline"


def test_next_step_is_none_when_core_flow_is_done():
    done = build_steps(
        "pipeline", has_profile=True, has_jobs=True, has_applications=True
    )
    assert next_step(done) is None


def test_core_steps_are_a_subset_of_all_steps():
    assert CORE_STEPS <= {key for key, _, _ in STEPS}


# --------------------------------------------------------------------------- #
# Empty states
# --------------------------------------------------------------------------- #


def test_empty_jobs_without_profile_sends_you_to_the_profile():
    state = empty_state("jobs", has_profile=False)
    assert state.action_page == "onboarding"
    assert "profile" in state.headline.lower()


def test_empty_jobs_with_profile_sends_you_to_discovery():
    state = empty_state("jobs", has_profile=True)
    assert state.action_page == "discovery"


def test_filtered_empty_state_blames_the_filters_not_the_data():
    state = empty_state("filtered")
    assert "filter" in state.headline.lower()
    # Nothing to navigate to — the fix is on the current screen.
    assert state.action_page is None


def test_every_empty_state_has_guidance():
    for screen in ("jobs", "filtered", "pipeline", "drafts"):
        state = empty_state(screen, has_profile=True)
        assert state.headline
        assert state.body


# --------------------------------------------------------------------------- #
# Formatting
# --------------------------------------------------------------------------- #


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
