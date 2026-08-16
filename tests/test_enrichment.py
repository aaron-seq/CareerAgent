"""Phase 9 -- enrichment, filters, and alerting."""

from __future__ import annotations

from datetime import datetime, timedelta

import httpx
import pytest
import respx

from core.alerting import (
    Digest,
    DigestItem,
    DiscordEmitter,
    TelegramEmitter,
    build_digest,
)
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


def _uk_register(tmp_path):
    """A CSV in the real Home Office register format (header names matter)."""
    path = tmp_path / "visa_sponsors.csv"
    path.write_text(
        "Organisation Name,Town/City,County,Type & Rating,Route\n"
        "Acme Robotics Ltd,London,,Worker (A rating),Skilled Worker\n"
        "Globex Corporation,Manchester,,Worker (A rating),Skilled Worker\n",
        encoding="utf-8",
    )
    return path


def test_visa_filter_reads_official_uk_format(tmp_path):
    vf = VisaSponsorFilter.from_csv(_uk_register(tmp_path))
    assert vf.loaded is True
    assert len(vf) == 2
    assert vf.is_sponsor("Acme Robotics") is True  # suffix normalized away
    assert vf.is_sponsor("Globex Corporation") is True
    assert vf.is_sponsor("Not On The Register Ltd") is False


def test_visa_filter_uscis_column_name(tmp_path):
    path = tmp_path / "h1b.csv"
    path.write_text(
        "Fiscal Year,Employer (Petitioner) Name,State\n2025,Initech,CA\n",
        encoding="utf-8",
    )
    assert VisaSponsorFilter.from_csv(path).is_sponsor("Initech") is True


def test_visa_filter_without_dataset_is_unknown_never_false(tmp_path):
    """The critical invariant: absence of data must not assert 'not a sponsor'."""
    vf = VisaSponsorFilter.from_csv(tmp_path / "does_not_exist.csv")
    assert vf.loaded is False
    assert vf.is_sponsor("Any Company") is None  # unknown, NOT False


