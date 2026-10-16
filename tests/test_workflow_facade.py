"""Persistence-to-workflow boundaries used by the guided application UI."""

from datetime import datetime

import pytest

from core import facade
from core.db import get_session
from core.db.repository import JobRepository
from core.db.tables import CVProfileRow
from core.models import CVProfile, JobPosting


def test_saved_profiles_are_recent_metadata_and_explicitly_loadable(temp_db):
    first = facade.persist_cv(CVProfile(name="First", raw_text="Private older CV"))
    second = facade.persist_cv(CVProfile(name="Second", raw_text="Private newer CV"))
    with get_session() as session:
        for cv_id in (first, second):
            session.get(CVProfileRow, cv_id).created_at = datetime(2026, 10, 16)
    summaries = facade.saved_cv_profiles(limit=1)
    assert summaries == [
        {
            "id": second,
            "name": "Second",
            "created_at": "2026-10-16T00:00:00+00:00",
            "saved_label": "16 Oct 2026, 00:00 UTC",
        }
    ]
    assert facade.load_cv(summaries[0]["id"]).raw_text == "Private newer CV"
    assert facade.load_cv(9999) is None


@pytest.mark.parametrize("limit", [0, -1, 101])
def test_saved_profile_list_is_bounded(temp_db, limit):
    with pytest.raises(ValueError, match="limit"):
        facade.saved_cv_profiles(limit)


def test_api_job_keeps_source_and_can_enter_draft_workflow(temp_db):
    job = JobPosting(
        title="Engineer",
        company="Example",
        url="https://remoteok.com/remote-jobs/123",
        description="Build Python services.",
        tech_stack=["Python"],
        requirements=["API experience"],
    )
    with get_session() as session:
        job_id = JobRepository(session).upsert(job, "remoteok", "123").id
    card = facade.top_jobs()[0]
    assert card["source"] == "remoteok"
    assert card["source_id"] == "123"
    assert card["attribution"] == facade.attribution_notice("remoteok")
    assert facade.job_for_drafting(job_id) == job
    assert facade.job_for_drafting(9999) is None
    assert facade.add_to_pipeline(job_id)["ok"]
    assert facade.pipeline_board()["saved"][0]["job_id"] == job_id


@pytest.mark.parametrize("url", [None, "https://example.test/jobs/123"])
def test_manual_job_save_updates_existing_posting_and_bridges_pipeline(temp_db, url):
    job = JobPosting(title="Engineer", company="Example", url=url, description="Old")
    job_id = facade.persist_manual_job(job)
    updated = job.model_copy(update={"description": "Updated posting"})
    assert facade.persist_manual_job(updated) == job_id
    assert facade.job_for_drafting(job_id).description == "Updated posting"
    cards = facade.top_jobs()
    assert len(cards) == 1
    assert cards[0]["source"] == "manual"
    assert facade.add_to_pipeline(job_id)["ok"]
