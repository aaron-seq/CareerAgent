"""
CareerAgent - Main Streamlit Application
6 screens: Onboarding, Job Discovery, Pipeline, Contact Finder, Draft Studio,
Export & Logs. Calls only core/facade.py -- no business logic here.
"""

from __future__ import annotations

import hashlib
import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

import streamlit as st
from dotenv import load_dotenv

from core import facade
from core.contact_finder import ContactFinder
from core.cv_parser import CVParser
from core.job_finder import JobFinder

# Core imports
from core.llm import GROQ_DEFAULT_MODEL, CloudLLMClient, LocalLLMClient
from core.logging_config import configure_logging
from core.models import CVProfile, EmailDraft, JobPosting, SearchQuery
from core.outreach import ComplianceConfig, LIARecord
from core.personalization import PersonalizationEngine
from core.storage import LocalStorage
from core.validators import DraftValidator

load_dotenv()
configure_logging()  # level from CAREERAGENT_LOG_LEVEL (default INFO)

# Page config
st.set_page_config(
    page_title="CareerAgent - Local AI Career Agent",
    page_icon=None,
    layout="wide",
    initial_sidebar_state="auto",
)


# Load custom CSS
def load_css():
    # Try multiple paths for robustness
    paths = [
        Path("assets/style.css"),
        Path("CareerAgent/assets/style.css"),
    ]
    for css_file in paths:
        if css_file.exists():
            with open(css_file) as f:
                st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
            return


load_css()


# Initialize session state
def init_session_state():
    """Initialize all session state variables"""
    if "page" not in st.session_state:
        st.session_state.page = "onboarding"

    if "llm_client" not in st.session_state:
        st.session_state.llm_client = None

    if "cv_profile" not in st.session_state:
        st.session_state.cv_profile = None

    if "selected_jobs" not in st.session_state:
        st.session_state.selected_jobs = []

    if "selected_job_refs" not in st.session_state:
        st.session_state.selected_job_refs = {}

    if "found_contacts" not in st.session_state:
        st.session_state.found_contacts = {}

    if "current_draft" not in st.session_state:
        st.session_state.current_draft = None

    if "draft_history" not in st.session_state:
        st.session_state.draft_history = []

    if "gmail_client" not in st.session_state:
        st.session_state.gmail_client = None

    if "storage" not in st.session_state:
        st.session_state.storage = LocalStorage()

    if "cv_id" not in st.session_state:
        st.session_state.cv_id = None

    if "draft_workspaces" not in st.session_state:
        st.session_state.draft_workspaces = {}


def _workspace_state() -> dict[str, Any]:
    return {
        key: st.session_state.get(key)
        for key in (
            "cv_id",
            "selected_jobs",
            "selected_job_refs",
            "found_contacts",
            "preferences",
            "page",
        )
    }


def _workspace_signature() -> str:
    data = _workspace_state()
    return hashlib.sha256(
        json.dumps(
            data, sort_keys=True, default=lambda value: value.model_dump()
        ).encode()
    ).hexdigest()


def _persist_workspace() -> None:
    """Save only deliberate choices, keeping live editors intact on failure."""
    if st.session_state.get("workspace_recovery_blocked"):
        return
    try:
        signature = _workspace_signature()
        if signature == st.session_state.get("workspace_saved_signature"):
            return
        facade.save_workspace(st.session_state.storage, _workspace_state())
        st.session_state.workspace_saved_signature = signature
        st.session_state.workspace_save_warning = None
    except Exception:
        st.session_state.workspace_save_warning = (
            "Your current work is still open, but workspace recovery could not be saved. "
            "Check storage/database access before refreshing; the previous saved workspace is retained."
        )


def _sync_preference_widgets() -> None:
    """Commit changed widgets before sidebar navigation can trigger a rerun."""
    preferences = st.session_state.get("preferences", {}).copy()
    for field in ("target_roles", "target_locations", "industries", "seniority"):
        key = f"preference_{field}"
        if key not in st.session_state:
            continue
        value = st.session_state[key]
        preferences[field] = (
            [line.strip() for line in value.splitlines() if line.strip()]
            if field in ("target_roles", "target_locations")
            else value
        )
    st.session_state.preferences = preferences
    _persist_workspace()


def _rerun() -> None:
    _persist_workspace()
    st.rerun()


def _use_profile(profile: CVProfile, cv_id: int | None = None) -> None:
    """Replace the active profile and invalidate its generated UI material."""
    st.session_state.cv_profile = profile
    st.session_state.cv_id = cv_id
    st.session_state.draft_workspaces = {}
    st.session_state.active_draft_job = None
    for name in ("current_draft", "tailored", "cover", "current_wa_draft"):
        st.session_state[name] = None
    for key in list(st.session_state):
        if isinstance(key, str) and key.startswith(
            ("draft_subject_", "draft_body_", "cover_text_")
        ):
            del st.session_state[key]
    try:
        with st.spinner("Updating job matches for this CV..."):
            facade.refresh_matches(profile)
        st.session_state.match_refresh_warning = None
    except Exception:
        st.session_state.match_refresh_warning = (
            "Your CV is ready, but job matches could not be updated. Choose "
            "Re-score matches in Pipeline before relying on the displayed scores."
        )


def _select_job(job: JobPosting) -> None:
    """Keep explicit job additions available to both drafting and tracking."""
    notices = []
    if job not in st.session_state.selected_jobs:
        st.session_state.selected_jobs.append(job)
        try:
            st.session_state.storage.save_job_posting(job)
        except Exception:
            notices.append(
                "This job is selected, but its local backup could not be saved."
            )
    try:
        job_id = facade.persist_manual_job(job)
        st.session_state.selected_job_refs[facade.workspace_job_key(job)] = job_id
        if st.session_state.cv_profile:
            facade.refresh_matches(st.session_state.cv_profile)
    except Exception:
        notices.append(
            "This job is selected, but could not be saved or scored in Pipeline. "
            "Check database access and add it again to retry."
        )
    st.session_state.job_save_notice = " ".join(notices)


def _activate_draft_job(job: JobPosting) -> str:
    """Keep generated material and editor widgets with their selected job."""
    key = hashlib.sha256(job.model_dump_json().encode()).hexdigest()[:20]
    previous = st.session_state.get("active_draft_job")
    if previous == key:
        return key
    names = ("current_draft", "tailored", "cover", "current_wa_draft")
    if previous is not None:
        st.session_state.draft_workspaces.setdefault(previous, {}).update(
            {name: st.session_state.get(name) for name in names}
        )
    workspace = st.session_state.draft_workspaces.setdefault(key, {})
    # Accept an existing session's email only when it belongs to this job.
    existing = st.session_state.get("current_draft")
    if previous is None and existing and existing.company == job.company:
        if not existing.job_title or existing.job_title == job.title:
            workspace = {**workspace, "current_draft": existing}
    for name in names:
        st.session_state[name] = workspace.get(name)
    st.session_state.active_draft_job = key
    return key


def _set_current_draft(draft: EmailDraft, workspace_key: str) -> None:
    """Fresh generations replace the editor's prior widget values on rerun."""
    st.session_state.current_draft = draft
    st.session_state[f"draft_subject_{workspace_key}"] = draft.subject
    st.session_state[f"draft_body_{workspace_key}"] = draft.body


def _prepare_application(job_id: int) -> None:
    """Choose the next screen before Streamlit renders the page body."""
    try:
        job = facade.job_for_drafting(job_id)
        if job is None:
            st.session_state.prepare_job_error = (
                "This posting is no longer available. Refresh the jobs list."
            )
            return
        if job not in st.session_state.selected_jobs:
            st.session_state.selected_jobs.append(job)
        st.session_state.selected_job_refs[facade.workspace_job_key(job)] = job_id
        st.session_state.draft_job_selection = st.session_state.selected_jobs.index(job)
        st.session_state.page = "draft" if st.session_state.cv_profile else "onboarding"
        st.session_state.prepare_job_error = None
        _persist_workspace()
    except Exception as exc:
        st.session_state.prepare_job_error = f"Could not open this job: {exc}"


_initial_workspace_keys = set(st.session_state)
init_session_state()

# Ensure the database schema exists (Phase 1+). Non-fatal if it can't init so
# the legacy JSON-only flow still works.
try:
    facade.init_persistence()
except Exception:  # pragma: no cover - defensive UI guard
    st.warning(
        "The database could not be opened. Check its location and permissions before saving."
    )


if not st.session_state.get("workspace_recovery_attempted"):
    st.session_state.workspace_recovery_attempted = True
    try:
        recovered = facade.restore_workspace(st.session_state.storage)
        if recovered is not None:
            for name, value in recovered["state"].items():
                if name not in _initial_workspace_keys:
                    st.session_state[name] = value
            st.session_state.workspace_recovery_notices = recovered["notices"]
        st.session_state.workspace_saved_signature = _workspace_signature()
    except Exception:
        st.session_state.workspace_recovery_blocked = True


def _render_workspace_notices() -> None:
    for notice in st.session_state.get("workspace_recovery_notices", []):
        st.warning(notice)
    if st.session_state.get("workspace_recovery_blocked"):
        st.warning(
            "Saved workspace recovery failed. Check your encryption key and storage, then reload. "
            "Your saved workspace has not been overwritten. CVs and jobs remain in the database."
        )
        with st.expander("Workspace recovery options"):
            st.caption(
                "Start a new saved workspace from the choices currently open here. "
                "The unreadable file will be retained as a private .bak file in your storage folder. "
                "Existing CVs, jobs and saved drafts are kept."
            )
            if st.button("Start a new saved workspace", key="reset_saved_workspace"):
                try:
                    facade.reset_workspace(st.session_state.storage)
                    st.session_state.workspace_recovery_blocked = False
                    st.session_state.workspace_saved_signature = None
                    _rerun()
                except Exception:
                    st.error(
                        "Could not retain the recovery backup. Check storage access and try again."
                    )
    if st.session_state.get("workspace_save_warning"):
        st.warning(st.session_state.workspace_save_warning)


