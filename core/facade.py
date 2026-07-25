"""
UI facade: the single entry point the Streamlit layer calls into.

Keeps business logic out of ``app.py`` (per CLAUDE.md). Each DB-backed function
opens its own short-lived session (a unit of work) and returns plain
dicts/values -- never detached ORM objects -- so the UI never touches the
session or the schema directly.
"""

from __future__ import annotations

from typing import Any, Optional

from .alerting import build_digest
from .analytics import compute_funnel, generate_interview_questions
from .db import get_session, init_db
from .db.repository import (
    ApplicationRepository,
    CompanyRepository,
    CVRepository,
    JobRepository,
    row_to_job,
)
from .db.tables import ApplicationStatus, Company
from .enrichment import (
    CompanyEnricher,
    GhostAnnotator,
    SalaryEnricher,
    VisaSponsorFilter,
    exclude_ghosts,
    filter_by_min_score,
    filter_remote,
    is_internship,
    is_new_grad,
)
from .fetching import PoliteFetcher, RobotsDisallowed, detect, extract_jsonld_jobs
from .ingestion import (
    AdzunaSource,
    ArbeitnowSource,
    AshbySource,
    GreenhouseSource,
    HimalayasSource,
    IngestionResult,
    IngestionService,
    JobicySource,
    LeverSource,
    RemoteOKSource,
    RemotiveSource,
    TheMuseSource,
)
from .matching import DedupService, ScoringService, get_embedder
from .models import CVProfile, JobPosting
from .outreach import ComplianceConfig, LIARecord, OutreachService, SendDecision
from .resume import lint as ats_lint
from .resume import render_markdown, render_pdf, tailor_resume, to_json_resume
from .tracking import (
    BlacklistedCompanyError,
    DuplicateApplicationError,
    TrackingService,
)

_ATS_SOURCES = {
    "greenhouse": GreenhouseSource,
    "lever": LeverSource,
    "ashby": AshbySource,
}

#: Aggregators that need no API key and no account.
_KEYLESS_SOURCES = {
    "arbeitnow": ArbeitnowSource,
    "himalayas": HimalayasSource,
    "jobicy": JobicySource,
    "remoteok": RemoteOKSource,
}

#: Everything ``ingest_aggregator`` accepts, keyless first.
AGGREGATOR_PROVIDERS = list(_KEYLESS_SOURCES) + ["remotive", "themuse", "adzuna"]


def init_persistence() -> None:
    """Ensure the schema exists. Safe to call on every app start."""
    init_db()


# --------------------------------------------------------------------------- #
# CV
# --------------------------------------------------------------------------- #


def persist_cv(profile: CVProfile) -> int:
    init_persistence()
    with get_session() as session:
        row = CVRepository(session).save(profile)
        return row.id


def load_cv(cv_id: int) -> Optional[CVProfile]:
    with get_session() as session:
        return CVRepository(session).get(cv_id)


# --------------------------------------------------------------------------- #
# Ingestion + matching
# --------------------------------------------------------------------------- #


def ingest_ats(
    ats_type: str,
    slug: str,
    company_name: str | None = None,
    client=None,
) -> IngestionResult:
    """Pull a company's jobs from its ATS public API into the DB."""
    init_persistence()
    source_cls = _ATS_SOURCES.get(ats_type)
    if source_cls is None:
        raise ValueError(f"Unsupported ATS: {ats_type}")
    source = source_cls(slug, company_name or slug)
    with get_session() as session:
        return IngestionService(session).ingest(source, client=client)


def link_companies(session) -> int:
    """Ensure every job points at a Company row.

    Ingestion stores the company *name* on the job; enrichment (visa,
    Glassdoor, layoffs) lives on ``Company``. This backfills the link so the
    two can be joined per job.
    """
    repo = JobRepository(session)
    companies = CompanyRepository(session)
    linked = 0
    for row in repo.list(include_duplicates=True):
        if row.company_id is not None or not row.company_name:
            continue
        row.company_id = companies.get_or_create(row.company_name).id
        session.add(row)
        linked += 1
    session.flush()
    return linked


#: Each provider names its free-text filter differently; some have none at all
#: (they return the whole current board and are filtered downstream).
_KEYWORD_PARAM = {
    "adzuna": "what",
    "themuse": "category",
    "remotive": "category",
    "jobicy": "industry",
}