def test_visa_filter_rejects_unrecognized_columns(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("foo,bar\n1,2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="employer-name column"):
        VisaSponsorFilter.from_csv(path)


def test_visa_annotate_companies(session, tmp_path):
    CompanyRepository(session).get_or_create("Acme Robotics")
    CompanyRepository(session).get_or_create("Nobody Co")
    session.commit()
    VisaSponsorFilter.from_csv(_uk_register(tmp_path)).annotate(session)
    session.commit()
    from sqlmodel import select

    from core.db.tables import Company

    companies = {c.name: c for c in session.exec(select(Company)).all()}
    assert companies["Acme Robotics"].sponsors_visa is True
    # The UK register is authoritative, so absence here IS a real negative.
    assert companies["Nobody Co"].sponsors_visa is False


def test_visa_annotate_is_noop_without_dataset(session, tmp_path):
    CompanyRepository(session).get_or_create("Acme Robotics")
    session.commit()
    updated = VisaSponsorFilter.from_csv(tmp_path / "missing.csv").annotate(session)
    session.commit()
    assert updated == 0
    from sqlmodel import select

    from core.db.tables import Company

    company = session.exec(select(Company)).first()
    assert company.sponsors_visa is None  # left unknown, not written as False


# --------------------------------------------------------------------------- #
# Company signals
# --------------------------------------------------------------------------- #


def _signals_csv(tmp_path):
    path = tmp_path / "company_signals.csv"
    path.write_text(
        "company_name,glassdoor_rating,had_layoffs\n"
        "Acme Robotics,4.1,true\n"
        "Globex Corporation,,\n",  # present but with no values -> unknown
        encoding="utf-8",
    )
    return path


def test_company_enricher_lookup_and_annotate(session, tmp_path):
    CompanyRepository(session).get_or_create("Acme Robotics")
    session.commit()
    enricher = CompanyEnricher.from_csv(_signals_csv(tmp_path))
    assert enricher.lookup("Acme Robotics").had_layoffs is True
    enricher.annotate(session)
    session.commit()
    from sqlmodel import select

    from core.db.tables import Company

    row = session.exec(select(Company)).first()
    assert row.had_layoffs is True
    assert row.glassdoor_rating == 4.1


def test_company_blank_fields_are_unknown_not_false(tmp_path):
    enricher = CompanyEnricher.from_csv(_signals_csv(tmp_path))
    signal = enricher.lookup("Globex Corporation")
    assert signal is not None
    assert signal.had_layoffs is None  # blank -> unknown, NOT False
    assert signal.glassdoor_rating is None


def test_company_enricher_without_dataset_is_noop(session, tmp_path):
    CompanyRepository(session).get_or_create("Acme Robotics")
    session.commit()
    enricher = CompanyEnricher.from_csv(tmp_path / "missing.csv")
    assert enricher.loaded is False
    assert enricher.lookup("Acme Robotics") is None
    assert enricher.annotate(session) == 0
    session.commit()
    from sqlmodel import select

    from core.db.tables import Company

    row = session.exec(select(Company)).first()
    assert row.had_layoffs is None  # never fabricated as False


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


@respx.mock
def test_telegram_emitter_truncates_oversized_digest():
    """Bot API rejects text over 4096 chars; must truncate, not fail outright."""
    route = respx.post("https://api.telegram.org/bot123:abc/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    digest = Digest(
        items=[
            DigestItem(
                title=f"Role {i}" * 20, company=f"Co{i}", url=f"https://x/{i}", score=90
            )
            for i in range(50)
        ]
    )
    assert len(digest.to_markdown()) > 4096  # sanity: the digest is actually oversized

    emitter = TelegramEmitter("123:abc", "@me")
    with httpx.Client() as client:
        assert emitter.send(digest, client) is True
    sent_text = route.calls.last.request.content
    import json as _json

    payload = _json.loads(sent_text)
    assert len(payload["text"]) <= 4096


@respx.mock
def test_telegram_emitter_reports_failure(session):
    respx.post("https://api.telegram.org/bot123:abc/sendMessage").mock(
        return_value=httpx.Response(400, json={"ok": False})
    )
    digest = build_digest([])
    emitter = TelegramEmitter("123:abc", "@me")
    with httpx.Client() as client:
        assert emitter.send(digest, client) is False


@respx.mock
def test_discord_emitter_sends():
    route = respx.post("https://discord.com/api/webhooks/abc/xyz").mock(
        return_value=httpx.Response(204)
    )
    digest = Digest(
        items=[DigestItem(title="A", company="X", url="https://x/1", score=80)]
    )
    emitter = DiscordEmitter("https://discord.com/api/webhooks/abc/xyz")
    with httpx.Client() as client:
        assert emitter.send(digest, client) is True
    assert route.called


@respx.mock
def test_discord_emitter_reports_failure():
    respx.post("https://discord.com/api/webhooks/abc/xyz").mock(
        return_value=httpx.Response(404)
    )
    digest = build_digest([])
    emitter = DiscordEmitter("https://discord.com/api/webhooks/abc/xyz")
    with httpx.Client() as client:
        assert emitter.send(digest, client) is False


def test_rss_channel_has_required_link_element():
    """RSS 2.0 requires <link> on <channel>; falls back to the top item's URL."""
    import xml.etree.ElementTree as ET

    digest = Digest(
        items=[
            DigestItem(
                title="A", company="X", url="https://acme.example/jobs/1", score=90
            )
        ]
    )
    rss = digest.to_rss()
    root = ET.fromstring(rss)
    channel = root.find("channel")
    assert channel.find("link") is not None
    assert channel.find("link").text == "https://acme.example/jobs/1"


def test_rss_channel_link_explicit_override():
    import xml.etree.ElementTree as ET

    digest = Digest(items=[])
    rss = digest.to_rss(feed_link="https://careeragent.local/feed")
    root = ET.fromstring(rss)
    assert root.find("channel/link").text == "https://careeragent.local/feed"


def test_empty_digest_still_valid_rss_and_markdown():
    import xml.etree.ElementTree as ET

    digest = Digest(items=[])
    assert "No new matching jobs" in digest.to_markdown()
    root = ET.fromstring(digest.to_rss())  # must not raise
    assert root.find("channel/link") is not None