# Sidebar configuration
def render_sidebar():
    """Render sidebar with navigation and settings"""
    with st.sidebar:
        st.title("CareerAgent")
        st.markdown(
            '<p class="wordmark-sub">Local AI Career Agent</p>',
            unsafe_allow_html=True,
        )

        st.divider()

        # Navigation
        st.subheader("Navigation")
        pages = {
            "onboarding": "Onboarding",
            "discovery": "Job Discovery",
            "pipeline": "Pipeline",
            "contacts": "Contact Finder",
            "draft": "Draft Studio",
            "export": "Export & Logs",
        }

        current = st.session_state.get("page", "onboarding")
        for key, label in pages.items():
            if st.button(
                label,
                key=f"nav_{key}",
                use_container_width=True,
                type="primary" if key == current else "secondary",
            ):
                st.session_state.page = key
                _rerun()

        st.divider()

        st.subheader("AI assistance")
        with st.expander("AI settings", expanded=False):
            st.caption(
                "Connect AI to import CV text or generate messages. Local Ollama keeps prompts on this machine."
            )
            provider = st.radio(
                "Provider",
                ["Ollama (local)", "Groq (cloud, free tier)"],
                key="llm_provider",
            )
            use_cloud = (provider or "").startswith("Groq")

            if use_cloud:
                model = (
                    st.text_input(
                        "Model",
                        value=GROQ_DEFAULT_MODEL,
                        key="selected_cloud_model",
                        help="Any model id your Groq key can access.",
                    )
                    or GROQ_DEFAULT_MODEL
                )
                st.caption(
                    "CV text and other prompts are sent to Groq when you use this provider."
                )
            else:
                configured_model = os.getenv("OLLAMA_MODEL") or "llama3.1:8b"
                models = list(
                    dict.fromkeys(
                        [
                            configured_model,
                            "llama3.1:8b",
                            "llama3.2:3b",
                            "qwen2.5:7b",
                            "mistral:7b",
                        ]
                    )
                )
                model = (
                    st.selectbox(
                        "Model",
                        models,
                        key="selected_model",
                    )
                    or configured_model
                )

            connected = st.session_state.llm_client
            if connected is not None and (
                isinstance(connected, CloudLLMClient) != use_cloud
                or connected.model != model
            ):
                # The displayed provider must describe the client receiving CV data.
                st.session_state.llm_client = None

            if st.button("Connect AI", use_container_width=True):
                target = "Groq" if use_cloud else "Ollama"
                with st.spinner(f"Connecting to {target}..."):
                    try:
                        if use_cloud:
                            llm = CloudLLMClient(
                                api_key=os.getenv("GROQ_API_KEY", ""), model=model
                            )
                        else:
                            llm = LocalLLMClient(model=model)

                        if llm.check_connection() and llm.check_model_availability(
                            model
                        ):
                            st.session_state.llm_client = llm
                            st.success(f"Connected to {model}")
                        elif use_cloud:
                            st.error(
                                "Groq or the selected model is unavailable. Check GROQ_API_KEY and the model."
                            )
                        else:
                            st.error(
                                f"Ollama or the selected model is unavailable. Start Ollama and run `ollama pull {model}`."
                            )
                    except Exception as e:
                        st.error(f"Error: {e}")

        if st.session_state.llm_client:
            st.caption(f"Connected: {st.session_state.llm_client.model}")
        else:
            st.caption(
                "Optional · off. Build CVs, browse jobs and track applications now."
            )
        st.divider()

        # Stats
        st.subheader("Session Stats")
        st.metric("Active CV", "Yes" if st.session_state.cv_profile else "No")
        st.metric("Jobs Selected", len(st.session_state.selected_jobs))
        st.metric("Drafts Created", len(st.session_state.draft_history))


def _save_cv_profile(profile: CVProfile) -> bool:
    """Activate a draft only after encrypted database persistence succeeds."""
    try:
        cv_id = facade.persist_cv(profile)
    except Exception:
        st.error(
            "Your CV could not be saved. Check database access and try again. "
            "Your current CV and application materials are unchanged."
        )
        return False
    try:
        st.session_state.storage.save_cv_profile(profile)
        st.session_state.cv_backup_warning = None
    except Exception:
        st.session_state.cv_backup_warning = (
            "Your CV is saved in the encrypted database, but its local backup "
            "could not be written. Check the backup folder permissions before "
            "relying on that copy."
        )
    _use_profile(profile, cv_id)
    return True


def _remember_cv_builder_value(scope: str, key: str) -> None:
    """Retain explicit editor input in RAM before navigation callbacks run."""
    draft = st.session_state.get("cv_builder_draft", {})
    if draft.get("scope") != scope:
        draft = {"scope": scope, "values": {}}
    draft["values"][key] = st.session_state[key]
    st.session_state.cv_builder_draft = draft


def _cv_builder_widget(scope: str, key: str) -> dict[str, Any]:
    return {"key": key, "on_change": _remember_cv_builder_value, "args": (scope, key)}


def _render_cv_builder() -> None:
    """Collect explicit candidate facts; core validates the submitted draft."""
    profile = st.session_state.cv_profile or CVProfile()
    source = f"{st.session_state.cv_id}:{profile.model_dump_json()}"
    scope = hashlib.sha256(source.encode()).hexdigest()[:16]
    prefix = f"cv_builder_{scope}"
    draft = st.session_state.get("cv_builder_draft", {})
    if draft.get("scope") != prefix:
        # One active-profile draft bounds memory; deliberately activating or
        # saving another profile starts its own editor from that profile's facts.
        draft = {"scope": prefix, "values": {}}
        st.session_state.cv_builder_draft = draft
    for key, value in draft["values"].items():
        if key not in st.session_state:
            st.session_state[key] = value
    with st.expander("Build or edit your CV", expanded=not st.session_state.cv_profile):
        st.caption(
            "Use your own facts. Changes become active when you choose "
            "Create CV and check readiness. Unsaved edits stay in this browser "
            "session; save to keep them after a refresh."
        )
        if len(profile.experiences) > 30 or len(profile.projects) > 30:
            st.warning(
                "This CV has more than 30 work or project entries. The editor "
                "supports up to 30 of each, so editing is unavailable to avoid "
                "dropping your records. Your complete CV remains available for export."
            )
            return
        data: dict[str, Any] = {}
        columns = st.columns(2)
        for column, field, label in (
            (columns[0], "name", "Full name"),
            (columns[1], "email", "CV email"),
        ):
            with column:
                data[field] = st.text_input(
                    label,
                    value=getattr(profile, field) or "",
                    **_cv_builder_widget(prefix, f"{prefix}_{field}"),
                )
        with st.expander("Contact details and links (optional)"):
            for field, label in (
                ("phone", "CV phone (optional)"),
                ("linkedin", "LinkedIn URL (optional)"),
                ("github", "GitHub URL (optional)"),
                ("portfolio", "Portfolio URL (optional)"),
            ):
                data[field] = st.text_input(
                    label,
                    value=getattr(profile, field) or "",
                    **_cv_builder_widget(prefix, f"{prefix}_{field}"),
                )
        data["summary"] = st.text_area(
            "Professional summary (optional)",
            value=profile.summary or "",
            **_cv_builder_widget(prefix, f"{prefix}_summary"),
        )
        data["skills"] = st.text_area(
            "Skills (one per line)",
            value="\n".join(profile.skills),
            **_cv_builder_widget(prefix, f"{prefix}_skills"),
        )
        data["education"] = st.text_area(
            "Education or training (one per line)",
            value="\n".join(profile.education),
            **_cv_builder_widget(prefix, f"{prefix}_education"),
        )
        st.caption(
            "Projects count as experience evidence for entry-level applicants. "
            "Add only the entries you need; reducing a count removes those entries "
            "from the next saved CV. Your existing saved CV stays available."
        )
        count_columns = st.columns(2)
        with count_columns[0]:
            work_count = st.number_input(
                "Work experience entries",
                min_value=0,
                max_value=30,
                value=len(profile.experiences),
                step=1,
                **_cv_builder_widget(prefix, f"{prefix}_work_count"),
            )
        with count_columns[1]:
            project_count = st.number_input(
                "Project entries",
                min_value=0,
                max_value=30,
                value=len(profile.projects),
                step=1,
                **_cv_builder_widget(prefix, f"{prefix}_project_count"),
            )
        data["experiences"] = []
        for index in range(work_count):
            original = (
                profile.experiences[index].model_dump()
                if index < len(profile.experiences)
                else {}
            )
            with st.container(border=True):
                st.markdown(f"**Work experience {index + 1}**")
                entry = {}
                for field, label in (
                    ("title", "Job title"),
                    ("company", "Employer"),
                    ("duration", "Actual dates or duration"),
                ):
                    entry[field] = st.text_input(
                        f"Role {index + 1}: {label}",
                        value=original.get(field, ""),
                        **_cv_builder_widget(prefix, f"{prefix}_role_{index}_{field}"),
                    )
                for field, label in (
                    ("achievements", "Accomplishments"),
                    ("metrics", "Existing metrics (optional)"),
                    ("technologies", "Technologies"),
                ):
                    entry[field] = st.text_area(
                        f"Role {index + 1}: {label} (one per line)",
                        value="\n".join(original.get(field, [])),
                        **_cv_builder_widget(prefix, f"{prefix}_role_{index}_{field}"),
                    )
                data["experiences"].append(entry)
        data["projects"] = []
        for index in range(project_count):
            original = (
                profile.projects[index].model_dump()
                if index < len(profile.projects)
                else {}
            )
            with st.container(border=True):
                st.markdown(f"**Project {index + 1}**")
                entry = {}
                for field, label in (
                    ("name", "Name"),
                    ("link", "Project URL (optional)"),
                    ("github", "Repository URL (optional)"),
                ):
                    entry[field] = st.text_input(
                        f"Project {index + 1}: {label}",
                        value=original.get(field) or "",
                        **_cv_builder_widget(
                            prefix, f"{prefix}_project_{index}_{field}"
                        ),
                    )
                for field, label in (
                    ("description", "Factual description"),
                    ("impact", "Real impact (optional)"),
                ):
                    entry[field] = st.text_area(
                        f"Project {index + 1}: {label}",
                        value=original.get(field) or "",
                        **_cv_builder_widget(
                            prefix, f"{prefix}_project_{index}_{field}"
                        ),
                    )
                entry["technologies"] = st.text_area(
                    f"Project {index + 1}: Technologies (one per line)",
                    value="\n".join(original.get("technologies", [])),
                    **_cv_builder_widget(
                        prefix, f"{prefix}_project_{index}_technologies"
                    ),
                )
                data["projects"].append(entry)
        if st.button(
            "Create CV and check readiness",
            type="primary",
            key=f"{prefix}_save",
            use_container_width=True,
        ):
            try:
                created = facade.build_cv_profile(data)
            except ValueError as exc:
                st.error(str(exc))
            else:
                if _save_cv_profile(created):
                    st.session_state.cv_save_notice = "Your CV is saved. Review its readiness and download the format you need."
                    _rerun()


def _render_cv_assessment(profile: CVProfile, job: JobPosting | None = None) -> None:
    """Present the core checklist and its explicit limits."""
    assessment = facade.assess_resume(profile, job)
    st.metric("Local CV readiness", f"{assessment['readiness_score']}/100")
    st.caption(
        "This weighted checklist measures CV content completeness. Layout checks "
        "are separate. It is not an external ATS score and cannot "
        "guarantee ranking, interviews or a hiring outcome."
    )
    with st.expander("Readiness checklist"):
        for check in assessment["checks"]:
            status = "Complete" if check["passed"] else "Needs attention"
            st.markdown(f"**{check['label']} — {status} ({check['weight']} points)**")
            st.caption(check["detail"])
    if assessment["actions"]:
        with st.expander("Ways to improve your CV", expanded=True):
            for action in assessment["actions"]:
                st.write(action)
    match = assessment["job_match"]
    if match is not None:
        if match["score"] is None:
            st.info(
                "There is not enough useful job-skill evidence to calculate coverage."
            )
        else:
            st.metric("Job skill coverage", f"{match['score']:g}%")
            st.write("Matched skills: " + (", ".join(match["matched"]) or "None found"))
            st.write(
                "Skills to review: "
                + (
                    ", ".join(match["missing"])
                    or "No gaps found in the recognized signals"
                )
            )
        st.caption(match["method"])
        st.caption(
            "Add a missing skill only when it truthfully describes you. Reordering the same facts does not increase coverage."
        )