def ingest_aggregator(
    provider: str,
    client=None,
    keywords: str | None = None,
    **params: Any,
) -> IngestionResult:
    """Pull jobs from a keyword-searchable aggregator.

    ``remotive`` needs no credentials. ``adzuna`` requires ADZUNA_APP_ID /
    ADZUNA_APP_KEY and ``themuse`` optionally uses THEMUSE_API_KEY (a key
    raises the rate limit); both are read from the environment.
    """
    import os

    init_persistence()
    provider = provider.lower()
    # Keyless providers first -- these work with no setup at all.
    if provider in _KEYLESS_SOURCES:
        source = _KEYLESS_SOURCES[provider]()
    elif provider == "remotive":
        source = RemotiveSource()
    elif provider == "themuse":
        source = TheMuseSource(api_key=os.environ.get("THEMUSE_API_KEY"))
    elif provider == "adzuna":
        app_id = os.environ.get("ADZUNA_APP_ID")
        app_key = os.environ.get("ADZUNA_APP_KEY")
        if not app_id or not app_key:
            raise ValueError(
                "Adzuna needs ADZUNA_APP_ID and ADZUNA_APP_KEY in the environment."
            )
        source = AdzunaSource(app_id, app_key, country=params.pop("country", "gb"))
    else:
        raise ValueError(f"Unsupported aggregator: {provider}")

    # Map free-text keywords onto whatever this provider calls that parameter.
    if keywords:
        param = _KEYWORD_PARAM.get(provider)
        if param:
            params[param] = keywords
        # Providers with no keyword filter (arbeitnow/himalayas/remoteok)
        # return the whole board; scoring and filters narrow it afterwards.

    with get_session() as session:
        return IngestionService(session).ingest(source, client=client, **params)


def refresh_matches(cv: CVProfile) -> int:
    """Full refresh: dedup, link companies, enrich, then score against the CV.

    Runs the whole annotation chain so the UI can filter on salary, visa
    sponsorship, company signals, and ghost-job risk.
    """
    init_persistence()
    embedder = get_embedder()
    with get_session() as session:
        DedupService(session).run()
        link_companies(session)
        SalaryEnricher().enrich(session)
        GhostAnnotator().annotate(session)
        # Dataset-backed enrichment; skip quietly if a dataset is unavailable.
        try:
            VisaSponsorFilter.from_csv().annotate(session)
            CompanyEnricher.from_csv().annotate(session)
        except (OSError, ValueError):
            pass
        return ScoringService(session, embedder=embedder).score_all(cv)


def top_jobs(
    limit: int = 25,
    min_score: float = 0.0,
    remote_only: bool = False,
    max_ghost_score: float | None = None,
    new_grad_only: bool = False,
    internships_only: bool = False,
    sponsors_visa_only: bool = False,
) -> list[dict[str, Any]]:
    """Non-duplicate jobs, best match first, with optional filters applied."""
    with get_session() as session:
        rows = JobRepository(session).list(include_duplicates=False)

        if min_score:
            rows = filter_by_min_score(rows, min_score)
        if remote_only:
            rows = filter_remote(rows)
        if max_ghost_score is not None:
            rows = exclude_ghosts(rows, max_ghost_score=max_ghost_score)
        if new_grad_only:
            rows = [r for r in rows if is_new_grad(r.title, r.description or "")]
        if internships_only:
            rows = [r for r in rows if is_internship(r.title, r.description or "")]

        # Company-derived signals need the linked Company row.
        companies = {}
        for row in rows:
            if row.company_id and row.company_id not in companies:
                companies[row.company_id] = session.get(Company, row.company_id)
        if sponsors_visa_only:
            rows = [
                r
                for r in rows
                if r.company_id
                and getattr(companies.get(r.company_id), "sponsors_visa", False)
            ]

        rows.sort(key=lambda r: r.match_score or 0, reverse=True)
        return [
            _job_to_dict(r, companies.get(r.company_id) if r.company_id else None)
            for r in rows[:limit]
        ]


def _job_to_dict(row, company=None) -> dict[str, Any]:
    explanation = row.match_explanation or {}
    return {
        "id": row.id,
        "title": row.title,
        "company": row.company_name,
        "location": row.location,
        "url": row.url,
        "remote": row.remote,
        "score": row.match_score,
        "matched": explanation.get("matched_keywords", []),
        "missing": explanation.get("missing_keywords", []),
        "salary_min": row.salary_min,
        "salary_max": row.salary_max,
        "ghost_score": row.ghost_score,
        "dedup_key": row.dedup_key,
        "sponsors_visa": getattr(company, "sponsors_visa", None),
        "glassdoor_rating": getattr(company, "glassdoor_rating", None),
        "had_layoffs": getattr(company, "had_layoffs", None),
    }


