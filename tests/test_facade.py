"""Tests for the UI facade (the boundary app.py calls into)."""

from __future__ import annotations

import httpx
import pytest
import respx

from core import facade
from core.db import reset_engine
from core.models import CVProfile, EmailDraft, Experience
from core.outreach import ComplianceConfig, LIARecord


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Point the global engine at a throwaway SQLite file for the facade."""
    db = tmp_path / "facade.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    reset_engine()
    facade.init_persistence()
    yield
    reset_engine()


def _cv() -> CVProfile:
    return CVProfile(
        name="Ada Lovelace",
        email="ada@example.com",
        skills=["Python", "PyTorch"],
        experiences=[
            Experience(
                title="ML Eng",
                company="AI Co",
                duration="3y",
                technologies=["Python", "PyTorch"],
            )
        ],
    )


def test_persist_and_load_cv(temp_db):
    cv_id = facade.persist_cv(_cv())
    loaded = facade.load_cv(cv_id)
    assert loaded is not None and loaded.name == "Ada Lovelace"


@respx.mock
def test_ingest_score_and_top_jobs(temp_db):
    respx.get(
        "https://boards-api.greenhouse.io/v1/boards/stripe/jobs?content=true"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "id": 1,
                        "title": "Machine Learning Engineer",
                        "location": {"name": "Remote"},
                        "absolute_url": "u1",
                        "content": "Python and PyTorch.",
                    },
                    {
                        "id": 2,
                        "title": "Accountant",
                        "location": {"name": "NYC"},
                        "absolute_url": "u2",
                        "content": "Tax filings.",
                    },
                ]
            },
        )
    )
    with httpx.Client() as client:
        result = facade.ingest_ats("greenhouse", "stripe", "Stripe", client=client)
    assert result.upserted == 2

    facade.refresh_matches(_cv())
    jobs = facade.top_jobs()
    assert jobs[0]["title"] == "Machine Learning Engineer"  # best match first
    assert jobs[0]["score"] >= jobs[-1]["score"]
    assert "python" in jobs[0]["matched"]


@respx.mock
def test_pipeline_flow(temp_db):
    respx.get(
        "https://boards-api.greenhouse.io/v1/boards/stripe/jobs?content=true"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "id": 1,
                        "title": "ML Engineer",
                        "location": {"name": "Remote"},
                        "absolute_url": "u1",
                        "content": "ML",
                    }
                ]
            },
        )
    )
    with httpx.Client() as client:
        facade.ingest_ats("greenhouse", "stripe", "Stripe", client=client)
    job = facade.top_jobs()[0]

    added = facade.add_to_pipeline(job["id"])
    assert added["ok"] is True
    app_id = added["application_id"]

    # Duplicate is prevented.
    assert facade.add_to_pipeline(job["id"])["ok"] is False

    # Advance and see it move on the board.
    assert facade.advance_application(app_id, "applied")["ok"] is True
    board = facade.pipeline_board()
    assert len(board["applied"]) == 1
    assert facade.funnel()["reached"]["applied"] == 1


def test_advance_illegal_transition_returns_error(temp_db):
    # No such application.
    assert facade.advance_application(999, "applied")["ok"] is False


def test_compliance_gate_and_opt_out(temp_db):
    config = ComplianceConfig(
        sender_name="Ada",
        sender_email="ada@example.com",
        postal_address="1 Analytical Way",
        unsubscribe="mailto:ada@example.com",
    )
    lia = LIARecord(campaign="c", purpose="p", necessity="n", balancing="b")
    draft = EmailDraft(
        subject="Hi", body="Hello", recipient_email="hm@corp.com", company="Corp"
    )
    decision = facade.compliance_gate(draft, config, lia, resolver=lambda d: ["mx"])
    assert decision.allowed is True

    facade.record_opt_out("hm@corp.com")
    blocked = facade.compliance_gate(draft, config, lia, resolver=lambda d: ["mx"])
    assert blocked.allowed is False


def test_unsupported_ats_raises(temp_db):
    with pytest.raises(ValueError):
        facade.ingest_ats("workday", "acme")


# --------------------------------------------------------------------------- #
# Aggregator ingestion
# --------------------------------------------------------------------------- #


@respx.mock
def test_ingest_aggregator_remotive(temp_db):
    respx.get(url__regex=r"https://remotive\.com/api/remote-jobs.*").mock(
        return_value=httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "id": 7,
                        "title": "Remote Python Dev",
                        "company_name": "RemoteCorp",
                        "candidate_required_location": "Worldwide",
                        "description": "<p>Python.</p>",
                        "url": "https://remotive.example/7",
                    }
                ]
            },
        )
    )
    with httpx.Client() as client:
        result = facade.ingest_aggregator("remotive", client=client)
    assert result.upserted == 1
    assert facade.top_jobs()[0]["remote"] is True


def test_ingest_aggregator_adzuna_requires_keys(temp_db, monkeypatch):
    monkeypatch.delenv("ADZUNA_APP_ID", raising=False)
    monkeypatch.delenv("ADZUNA_APP_KEY", raising=False)
    with pytest.raises(ValueError, match="ADZUNA_APP_ID"):
        facade.ingest_aggregator("adzuna")


def test_ingest_aggregator_unsupported(temp_db):
    with pytest.raises(ValueError, match="Unsupported aggregator"):
        facade.ingest_aggregator("linkedin")


# --- Boards added 2026-08-27 ------------------------------------------------ #


def test_provider_lists_cover_the_new_sources(temp_db):
    assert set(facade.aggregator_providers()) == {
        "adzuna",
        "arbeitnow",
        "himalayas",
        "jobicy",
        "remoteok",
        "remotive",
        "themuse",
    }
    assert set(facade.ats_providers()) == {
        "greenhouse",
        "lever",
        "ashby",
        "smartrecruiters",
        "recruitee",
        "workable",
    }


@respx.mock
def test_ingest_aggregator_keyless_board_needs_no_credentials(temp_db, monkeypatch):
    """A keyless board must work with a completely bare environment."""
    for var in ("ADZUNA_APP_ID", "ADZUNA_APP_KEY", "THEMUSE_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    respx.get("https://remoteok.com/api").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"legal": "attribution notice", "last_updated": 1},
                {
                    "id": "42",
                    "position": "Platform Engineer",
                    "company": "Acme",
                    "location": "Worldwide",
                    "description": "<p>Run the platform.</p>",
                    "url": "https://remoteOK.com/remote-jobs/42",
                    "date": "2026-08-25T18:50:43+00:00",
                },
            ],
        )
    )
    with httpx.Client() as client:
        result = facade.ingest_aggregator("remoteok", client=client)
    assert result.fetched == 1  # the legal element is not a job
    assert result.upserted == 1
    assert facade.top_jobs()[0]["title"] == "Platform Engineer"


@respx.mock
def test_ingest_aggregator_maps_keywords_per_provider(temp_db):
    """The UI passes a provider-neutral ``keywords``; the facade owns the
    per-API parameter name so app.py holds no provider logic."""
    route = respx.get(url__regex=r"https://jobicy\.com/api/v2/remote-jobs.*").mock(
        return_value=httpx.Response(200, json={"jobs": []})
    )
    with httpx.Client() as client:
        facade.ingest_aggregator("jobicy", client=client, keywords="python")
    assert "tag=python" in str(route.calls.last.request.url)


@respx.mock
def test_ingest_aggregator_drops_keywords_for_unsearchable_boards(temp_db):
    """Arbeitnow has no server-side search, so a keyword must not be smuggled
    into the query string as a parameter the API would silently ignore."""
    assert facade.aggregator_supports_keywords("arbeitnow") is False
    route = respx.get(
        url__regex=r"https://www\.arbeitnow\.com/api/job-board-api.*"
    ).mock(return_value=httpx.Response(200, json={"data": []}))
    with httpx.Client() as client:
        facade.ingest_aggregator("arbeitnow", client=client, keywords="python")
    assert "python" not in str(route.calls.last.request.url)


def test_attribution_notice_is_present_for_contractual_sources(temp_db):
    assert "RemoteOK" in facade.attribution_notice("remoteok")
    assert facade.attribution_notice("remotive")
    assert facade.attribution_notice("adzuna") is None


@respx.mock
def test_ingest_ats_supports_a_new_company_board(temp_db):
    respx.get(
        url__regex=r"https://apply\.workable\.com/api/v1/widget/accounts/enfos-inc.*"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "name": "ENFOS, Inc.",
                "jobs": [
                    {
                        "title": "Senior Software Engineer",
                        "shortcode": "77DF64C44E",
                        "telecommuting": True,
                        "url": "https://apply.workable.com/j/77DF64C44E",
                        "published_on": "2026-04-25",
                        "country": "United States",
                        "city": "Chicago",
                        "state": "Illinois",
                        "description": "<p>Scale the backend.</p>",
                    }
                ],
            },
        )
    )
    with httpx.Client() as client:
        result = facade.ingest_ats("workable", "enfos-inc", client=client)
    assert result.upserted == 1
    top = facade.top_jobs()[0]
    assert top["title"] == "Senior Software Engineer"
    assert top["remote"] is True


# --------------------------------------------------------------------------- #
# Enrichment + filters via the facade
# --------------------------------------------------------------------------- #


@respx.mock
def test_refresh_matches_links_company_and_leaves_unknown_unset(temp_db):
    """With no real datasets present, enrichment must report unknown, not False."""
    respx.get(
        "https://boards-api.greenhouse.io/v1/boards/stripe/jobs?content=true"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "id": 1,
                        "title": "ML Engineer",
                        "location": {"name": "Remote"},
                        "absolute_url": "u1",
                        "content": "Python",
                    }
                ]
            },
        )
    )
    with httpx.Client() as client:
        facade.ingest_ats("greenhouse", "stripe", "Stripe", client=client)

    facade.refresh_matches(_cv())
    job = facade.top_jobs()[0]
    # Ghost score is computed locally, so it is always available.
    assert job["ghost_score"] is not None
    # No sponsor/company dataset shipped -> these must be unknown, never False.
    assert job["sponsors_visa"] is None
    assert job["glassdoor_rating"] is None
    assert job["had_layoffs"] is None


@respx.mock
def test_visa_filter_requires_a_dataset(temp_db):
    """Filtering by sponsorship with no dataset must return nothing, not lie."""
    respx.get(
        "https://boards-api.greenhouse.io/v1/boards/stripe/jobs?content=true"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "id": 1,
                        "title": "ML Engineer",
                        "location": {"name": "Remote"},
                        "absolute_url": "u1",
                        "content": "Python",
                    }
                ]
            },
        )
    )
    with httpx.Client() as client:
        facade.ingest_ats("greenhouse", "stripe", "Stripe", client=client)
    facade.refresh_matches(_cv())

    status = facade.data_status()
    assert status["visa_dataset_loaded"] is False
    # The job exists unfiltered, but cannot be claimed as a sponsor.
    assert len(facade.top_jobs()) == 1
    assert facade.top_jobs(sponsors_visa_only=True) == []


def test_data_status_reports_capabilities(temp_db):
    status = facade.data_status()
    assert status["visa_dataset_loaded"] is False
    assert status["company_dataset_loaded"] is False
    assert "embedder" in status
    # Semantic embeddings are optional; the flag must reflect reality.
    assert isinstance(status["semantic_embeddings"], bool)


@respx.mock
def test_top_jobs_filters(temp_db):
    respx.get("https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=true").mock(
        return_value=httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "id": 1,
                        "title": "Senior Python Engineer",
                        "location": {"name": "Remote"},
                        "absolute_url": "u1",
                        "content": "Python " * 60,
                    },
                    {
                        "id": 2,
                        "title": "New Grad Software Engineer",
                        "location": {"name": "NYC"},
                        "absolute_url": "u2",
                        "content": "Entry level " * 60,
                    },
                    {
                        "id": 3,
                        "title": "Engineering Intern",
                        "location": {"name": "NYC"},
                        "absolute_url": "u3",
                        "content": "Internship " * 60,
                    },
                ]
            },
        )
    )
    with httpx.Client() as client:
        facade.ingest_ats("greenhouse", "acme", "Acme", client=client)
    facade.refresh_matches(_cv())

    assert len(facade.top_jobs()) == 3
    remote = facade.top_jobs(remote_only=True)
    assert len(remote) == 1 and remote[0]["remote"] is True

    grads = facade.top_jobs(new_grad_only=True)
    assert [j["title"] for j in grads] == ["New Grad Software Engineer"]

    interns = facade.top_jobs(internships_only=True)
    assert [j["title"] for j in interns] == ["Engineering Intern"]

    # Acme is not in the visa sample -> filtered out entirely.
    assert facade.top_jobs(sponsors_visa_only=True) == []

    # A min-score above every score removes everything.
    assert facade.top_jobs(min_score=101) == []


# --------------------------------------------------------------------------- #
# Digest + interview prep
# --------------------------------------------------------------------------- #


@respx.mock
def test_digest_markdown_and_rss(temp_db):
    respx.get(
        "https://boards-api.greenhouse.io/v1/boards/stripe/jobs?content=true"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "id": 1,
                        "title": "ML Engineer",
                        "location": {"name": "Remote"},
                        "absolute_url": "https://x.example/1",
                        "content": "Python",
                    }
                ]
            },
        )
    )
    with httpx.Client() as client:
        facade.ingest_ats("greenhouse", "stripe", "Stripe", client=client)
    facade.refresh_matches(_cv())

    md = facade.digest_markdown()
    assert "ML Engineer" in md and "CareerAgent digest" in md

    rss = facade.digest_rss()
    assert rss.startswith("<?xml") and "ML Engineer" in rss


def test_interview_questions_from_job():
    from core.models import JobPosting

    job = JobPosting(
        title="ML Engineer",
        company="Acme",
        tech_stack=["PyTorch"],
        requirements=["Ship models to production"],
    )
    qs = facade.interview_questions(job, limit=6)
    assert any("PyTorch" in q for q in qs)
    assert any("production" in q for q in qs)
    assert len(qs) <= 6


# --------------------------------------------------------------------------- #
# Careers-URL discovery (API-first, JSON-LD fallback)
# --------------------------------------------------------------------------- #


@respx.mock
def test_discover_from_url_detects_ats(temp_db):
    respx.get(
        "https://boards-api.greenhouse.io/v1/boards/stripe/jobs?content=true"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "id": 1,
                        "title": "ML Engineer",
                        "location": {"name": "Remote"},
                        "absolute_url": "u1",
                        "content": "ML",
                    }
                ]
            },
        )
    )
    with httpx.Client() as client:
        result = facade.discover_from_url(
            "https://boards.greenhouse.io/stripe", client=client
        )
    assert result["method"] == "ats"
    assert result["ats_type"] == "greenhouse"
    assert result["stored"] == 1
    assert facade.top_jobs()[0]["title"] == "ML Engineer"


@respx.mock
def test_discover_from_url_falls_back_to_jsonld(temp_db):
    html = """
    <script type="application/ld+json">
    {"@type": "JobPosting", "title": "Platform Engineer",
     "hiringOrganization": {"name": "Indie Co"},
     "datePosted": "2026-06-01",
     "jobLocationType": "TELECOMMUTE",
     "description": "<p>Run the platform.</p>"}
    </script>
    """
    respx.get("https://indie.example/robots.txt").mock(return_value=httpx.Response(404))
    respx.get("https://indie.example/careers").mock(
        return_value=httpx.Response(200, text=html)
    )
    with httpx.Client() as client:
        result = facade.discover_from_url(
            "https://indie.example/careers", client=client
        )
    assert result["method"] == "jsonld"
    assert result["stored"] == 1
    job = facade.top_jobs()[0]
    assert job["title"] == "Platform Engineer"
    assert job["remote"] is True


@respx.mock
def test_discover_from_url_reports_unsupported_ats(temp_db):
    result = facade.discover_from_url("https://acme.wd5.myworkdayjobs.com/External")
    assert result["method"] == "unsupported_ats"
    assert result["stored"] == 0
    assert result["errors"]


@respx.mock
def test_discover_from_url_honors_robots(temp_db):
    respx.get("https://blocked.example/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nDisallow: /careers")
    )
    with httpx.Client() as client:
        result = facade.discover_from_url(
            "https://blocked.example/careers", client=client
        )
    assert result["stored"] == 0
    assert "robots.txt" in result["errors"][0]


@respx.mock
def test_discover_from_url_no_jsonld_found(temp_db):
    respx.get("https://plain.example/robots.txt").mock(return_value=httpx.Response(404))
    respx.get("https://plain.example/jobs").mock(
        return_value=httpx.Response(200, text="<html><body>No data</body></html>")
    )
    with httpx.Client() as client:
        result = facade.discover_from_url("https://plain.example/jobs", client=client)
    assert result["stored"] == 0
    assert "JSON-LD" in result["errors"][0]


# --------------------------------------------------------------------------- #
# Resume tooling (no DB needed)
# --------------------------------------------------------------------------- #


def test_lint_resume_reports_severities():
    report = facade.lint_resume(_cv())
    assert report["ok"] is True  # name + email present
    assert isinstance(report["warnings"], list)

    bad = _cv()
    bad.email = None
    assert facade.lint_resume(bad)["ok"] is False
    assert any("email" in e.lower() for e in facade.lint_resume(bad)["errors"])


def test_lint_resume_flags_emoji_in_raw_text():
    report = facade.lint_resume(_cv(), raw_text="EXPERIENCE\nShipped it 🚀\n")
    assert report["ok"] is False
    assert any("emoji" in e.lower() for e in report["errors"])


def test_resume_pdf_and_markdown_and_json():
    cv = _cv()
    pdf = facade.resume_pdf(cv)
    assert pdf.startswith(b"%PDF") and len(pdf) > 500

    md = facade.resume_markdown(cv)
    assert "# Ada Lovelace" in md

    doc = facade.resume_json(cv)
    assert doc["basics"]["name"] == "Ada Lovelace"
    assert doc["work"][0]["name"] == "AI Co"


def test_tailor_for_job_is_truthful():
    from core.models import JobPosting

    cv = _cv()  # Python, PyTorch
    job = JobPosting(
        title="Rust Engineer",
        company="Acme",
        description="Rust systems work",
        tech_stack=["Rust", "PyTorch"],
    )
    result = facade.tailor_for_job(cv, job)
    tailored = result["profile"]
    # PyTorch is emphasized; Rust is reported as a gap, never invented.
    assert set(tailored.skills) == set(cv.skills)
    assert "rust" in result["gaps"]
    assert "PyTorch" in result["emphasized"]