def _remember_application_detail(cv_id: int, path: str, key: str) -> None:
    draft = st.session_state.application_detail_drafts[cv_id]
    value = st.session_state[key]
    if value == draft["initial"][path]:
        draft["values"].pop(path, None)
    else:
        draft["values"][path] = value
    st.session_state.application_detail_notice = None


def _application_detail_widget(cv_id: int, path: str, default: Any) -> dict[str, Any]:
    draft = st.session_state.application_detail_drafts[cv_id]
    key = f"application_detail_{cv_id}_{draft['revision']}_{path}"
    draft["initial"].setdefault(path, default)
    if key not in st.session_state:
        st.session_state[key] = draft["values"].get(path, default)
    return {
        "key": key,
        "on_change": _remember_application_detail,
        "args": (cv_id, path, key),
    }


def _render_application_details() -> None:
    """Edit only explicit answers associated with the active encrypted CV row."""
    st.subheader("Application details")
    st.caption(
        "Optional answers for application forms, stored encrypted with this saved CV. "
        "Leave undecided answers blank. A new CV starts with unanswered details."
    )
    cv_id = st.session_state.cv_id
    if cv_id is None:
        st.info("Save this CV before adding application details.")
        if st.button("Save this CV", key="save_current_cv_for_details"):
            if _save_cv_profile(st.session_state.cv_profile):
                _rerun()
        return
    drafts = st.session_state.setdefault("application_detail_drafts", {})
    if cv_id not in drafts:
        try:
            candidate = facade.load_candidate_profile(cv_id)
            if candidate is None:
                raise ValueError("Saved CV not found")
        except Exception:
            st.error(
                "Application details could not be opened. Check database access and "
                "the original encryption key. Existing saved answers are unchanged."
            )
            return
        revision = st.session_state.get("application_detail_revision", 0) + 1
        st.session_state.application_detail_revision = revision
        drafts[cv_id] = {
            "saved": candidate.model_dump(mode="json"),
            "values": {},
            "initial": {},
            "revision": revision,
        }
    draft = drafts[cv_id]
    saved = draft["saved"]
    st.caption(f"Editing application details for saved CV #{cv_id}.")
    notice = st.empty()
    if st.session_state.get("application_detail_notice") == cv_id:
        notice.success("Application details saved. New downloads use these answers.")
    if draft["values"]:
        notice.warning(
            "You have unsaved application details. Downloads use the last saved answers."
        )
    with st.expander("Edit application details", expanded=False):
        st.caption(
            "Unsaved edits stay in this browser session. Save to keep them after a refresh. "
            "These answers do not change job-match or CV-readiness scores."
        )
        st.text_input(
            "Current city or region (optional)",
            **_application_detail_widget(cv_id, "location", saved["location"] or ""),
        )
        st.text_area(
            "Other portfolio websites (one per line, optional)",
            help="The first website is used only if your CV has no portfolio URL.",
            **_application_detail_widget(
                cv_id, "websites", "\n".join(saved["websites"])
            ),
        )
        st.markdown("**Work eligibility**")
        authorization = saved["work_authorization"]
        st.text_input(
            "Country this work eligibility applies to (optional)",
            max_chars=100,
            **_application_detail_widget(
                cv_id, "work_authorization.country", authorization["country"] or ""
            ),
        )
        st.caption(
            "Autofill uses eligibility only for supported questions explicitly naming "
            "that same country. Missing, unfamiliar or different countries need your review."
        )
        for field, label in (
            ("authorized", "Authorized to work in that country?"),
            (
                "requires_sponsorship",
                "Require sponsorship now or in the future in that country?",
            ),
        ):
            st.selectbox(
                label,
                [None, True, False],
                format_func=lambda value: (
                    "Not answered" if value is None else "Yes" if value else "No"
                ),
                **_application_detail_widget(
                    cv_id, f"work_authorization.{field}", authorization[field]
                ),
            )
        st.text_input(
            "Visa or immigration status (optional)",
            max_chars=5000,
            **_application_detail_widget(
                cv_id,
                "work_authorization.visa_status",
                authorization["visa_status"] or "",
            ),
        )
        st.markdown("**Pay and availability**")
        compensation = saved["compensation"]
        for field, label in (
            ("target", "Expected pay to share on applications (optional)"),
            ("minimum", "Minimum pay fallback (optional)"),
        ):
            st.text_input(
                label,
                **_application_detail_widget(
                    cv_id,
                    f"compensation.{field}",
                    "" if compensation[field] is None else str(compensation[field]),
                ),
            )
        st.caption(
            "Downloads use expected pay when supplied, otherwise your saved minimum. "
            "Both are shared as stated with currency and period; no conversion or rounding."
        )
        pay_columns = st.columns(2)
        with pay_columns[0]:
            st.text_input(
                "Pay currency (three-letter code)",
                max_chars=3,
                **_application_detail_widget(
                    cv_id, "compensation.currency", compensation["currency"]
                ),
            )
        with pay_columns[1]:
            st.selectbox(
                "Pay period",
                ["year", "month", "day", "hour"],
                **_application_detail_widget(
                    cv_id, "compensation.period", compensation["period"]
                ),
            )
        availability = saved["availability"]
        st.text_input(
            "Notice period in weeks (optional)",
            help="Leave blank if undecided; 0 means no notice period. Maximum 104 weeks.",
            **_application_detail_widget(
                cv_id,
                "availability.notice_period_weeks",
                ""
                if availability["notice_period_weeks"] is None
                else str(availability["notice_period_weeks"]),
            ),
        )
        st.text_input(
            "Earliest start date or availability (optional)",
            max_chars=5000,
            **_application_detail_widget(
                cv_id,
                "availability.earliest_start_date",
                availability["earliest_start_date"] or "",
            ),
        )
        st.selectbox(
            "Open to relocation?",
            [None, True, False],
            format_func=lambda value: (
                "Not answered" if value is None else "Yes" if value else "No"
            ),
            **_application_detail_widget(
                cv_id,
                "preferences.open_to_relocation",
                saved["preferences"]["open_to_relocation"],
            ),
        )
        st.text_area(
            "Reusable cover note (optional)",
            max_chars=5000,
            help="Use your own words. Review this generic note for each employer.",
            **_application_detail_widget(
                cv_id, "default_cover_note", saved["default_cover_note"] or ""
            ),
        )
        with st.expander("Voluntary application answers", expanded=False):
            st.caption(
                "Leave any or all blank. They do not affect readiness or matching."
            )
            demographics = saved["demographics"]
            for field, label in (
                ("pronouns", "Pronouns (optional)"),
                ("gender", "Gender (optional)"),
                ("ethnicity", "Ethnicity (optional)"),
                ("veteran_status", "Veteran status (optional)"),
                ("disability_status", "Disability status (optional)"),
            ):
                st.text_input(
                    label,
                    max_chars=5000,
                    **_application_detail_widget(
                        cv_id, f"demographics.{field}", demographics[field] or ""
                    ),
                )
            st.checkbox(
                "Include these voluntary answers in my autofill profile",
                **_application_detail_widget(
                    cv_id,
                    "demographics.share_on_applications",
                    demographics["share_on_applications"],
                ),
            )
        save_column, reset_column = st.columns(2)
        with save_column:
            if st.button(
                "Save application details", type="primary", use_container_width=True
            ):
                data = deepcopy(saved)
                for path, value in draft["values"].items():
                    parts = path.split(".")
                    target = data
                    for part in parts[:-1]:
                        target = target[part]
                    target[parts[-1]] = value
                try:
                    result = facade.save_candidate_profile(cv_id, data)
                except Exception:
                    st.error(
                        "Application details could not be saved. Your edits remain here; existing saved answers are unchanged."
                    )
                else:
                    if result["ok"]:
                        drafts.pop(cv_id)
                        st.session_state.application_detail_notice = cv_id
                        _rerun()
                    else:
                        st.error(result["error"])
        with reset_column:
            if st.button("Reset unsaved changes", use_container_width=True):
                drafts.pop(cv_id)
                st.session_state.application_detail_notice = None
                _rerun()


def _render_autofill_handoff() -> None:
    """Review saved answers and offer one existing extension import contract."""
    profile = st.session_state.cv_profile
    if profile is None:
        st.info("Create, import or restore a CV before preparing an autofill profile.")
        if st.button("Add or restore my CV", key="autofill_add_cv"):
            st.session_state.page = "onboarding"
            _rerun()
        return
    cv_id = st.session_state.cv_id
    candidate = None
    if cv_id is not None:
        try:
            candidate = facade.load_candidate_profile(cv_id)
            if candidate is None:
                raise ValueError("Saved CV not found")
            preview = facade.application_details_preview(candidate)
        except Exception:
            st.error(
                "Saved application details could not be opened. Check the database and original encryption key before exporting."
            )
            return
        st.caption(f"Using {profile.name or 'Unnamed CV'} · saved CV #{cv_id}.")
        source = preview["compensation_source"]
        if source is not None:
            label = "Expected pay" if source == "target" else "Minimum pay fallback"
            st.info(
                f"{label} in this download: {preview['answers']['salary_expectation']}"
            )
        st.caption(
            "Voluntary answers included by your saved choice."
            if preview["voluntary_answers_shared"]
            else "Voluntary answers excluded."
        )
        if (
            st.session_state.get("application_detail_drafts", {})
            .get(cv_id, {})
            .get("values")
        ):
            st.warning(
                "You have unsaved application details. This download uses the last saved answers."
            )
    else:
        st.info(
            "This CV is not saved yet. This download includes CV identity only; save it in Onboarding to add application details."
        )
    if st.button("Edit application details", key="autofill_edit_details"):
        st.session_state.page = "onboarding"
        _rerun()
    exported = facade.extension_profile(profile, candidate)
    with st.expander("Saved fields in this download", expanded=True):
        st.json(exported)
    include_pdf = st.checkbox(
        "Include my CV PDF for resume upload",
        value=False,
        key=f"autofill_include_pdf_{cv_id}",
        help="Optional readable PDF, up to 2 MB. It contains the active CV shown above.",
    )
    if include_pdf:
        try:
            exported = facade.extension_profile(profile, candidate, include_resume=True)
        except ValueError as exc:
            st.warning(
                f"{exc} The download below contains answers only, without a PDF."
            )
        except Exception:
            st.warning(
                "The PDF could not be prepared. The download below contains answers only, without a PDF."
            )
        else:
            st.caption(f"PDF included: {exported['resume']['filename']}")
    st.download_button(
        "Download autofill profile (JSON)",
        data=json.dumps(exported, indent=2),
        file_name="careeragent_autofill_profile.json",
        mime="application/json",
    )
    st.caption(
        "The JSON contains readable personal data. Load the CareerAgent extension from "
        "the extension/ folder using Chrome's Load unpacked option. Open the downloaded "
        "JSON and paste its contents into Import from CareerAgent in the popup. On a "
        "supported Greenhouse, Lever or Ashby form, choose Autofill this page. "
        "Review every answer and submit the employer's form yourself."
    )