# --------------------------------------------------------------------------- #
# Pipeline / tracking
# --------------------------------------------------------------------------- #


def add_to_pipeline(job_id: int, cv_profile_id: int | None = None) -> dict[str, Any]:
    """Create a SAVED application for a job. Returns a status dict."""
    init_persistence()
    with get_session() as session:
        job = JobRepository(session).get(job_id)
        if job is None:
            return {"ok": False, "error": "job not found"}
        try:
            app = TrackingService(session).create_application(job, cv_profile_id)
            return {"ok": True, "application_id": app.id, "status": app.status.value}
        except DuplicateApplicationError as exc:
            return {"ok": False, "error": f"duplicate: {exc}"}
        except BlacklistedCompanyError as exc:
            return {"ok": False, "error": f"blacklisted: {exc}"}


def advance_application(application_id: int, new_status: str) -> dict[str, Any]:
    from .db.tables import ApplicationRow

    with get_session() as session:
        app = session.get(ApplicationRow, application_id)
        if app is None:
            return {"ok": False, "error": "application not found"}
        try:
            TrackingService(session).transition(app, ApplicationStatus(new_status))
            return {"ok": True, "status": new_status}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}


def pipeline_board() -> dict[str, list[dict[str, Any]]]:
    """Kanban board: status -> list of application cards."""
    with get_session() as session:
        board = TrackingService(session).board()
        jobs = JobRepository(session)
        out: dict[str, list[dict[str, Any]]] = {}
        for status, apps in board.items():
            cards = []
            for app in apps:
                job = jobs.get(app.job_id) if app.job_id else None
                cards.append(
                    {
                        "application_id": app.id,
                        "title": job.title if job else "(job removed)",
                        "company": job.company_name if job else "",
                        "next_follow_up": (
                            app.next_follow_up_at.isoformat()
                            if app.next_follow_up_at
                            else None
                        ),
                    }
                )
            out[status] = cards
        return out


def funnel() -> dict[str, Any]:
    with get_session() as session:
        f = compute_funnel(ApplicationRepository(session).list())
        return {
            "total": f.total,
            "counts": f.counts,
            "reached": f.reached,
            "rejected": f.rejected,
            "withdrawn": f.withdrawn,
        }


def digest_markdown(limit: int = 10) -> str:
    with get_session() as session:
        rows = JobRepository(session).list(include_duplicates=False)
        return build_digest(rows, limit=limit).to_markdown()


def digest_rss(limit: int = 10) -> str:
    """The same digest as an RSS feed (for feed readers / static hosting)."""
    with get_session() as session:
        rows = JobRepository(session).list(include_duplicates=False)
        return build_digest(rows, limit=limit).to_rss()


def interview_questions(job: JobPosting, limit: int = 10) -> list[str]:
    """Likely interview questions derived from the job description."""
    return generate_interview_questions(job, limit=limit)


# --------------------------------------------------------------------------- #
# Capability / data-availability reporting
# --------------------------------------------------------------------------- #


def data_status() -> dict[str, Any]:
    """Report which real datasets and models are actually available.

    The UI uses this to disable filters it cannot answer honestly and to say
    whether matching is semantic or a lexical fallback -- rather than quietly
    presenting degraded results as if they were the real thing.
    """
    visa = VisaSponsorFilter.from_csv()
    company = CompanyEnricher.from_csv()
    embedder = get_embedder()
    semantic = type(embedder).__name__ == "SentenceTransformerEmbedder"
    return {
        "visa_dataset_loaded": visa.loaded,
        "visa_employer_count": len(visa),
        "visa_dataset_path": visa.source,
        "company_dataset_loaded": company.loaded,
        "company_dataset_path": company.source,
        "embedder": type(embedder).__name__,
        "semantic_embeddings": semantic,
    }


# --------------------------------------------------------------------------- #
# Outreach compliance gate (no DB write; suppression check reads DB)
# --------------------------------------------------------------------------- #


def compliance_gate(
    draft,
    config: ComplianceConfig,
    lia: LIARecord,
    resolver=None,
) -> SendDecision:
    """Run the pre-send gate. Returns a decision (never sends)."""
    init_persistence()
    with get_session() as session:
        service = OutreachService(session, config, resolver=resolver)
        return service.prepare_send(draft, lia)


def record_opt_out(email: str) -> None:
    with get_session() as session:
        OutreachService(
            session,
            ComplianceConfig("x", "x@x.com", "addr", "mailto:x@x.com"),
        ).opt_out(email)


