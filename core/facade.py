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
from .analytics import compute_funnel
from .db import get_session, init_db
from .db.repository import (
    ApplicationRepository,
    CVRepository,
    JobRepository,
    row_to_job,
)
from .db.tables import ApplicationStatus
from .enrichment import SalaryEnricher
from .ingestion import (
    AshbySource,
    GreenhouseSource,
    IngestionResult,
    IngestionService,
    LeverSource,
)
from .matching import DedupService, ScoringService, get_embedder
from .models import CVProfile, JobPosting
from .outreach import ComplianceConfig, LIARecord, OutreachService, SendDecision
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


def refresh_matches(cv: CVProfile) -> int:
    """Dedup, backfill salary, and score all jobs against the CV."""
    init_persistence()
    embedder = get_embedder()
    with get_session() as session:
        DedupService(session).run()
        SalaryEnricher().enrich(session)
        return ScoringService(session, embedder=embedder).score_all(cv)


def top_jobs(limit: int = 25) -> list[dict[str, Any]]:
    """Non-duplicate jobs, best match first, as plain dicts for the UI."""
    with get_session() as session:
        rows = JobRepository(session).list(include_duplicates=False)
        rows.sort(key=lambda r: r.match_score or 0, reverse=True)
        return [_job_to_dict(r) for r in rows[:limit]]


def _job_to_dict(row) -> dict[str, Any]:
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
