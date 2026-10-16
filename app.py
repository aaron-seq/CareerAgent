"""
CareerAgent - Main Streamlit Application
6 screens: Onboarding, Job Discovery, Pipeline, Contact Finder, Draft Studio,
Export & Logs. Calls only core/facade.py -- no business logic here.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from core import facade
from core.candidate import RemotePreference
from core.contact_finder import ContactFinder
from core.cv_parser import CVParser
from core.job_finder import JobFinder

# Core imports
from core.llm import GROQ_DEFAULT_MODEL, CloudLLMClient, LocalLLMClient
from core.logging_config import configure_logging
from core.models import CVProfile, EmailDraft, JobPosting, SearchQuery
from core.outreach import ComplianceConfig, LIARecord
from core.personalization import PersonalizationEngine
from core.presentation import job_chips, match_quality, risk_notes
from core.storage import LocalStorage
from core.validators import DraftValidator

load_dotenv()
configure_logging()  # level from CAREERAGENT_LOG_LEVEL (default INFO)

# Page config
st.set_page_config(
    page_title="CareerAgent - Local AI Career Agent",
    page_icon=None,
    layout="wide",
    # "auto" collapses the sidebar on phones so it doesn't cover the page.
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


def _flash(message: str, kind: str = "success") -> None:
    """Queue feedback that must survive the ``st.rerun()`` that follows it.

    ``st.success`` immediately before ``st.rerun()`` is wiped before anyone
    can read it, so a click looked like it did nothing (real-user test).
    """
    st.session_state.setdefault("flash", []).append((kind, message))


def _render_flash() -> None:
    for kind, message in st.session_state.pop("flash", []):
        getattr(st, kind, st.info)(message)


def _go(page: str, reason: str | None = None) -> None:
    """Navigate, optionally telling the user why they were sent there."""
    if reason:
        _flash(reason, "info")
    st.session_state.page = page
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
        facade.persist_manual_job(job)
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
        st.session_state.draft_job_selection = st.session_state.selected_jobs.index(job)
        if st.session_state.cv_profile:
            st.session_state.page = "draft"
        else:
            st.session_state.page = "onboarding"
            _flash(
                f"Add your profile first. Your job ({job.title} at {job.company}) "
                "is saved and will be ready in Draft Studio.",
                "info",
            )
        st.session_state.prepare_job_error = None
    except Exception as exc:
        st.session_state.prepare_job_error = f"Could not open this job: {exc}"


init_session_state()

# Ensure the database schema exists (Phase 1+). Non-fatal if it can't init so
# the legacy JSON-only flow still works.
try:
    facade.init_persistence()
except Exception:  # pragma: no cover - defensive UI guard
    st.warning(
        "The database could not be opened. Check its location and permissions before saving."
    )


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
        pages = {
            "onboarding": "Your profile",
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
                st.rerun()

        st.divider()

        connected_now = st.session_state.llm_client is not None
        ai_settings = st.expander(
            "AI settings: " + ("connected" if connected_now else "not connected"),
            expanded=False,
        )
        ai_settings.caption(
            "Only needed to read CV files and write drafts for you. Everything "
            "else works without it."
        )
        with ai_settings:
            _render_ai_settings()


def _render_ai_settings() -> None:
    """Model provider picker; lives in a collapsed sidebar expander."""
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
        isinstance(connected, CloudLLMClient) != use_cloud or connected.model != model
    ):
        # The displayed provider must describe the client receiving CV data.
        st.session_state.llm_client = None

    if st.button("Connect", use_container_width=True):
        target = "Groq" if use_cloud else "Ollama"
        with st.spinner(f"Connecting to {target}..."):
            try:
                if use_cloud:
                    llm = CloudLLMClient(
                        api_key=os.getenv("GROQ_API_KEY", ""), model=model
                    )
                else:
                    llm = LocalLLMClient(model=model)

                if llm.check_connection() and llm.check_model_availability(model):
                    st.session_state.llm_client = llm
                    _flash(f"Connected to {model}.")
                    st.rerun()
                elif use_cloud:
                    st.error(
                        "Couldn't reach Groq. Add your free GROQ_API_KEY to the "
                        ".env file, restart the app, and try again."
                    )
                else:
                    st.error(
                        "Couldn't reach Ollama, or the model isn't downloaded. "
                        "Install Ollama from ollama.com, then run "
                        f"`ollama pull {model}` once and try again."
                    )
            except Exception as e:
                st.error(f"Could not connect: {e}")


# The rail reports which outputs exist. Discovery and tracking can be used
# before a CV or a model is ready; only personalized generation needs both.
STAGES = [
    ("onboarding", "Your profile"),
    ("discovery", "Job Discovery"),
    ("pipeline", "Pipeline"),
    ("contacts", "Contact Finder"),
    ("draft", "Draft Studio"),
    ("export", "Export & Logs"),
]


def _completed_stages() -> set:
    """Which stages have produced their output yet (presentation state only)."""
    done = set()
    if st.session_state.cv_profile:
        done.add("onboarding")
    if st.session_state.selected_jobs:
        done.add("discovery")
        done.add("pipeline")
    if st.session_state.found_contacts:
        done.add("contacts")
    if st.session_state.draft_history:
        done.add("draft")
    return done


def render_stage_rail(current: str) -> None:
    """Draw the pipeline rail above the active screen."""
    done = _completed_stages()
    ready = {"onboarding", "discovery", "pipeline", "export"}
    if st.session_state.selected_jobs:
        ready.add("contacts")
        if st.session_state.cv_profile:
            ready.add("draft")

    cells = []
    for index, (key, label) in enumerate(STAGES, start=1):
        if key == current:
            state = "is-active"
        elif key in done:
            state = "is-done"
        elif key in ready:
            state = "is-ready"
        else:
            state = "is-locked"
        cells.append(
            f'<div class="stage {state}">'
            f'<span class="stage-lamp"></span>'
            f'<span class="stage-num">{index:02d}</span>'
            f'<span class="stage-name">{label}</span>'
            f"</div>"
        )

    st.markdown(
        f'<div class="stage-rail">{"".join(cells)}</div>', unsafe_allow_html=True
    )


# Tri-state answers: "unknown" is a real answer and must never become False.
_TRISTATE = {"Prefer not to say / not sure": None, "Yes": True, "No": False}


def _tristate(label: str, value, key: str, help: str | None = None):
    options = list(_TRISTATE)
    current = next(k for k, v in _TRISTATE.items() if v is value)
    choice = st.selectbox(
        label, options, index=options.index(current), key=key, help=help
    )
    return _TRISTATE[choice]


def _render_manual_profile_form() -> None:
    """Hand-entry CV form; works with no model connected."""
    current = st.session_state.cv_profile
    editing = current is not None and st.session_state.cv_id is not None
    base = current or CVProfile()
    with st.form("manual_profile"):
        st.markdown("**About you**")
        c1, c2 = st.columns(2)
        name = c1.text_input("Full name *", value=base.name or "")
        email = c2.text_input("Email *", value=base.email or "")
        c3, c4 = st.columns(2)
        phone = c3.text_input("Phone", value=base.phone or "")
        linkedin = c4.text_input(
            "LinkedIn link", value=base.linkedin or "", placeholder="https://"
        )
        c5, c6 = st.columns(2)
        github = c5.text_input("GitHub link", value=base.github or "")
        portfolio = c6.text_input("Portfolio / website", value=base.portfolio or "")
        summary = st.text_area(
            "Short summary",
            value=base.summary or "",
            height=80,
            placeholder="One or two sentences about what you do best.",
        )
        skills = st.text_area(
            "Skills",
            value=", ".join(base.skills),
            height=70,
            help="Separate with commas or new lines.",
        )

        st.markdown("**Work history** (most recent first; leave unused rows blank)")
        experiences = []
        rows = list(base.experiences) + [None] * max(0, 3 - len(base.experiences))
        for i, exp in enumerate(rows[: max(3, len(base.experiences))], start=1):
            with st.expander(
                f"Job {i}" + (f": {exp.title} at {exp.company}" if exp else ""),
                expanded=i == 1,
            ):
                e1, e2, e3 = st.columns([2, 2, 1])
                experiences.append(
                    {
                        "title": e1.text_input(
                            "Job title", value=exp.title if exp else "", key=f"mx_t{i}"
                        ),
                        "company": e2.text_input(
                            "Company", value=exp.company if exp else "", key=f"mx_c{i}"
                        ),
                        "duration": e3.text_input(
                            "Dates",
                            value=exp.duration if exp else "",
                            placeholder="2021-2024",
                            key=f"mx_d{i}",
                        ),
                        "achievements": st.text_area(
                            "What you achieved (one per line)",
                            value="\n".join(exp.achievements) if exp else "",
                            height=90,
                            key=f"mx_a{i}",
                        ),
                    }
                )
        education = st.text_area(
            "Education (one per line)", value="\n".join(base.education), height=70
        )
        submitted = st.form_submit_button(
            "Save changes" if editing else "Save my profile",
            type="primary",
            use_container_width=True,
        )
    if not submitted:
        return
    result = facade.save_manual_profile(
        {
            "name": name,
            "email": email,
            "phone": phone,
            "linkedin": linkedin,
            "github": github,
            "portfolio": portfolio,
            "summary": summary,
            "skills": skills,
            "education": education,
            "experiences": experiences,
        },
        cv_id=st.session_state.cv_id if editing else None,
    )
    if not result["ok"]:
        st.error("Please fix the following, then save again:")
        for message in result["errors"]:
            st.markdown(f"- {message}")
        return
    _use_profile(result["profile"], result["cv_id"])
    _flash("Profile saved." if editing else "Profile saved. Next, find some jobs.")
    st.rerun()


def _render_cv_upload(llm_ready: bool) -> None:
    """LLM-assisted parsing: fills the profile from an uploaded CV."""
    if not llm_ready:
        st.info(
            "Reading a CV file needs an AI model. Connect one under **AI settings** "
            "in the sidebar, or choose **Type it in** above."
        )
    cv_file = st.file_uploader("Your CV (PDF)", type=["pdf"])
    with st.expander("Or paste your CV as text"):
        cv_text = st.text_area("CV text", height=200, key="cv_paste_text")
    if not st.button(
        "Read my CV", type="primary", use_container_width=True, disabled=not llm_ready
    ):
        return
    if not (cv_file or cv_text):
        st.warning("Upload a PDF or paste your CV text first.")
        return
    with st.spinner("Reading your CV with the selected model..."):
        try:
            parser = CVParser(st.session_state.llm_client)
            profile = (
                parser.parse_pdf_bytes(cv_file.getbuffer())
                if cv_file
                else parser.parse_text(cv_text)
            )
        except Exception as e:
            st.error(f"Your CV could not be read: {e}")
            st.info(
                "Try a smaller model, paste the text instead, or choose "
                "**Type it in** to enter it yourself."
            )
            return
    previous_id = st.session_state.cv_id
    st.session_state.storage.save_cv_profile(profile)
    try:
        cv_id = facade.persist_cv(profile)
    except Exception:
        cv_id = None
        _flash(
            "Your CV was read but could not be saved, so it will be lost on "
            "refresh. Check that the app can write to its data folder.",
            "warning",
        )
    if cv_id is not None and previous_id is not None:
        # Keep the application answers already given for the old CV.
        answers = facade.load_candidate_profile(previous_id)
        if answers is not None:
            facade.save_candidate_profile(cv_id, answers)
    _use_profile(profile, cv_id)
    _flash(
        f"CV read: {len(profile.experiences)} jobs and {len(profile.skills)} skills "
        "found. Check them under **Type it in** and fix anything that is wrong."
    )
    st.rerun()


def _render_candidate_answers(cv_id: int) -> None:
    """Answers job applications ask beyond the CV (work rights, pay, ...)."""
    try:
        answers = facade.load_candidate_profile(cv_id)
    except Exception:
        st.warning("Your saved answers could not be loaded. Check database access.")
        return
    if answers is None:
        return
    auth, pay = answers.work_authorization, answers.compensation
    avail, prefs, demo = answers.availability, answers.preferences, answers.demographics
    with st.form("candidate_answers"):
        st.caption(
            "Used to fill application forms. Anything you leave as "
            "'not sure' is left blank for you to answer on the form."
        )
        a1, a2 = st.columns(2)
        location = a1.text_input(
            "Where you live", value=answers.location or "", placeholder="City, Country"
        )
        websites = a2.text_input(
            "Other links (comma-separated)", value=", ".join(answers.websites)
        )

        st.markdown("**Right to work**")
        w1, w2 = st.columns(2)
        country = w1.text_input(
            "Country you're applying to work in", value=auth.country or ""
        )
        visa_status = w2.text_input(
            "Current visa or status (optional)", value=auth.visa_status or ""
        )
        w3, w4 = st.columns(2)
        with w3:
            authorized = _tristate(
                "Are you allowed to work there?", auth.authorized, "ans_auth"
            )
        with w4:
            sponsorship = _tristate(
                "Will you need visa sponsorship?",
                auth.requires_sponsorship,
                "ans_sponsor",
            )

        st.markdown("**Pay and start date**")
        p1, p2, p3, p4 = st.columns(4)
        minimum = p1.number_input(
            "Minimum pay", min_value=0.0, value=pay.minimum, step=1000.0
        )
        target = p2.number_input(
            "Target pay", min_value=0.0, value=pay.target, step=1000.0
        )
        currency = p3.text_input("Currency", value=pay.currency, max_chars=3)
        periods = ["year", "month", "day", "hour"]
        period = p4.selectbox("Per", periods, index=periods.index(pay.period))
        s1, s2, s3 = st.columns(3)
        notice = s1.number_input(
            "Notice period (weeks)",
            min_value=0,
            max_value=104,
            value=avail.notice_period_weeks,
            step=1,
        )
        start = s2.text_input(
            "Earliest start date",
            value=avail.earliest_start_date or "",
            placeholder="2026-11-01",
        )
        with s3:
            contract = _tristate(
                "Open to contract work?", avail.open_to_contract, "ans_contract"
            )

        st.markdown("**What you're looking for**")
        j1, j2 = st.columns(2)
        titles = j1.text_input(
            "Job titles (comma-separated)", value=", ".join(prefs.desired_titles)
        )
        locations = j2.text_input(
            "Preferred locations (comma-separated)", value=", ".join(prefs.locations)
        )
        j3, j4 = st.columns(2)
        remote_labels = {
            None: "No preference",
            RemotePreference.REMOTE_ONLY: "Remote only",
            RemotePreference.HYBRID: "Hybrid",
            RemotePreference.ONSITE: "In the office",
            RemotePreference.FLEXIBLE: "Flexible",
        }
        remote_keys = list(remote_labels)
        remote = j3.selectbox(
            "Remote work",
            remote_keys,
            index=remote_keys.index(prefs.remote_preference),
            format_func=remote_labels.get,
        )
        with j4:
            relocate = _tristate(
                "Open to relocating?", prefs.open_to_relocation, "ans_relocate"
            )

        with st.expander("Optional: diversity questions"):
            st.caption(
                "Only shared with applications if you tick the box below. "
                "Leave blank to answer on each form yourself."
            )
            d1, d2 = st.columns(2)
            pronouns = d1.text_input("Pronouns", value=demo.pronouns or "")
            gender = d2.text_input("Gender", value=demo.gender or "")
            d3, d4 = st.columns(2)
            ethnicity = d3.text_input("Ethnicity", value=demo.ethnicity or "")
            veteran = d4.text_input("Veteran status", value=demo.veteran_status or "")
            disability = st.text_input(
                "Disability status", value=demo.disability_status or ""
            )
            share = st.checkbox(
                "Let the autofill extension use these answers",
                value=demo.share_on_applications,
            )
        cover_note = st.text_area(
            "Default note for 'anything else?' questions (optional)",
            value=answers.default_cover_note or "",
            height=70,
        )
        saved = st.form_submit_button(
            "Save answers", type="primary", use_container_width=True
        )
    if not saved:
        return

    def _csv(text: str) -> list[str]:
        return [part.strip() for part in text.split(",") if part.strip()]

    result = facade.save_candidate_profile(
        cv_id,
        {
            "location": location.strip() or None,
            "websites": _csv(websites),
            "work_authorization": {
                "country": country.strip() or None,
                "authorized": authorized,
                "requires_sponsorship": sponsorship,
                "visa_status": visa_status.strip() or None,
            },
            "compensation": {
                "minimum": minimum or None,
                "target": target or None,
                "currency": (currency or "USD").strip().upper(),
                "period": period,
            },
            "availability": {
                "notice_period_weeks": notice,
                "earliest_start_date": start.strip() or None,
                "open_to_contract": contract,
            },
            "preferences": {
                "desired_titles": _csv(titles),
                "remote_preference": remote,
                "locations": _csv(locations),
                "open_to_relocation": relocate,
            },
            "demographics": {
                "pronouns": pronouns.strip() or None,
                "gender": gender.strip() or None,
                "ethnicity": ethnicity.strip() or None,
                "veteran_status": veteran.strip() or None,
                "disability_status": disability.strip() or None,
                "share_on_applications": share,
            },
            "default_cover_note": cover_note.strip() or None,
        },
    )
    if result["ok"]:
        _flash("Answers saved.")
        st.rerun()
    else:
        st.error(f"Answers not saved: {result['error']}")


def _render_completeness(profile: CVProfile) -> None:
    answers = None
    if st.session_state.cv_id is not None:
        try:
            answers = facade.load_candidate_profile(st.session_state.cv_id)
        except Exception:
            answers = None
    report = facade.profile_completeness(profile, answers)
    st.progress(report["percent"] / 100, text=f"Profile {report['percent']}% complete")
    if report["next_best_action"]:
        st.caption(f"Next best step: {report['next_best_action']}")


# Page 1: Onboarding
def page_onboarding():
    """Profile screen: add or restore a CV, then the answers forms ask for."""
    st.title("Your profile")
    st.markdown(
        "Add your CV once, then find jobs and prepare applications. "
        "Everything stays on this computer."
    )
    try:
        saved_profiles = facade.saved_cv_profiles()
    except Exception:
        saved_profiles = []
        st.warning("Saved profiles could not be listed. Check database access.")
    if saved_profiles:
        with st.expander(
            "Use a saved profile", expanded=not st.session_state.cv_profile
        ):
            profiles_by_id = {item["id"]: item for item in saved_profiles}
            saved_id = st.selectbox(
                "Saved profile",
                list(profiles_by_id),
                format_func=lambda value: (
                    f"{profiles_by_id[value]['name'] or 'Unnamed profile'} "
                    f"(saved {profiles_by_id[value]['saved_label']})"
                ),
            )
            if st.button("Use this profile", use_container_width=True):
                try:
                    profile = facade.load_cv(saved_id)
                    if profile is None:
                        st.error("That profile is unavailable. Choose another one.")
                    else:
                        _use_profile(profile, saved_id)
                        _flash(f"Using {profile.name or 'your saved profile'}.")
                        st.rerun()
                except Exception:
                    st.error(
                        "This profile could not be opened: it was saved with a "
                        "different key. Restore the original encryption key "
                        "(CAREERAGENT_ENCRYPTION_KEY in .env) to open it."
                    )

    profile = st.session_state.cv_profile
    if profile:
        _render_completeness(profile)

    llm_ready = bool(st.session_state.llm_client)
    modes = ["Type it in", "Upload a CV (uses AI)"]
    mode = st.radio(
        "How do you want to add your CV?",
        modes,
        index=1 if llm_ready and not profile else 0,
        horizontal=True,
        key="onboarding_mode",
    )
    if mode == modes[0]:
        _render_manual_profile_form()
    else:
        _render_cv_upload(llm_ready)

    if not profile:
        return

    st.divider()
    st.subheader("Application answers")
    if st.session_state.cv_id is None:
        st.info("Save your profile first; answers are stored with it.")
    else:
        _render_candidate_answers(st.session_state.cv_id)

    st.divider()
    st.subheader("Resume check")
    st.caption(
        "Job sites read resumes with software (an applicant tracking system, "
        "or ATS). These checks catch formatting it often misreads."
    )
    report = facade.lint_resume(profile, raw_text=profile.raw_text or None)
    if report["ok"]:
        st.success("No blocking issues found.")
    else:
        for msg in report["errors"]:
            st.error(msg)
    for msg in report["warnings"]:
        st.warning(msg)
    if report["info"]:
        with st.expander(f"Suggestions ({len(report['info'])})"):
            for msg in report["info"]:
                st.info(msg)

    st.caption("Download a clean, single-column version of your resume:")
    exp1, exp2, exp3 = st.columns(3)
    exp1.download_button(
        "PDF",
        data=facade.resume_pdf(profile),
        file_name="resume.pdf",
        mime="application/pdf",
        use_container_width=True,
    )
    exp2.download_button(
        "Markdown",
        data=facade.resume_markdown(profile),
        file_name="resume.md",
        mime="text/markdown",
        use_container_width=True,
    )
    exp3.download_button(
        "JSON Resume",
        data=json.dumps(facade.resume_json(profile), indent=2),
        file_name="resume.json",
        mime="application/json",
        use_container_width=True,
    )

    if st.button("Next: find jobs", type="primary", use_container_width=True):
        _go("discovery")


# Page 2: Job Discovery
def page_discovery():
    """Job discovery screen"""
    st.title("Find jobs")
    st.markdown(
        "Pull real postings from a company's careers page or from job boards. "
        "Everything you find is saved and scored in **Pipeline**."
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
        # A key keeps the chosen mode when the user navigates away and back.
        key="discovery_mode",
        help=(
            "A careers page link works best: most company job sites (Greenhouse, "
            "Lever, Ashby and others) publish their jobs in a form we can read "
            "directly. Job boards search several remote-job sites by keyword."
        ),
    )

    st.divider()

    if mode == "Company careers URL (recommended)":
        careers_url = st.text_input(
            "Careers page or job board URL",
            placeholder="https://boards.greenhouse.io/stripe",
            help="Paste the link to a company's jobs page.",
            key="careers_url",
        )
        if st.button("Discover jobs", type="primary"):
            if not careers_url:
                st.warning("Paste a careers page link first.")
            elif not careers_url.strip().lower().startswith(("http://", "https://")):
                st.warning(
                    "That doesn't look like a web link. It should start with https://"
                )
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
            "Search job boards that publish their listings openly. All work "
            "without setup except Adzuna, which needs a free API key."
        )
        bcol1, bcol2 = st.columns([1, 2])
        with bcol1:
            provider = st.selectbox(
                "Job board",
                facade.aggregator_providers(),
                format_func=facade.provider_label,
                key="board_provider",
            )
        searchable = facade.aggregator_supports_keywords(provider)
        with bcol2:
            keywords = st.text_input(
                "Keywords (optional)",
                placeholder="machine learning",
                key="board_keywords",
                disabled=not searchable,
                help=(
                    "This provider has no server-side search - it returns its "
                    "newest postings. Filter them on the Pipeline screen."
                )
                if not searchable
                else None,
            )

        if st.button("Search job boards", type="primary"):
            label = facade.provider_label(provider)
            with st.spinner(f"Searching {label}..."):
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
                    st.error(
                        f"{label} didn't respond ({result.errors[0]}). The site "
                        "may be busy or blocked on this network; try another "
                        "job board or try again later."
                    )
                elif result.upserted:
                    st.success(
                        f"Saved {result.upserted} job(s) from {label}. "
                        "See them scored in Pipeline."
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
                "No model connected. Pick a provider in the sidebar, then choose Initialize LLM."
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
                        _flash(f"Added {job.title} at {job.company}.")
                        st.rerun()

    elif mode == "Paste Job URL":
        job_url = st.text_input(
            "Job Post URL", placeholder="https://company.com/careers/job-id"
        )

        if not st.session_state.llm_client:
            st.info(
                "This mode uses the local LLM to parse the page. Initialize it "
                "from the sidebar, or use the careers-URL mode instead."
            )

        if st.button("Fetch Job Details", type="primary"):
            if not st.session_state.llm_client:
                st.info(
                    "No model connected. Pick a provider in the sidebar, then choose Initialize LLM."
                )
                return
            with st.spinner("Fetching job details..."):
                try:
                    finder = JobFinder(st.session_state.llm_client)
                    job = finder.fetch_job_details(job_url)

                    if job:
                        _select_job(job)
                        _flash(f"Added {job.title} at {job.company}.")
                        st.rerun()
                    else:
                        st.error("Failed to fetch job details")
                except Exception as e:
                    st.error(f"Error: {e}")

    else:  # Paste Job Description
        # Keys keep half-typed text when the user navigates away and back.
        job_desc = st.text_area(
            "Paste Job Description",
            height=300,
            help="Paste the full job description text",
            key="jd_text",
        )

        col1, col2 = st.columns(2)
        with col1:
            job_title = st.text_input(
                "Job Title", placeholder="Senior Software Engineer", key="jd_title"
            )
        with col2:
            company_name = st.text_input(
                "Company Name", placeholder="Google", key="jd_company"
            )

        if st.button("Add Job", type="primary"):
            if job_desc and job_title and company_name:
                job = JobPosting(
                    title=job_title, company=company_name, description=job_desc
                )
                _select_job(job)
                for key in ("jd_text", "jd_title", "jd_company"):
                    st.session_state.pop(key, None)
                _flash(
                    f"Added {job_title} at {company_name}. It's in Pipeline and "
                    "ready in Draft Studio."
                )
                st.rerun()
            else:
                missing = [
                    name
                    for name, value in (
                        ("the description", job_desc),
                        ("the job title", job_title),
                        ("the company name", company_name),
                    )
                    if not (value or "").strip()
                ]
                st.warning("Please add " + ", ".join(missing) + ".")

    if st.button("View saved jobs in Pipeline", use_container_width=True):
        st.session_state.page = "pipeline"
        st.rerun()

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
                    st.rerun()

        if st.button("Next: Find Contacts", type="primary", use_container_width=True):
            st.session_state.page = "contacts"
            st.rerun()


# Page 3: Contact Discovery
def page_contacts():
    """Contact discovery screen"""
    st.title("Contact Discovery")
    st.markdown("Find hiring managers and generate email permutations")

    if not st.session_state.selected_jobs:
        st.info(
            "Choose a job in Job Discovery or select Prepare application in Pipeline."
        )
        if st.button("Find a job", use_container_width=True):
            st.session_state.page = "discovery"
            st.rerun()
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

                            st.session_state.found_contacts[job.company].extend(
                                contacts
                            )
                            st.success(f"Found {len(contacts)} contacts")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Search failed: {e}")

            with col2:
                with st.popover("Add Manual Contact"):
                    name = st.text_input("Name", key=f"manual_name_{idx}")
                    email = st.text_input("Email", key=f"manual_email_{idx}")
                    role = st.text_input("Role", key=f"manual_role_{idx}")

                    if st.button("Add", key=f"add_manual_{idx}"):
                        result = facade.manual_contact(name, email, role)
                        if result["ok"]:
                            st.session_state.found_contacts.setdefault(
                                job.company, []
                            ).append(result["contact"])
                            for field in ("name", "email", "role"):
                                st.session_state.pop(f"manual_{field}_{idx}", None)
                            _flash(f"Added {result['contact'].name}.")
                            st.rerun()
                        else:
                            st.error(result["error"])

            # Show found contacts
            if job.company in st.session_state.found_contacts:
                contacts = st.session_state.found_contacts[job.company]

                if contacts:
                    st.write("**Found Contacts:**")

                    for i, contact in enumerate(contacts):
                        col1, col2, col3 = st.columns([3, 2, 1])

                        manual = contact.source == "manual"
                        with col1:
                            st.write(
                                f"**{contact.name}** - {contact.role or 'role unknown'}"
                            )

                        with col2:
                            if not contact.email:
                                st.caption("No email found")
                            elif manual:
                                st.caption(f"Added by you: {contact.email}")
                            elif contact.email_confidence == "confirmed":
                                st.caption(f"Verified: {contact.email}")
                            else:
                                st.caption(f"Unverified guess: {contact.email}")

                        with col3:
                            if not manual:
                                st.caption(
                                    f"{int(contact.confidence_score * 100)}% likely",
                                    help="How likely this person and address are right.",
                                )

            # Email permutations
            st.write("**Generate Email Permutations:**")
            col1, col2, col3 = st.columns(3)

            with col1:
                first_name = st.text_input("First Name", key=f"fname_{idx}")
            with col2:
                last_name = st.text_input("Last Name", key=f"lname_{idx}")
            with col3:
                # Extract domain from company name or URL
                domain = (
                    job.url.split("/")[2]
                    if job.url
                    else f"{job.company.lower().replace(' ', '')}.com"
                )
                domain_input = st.text_input(
                    "Domain", value=domain, key=f"domain_{idx}"
                )

            if st.button("Generate Permutations", key=f"gen_perm_{idx}"):
                if first_name and last_name and domain_input:
                    finder = ContactFinder(st.session_state.llm_client)
                    permutations = finder.generate_email_permutations(
                        first_name, last_name, domain_input
                    )

                    if job.company not in st.session_state.found_contacts:
                        st.session_state.found_contacts[job.company] = []

                    st.session_state.found_contacts[job.company].extend(permutations)
                    st.success(f"Generated {len(permutations)} email permutations")
                    st.rerun()

    st.divider()

    if st.button("Next: Draft Studio", type="primary", use_container_width=True):
        st.session_state.page = "draft"
        st.rerun()


# Page 4: Draft Studio
def page_draft_studio():
    """Draft generation and editing screen"""
    st.title("Draft Studio")
    st.markdown("Generate and refine personalized outreach messages")

    if not st.session_state.selected_jobs:
        st.info(
            "Choose a job in Job Discovery or select Prepare application in Pipeline."
        )
        if st.button("Find a job", use_container_width=True):
            st.session_state.page = "discovery"
            st.rerun()
        return

    if not st.session_state.cv_profile:
        st.info("Add or restore your CV to prepare personalized application materials.")
        if st.button("Add or restore my CV", use_container_width=True):
            st.session_state.page = "onboarding"
            st.rerun()
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
                st.download_button(
                    "Download tailored ATS PDF",
                    data=facade.resume_pdf(tailored["profile"]),
                    file_name=f"resume_{current_job.company}.pdf".replace(" ", "_"),
                    mime="application/pdf",
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
            angle = st.selectbox(
                "Focus",
                ["technical", "impact", "product"],
                help="What the AI draft leads with: your technical depth, "
                "measurable results, or product sense.",
            )

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
                        st.rerun()
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
                            st.rerun()
                        except Exception as e:
                            st.error(f"Regeneration failed: {e}")

        if not st.session_state.current_draft:
            if not llm_ready:
                st.caption(
                    "No AI model connected. You can still write the email "
                    "yourself and use every check below."
                )
            if st.button("Write it myself", use_container_width=True):
                _set_current_draft(
                    EmailDraft(
                        subject=f"{current_job.title} at {current_job.company}",
                        body="",
                        company=current_job.company,
                        job_title=current_job.title,
                    ),
                    workspace_key,
                )
                st.rerun()

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
            st.caption(
                "Cold emails are regulated. Before sending, the law asks you to "
                "say who you are, give a postal address, and let people opt out."
            )
            with st.expander("Your sender details (required to send)"):
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
                    postal_address = st.text_input(
                        "Physical postal address",
                        help="Required by anti-spam law (CAN-SPAM). A PO box works.",
                    )
                    unsubscribe = st.text_input(
                        "Opt-out (URL or mailto:)",
                        help="How the recipient can ask you to stop emailing. "
                        "The default is an email reply asking to unsubscribe.",
                        value=f"mailto:{st.session_state.cv_profile.email or ''}"
                        "?subject=unsubscribe",
                    )
                lia_purpose = st.text_input(
                    "LIA purpose (GDPR)",
                    help="Why contacting this person is reasonable. EU privacy "
                    "law (GDPR) asks you to record this 'legitimate interest'.",
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

    st.caption(
        "One ZIP with everything CareerAgent holds for you, in readable form: "
        "your saved profiles, your application board with notes, saved jobs "
        "and drafts. It contains personal details, so store it carefully."
    )
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
    st.caption(
        "The CareerAgent Autofill extension fills application forms from these "
        "fields. Copy the JSON into the extension popup (**Import from "
        "CareerAgent**) instead of retyping what your CV already says. It "
        "travels by clipboard on purpose - the extension needs no access to "
        "this app, and your details never leave the browser."
    )
    if not st.session_state.cv_profile:
        st.info("Add your profile on the **Your profile** screen to fill this in.")
    else:
        answers = None
        if st.session_state.cv_id is not None:
            try:
                answers = facade.load_candidate_profile(st.session_state.cv_id)
            except Exception:
                st.warning("Saved application answers could not be loaded.")
        include_resume = st.checkbox(
            "Include my resume PDF so the extension can attach it",
            help="Adds your resume to the file. It stays on your computer.",
        )
        preview = facade.extension_profile(st.session_state.cv_profile, answers)
        st.code(json.dumps(preview, indent=2), language="json")
        st.download_button(
            "Download profile (JSON)",
            data=json.dumps(
                facade.extension_profile(
                    st.session_state.cv_profile,
                    answers,
                    include_resume=include_resume,
                ),
                indent=2,
            ),
            file_name="careeragent_autofill_profile.json",
            mime="application/json",
        )
        if answers is None or not answers.location:
            st.caption(
                "Tip: add where you live and your right-to-work answers under "
                "**Your profile > Application answers** so forms fill further."
            )

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
            if card.get("url"):
                st.markdown(f"[Open posting]({card['url']})")

            c1, c2, c3 = st.columns(3)
            if c1.button("Snooze 3d", key=f"snooze3_{app_id}"):
                facade.snooze_followup(app_id, 3)
                st.rerun()
            if c2.button("Snooze 7d", key=f"snooze7_{app_id}"):
                facade.snooze_followup(app_id, 7)
                st.rerun()
            if c3.button("No reply — reject", key=f"rej_{app_id}"):
                res = facade.advance_application(app_id, "rejected")
                if res["ok"]:
                    st.rerun()
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

    # --- Ingest from an ATS public API --- #
    st.subheader("Ingest jobs from a company ATS")
    col1, col2, col3 = st.columns([2, 2, 1])
    with col1:
        slug = st.text_input(
            "Board slug",
            placeholder="e.g. stripe",
            help="The company's name as it appears in its jobs-page link, "
            "e.g. 'stripe' in boards.greenhouse.io/stripe.",
        )
    with col2:
        ats_type = st.selectbox(
            "ATS",
            facade.ats_providers(),
            help="The hiring software the company uses (an applicant tracking "
            "system). It's usually visible in the jobs-page link.",
        )
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
                result = facade.ingest_ats(ats_type, slug, company, **import_options)
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
                st.rerun()
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
                help="Ghost jobs are postings that look stale or vague and may "
                "not really be hiring. This hides the riskiest ones.",
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
                    else "Off: no visa-sponsor list is installed yet. To turn it "
                    "on, run `python -m scripts.fetch_datasets --uk` once."
                ),
            )
        with f3:
            level = st.radio(
                "Level", ["Any", "New grad", "Internship"], horizontal=False
            )

        if not visa_loaded:
            st.caption(
                "Visa-sponsor data isn't included, because it has to come from "
                "official registers rather than guesses. The setup command is "
                "in the 'Visa sponsors only' tooltip."
            )
        if not status.get("semantic_embeddings", False):
            st.caption(
                "Matching compares words, not meaning. For smarter matching, "
                "install the optional `sentence-transformers` package."
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
        quality, _tone = match_quality(job["score"])
        score = f" · {job['score']:.0f}%" if job["score"] is not None else ""
        with st.expander(f"{job['title']} - {job['company']} ({quality}{score})"):
            chips = job_chips(job)
            if job.get("glassdoor_rating"):
                chips.append(f"Glassdoor {job['glassdoor_rating']}")
            if chips:
                st.caption(" · ".join(chips))
            if job.get("source"):
                st.caption(f"Source: {facade.provider_label(job['source'])}")
            if job.get("attribution"):
                st.caption(job["attribution"])
            for note in risk_notes(job):
                st.warning(note)

            if job["matched"]:
                st.success("You have: " + ", ".join(job["matched"][:12]))
            if job["missing"]:
                st.warning("Not in your profile yet: " + ", ".join(job["missing"][:12]))

            target = facade.apply_target(job["id"])
            a1, a2, a3, a4 = st.columns(4)
            if target.get("url"):
                a1.link_button("Apply", target["url"], use_container_width=True)
            if a2.button(
                "I applied", key=f"applied_{job['id']}", use_container_width=True
            ):
                res = facade.mark_applied(job["id"], st.session_state.cv_id)
                if res["ok"]:
                    _flash(
                        f"Marked as applied: {job['title']}. We'll remind you "
                        "to follow up."
                        if res.get("changed", True)
                        else f"{job['title']} is already further along."
                    )
                    st.rerun()
                else:
                    st.warning(res["error"])
            if a3.button(
                "Save for later",
                key=f"track_{job['id']}",
                use_container_width=True,
            ):
                res = facade.add_to_pipeline(job["id"], st.session_state.cv_id)
                if res["ok"]:
                    _flash(f"Saved {job['title']} to your application board.")
                    st.rerun()
                else:
                    st.warning(res["error"])
            a4.button(
                "Prepare application",
                key=f"prepare_{job['id']}",
                on_click=_prepare_application,
                args=(job["id"],),
                use_container_width=True,
            )
            if target.get("note"):
                st.caption(target["note"])

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
                        f"→ {next_status[status].title()}",
                        key=f"adv_{card['application_id']}",
                        help=f"Move to {next_status[status]}",
                        use_container_width=True,
                    ):
                        facade.advance_application(
                            card["application_id"], next_status[status]
                        )
                        st.rerun()

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
        if card.get("url"):
            st.markdown(f"[Open posting]({card['url']})")
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
                st.rerun()
        # Every active state can also end badly. Without this the board only
        # models the happy path and dead applications sit in "applied"
        # forever, skewing the funnel and nagging with stale reminders.
        if status not in ("rejected", "withdrawn"):
            if st.button(
                "Mark rejected", key=f"detail_rej_{app_id}", use_container_width=True
            ):
                res = facade.advance_application(app_id, "rejected")
                if res["ok"]:
                    st.rerun()
                else:
                    st.warning(res["error"])
            if st.button(
                "Withdraw", key=f"detail_wd_{app_id}", use_container_width=True
            ):
                res = facade.advance_application(app_id, "withdrawn")
                if res["ok"]:
                    st.rerun()
                else:
                    st.warning(res["error"])


# Router
render_sidebar()
render_stage_rail(st.session_state.get("page", "onboarding"))
for notice_key in ("match_refresh_warning", "job_save_notice"):
    if st.session_state.get(notice_key):
        st.warning(st.session_state[notice_key])
if st.session_state.get("prepare_job_error"):
    st.error(st.session_state.prepare_job_error)
_render_flash()

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

if __name__ == "__main__":
    pass