def _render_apply_target(job_id: int | None, label: str = "Open application") -> None:
    """Render only a validated stored posting URL, without changing tracking."""
    if job_id is None:
        return
    try:
        target = facade.apply_target(job_id)
    except Exception:
        st.caption("The saved application link could not be opened. Try again later.")
        return
    if not target["ok"]:
        st.caption("This saved job is unavailable. Choose another posting.")
        return
    if target["url"]:
        st.link_button(label, target["url"], use_container_width=True)
    st.caption(target["note"])


# Page 1: Onboarding
def page_onboarding():
    """Onboarding screen - CV upload and preferences"""
    st.title("Onboarding")
    st.markdown(
        "Create, import or restore your CV, then prepare materials for the jobs you choose."
    )
    st.caption("CV building, downloads, job browsing and tracking work without AI.")
    try:
        saved_profiles = facade.saved_cv_profiles()
    except Exception:
        saved_profiles = []
        st.warning("Saved profiles could not be listed. Check database access.")
    if saved_profiles:
        with st.expander("Use a saved CV", expanded=not st.session_state.cv_profile):
            profiles_by_id = {item["id"]: item for item in saved_profiles}
            saved_id = st.selectbox(
                "Saved profile",
                list(profiles_by_id),
                format_func=lambda value: (
                    f"{profiles_by_id[value]['name'] or 'Unnamed profile'} "
                    f"(saved {profiles_by_id[value]['saved_label']})"
                ),
            )
            if st.button("Use this CV", use_container_width=True):
                try:
                    profile = facade.load_cv(saved_id)
                    if profile is None:
                        st.error(
                            "That profile is unavailable. Choose another or upload a CV."
                        )
                    else:
                        _use_profile(profile, saved_id)
                        _rerun()
                except Exception:
                    st.error(
                        "This CV could not be opened. Check database access and restore "
                        "its original encryption key; keep the current key unchanged."
                    )

    llm_ready = bool(st.session_state.llm_client)
    if st.session_state.get("cv_save_notice"):
        st.success(st.session_state.cv_save_notice)
    if st.session_state.get("cv_backup_warning"):
        st.warning(st.session_state.cv_backup_warning)
    build_tab, import_tab = st.tabs(["Build or edit a CV", "Import PDF or text"])
    with build_tab:
        _render_cv_builder()
    with import_tab:
        if not llm_ready:
            st.info(
                "Importing uses AI to organize your existing facts. Open AI settings in the sidebar and choose Connect AI, or choose Build or edit a CV to start now."
            )
        st.subheader("Upload CV")

        # PDF upload
        cv_file = st.file_uploader(
            "Upload CV (PDF)", type=["pdf"], help="Drag and drop your CV PDF here"
        )

        # Text fallback
        with st.expander("Or Paste CV Text (Fallback)"):
            cv_text = st.text_area(
                "Paste CV text",
                height=200,
                help="Use this if PDF upload fails",
                key="import_cv_text",
            )

        if st.button(
            "Parse CV", type="primary", use_container_width=True, disabled=not llm_ready
        ):
            if cv_file or cv_text:
                with st.spinner("Parsing CV with your selected model..."):
                    try:
                        # Progress indicator
                        progress_bar = st.progress(0, text="Initializing...")
                        import time

                        start_time = time.time()

                        progress_bar.progress(
                            20, text="Connecting to LLM & sending data..."
                        )
                        parser = CVParser(st.session_state.llm_client)

                        if cv_file:
                            progress_bar.progress(
                                40, text="Extracting text from PDF..."
                            )
                            profile = parser.parse_pdf_bytes(cv_file.getbuffer())
                        else:
                            progress_bar.progress(
                                40, text="Analyzing text structure..."
                            )
                            profile = parser.parse_text(cv_text)

                        elapsed = time.time() - start_time
                        progress_bar.progress(100, text=f"Complete in {elapsed:.1f}s!")

                        if _save_cv_profile(profile):
                            st.session_state.cv_save_notice = f"CV parsed and saved. Found {len(profile.experiences)} work experiences."
                            _rerun()

                    except Exception as e:
                        st.error(f"❌ Parsing failed: {e}")
                        st.info(
                            "Tip: Try a smaller model (qwen2.5:3b) or shorten the CV text."
                        )
            else:
                st.warning("Please upload a CV or paste text")

    with st.expander("Job search preferences", expanded=False):
        preferences = st.session_state.get("preferences", {})

        # Widget state is temporary when changing pages. Keep the independent
        # preferences dict current in callbacks before sidebar navigation runs.
        defaults = {
            "target_roles": [],
            "target_locations": [],
            "industries": [],
            "seniority": "Any",
        }
        for field, default in defaults.items():
            key = f"preference_{field}"
            if key not in st.session_state:
                value = preferences.get(field, default)
                st.session_state[key] = (
                    "\n".join(value)
                    if field in ("target_roles", "target_locations")
                    else value
                )

        st.text_area(
            "Target Roles (one per line)",
            key="preference_target_roles",
            on_change=_sync_preference_widgets,
            height=100,
        )
        st.text_area(
            "Target Locations (one per line)",
            key="preference_target_locations",
            on_change=_sync_preference_widgets,
            height=100,
        )
        st.multiselect(
            "Preferred Industries",
            ["Tech/Software", "AI/ML", "Finance", "Healthcare", "E-commerce", "Other"],
            key="preference_industries",
            on_change=_sync_preference_widgets,
        )
        st.select_slider(
            "Seniority Level",
            options=["Any", "Junior", "Mid-level", "Senior", "Staff", "Principal"],
            key="preference_seniority",
            on_change=_sync_preference_widgets,
        )
        _sync_preference_widgets()

    # Show parsed CV
    if st.session_state.cv_profile:
        st.divider()
        st.subheader("CV Profile")

        profile = st.session_state.cv_profile

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Name", profile.name or "N/A")
        col2.metric("Email", profile.email or "N/A")
        col3.metric("Projects", len(profile.projects))
        col4.metric("Skills", len(profile.skills))

        with st.expander("View Full Profile"):
            st.json(profile.model_dump())

        st.subheader("CV readiness")
        selected_job = None
        selected_jobs = st.session_state.selected_jobs
        if selected_jobs:
            options = [None, *range(len(selected_jobs))]
            if st.session_state.get("cv_readiness_job") not in options:
                st.session_state.cv_readiness_job = None
            index = st.selectbox(
                "Compare CV with a selected job",
                options,
                format_func=lambda value: (
                    "Choose a job (optional)"
                    if value is None
                    else f"{selected_jobs[value].title} at {selected_jobs[value].company}"
                ),
                key="cv_readiness_job",
            )
            if index is not None:
                selected_job = selected_jobs[index]
        _render_cv_assessment(profile, selected_job)

        # --- ATS-friendliness report + ATS-clean exports (Phase 5) --- #
        st.divider()
        st.subheader("ATS check")
        report = facade.lint_resume(profile, raw_text=profile.raw_text or None)

        if report["ok"]:
            st.success("No blocking ATS issues found.")
        else:
            for msg in report["errors"]:
                st.error(msg)
        for msg in report["warnings"]:
            st.warning(msg)
        if report["info"]:
            with st.expander(f"Suggestions ({len(report['info'])})"):
                for msg in report["info"]:
                    st.info(msg)

        st.caption(
            "Exports are single-column, standard-font, selectable text - the "
            "format applicant-tracking systems parse most reliably."
        )
        exp1, exp2, exp3 = st.columns(3)
        with exp1:
            try:
                pdf = facade.resume_pdf(profile)
            except ValueError as exc:
                st.warning(f"{exc} Markdown and JSON downloads remain available.")
            else:
                st.download_button(
                    "Download ATS-clean PDF",
                    data=pdf,
                    file_name="resume_ats.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                )
        with exp2:
            st.download_button(
                "Download Markdown",
                data=facade.resume_markdown(profile),
                file_name="resume.md",
                mime="text/markdown",
                use_container_width=True,
            )
        with exp3:
            import json as _json

            st.download_button(
                "Download JSON Resume",
                data=_json.dumps(facade.resume_json(profile), indent=2),
                file_name="resume.json",
                mime="application/json",
                use_container_width=True,
            )

        st.divider()
        _render_application_details()

        next_page = "draft" if st.session_state.selected_jobs else "discovery"
        next_label = "Draft Studio" if next_page == "draft" else "Job Discovery"
        if st.button(f"Next: {next_label}", type="primary", use_container_width=True):
            st.session_state.page = next_page
            _rerun()


# Page 2: Job Discovery
def page_discovery():
    """Job discovery screen"""
    st.title("Job Discovery")
    st.markdown(
        "API-first discovery: pull structured postings straight from a "
        "company's ATS, or extract them from a careers page. Web search is a "
        "last-resort fallback."
    )

    if not st.session_state.cv_profile:
        st.info(
            "Browse and save jobs now. Add or restore your CV in Onboarding "
            "when you want personalized matching and application materials."
        )

    # Search mode. Ordered best-data-first; the DuckDuckGo path is retained as
    # an explicitly-labeled fallback for companies without a supported ATS.
    mode = st.radio(
        "Discovery mode",
        [
            "Company careers URL (recommended)",
            "Job boards (API)",
            "Paste Job URL",
            "Paste Job Description",
            "Web Search (fallback)",
        ],
        horizontal=True,
        help=(
            "Careers URL auto-detects Greenhouse/Lever/Ashby and uses their "
            "public API; otherwise it reads schema.org JSON-LD, honoring "
            "robots.txt. Job boards query aggregator APIs by keyword."
        ),
    )

    st.divider()

    if mode == "Company careers URL (recommended)":
        careers_url = st.text_input(
            "Careers page or job board URL",
            placeholder="https://boards.greenhouse.io/stripe",
            help="e.g. a Greenhouse/Lever/Ashby board, or any careers page.",
        )
        if st.button("Discover jobs", type="primary"):
            if not careers_url:
                st.warning("Enter a URL first")
            else:
                with st.spinner("Detecting ATS / reading structured data..."):
                    try:
                        result = facade.discover_from_url(careers_url)
                    except Exception as e:
                        result = {"stored": 0, "errors": [str(e)], "method": "error"}

                if result["stored"]:
                    method = (
                        f"{result.get('ats_type', '')} API"
                        if result["method"] == "ats"
                        else "JSON-LD extraction"
                    )
                    st.success(
                        f"Stored {result['stored']} job(s) via {method}. "
                        "See them scored on the Pipeline screen."
                    )
                    if st.session_state.cv_profile:
                        with st.spinner("Scoring against your CV..."):
                            facade.refresh_matches(st.session_state.cv_profile)
                else:
                    for err in result.get("errors", ["Nothing found."]):
                        st.warning(err)
                for warning in result.get("warnings", []):
                    st.warning(warning)
                if (
                    result.get("warnings")
                    and result.get("ats_type") == "smartrecruiters"
                ):
                    st.caption(
                        "Continue this board in Pipeline: choose SmartRecruiters and "
                        "enter the next offset under Import a large job board."
                    )

        st.info(
            "Discovered jobs are deduplicated, enriched, and scored on the "
            "**Pipeline** screen.",
            icon=None,
        )

    elif mode == "Job boards (API)":
        st.caption(
            "Structured results from aggregator APIs. Remotive, Arbeitnow, "
            "Jobicy, RemoteOK and Himalayas need no key; The Muse works "
            "keyless at a lower rate limit; Adzuna requires ADZUNA_APP_ID / "
            "ADZUNA_APP_KEY in your environment."
        )
        bcol1, bcol2 = st.columns([1, 2])
        with bcol1:
            provider = st.selectbox("Provider", facade.aggregator_providers())
        searchable = facade.aggregator_supports_keywords(provider)
        with bcol2:
            keywords = st.text_input(
                "Keywords (optional)",
                placeholder="machine learning",
                disabled=not searchable,
                help=(
                    "This provider has no server-side search - it returns its "
                    "newest postings. Filter them on the Pipeline screen."
                )
                if not searchable
                else None,
            )

        if st.button("Search job boards", type="primary"):
            with st.spinner(f"Querying {provider}..."):
                try:
                    result = facade.ingest_aggregator(provider, keywords=keywords)
                except ValueError as e:
                    result = None
                    st.error(str(e))
                except Exception as e:
                    result = None
                    st.error(f"Search failed: {e}")

            if result is not None:
                if result.errors:
                    st.error(f"{provider} error: {result.errors[0]}")
                elif result.upserted:
                    st.success(
                        f"Stored {result.upserted} job(s) from {provider}. "
                        "See them scored on the Pipeline screen."
                    )
                    if st.session_state.cv_profile:
                        with st.spinner("Scoring against your CV..."):
                            facade.refresh_matches(st.session_state.cv_profile)
                else:
                    st.warning("No jobs returned. Try different keywords.")

        notice = facade.attribution_notice(provider)
        if notice:
            st.caption(notice)

    elif mode == "Web Search (fallback)":
        st.caption(
            "Fallback only. Search results are unstructured snippets, not real "
            "postings - no salary, dates, or reliable company data. Prefer a "
            "careers URL when you have one. Requires the local LLM."
        )
        if not st.session_state.llm_client:
            st.info(
                "No model connected. Open AI settings in the sidebar, then choose Connect AI."
            )
            return

        col1, col2 = st.columns([3, 1])

        with col1:
            query = st.text_input(
                "Search Query",
                value="senior python developer remote",
                help="e.g., 'machine learning engineer Berlin 2024'",
            )

        with col2:
            max_results = st.number_input("Max Results", 5, 20, 10)

        if st.button("Search Jobs", type="primary"):
            with st.spinner("Searching DuckDuckGo..."):
                try:
                    finder = JobFinder(st.session_state.llm_client)
                    search_query = SearchQuery(query=query, max_results=max_results)
                    jobs = finder.search_jobs(search_query)

                    if jobs:
                        st.success(f"Found {len(jobs)} jobs")
                        st.session_state.search_results = jobs
                    else:
                        st.warning("No jobs found. Try different keywords.")

                except Exception as e:
                    st.error(f"Search failed: {e}")

        # Display results
        if "search_results" in st.session_state and st.session_state.search_results:
            st.subheader("Search Results")

            for i, job in enumerate(st.session_state.search_results):
                with st.expander(f"{job.title} at {job.company}"):
                    st.write(f"**Location:** {job.location or 'Not specified'}")
                    st.write(f"**URL:** {job.url}")
                    st.write(f"**Description:** {job.description[:300]}...")

                    if st.button("Select This Job", key=f"select_{i}"):
                        _select_job(job)
                        st.success(f"Added {job.title}")
                        _rerun()

    elif mode == "Paste Job URL":
        job_url = st.text_input(
            "Job Post URL", placeholder="https://company.com/careers/job-id"
        )

        if not st.session_state.llm_client:
            st.info(
                "This mode uses your selected AI provider to parse the page. Connect it "
                "from AI settings in the sidebar, or use the careers-URL mode instead."
            )

        if st.button("Fetch Job Details", type="primary"):
            if not st.session_state.llm_client:
                st.info(
                    "No model connected. Open AI settings in the sidebar, then choose Connect AI."
                )
                return
            with st.spinner("Fetching job details..."):
                try:
                    finder = JobFinder(st.session_state.llm_client)
                    job = finder.fetch_job_details(job_url)

                    if job:
                        _select_job(job)
                        st.success("Job added!")
                        _rerun()
                    else:
                        st.error("Failed to fetch job details")
                except Exception as e:
                    st.error(f"Error: {e}")

    else:  # Paste Job Description
        job_desc = st.text_area(
            "Paste Job Description",
            height=300,
            help="Paste the full job description text",
        )

        col1, col2 = st.columns(2)
        with col1:
            job_title = st.text_input(
                "Job Title", placeholder="Senior Software Engineer"
            )
        with col2:
            company_name = st.text_input("Company Name", placeholder="Google")

        if st.button("Add Job", type="primary"):
            if job_desc and job_title and company_name:
                job = JobPosting(
                    title=job_title, company=company_name, description=job_desc
                )
                _select_job(job)
                st.success("Job added!")
                _rerun()
            else:
                st.warning("Please fill all fields")

    if st.button("View saved jobs in Pipeline", use_container_width=True):
        st.session_state.page = "pipeline"
        _rerun()

    # Show selected jobs
    if st.session_state.selected_jobs:
        st.divider()
        st.subheader(f"Selected Jobs ({len(st.session_state.selected_jobs)})")

        for i, job in enumerate(st.session_state.selected_jobs):
            col1, col2 = st.columns([4, 1])
            with col1:
                st.write(f"**{i + 1}. {job.title}** at {job.company}")
            with col2:
                if st.button("Remove", key=f"remove_{i}"):
                    st.session_state.selected_jobs.pop(i)
                    _rerun()

        if st.button(
            "Next: Prepare application materials",
            type="primary",
            use_container_width=True,
        ):
            st.session_state.page = "draft"
            _rerun()


# Page 3: Contact Discovery
def page_contacts():
    """Contact discovery screen"""
    st.title("Contact Finder")
    st.markdown(
        "Keep known contacts or explore unverified email patterns. Outreach is optional."
    )

    if not st.session_state.selected_jobs:
        st.info(
            "Choose a job in Job Discovery or select Prepare application in Pipeline."
        )
        if st.button("Find a job", use_container_width=True):
            st.session_state.page = "discovery"
            _rerun()
        return

    llm_ready = bool(st.session_state.llm_client)
    if not llm_ready:
        st.info(
            "Connect a model in the sidebar to search for contacts. You can "
            "add a known contact or generate email patterns without it. "
            "Generated patterns still need verification."
        )

    # For each selected job
    for idx, job in enumerate(st.session_state.selected_jobs):
        with st.expander(f"{job.title} at {job.company}", expanded=True):
            st.write(f"**Company:** {job.company}")
            st.write(f"**URL:** {job.url or 'N/A'}")

            col1, col2 = st.columns(2)

            with col1:
                if st.button(
                    "Search Contacts",
                    key=f"search_contacts_{idx}",
                    disabled=not llm_ready,
                ):
                    with st.spinner("Searching for contacts..."):
                        try:
                            finder = ContactFinder(st.session_state.llm_client)
                            contacts = finder.find_contacts(
                                job.company, job.title, max_results=5
                            )

                            if job.company not in st.session_state.found_contacts:
                                st.session_state.found_contacts[job.company] = []

                            st.session_state.found_contacts[job.company] = (
                                facade.merge_contacts(
                                    st.session_state.found_contacts[job.company],
                                    contacts,
                                )
                            )
                            st.success(f"Found {len(contacts)} contacts")
                            _rerun()
                        except Exception as e:
                            st.error(f"Search failed: {e}")

            with col2:
                with st.popover("Add Manual Contact"):
                    name = st.text_input("Name", key=f"manual_name_{idx}")
                    email = st.text_input("Email", key=f"manual_email_{idx}")
                    role = st.text_input("Role", key=f"manual_role_{idx}")

                    if st.button("Add", key=f"add_manual_{idx}"):
                        try:
                            contact = facade.create_manual_contact(name, email, role)
                        except ValueError as exc:
                            st.error(str(exc))
                        else:
                            previous = st.session_state.found_contacts.get(
                                job.company, []
                            )
                            merged = facade.merge_contacts(previous, [contact])
                            if len(merged) == len(previous):
                                st.info(
                                    "This email address is already in your contacts."
                                )
                            else:
                                st.session_state.found_contacts[job.company] = merged
                                _rerun()

            # Show found contacts
            if job.company in st.session_state.found_contacts:
                contacts = st.session_state.found_contacts[job.company]

                if contacts:
                    st.write("**Contacts:**")
                    st.caption(
                        "Addresses are not independently verified. Review the source and recipient before outreach."
                    )

                    for i, contact in enumerate(contacts):
                        col1, col2, col3 = st.columns([3, 3, 1])

                        with col1:
                            st.write(
                                f"**{contact.name}** — {contact.role or 'Role not supplied'}"
                            )

                        with col2:
                            if contact.email:
                                st.write(contact.email)
                                provenance = (
                                    "User provided"
                                    if contact.source == "manual"
                                    else "Generated pattern"
                                    if contact.email_confidence == "guessed"
                                    else "Found in source"
                                    if contact.source
                                    or contact.email_confidence == "confirmed"
                                    else "Source unknown"
                                )
                                st.caption(f"{provenance} · unverified")
                            else:
                                st.caption("No email found")

                        with col3:
                            if st.button("Remove", key=f"remove_contact_{idx}_{i}"):
                                st.session_state.found_contacts[job.company].pop(i)
                                _rerun()

            # Email permutations
            st.write("**Explore email patterns (optional)**")
            st.caption(
                "Enter an employer email domain you already know. Patterns are guesses; they do not verify a person's address."
            )
            col1, col2, col3 = st.columns(3)

            with col1:
                first_name = st.text_input("First Name", key=f"fname_{idx}")
            with col2:
                last_name = st.text_input("Last Name", key=f"lname_{idx}")
            with col3:
                domain_input = st.text_input(
                    "Employer email domain",
                    placeholder="company.com",
                    key=f"domain_{idx}",
                )

            if st.button("Generate Permutations", key=f"gen_perm_{idx}"):
                try:
                    permutations = facade.generate_contact_patterns(
                        first_name, last_name, domain_input
                    )
                except ValueError as exc:
                    st.error(str(exc))
                else:
                    previous = st.session_state.found_contacts.get(job.company, [])
                    st.session_state.found_contacts[job.company] = (
                        facade.merge_contacts(previous, permutations)
                    )
                    _rerun()

    st.divider()

    if st.button("Next: Draft Studio", type="primary", use_container_width=True):
        st.session_state.page = "draft"
        _rerun()


# Page 4: Draft Studio
def page_draft_studio():
    """Draft generation and editing screen"""
    st.title("Draft Studio")
    st.markdown("Prepare your resume, cover letter and outreach for a selected job.")

    if not st.session_state.selected_jobs:
        st.info(
            "Choose a job in Job Discovery or select Prepare application in Pipeline."
        )
        if st.button("Find a job", use_container_width=True):
            st.session_state.page = "discovery"
            _rerun()
        return

    if not st.session_state.cv_profile:
        st.info("Add or restore your CV to prepare personalized application materials.")
        if st.button("Add or restore my CV", use_container_width=True):
            st.session_state.page = "onboarding"
            _rerun()
        return

    llm_ready = bool(st.session_state.llm_client)
    if not llm_ready:
        st.info(
            "Connect a model in the sidebar to generate new messages. You can "
            "tailor your resume and review existing materials without it."
        )

    # Job selector
    job_titles = [
        f"{job.title} at {job.company}" for job in st.session_state.selected_jobs
    ]
    if not job_titles:
        st.error("No jobs selected")
        return
    if st.session_state.get("draft_job_selection", 0) not in range(len(job_titles)):
        st.session_state.draft_job_selection = 0

    selected_idx = st.selectbox(
        "Select Job",
        range(len(job_titles)),
        format_func=lambda x: job_titles[x],
        key="draft_job_selection",
    )
    current_job = st.session_state.selected_jobs[selected_idx]
    workspace_key = _activate_draft_job(current_job)
    workspace = st.session_state.draft_workspaces[workspace_key]

    job_id = st.session_state.selected_job_refs.get(
        facade.workspace_job_key(current_job)
    )
    _render_apply_target(job_id)
    st.caption(
        f"Active CV: {st.session_state.cv_profile.name or 'Unnamed CV'} "
        f"· {'saved CV #' + str(st.session_state.cv_id) if st.session_state.cv_id is not None else 'not saved yet'}. "
        "Opening the posting or preparing downloads does not mark this application as applied."
    )
    if st.button("Prepare browser autofill profile", key="draft_prepare_autofill"):
        st.session_state.page = "export"
        _rerun()

    st.divider()

    # Two columns: Context + Draft
    col1, col2 = st.columns([1, 2])

    with col1:
        st.subheader("Context")

        # Job info
        with st.expander("Job Details", expanded=True):
            st.write(f"**Title:** {current_job.title}")
            st.write(f"**Company:** {current_job.company}")
            st.write(f"**Location:** {current_job.location or 'N/A'}")
            if current_job.tech_stack:
                st.write(f"**Tech Stack:** {', '.join(current_job.tech_stack[:5])}")

        # CV highlights
        if st.session_state.cv_profile:
            with st.expander("Your Highlights"):
                profile = st.session_state.cv_profile
                if profile.projects:
                    st.write("**Top Projects:**")
                    for proj in profile.projects[:3]:
                        st.write(f"- {proj.name}")

                if profile.skills:
                    st.write(f"**Skills:** {', '.join(profile.skills[:8])}")

        # --- Tailored resume variant for this job (Phase 5) --- #
        if st.session_state.cv_profile:
            st.subheader("Tailored resume")
            st.caption(
                "Reorders and emphasizes what you already have. Never invents "
                "skills or experience - unmatched requirements are listed as gaps."
            )
            if st.button("Tailor resume to this job", use_container_width=True):
                with st.spinner("Tailoring (truthfully)..."):
                    try:
                        st.session_state.tailored = facade.tailor_for_job(
                            st.session_state.cv_profile, current_job
                        )
                    except Exception as e:
                        st.error(f"Tailoring failed: {e}")

            tailored = st.session_state.get("tailored")
            if tailored:
                if tailored["emphasized"]:
                    st.success("Emphasized: " + ", ".join(tailored["emphasized"][:10]))
                if tailored["gaps"]:
                    st.warning(
                        "Gaps (address honestly, do not fake): "
                        + ", ".join(tailored["gaps"][:10])
                    )
                if tailored["reordered_experience"]:
                    st.caption("Experience order adjusted for relevance.")
                _render_cv_assessment(tailored["profile"], current_job)
                try:
                    pdf = facade.resume_pdf(tailored["profile"])
                except ValueError as exc:
                    st.warning(f"{exc} Markdown and JSON downloads remain available.")
                else:
                    st.download_button(
                        "Download tailored ATS PDF",
                        data=pdf,
                        file_name=f"resume_{current_job.company}.pdf".replace(" ", "_"),
                        mime="application/pdf",
                        use_container_width=True,
                    )
                st.download_button(
                    "Download tailored Markdown",
                    data=facade.resume_markdown(tailored["profile"]),
                    file_name="resume_tailored.md",
                    mime="text/markdown",
                    use_container_width=True,
                )
                st.download_button(
                    "Download tailored JSON Resume",
                    data=json.dumps(
                        facade.resume_json(tailored["profile"]),
                        indent=2,
                        ensure_ascii=False,
                    ),
                    file_name="resume_tailored.json",
                    mime="application/json",
                    use_container_width=True,
                )

        # --- Cover letter, grounded in the CV --- #
        if st.session_state.cv_profile:
            st.subheader("Cover letter")
            st.caption(
                "Uses your CV and checks for unsupported numbers. Review every "
                "employer, qualification, and claim before exporting."
            )
            tone = st.selectbox(
                "Tone",
                ["professional", "conversational", "direct"],
                key=f"cover_tone_{workspace_key}",
            )
            if st.button(
                "Draft cover letter", use_container_width=True, disabled=not llm_ready
            ):
                with st.spinner("Drafting from your CV..."):
                    try:
                        st.session_state.cover = facade.cover_letter_for_job(
                            st.session_state.llm_client,
                            st.session_state.cv_profile,
                            current_job,
                            tone=tone,
                        )
                        st.session_state[f"cover_text_{workspace_key}"] = (
                            st.session_state.cover["letter"]
                        )
                    except Exception as e:
                        st.session_state.cover = None
                        st.error(f"Cover letter rejected: {e}")

            cover = st.session_state.get("cover")
            if cover:
                cover_key = f"cover_text_{workspace_key}"
                if cover_key not in st.session_state:
                    st.session_state[cover_key] = cover["letter"]
                cover["letter"] = st.text_area("Letter", height=300, key=cover_key)
                st.caption(f"{len(cover['letter'].split())} words")
                if cover["cited_metrics"]:
                    st.caption(
                        "Numbers checked during generation: "
                        + ", ".join(cover["cited_metrics"][:6])
                        + ". Review edited claims against your CV."
                    )
                if cover["gaps"]:
                    st.warning(
                        "Asked for but not evidenced in your CV - address "
                        "honestly: " + ", ".join(cover["gaps"][:6])
                    )
                st.download_button(
                    "Download cover letter",
                    data=st.session_state.get(
                        f"cover_text_{workspace_key}", cover["letter"]
                    ),
                    file_name=f"cover_{current_job.company}.md".replace(" ", "_"),
                    mime="text/markdown",
                    use_container_width=True,
                )

        # --- Interview prep from the job description (Phase 10) --- #
        with st.expander("Interview prep"):
            questions = facade.interview_questions(current_job, limit=10)
            st.caption(
                "Likely questions derived from this job description, plus "
                "standard behavioral prompts."
            )
            for q in questions:
                st.write(f"- {q}")
            st.download_button(
                "Download prep list",
                data="\n".join(f"- {q}" for q in questions),
                file_name=f"prep_{current_job.company}.md".replace(" ", "_"),
                mime="text/markdown",
                use_container_width=True,
            )

        # Contact selection
        st.subheader("Recipient")

        contacts = st.session_state.found_contacts.get(current_job.company, [])

        recipient_name = "Hiring Manager"
        recipient_email = ""

        if contacts:
            contact_names = [f"{c.name} ({c.email or 'No email'})" for c in contacts]
            selected_contact_idx = st.selectbox(
                "Select Contact",
                range(len(contacts)),
                format_func=lambda x: contact_names[x],
                key=f"draft_contact_{workspace_key}",
            )
            selected_contact = contacts[selected_contact_idx]

            recipient_name = selected_contact.name
            recipient_email = selected_contact.email
        else:
            recipient_name = st.text_input(
                "Recipient Name",
                value=workspace.get("recipient_name", "Hiring Manager"),
                key=f"recipient_name_{workspace_key}",
            )
            recipient_email = st.text_input(
                "Recipient Email",
                value=workspace.get("recipient_email", ""),
                placeholder="hiring@company.com",
                key=f"recipient_email_{workspace_key}",
            )
        workspace["recipient_name"] = recipient_name
        workspace["recipient_email"] = recipient_email

    with col2:
        st.subheader("Draft")

        # Generation controls
        col_a, col_b, col_c = st.columns(3)

        with col_a:
            angle = st.selectbox("Angle", ["technical", "impact", "product"])

        with col_b:
            if st.button("Generate Email", type="primary", disabled=not llm_ready):
                with st.spinner("Generating email..."):
                    try:
                        engine = PersonalizationEngine(st.session_state.llm_client)
                        draft = engine.generate_email(
                            st.session_state.cv_profile,
                            current_job,
                            recipient_name=recipient_name,
                            angle=angle,
                        )
                        draft.recipient_email = recipient_email
                        _set_current_draft(draft, workspace_key)
                        _rerun()
                    except Exception as e:
                        st.error(f"Generation failed: {e}")

        with col_c:
            if st.session_state.current_draft:
                if st.button("Regenerate", disabled=not llm_ready):
                    with st.spinner("Regenerating..."):
                        try:
                            engine = PersonalizationEngine(st.session_state.llm_client)
                            draft = engine.regenerate_email_with_angle(
                                st.session_state.current_draft, angle=angle
                            )
                            draft.recipient_email = recipient_email
                            _set_current_draft(draft, workspace_key)
                            _rerun()
                        except Exception as e:
                            st.error(f"Regeneration failed: {e}")

        # Show draft
        if st.session_state.current_draft:
            draft = st.session_state.current_draft
            draft.recipient_name = recipient_name
            draft.recipient_email = recipient_email

            # Editable subject
            subject_key = f"draft_subject_{workspace_key}"
            body_key = f"draft_body_{workspace_key}"
            if subject_key not in st.session_state:
                st.session_state[subject_key] = draft.subject
            if body_key not in st.session_state:
                st.session_state[body_key] = draft.body
            subject = st.text_input("Subject", key=subject_key)

            # Editable body
            body = st.text_area("Body", height=300, key=body_key)

            # Update draft if edited
            if subject != draft.subject or body != draft.body:
                draft.subject = subject
                draft.body = body

            st.divider()

            # Quality check
            st.subheader("Quality Checklist")

            validator = DraftValidator()
            quality = validator.validate_draft(draft)

            # Display checks
            col1, col2 = st.columns(2)

            checks_display = [
                ("Has Metric", quality.has_metric),
                ("Has Project Link", quality.has_project_link),
                ("Company Hook", quality.has_company_hook),
                ("Clear CTA", quality.has_clear_cta),
                ("Under 180 words", quality.under_word_limit),
                ("No Emojis", quality.no_emojis),
                ("No Bullets", quality.no_bullet_dashes),
            ]

            for i, (label, passed) in enumerate(checks_display):
                with col1 if i < 4 else col2:
                    icon = "[OK]" if passed else "[Missing]"
                    st.write(f"{icon} {label}")

            # Overall score
            st.metric(
                "Quality Score",
                f"{quality.score:.0f}%",
                delta="Pass" if quality.passed else "Needs Work",
                delta_color="normal" if quality.passed else "inverse",
            )

            # Issues
            if quality.issues:
                with st.expander("Issues to Fix"):
                    for issue in quality.issues:
                        st.write(issue)

            st.divider()

            # Outreach compliance gate (CAN-SPAM / GDPR) - Phase 7.
            st.subheader("Compliance check")
            with st.expander("Sender identity + opt-out (required to send)"):
                c1, c2 = st.columns(2)
                with c1:
                    sender_name = st.text_input(
                        "Sender name", value=st.session_state.cv_profile.name or ""
                    )
                    sender_email = st.text_input(
                        "Sender email",
                        value=st.session_state.cv_profile.email or "",
                    )
                with c2:
                    postal_address = st.text_input("Physical postal address")
                    unsubscribe = st.text_input(
                        "Opt-out (URL or mailto:)",
                        value=f"mailto:{st.session_state.cv_profile.email or ''}"
                        "?subject=unsubscribe",
                    )
                lia_purpose = st.text_input(
                    "LIA purpose (GDPR)",
                    value="Relevant B2B job application to a hiring contact.",
                )

            cfg = ComplianceConfig(
                sender_name=sender_name,
                sender_email=sender_email,
                postal_address=postal_address,
                unsubscribe=unsubscribe,
            )
            lia = LIARecord(
                campaign="outreach",
                purpose=lia_purpose,
                necessity="Direct role-specific contact.",
                balancing="Business address + opt-out honored.",
            )
            gate_draft = EmailDraft.model_validate(
                {
                    **draft.model_dump(),
                    "subject": subject,
                    "body": body,
                    "recipient_email": recipient_email,
                    "recipient_name": recipient_name,
                    "company": current_job.company,
                }
            )
            if st.button("Run compliance check"):
                try:
                    decision = facade.compliance_gate(gate_draft, cfg, lia)
                    if decision.allowed:
                        st.success("Compliance preview passed:")
                        st.code(decision.body)
                    else:
                        st.error(f"Blocked: {decision.reason}")
                except ValueError as e:
                    st.error(f"Fill required fields: {e}")

            st.divider()

            # Actions
            col1, col2, col3 = st.columns(3)

            with col1:
                if st.button("Create Gmail Draft", use_container_width=True):
                    if not recipient_email:
                        st.error("Please enter recipient email")
                    else:
                        with st.spinner("Creating Gmail draft..."):
                            try:
                                prepared = facade.create_gmail_draft(
                                    gate_draft,
                                    cfg,
                                    lia,
                                    gmail_client=st.session_state.gmail_client,
                                )
                                st.session_state.current_draft = prepared
                                st.session_state.draft_history.append(prepared)
                                st.session_state.storage.save_email_draft(prepared)
                                st.success(f"Draft created: {prepared.gmail_draft_id}")
                            except Exception as e:
                                st.error(f"Gmail Error: {e}")

            with col2:
                if st.button("Save Local", use_container_width=True):
                    st.session_state.draft_history.append(draft)
                    st.session_state.storage.save_email_draft(draft)
                    st.success("Draft saved!")

            with col3:
                if st.button(
                    "WhatsApp Link", use_container_width=True, disabled=not llm_ready
                ):
                    engine = PersonalizationEngine(st.session_state.llm_client)
                    try:
                        wa_draft = engine.generate_whatsapp_message(
                            st.session_state.cv_profile, current_job, phone=None
                        )
                        st.session_state.current_wa_draft = wa_draft
                        st.session_state.storage.save_whatsapp_draft(wa_draft)
                    except Exception as e:
                        st.error(f"WhatsApp Error: {e}")

            if st.session_state.get("current_wa_draft"):
                st.info("WhatsApp Draft:")
                st.code(st.session_state.current_wa_draft.message)
                st.markdown(
                    f"[Open in WhatsApp]({st.session_state.current_wa_draft.click_to_chat_url})"
                )


# Page 5: Export
def page_export():
    """Export screen"""
    st.title("Export & Logs")

    st.caption(
        "Downloaded exports contain readable personal data. Share and store them carefully."
    )
    st.subheader("Draft History")

    drafts = st.session_state.storage.list_email_drafts()

    if drafts:
        for filename in drafts:
            st.text(f"File: {filename}")
    else:
        st.info("No drafts saved yet.")

    st.divider()

    if st.button("Export All Data (ZIP)", type="primary"):
        with st.spinner("Creating export bundle..."):
            try:
                zip_path = facade.export_all_data(st.session_state.storage)
                st.session_state.export_zip = Path(zip_path).read_bytes()
                st.success("Your export is ready to download.")
            except Exception as e:
                st.error(f"Export failed: {e}")
    if st.session_state.get("export_zip") is not None:
        st.download_button(
            "Download all data (ZIP)",
            data=st.session_state.export_zip,
            file_name="careeragent_export.zip",
            mime="application/zip",
            use_container_width=True,
        )

    st.divider()

    # --- Autofill extension handoff (Phase 8) --- #
    st.subheader("Browser autofill profile")
    _render_autofill_handoff()

    st.divider()

    # --- Job digest (Phase 9) --- #
    st.subheader("Job digest")
    st.caption(
        "Your top scored matches as a shareable digest. The same digest can be "
        "delivered on a schedule via the daily GitHub Actions workflow."
    )
    digest_limit = st.slider("Jobs in digest", 5, 25, 10)
    try:
        digest_md = facade.digest_markdown(limit=digest_limit)
        digest_feed = facade.digest_rss(limit=digest_limit)
    except Exception as e:
        digest_md = digest_feed = None
        st.error(f"Could not build digest: {e}")

    if digest_md:
        st.markdown(digest_md)
        dcol1, dcol2 = st.columns(2)
        with dcol1:
            st.download_button(
                "Download digest (Markdown)",
                data=digest_md,
                file_name="careeragent_digest.md",
                mime="text/markdown",
                use_container_width=True,
            )
        with dcol2:
            st.download_button(
                "Download feed (RSS)",
                data=digest_feed,
                file_name="careeragent_jobs.xml",
                mime="application/rss+xml",
                use_container_width=True,
            )


def _due_label(card: dict) -> str:
    """How overdue a follow-up is, in words the candidate can act on."""
    days = card.get("days_until_follow_up")
    if days is None:
        return ""
    if days < 0:
        return f"{abs(days)}d overdue"
    if days == 0:
        return "due today"
    return f"due in {days}d"


def _render_followups():
    """Reminder panel: the applications the candidate owes a nudge.

    Sits above everything else on the screen because it is the only part of
    the pipeline with a deadline attached.
    """
    try:
        due = facade.due_followups()
    except Exception as e:
        st.error(f"Could not load follow-ups: {e}")
        return

    if not due:
        st.success(
            "No follow-ups due. Applications you mark **Applied** get a "
            "reminder here after a week."
        )
        return

    st.warning(f"**{len(due)} follow-up{'s' if len(due) > 1 else ''} due**")
    for card in due:
        app_id = card["application_id"]
        with st.container(border=True):
            st.markdown(f"**{card['title']}** — {card['company']}")
            bits = [_due_label(card)]
            if card.get("days_since_applied") is not None:
                bits.append(f"applied {card['days_since_applied']}d ago")
            st.caption(" · ".join(b for b in bits if b))
            _render_apply_target(card.get("job_id"), "Open posting")

            c1, c2, c3 = st.columns(3)
            if c1.button("Snooze 3d", key=f"snooze3_{app_id}"):
                facade.snooze_followup(app_id, 3)
                _rerun()
            if c2.button("Snooze 7d", key=f"snooze7_{app_id}"):
                facade.snooze_followup(app_id, 7)
                _rerun()
            if c3.button("No reply — reject", key=f"rej_{app_id}"):
                res = facade.advance_application(app_id, "rejected")
                if res["ok"]:
                    _rerun()
                else:
                    st.warning(res["error"])


def page_pipeline():
    """Pipeline screen - API-first ingestion, scored matches, and tracking."""
    st.title("Pipeline")
    st.markdown(
        "Pull jobs directly from company ATS APIs, see explainable match "
        "scores against your CV, and track applications through the funnel."
    )

    st.subheader("Follow-ups")
    _render_followups()
    st.divider()

    with st.expander("Import a company job board (advanced)"):
        st.caption(
            "Use Job Discovery for a careers URL or keyword search. Import by provider and board name here when you already know them."
        )
        col1, col2, col3 = st.columns([2, 2, 1])
        with col1:
            slug = st.text_input(
                "Board slug",
                placeholder="the company's board name on the ATS you pick",
            )
        with col2:
            ats_type = st.selectbox("ATS", facade.ats_providers())
        with col3:
            company = st.text_input("Company name", placeholder="Display name")

        import_options = {}
        if ats_type == "smartrecruiters":
            with st.expander("Import a large job board"):
                import_options["offset"] = st.number_input(
                    "Skip jobs already imported",
                    min_value=0,
                    value=0,
                    step=1,
                    help="Use the next offset shown in a partial import warning.",
                )
                import_options["max_jobs"] = st.number_input(
                    "Jobs per import", min_value=1, max_value=1000, value=250, step=1
                )
                st.caption(
                    "Each import is bounded. Repeat with the next offset to continue."
                )

        if st.button("Ingest", type="primary", disabled=not slug):
            with st.spinner(f"Pulling {slug} jobs from {ats_type}..."):
                try:
                    result = facade.ingest_ats(
                        ats_type, slug, company, **import_options
                    )
                    if result.errors:
                        st.error(f"Ingestion error: {result.errors[0]}")
                    else:
                        st.success(
                            f"Fetched {result.fetched}, stored {result.upserted} jobs."
                        )
                        if st.session_state.cv_profile:
                            facade.refresh_matches(st.session_state.cv_profile)
                    for warning in getattr(result, "warnings", []):
                        st.warning(warning)
                except Exception as e:
                    st.error(f"Ingestion failed: {e}")

    if st.session_state.cv_profile and st.button("Re-score matches"):
        with st.spinner("Dedup + score against your CV..."):
            try:
                facade.refresh_matches(st.session_state.cv_profile)
                st.session_state.match_refresh_warning = None
                st.success("Matches refreshed.")
                _rerun()
            except Exception:
                st.error(
                    "Matches could not be refreshed. Check database access and try again."
                )

    st.divider()

    # --- Scored matches, with filters --- #
    st.subheader("Top matches")

    try:
        status = facade.data_status()
    except Exception:
        status = {"visa_dataset_loaded": False, "semantic_embeddings": False}

    with st.expander("Filters"):
        f1, f2, f3 = st.columns(3)
        with f1:
            min_score = st.slider("Minimum match score", 0, 100, 0)
            remote_only = st.checkbox("Remote only")
        with f2:
            hide_ghosts = st.checkbox(
                "Hide likely ghost jobs",
                help="Excludes stale/vague postings scoring above 0.6 ghost risk.",
            )
            # Only offer the visa filter when a real sponsor register is
            # loaded. Without one we have no basis to say an employer does or
            # does not sponsor, and guessing would be worse than not offering.
            visa_loaded = status.get("visa_dataset_loaded", False)
            sponsors_visa_only = st.checkbox(
                "Visa sponsors only",
                disabled=not visa_loaded,
                help=(
                    f"{status.get('visa_employer_count', 0):,} employers loaded."
                    if visa_loaded
                    else "No sponsor register loaded. Run "
                    "`python -m scripts.fetch_datasets --uk` to enable."
                ),
            )
        with f3:
            level = st.radio(
                "Level", ["Any", "New grad", "Internship"], horizontal=False
            )

        if not visa_loaded:
            st.caption(
                "Sponsorship and employer-signal data are not bundled — they "
                "are facts about real companies, so nothing is shipped as "
                "placeholder. See `core/enrichment/data/README.md`."
            )
        if not status.get("semantic_embeddings", False):
            st.caption(
                "Matching is using the offline lexical embedder. For semantic "
                "matching install `sentence-transformers`."
            )

    try:
        jobs = facade.top_jobs(
            limit=25,
            min_score=float(min_score),
            remote_only=remote_only,
            max_ghost_score=0.6 if hide_ghosts else None,
            new_grad_only=(level == "New grad"),
            internships_only=(level == "Internship"),
            sponsors_visa_only=sponsors_visa_only,
        )
    except Exception as e:
        jobs = []
        st.error(f"Could not load jobs: {e}")

    if not jobs:
        st.info("No jobs match. Ingest more above, or relax the filters.")
    for job in jobs:
        score = f"{job['score']:.0f}%" if job["score"] is not None else "unscored"
        with st.expander(f"[{score}] {job['title']} - {job['company']}"):
            st.write(f"**Location:** {job['location'] or 'N/A'}")
            if job.get("source"):
                st.caption(f"Source: {job['source']}")
            if job.get("attribution"):
                st.caption(job["attribution"])
            if job["salary_min"]:
                st.write(f"**Salary:** {int(job['salary_min']):,}+")

            # Company + risk signals from enrichment.
            signals = []
            if job.get("sponsors_visa"):
                signals.append("Visa sponsor")
            if job.get("glassdoor_rating"):
                signals.append(f"Glassdoor {job['glassdoor_rating']}")
            if job.get("had_layoffs"):
                signals.append("Recent layoffs")
            if signals:
                st.caption(" · ".join(signals))
            if job.get("ghost_score") and job["ghost_score"] > 0.6:
                st.warning(
                    f"Possible ghost job (risk {job['ghost_score']:.0%}) - "
                    "stale or vague posting."
                )

            if job["matched"]:
                st.success("Matched: " + ", ".join(job["matched"][:12]))
            if job["missing"]:
                st.warning("Missing: " + ", ".join(job["missing"][:12]))
            _render_apply_target(job["id"], "View posting")
            if st.button("Add to pipeline", key=f"track_{job['id']}"):
                res = facade.add_to_pipeline(job["id"], st.session_state.cv_id)
                if res["ok"]:
                    st.success("Added to pipeline (Saved).")
                    _rerun()
                else:
                    st.warning(res["error"])
            st.button(
                "Prepare application",
                key=f"prepare_{job['id']}",
                on_click=_prepare_application,
                args=(job["id"],),
            )

    st.divider()

    # --- Kanban board + funnel --- #
    st.subheader("Application board")
    try:
        board = facade.pipeline_board()
        f = facade.funnel()
    except Exception as e:
        board, f = {}, None
        st.error(f"Could not load board: {e}")

    statuses = [
        "saved",
        "applied",
        "screening",
        "interview",
        "offer",
        "rejected",
        "withdrawn",
    ]
    next_status = {
        "saved": "applied",
        "applied": "screening",
        "screening": "interview",
        "interview": "offer",
    }
    if not any(board.get(s) for s in statuses):
        st.info(
            "No applications yet. Add a job from **Top matches** above to "
            "start tracking it."
        )

    # Six columns leave ~130px each, so the columns stay a compact overview.
    # Anything the candidate edits lives in the full-width detail panel below --
    # a notes box rendered inside a column here comes out 94px wide.
    visible_statuses = [status for status in statuses if status != "withdrawn"]
    cols = st.columns(len(visible_statuses))
    for col, status in zip(cols, visible_statuses):
        with col:
            cards = board.get(status, [])
            st.markdown(f"**{status.title()}** ({len(cards)})")
            for card in cards:
                flag = " ⚠️" if card.get("overdue") else ""
                st.caption(f"{card['title']}{flag}")
                st.caption(f"_{card['company']}_")
                if status in next_status:
                    if st.button(
                        next_status[status][:9],
                        key=f"adv_{card['application_id']}",
                        use_container_width=True,
                    ):
                        facade.advance_application(
                            card["application_id"], next_status[status]
                        )
                        _rerun()

    withdrawn = board.get("withdrawn", [])
    if withdrawn:
        with st.expander(f"Withdrawn ({len(withdrawn)})"):
            for card in withdrawn:
                st.write(f"{card['title']} — {card['company']}")

    _render_application_detail(board, statuses)

    if f:
        st.divider()
        st.subheader("Funnel")
        m = st.columns(5)
        m[0].metric("Total", f["total"])
        m[1].metric("Applied", f["reached"].get("applied", 0))
        m[2].metric("Screening", f["reached"].get("screening", 0))
        m[3].metric("Interview", f["reached"].get("interview", 0))
        m[4].metric("Offer", f["reached"].get("offer", 0))

        conv = f.get("conversion", {})
        if f["reached"].get("applied", 0):
            c = st.columns(3)
            c[0].metric(
                "Applied → Screening",
                f"{conv.get('applied_to_screening', 0):.0%}",
            )
            c[1].metric(
                "Screening → Interview",
                f"{conv.get('screening_to_interview', 0):.0%}",
            )
            c[2].metric("Interview → Offer", f"{conv.get('interview_to_offer', 0):.0%}")


def _render_application_detail(board: dict, statuses: list):
    """Full-width editor for one application.

    The kanban columns are too narrow to hold a notes field or a readable
    button, so the per-application controls live here instead of inside them.
    """
    everything = [(s, c) for s in statuses for c in board.get(s, [])]
    if not everything:
        return

    st.markdown("**Application detail**")
    cards_by_id = {
        card["application_id"]: (status, card) for status, card in everything
    }
    choice = st.selectbox(
        "Application",
        list(cards_by_id),
        format_func=lambda app_id: (
            f"{cards_by_id[app_id][1]['title']} — {cards_by_id[app_id][1]['company']} "
            f"({cards_by_id[app_id][0]}) · #{app_id}"
        ),
        label_visibility="collapsed",
    )
    status, card = cards_by_id[choice]
    app_id = card["application_id"]

    left, right = st.columns([3, 2])
    with left:
        _render_apply_target(card.get("job_id"), "Open posting")
        if card.get("applied_at"):
            st.caption(
                f"Applied {card['days_since_applied']}d ago · "
                f"{_due_label(card) or 'no follow-up set'}"
            )
        else:
            st.caption("Not applied yet.")
        notes = st.text_area(
            "Notes",
            value=card.get("notes", ""),
            key=f"notes_{app_id}",
            placeholder="Recruiter name, referral, interview date...",
        )
        if notes != card.get("notes", ""):
            facade.set_application_notes(app_id, notes)
            st.caption("Notes saved.")

    with right:
        if card.get("job_id"):
            st.button(
                "Prepare application",
                key=f"detail_prepare_{app_id}",
                use_container_width=True,
                on_click=_prepare_application,
                args=(card["job_id"],),
            )
        next_status = {
            "saved": "applied",
            "applied": "screening",
            "screening": "interview",
            "interview": "offer",
        }
        if status in next_status:
            if st.button(
                f"Move to {next_status[status]}",
                key=f"detail_adv_{app_id}",
                type="primary",
                use_container_width=True,
            ):
                facade.advance_application(app_id, next_status[status])
                _rerun()
        # Every active state can also end badly. Without this the board only
        # models the happy path and dead applications sit in "applied"
        # forever, skewing the funnel and nagging with stale reminders.
        if status not in ("rejected", "withdrawn"):
            if st.button(
                "Mark rejected", key=f"detail_rej_{app_id}", use_container_width=True
            ):
                res = facade.advance_application(app_id, "rejected")
                if res["ok"]:
                    _rerun()
                else:
                    st.warning(res["error"])
            if st.button(
                "Withdraw", key=f"detail_wd_{app_id}", use_container_width=True
            ):
                res = facade.advance_application(app_id, "withdrawn")
                if res["ok"]:
                    _rerun()
                else:
                    st.warning(res["error"])


# Router
render_sidebar()
for notice_key in ("match_refresh_warning", "job_save_notice"):
    if st.session_state.get(notice_key):
        st.warning(st.session_state[notice_key])
if st.session_state.get("prepare_job_error"):
    st.error(st.session_state.prepare_job_error)

if st.session_state.get("page") == "onboarding":
    page_onboarding()
elif st.session_state.get("page") == "discovery":
    page_discovery()
elif st.session_state.get("page") == "pipeline":
    page_pipeline()
elif st.session_state.get("page") == "contacts":
    page_contacts()
elif st.session_state.get("page") == "draft":
    page_draft_studio()
elif st.session_state.get("page") == "export":
    page_export()

_persist_workspace()
_render_workspace_notices()

if __name__ == "__main__":
    pass