def job_from_dict(d: dict[str, Any]) -> JobPosting:
    """Rehydrate a JobPosting from a top_jobs() card (for tailoring/scoring)."""
    with get_session() as session:
        row = JobRepository(session).get(d["id"])
        return (
            row_to_job(row)
            if row
            else JobPosting(title=d["title"], company=d["company"])
        )


# --------------------------------------------------------------------------- #
# Careers-URL discovery (ATS detection -> JSON-LD fallback)
# --------------------------------------------------------------------------- #


def discover_from_url(url: str, client=None, fetcher=None) -> dict[str, Any]:
    """Discover jobs from a company careers URL, API-first.

    1. Detect the ATS from the URL. If recognized, pull the structured feed via
       its public API (best data, zero scraping).
    2. Otherwise fetch the page politely (robots.txt honored, rate-limited) and
       extract any ``schema.org/JobPosting`` JSON-LD.

    Returns a summary dict; ingested jobs are persisted.
    """
    init_persistence()
    match = detect(url=url)
    if match is not None and match.ats_type in _ATS_SOURCES:
        result = ingest_ats(match.ats_type, match.slug, client=client)
        return {
            "method": "ats",
            "ats_type": match.ats_type,
            "slug": match.slug,
            "fetched": result.fetched,
            "stored": result.upserted,
            "errors": result.errors,
        }

    if match is not None:
        # Recognized but unsupported (e.g. Workday) -- say so rather than
        # silently scraping.
        return {
            "method": "unsupported_ats",
            "ats_type": match.ats_type,
            "slug": match.slug,
            "fetched": 0,
            "stored": 0,
            "errors": [
                f"{match.ats_type} has no public feed adapter; "
                "paste the job description instead."
            ],
        }

    # JSON-LD fallback.
    fetcher = fetcher or PoliteFetcher(client=client)
    try:
        response = fetcher.get(url)
    except RobotsDisallowed:
        return {
            "method": "jsonld",
            "fetched": 0,
            "stored": 0,
            "errors": ["robots.txt disallows fetching this URL"],
        }
    except Exception as exc:
        return {"method": "jsonld", "fetched": 0, "stored": 0, "errors": [str(exc)]}

    found = extract_jsonld_jobs(response.text, page_url=url)
    if not found:
        return {
            "method": "jsonld",
            "fetched": 0,
            "stored": 0,
            "errors": ["no JSON-LD JobPosting found on the page"],
        }

    stored = 0
    with get_session() as session:
        repo = JobRepository(session)
        for fj in found:
            row = repo.upsert(fj.job, source=fj.source, source_id=fj.source_id)
            row.remote = fj.remote
            row.salary_min = fj.salary_min
            row.salary_max = fj.salary_max
            row.salary_currency = fj.salary_currency
            row.employment_type = fj.employment_type
            row.date_posted = fj.date_posted
            session.add(row)
            stored += 1
    return {
        "method": "jsonld",
        "fetched": len(found),
        "stored": stored,
        "errors": [],
    }


# --------------------------------------------------------------------------- #
# Resume tooling (no DB required -- pure functions over a CVProfile)
# --------------------------------------------------------------------------- #


def lint_resume(cv: CVProfile, raw_text: str | None = None) -> dict[str, Any]:
    """ATS-friendliness report: issues grouped by severity + a pass/fail flag."""
    issues = ats_lint(cv, raw_text)
    return {
        "ok": not any(i.severity == "error" for i in issues),
        "errors": [i.message for i in issues if i.severity == "error"],
        "warnings": [i.message for i in issues if i.severity == "warning"],
        "info": [i.message for i in issues if i.severity == "info"],
    }


def resume_pdf(cv: CVProfile) -> bytes:
    """Render an ATS-clean, single-column, selectable-text PDF."""
    return render_pdf(to_json_resume(cv))


def resume_markdown(cv: CVProfile) -> str:
    return render_markdown(to_json_resume(cv))


def resume_json(cv: CVProfile) -> dict[str, Any]:
    """The JSON Resume document (portable interchange format)."""
    return to_json_resume(cv)


def tailor_for_job(cv: CVProfile, job: JobPosting) -> dict[str, Any]:
    """Truthfully tailor a CV to a job.

    Returns the tailored profile plus the report. Never fabricates -- the
    underlying service raises if the tailored copy would add skills or
    experience the candidate doesn't have.
    """
    tailored, report = tailor_resume(cv, job, embedder=get_embedder())
    return {
        "profile": tailored,
        "emphasized": report.emphasized_skills,
        "gaps": report.gaps,
        "reordered_experience": report.reordered_experience,
    }
