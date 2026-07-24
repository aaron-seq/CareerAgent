"""Phase 9 -- enrichment, filters, and alerting."""

from __future__ import annotations

from datetime import datetime, timedelta

import httpx
import respx

from core.alerting import TelegramEmitter, build_digest
from core.db.repository import CompanyRepository, JobRepository
from core.enrichment import (
    CompanyEnricher,
    GhostAnnotator,
    SalaryEnricher,
    VisaSponsorFilter,
    exclude_ghosts,
    filter_by_min_score,
    ghost_score,
    is_internship,
    is_new_grad,
    parse_salary,
)
from core.models import JobPosting

# --------------------------------------------------------------------------- #
# Salary
# --------------------------------------------------------------------------- #


def test_parse_salary_formats():
    assert parse_salary("$180K - $220K") == (180000, 220000, "USD")
    assert parse_salary("£60,000") == (60000, 60000, "GBP")
    assert parse_salary("80k-100k USD") == (80000, 100000, "USD")
    assert parse_salary("") == (None, None, None)


def test_salary_enricher_backfills(session):
    JobRepository(session).upsert(
        JobPosting(title="Eng", company="Acme", salary_range="$100k - $120k"),
        "greenhouse",
        "1",
    )
    session.commit()
    updated = SalaryEnricher().enrich(session)
    session.commit()
    assert updated == 1
    row = JobRepository(session).list()[0]
    assert row.salary_min == 100000 and row.salary_max == 120000


# --------------------------------------------------------------------------- #
# Visa
# --------------------------------------------------------------------------- #


def test_visa_sponsor_filter_from_sample():
    vf = VisaSponsorFilter.from_csv()
    assert vf.is_sponsor("Stripe") is True
    assert vf.is_sponsor("Stripe Inc.") is True  # normalized
    assert vf.is_sponsor("Nonexistent LLC") is False


def test_visa_annotate_companies(session):
    CompanyRepository(session).get_or_create("Stripe")
    CompanyRepository(session).get_or_create("Nobody Co")
    session.commit()
    VisaSponsorFilter.from_csv().annotate(session)
    session.commit()
    from sqlmodel import select

    from core.db.tables import Company

    companies = {c.name: c for c in session.exec(select(Company)).all()}
    assert companies["Stripe"].sponsors_visa is True
    assert companies["Nobody Co"].sponsors_visa is False


# --------------------------------------------------------------------------- #
# Company signals
# --------------------------------------------------------------------------- #


def test_company_enricher_lookup_and_annotate(session):
    CompanyRepository(session).get_or_create("Twitter")
    session.commit()
    enricher = CompanyEnricher.from_csv()
    assert enricher.lookup("Twitter").had_layoffs is True
    enricher.annotate(session)
    session.commit()
    from sqlmodel import select

    from core.db.tables import Company

    twitter = session.exec(select(Company).where(Company.name == "Twitter")).first()
    assert twitter.had_layoffs is True
    assert twitter.glassdoor_rating == 2.8


# --------------------------------------------------------------------------- #
# Ghost detection
# --------------------------------------------------------------------------- #


def test_ghost_score_old_posting():
    now = datetime(2026, 6, 1)
    old = now - timedelta(days=120)
    assessment = ghost_score(old, now=now, description="x" * 500)
    assert assessment.score >= 0.5
    assert any("days" in r for r in assessment.reasons)


def test_ghost_score_fresh_detailed_posting():
    now = datetime(2026, 6, 1)
    fresh = now - timedelta(days=3)
    assessment = ghost_score(fresh, now=now, description="x" * 500)
    assert assessment.score == 0.0


def test_ghost_annotator(session):
    now = datetime(2026, 6, 1)
    row = JobRepository(session).upsert(
        JobPosting(title="Eng", company="Acme", description="short"), "greenhouse", "1"
    )
    row.date_posted = now - timedelta(days=100)
    session.add(row)
    session.commit()
    GhostAnnotator().annotate(session, now=now)
    session.commit()
    assert JobRepository(session).list()[0].ghost_score > 0.5


# --------------------------------------------------------------------------- #
# Filters
# --------------------------------------------------------------------------- #


def test_new_grad_and_internship_filters():
    assert is_new_grad("New Grad Software Engineer") is True
    assert is_new_grad("Senior Software Engineer") is False  # senior overrides
    assert is_internship("Summer Engineering Intern") is True
    assert is_internship("Staff Engineer") is False


def test_min_score_and_ghost_filters():
    class Row:
        def __init__(self, score, ghost):
            self.match_score = score
            self.ghost_score = ghost

    rows = [Row(80, 0.1), Row(40, 0.1), Row(90, 0.9)]
    assert len(filter_by_min_score(rows, 60)) == 2
    assert len(exclude_ghosts(rows, max_ghost_score=0.6)) == 2


# --------------------------------------------------------------------------- #
# Alerting
# --------------------------------------------------------------------------- #


def test_build_digest_sorts_by_score_and_skips_duplicates(session):
    repo = JobRepository(session)
    a = repo.upsert(JobPosting(title="A", company="X"), "greenhouse", "1")
    b = repo.upsert(JobPosting(title="B", company="Y"), "greenhouse", "2")
    dup = repo.upsert(JobPosting(title="C", company="Z"), "greenhouse", "3")
    a.match_score, b.match_score, dup.match_score = 50.0, 90.0, 99.0
    dup.is_duplicate = True
    session.add_all([a, b, dup])
    session.commit()

    digest = build_digest(repo.list(include_duplicates=True))
    titles = [i.title for i in digest.items]
    assert titles == ["B", "A"]  # sorted by score, duplicate excluded
    md = digest.to_markdown()
    assert "CareerAgent digest" in md and "90% match" in md
    rss = digest.to_rss()
    assert rss.startswith("<?xml") and "<item>" in rss


@respx.mock
def test_telegram_emitter_sends(session):
    route = respx.post("https://api.telegram.org/bot123:abc/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    repo = JobRepository(session)
    row = repo.upsert(JobPosting(title="A", company="X"), "greenhouse", "1")
    row.match_score = 80.0
    session.add(row)
    session.commit()

    digest = build_digest(repo.list())
    emitter = TelegramEmitter("123:abc", "@me")
    with httpx.Client() as client:
        assert emitter.send(digest, client) is True
    assert route.called
