"""
CareerAgent - Main Streamlit Application
Complete UI with 5 screens: Onboarding, Discovery, Contacts, Draft Studio, Export
"""

import json
import os
from pathlib import Path

import streamlit as st

from core import facade
from core.contact_finder import ContactFinder
from core.cv_parser import CVParser
from core.gmail_drafts import GmailDraftClient
from core.job_finder import JobFinder

# Core imports
from core.llm import LocalLLMClient
from core.models import ContactCandidate, EmailDraft, JobPosting, SearchQuery
from core.outreach import ComplianceConfig, LIARecord
from core.personalization import PersonalizationEngine
from core.storage import LocalStorage
from core.validators import DraftValidator

# Page config
st.set_page_config(
    page_title="CareerAgent - Local AI Career Agent",
    page_icon=None,
    layout="wide",
    initial_sidebar_state="expanded",
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


init_session_state()

# Ensure the database schema exists (Phase 1+). Non-fatal if it can't init so
# the legacy JSON-only flow still works.
try:
    facade.init_persistence()
except Exception:  # pragma: no cover - defensive UI guard
    pass


# Sidebar configuration
def render_sidebar():
    """Render sidebar with navigation and settings"""
    with st.sidebar:
        st.title("CareerAgent")
        st.caption("Local AI Career Agent")

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

        for key, label in pages.items():
            if st.button(label, key=f"nav_{key}", use_container_width=True):
                st.session_state.page = key
                st.rerun()

        st.divider()

        # LLM Settings
        st.subheader("LLM Settings")

        model = st.selectbox(
            "Model",
            ["llama3.1:8b", "llama3.2:3b", "qwen2.5:7b", "mistral:7b"],
            key="selected_model",
        )

        if st.button("Initialize LLM", use_container_width=True):
            with st.spinner("Connecting to Ollama..."):
                try:
                    llm = LocalLLMClient(model=model)
                    if llm.check_connection():
                        st.session_state.llm_client = llm
                        st.success(f"Connected to {model}")
                    else:
                        st.error("Ollama not running. Run `ollama serve`")
                except Exception as e:
                    st.error(f"Error: {e}")

        # Show connection status
        if st.session_state.llm_client:
            st.success("LLM Connected")
        else:
            st.warning("LLM Not Connected")

        st.divider()

        # Stats
        st.subheader("Session Stats")
        st.metric("CV Parsed", "Yes" if st.session_state.cv_profile else "No")
        st.metric("Jobs Selected", len(st.session_state.selected_jobs))
        st.metric("Drafts Created", len(st.session_state.draft_history))


def _current_candidate():
    """The candidate profile held in session, seeded from the parsed CV."""
    from core.candidate import CandidateProfile

    candidate = st.session_state.get("candidate")
    if candidate is None:
        candidate = CandidateProfile()
    # Keep the CV half in step with whatever onboarding parsed.
    if st.session_state.get("cv_profile") is not None:
        candidate.cv = st.session_state.cv_profile
    st.session_state.candidate = candidate
    return candidate


def _persist_candidate(candidate):
    """Save the profile, remembering the row id so we update rather than insert."""
    try:
        st.session_state.cv_id = facade.save_candidate(
            candidate, cv_id=st.session_state.get("cv_id")
        )
        return True
    except Exception as e:  # pragma: no cover - defensive UI guard
        st.error(f"Could not save profile: {e}")
        return False


def render_profile_builder(candidate):
    """Structured profile capture: the answers application forms demand.

    Grouped into tabs so the form never looks like a wall of inputs, following
    the pattern used by candidate-profile platforms: eligibility and
    compensation are first-class fields, not resume afterthoughts.
    """
    from core.candidate import CompanyStage, RemotePreference

    st.subheader("Your profile")
    st.caption(
        "These answers are what application forms actually block on. "
        "Anything you leave blank is left blank on the form too — nothing is "
        "guessed on your behalf."
    )

    tab_basics, tab_elig, tab_prefs, tab_comp, tab_eeo = st.tabs(
        ["Basics", "Work eligibility", "Preferences", "Compensation", "Optional (EEO)"]
    )

    with tab_basics:
        b1, b2 = st.columns(2)
        with b1:
            candidate.location = st.text_input(
                "Location",
                value=candidate.location or "",
                placeholder="London, UK",
                help="Fills the 'City' field on application forms.",
            )
        with b2:
            websites = st.text_input(
                "Personal site / portfolio",
                value=candidate.websites[0] if candidate.websites else "",
                placeholder="https://yoursite.com",
            )
            candidate.websites = [websites] if websites else []
        candidate.default_cover_note = st.text_area(
            "Default answer for 'Why do you want to work here?'",
            value=candidate.default_cover_note or "",
            height=90,
            help="Reused as a starting point; edit per company before submitting.",
        )

    with tab_elig:
        st.markdown(
            "**The most common reason autofill stalls.** Without these, the "
            "extension leaves the question for you rather than guessing."
        )
        auth = candidate.work_authorization
        e1, e2 = st.columns(2)
        with e1:
            auth.country = st.text_input(
                "Country you're applying in",
                value=auth.country or "",
                placeholder="United States",
            )
            auth.visa_status = st.text_input(
                "Current visa status (optional)",
                value=auth.visa_status or "",
                placeholder="e.g. H-1B, Skilled Worker, Citizen",
            )
        with e2:
            auth.authorized = _tristate(
                "Legally authorized to work there?", auth.authorized, "auth_ok"
            )
            auth.requires_sponsorship = _tristate(
                "Will you require visa sponsorship?",
                auth.requires_sponsorship,
                "auth_sponsor",
            )

    with tab_prefs:
        p = candidate.preferences
        titles = st.text_area(
            "Target roles (one per line)",
            value="\n".join(p.desired_titles),
            height=90,
            placeholder="Senior Software Engineer\nML Engineer",
        )
        p.desired_titles = [t.strip() for t in titles.splitlines() if t.strip()]

        pf1, pf2 = st.columns(2)
        with pf1:
            remote_options = ["(not set)"] + [r.value for r in RemotePreference]
            current = p.remote_preference.value if p.remote_preference else "(not set)"
            chosen = st.selectbox(
                "Work style",
                remote_options,
                index=remote_options.index(current),
            )
            p.remote_preference = (
                RemotePreference(chosen) if chosen != "(not set)" else None
            )
            p.seniority = (
                st.selectbox(
                    "Seniority",
                    ["", "Junior", "Mid-level", "Senior", "Staff", "Principal"],
                    index=0
                    if not p.seniority
                    else [
                        "",
                        "Junior",
                        "Mid-level",
                        "Senior",
                        "Staff",
                        "Principal",
                    ].index(p.seniority),
                )
                or None
            )
        with pf2:
            locs = st.text_area(
                "Preferred locations (one per line)",
                value="\n".join(p.locations),
                height=90,
                placeholder="Remote\nLondon",
            )
            p.locations = [x.strip() for x in locs.splitlines() if x.strip()]
            p.open_to_relocation = _tristate(
                "Open to relocation?", p.open_to_relocation, "relocate"
            )

        p.company_stages = [
            CompanyStage(s)
            for s in st.multiselect(
                "Company stage",
                [s.value for s in CompanyStage],
                default=[s.value for s in p.company_stages],
            )
        ]
        excluded = st.text_area(
            "Never show me these companies (one per line)",
            value="\n".join(p.excluded_companies),
            height=70,
        )
        p.excluded_companies = [x.strip() for x in excluded.splitlines() if x.strip()]

    with tab_comp:
        c = candidate.compensation
        c1, c2, c3 = st.columns(3)
        with c1:
            minimum = st.number_input(
                "Minimum acceptable",
                min_value=0,
                step=1000,
                value=int(c.minimum) if c.minimum else 0,
                help="Roles below this are filtered out.",
            )
            c.minimum = float(minimum) if minimum else None
        with c2:
            target = st.number_input(
                "Target",
                min_value=0,
                step=1000,
                value=int(c.target) if c.target else 0,
            )
            c.target = float(target) if target else None
        with c3:
            c.currency = st.selectbox(
                "Currency",
                ["USD", "GBP", "EUR", "CAD", "AUD", "INR"],
                index=["USD", "GBP", "EUR", "CAD", "AUD", "INR"].index(c.currency),
            )
            c.period = st.selectbox(
                "Per",
                ["year", "day", "hour"],
                index=["year", "day", "hour"].index(c.period),
            )

        a = candidate.availability
        av1, av2 = st.columns(2)
        with av1:
            weeks = st.number_input(
                "Notice period (weeks)",
                min_value=0,
                max_value=52,
                value=a.notice_period_weeks or 0,
            )
            a.notice_period_weeks = weeks if weeks else None
        with av2:
            a.earliest_start_date = (
                st.text_input(
                    "Earliest start date",
                    value=a.earliest_start_date or "",
                    placeholder="Immediately / 2026-09-01",
                )
                or None
            )

    with tab_eeo:
        d = candidate.demographics
        st.caption(
            "Entirely optional. US forms often ask these for EEO reporting. "
            "They are **never** inferred, and are only ever put on a form if "
            "you tick the box below."
        )
        d.share_on_applications = st.checkbox(
            "Use these answers on application forms",
            value=d.share_on_applications,
        )
        d1, d2 = st.columns(2)
        with d1:
            d.pronouns = st.text_input("Pronouns", value=d.pronouns or "") or None
            d.gender = st.text_input("Gender", value=d.gender or "") or None
            d.ethnicity = st.text_input("Ethnicity", value=d.ethnicity or "") or None
        with d2:
            d.veteran_status = (
                st.text_input("Veteran status", value=d.veteran_status or "") or None
            )
            d.disability_status = (
                st.text_input("Disability status", value=d.disability_status or "")
                or None
            )

    st.session_state.candidate = candidate
    if st.button("Save profile", type="primary", use_container_width=True):
        if _persist_candidate(candidate):
            st.success("Profile saved.")
            st.rerun()
    return candidate


def _tristate(label: str, value, key: str):
    """A yes/no control that keeps 'not answered' as a real, distinct state."""
    options = ["Not answered", "Yes", "No"]
    index = 0 if value is None else (1 if value else 2)
    choice = st.radio(label, options, index=index, key=key, horizontal=True)
    if choice == "Yes":
        return True
    if choice == "No":
        return False
    return None


# Page 1: Onboarding
def page_onboarding():
    """Onboarding screen - CV upload and preferences"""
    st.title("Onboarding")
    st.markdown("Upload your CV and define your target roles")

    # Check LLM connection
    if not st.session_state.llm_client:
        st.error("Please initialize LLM from sidebar first")
        return

    col1, col2 = st.columns([2, 1])

    with col1:
        st.subheader("Upload CV")

        # PDF upload
        cv_file = st.file_uploader(
            "Upload CV (PDF)", type=["pdf"], help="Drag and drop your CV PDF here"
        )

        # Text fallback
        with st.expander("Or Paste CV Text (Fallback)"):
            cv_text = st.text_area(
                "Paste CV text", height=200, help="Use this if PDF upload fails"
            )

        if st.button("Parse CV", type="primary", use_container_width=True):
            if cv_file or cv_text:
                with st.spinner("Parsing CV with local LLM..."):
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
                            # Save temp file
                            temp_path = f"temp_cv_{cv_file.name}"
                            with open(temp_path, "wb") as f:
                                f.write(cv_file.getbuffer())

                            progress_bar.progress(
                                40, text="Extracting text from PDF..."
                            )
                            profile = parser.parse_pdf(temp_path)
                            os.remove(temp_path)
                        else:
                            progress_bar.progress(
                                40, text="Analyzing text structure..."
                            )
                            profile = parser.parse_text(cv_text)

                        elapsed = time.time() - start_time
                        progress_bar.progress(100, text=f"Complete in {elapsed:.1f}s!")

                        st.session_state.cv_profile = profile
                        st.session_state.storage.save_cv_profile(profile)
                        # Persist to the encrypted DB (Phase 1) for matching/tracking.
                        try:
                            st.session_state.cv_id = facade.persist_cv(profile)
                        except Exception:
                            st.session_state.cv_id = None
                        st.success(
                            f"✅ CV parsed successfully! Found {len(profile.experiences)} experiences."
                        )
                        st.rerun()

                    except Exception as e:
                        st.error(f"❌ Parsing failed: {e}")
                        st.info(
                            "Tip: Try a smaller model (qwen2.5:3b) or shorten the CV text."
                        )
            else:
                st.warning("Please upload a CV or paste text")

    with col2:
        st.subheader("Profile strength")
        candidate = _current_candidate()
        report = facade.profile_completeness(candidate)
        st.progress(report["percent"] / 100, text=f"{report['percent']}% complete")

        nba = report["next_best_action"]
        if nba:
            st.info(f"**Next: {nba['label']}** — {nba['why']}")
        else:
            st.success("Profile complete. Applications will fill end to end.")

        missing = report["missing"]
        if missing:
            with st.expander(f"{len(missing)} item(s) still missing"):
                for item in missing:
                    st.markdown(
                        f"- **{item['label']}** ({item['section']}) — {item['why']}"
                    )

    # Show parsed CV
    if st.session_state.cv_profile:
        st.divider()
        st.subheader("Parsed CV Profile")

        profile = st.session_state.cv_profile

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Name", profile.name or "N/A")
        col2.metric("Email", profile.email or "N/A")
        col3.metric("Projects", len(profile.projects))
        col4.metric("Skills", len(profile.skills))

        with st.expander("View Full Profile"):
            st.json(profile.model_dump())

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
            st.download_button(
                "Download ATS-clean PDF",
                data=facade.resume_pdf(profile),
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
            st.download_button(
                "Download JSON Resume",
                data=json.dumps(facade.resume_json(profile), indent=2),
                file_name="resume.json",
                mime="application/json",
                use_container_width=True,
            )

        # --- Structured profile: the answers forms block on --- #
        st.divider()
        candidate = render_profile_builder(_current_candidate())

        # --- Autofill profile for the browser extension --- #
        st.divider()
        st.subheader("Browser autofill")
        st.markdown(
            "Export this profile once, import it into the **CareerAgent "
            "Autofill** extension, and application forms on Greenhouse, Lever, "
            "and Ashby will fill themselves when you click **Apply**. "
            "You always review and submit."
        )
        include_resume = st.checkbox("Include resume PDF", value=True)

        st.download_button(
            "Export autofill profile",
            data=facade.candidate_autofill_json(
                candidate, include_resume=include_resume
            ),
            file_name="careeragent_autofill_profile.json",
            mime="application/json",
            use_container_width=True,
        )
        answer_count = len(
            json.loads(
                facade.candidate_autofill_json(candidate, include_resume=False)
            ).get("answers", {})
        )
        st.caption(
            f"Includes {answer_count} pre-answered application question(s) "
            "(work authorization, salary, notice period). Fill more of your "
            "profile above to raise that number."
        )
        st.caption(
            "This file contains your personal details"
            + (" and resume" if include_resume else "")
            + " — it stays on your machine. Load the extension from the "
            "`extension/` folder via chrome://extensions (Developer mode → "
            "Load unpacked)."
        )

        if st.button("Next: Job Discovery", type="primary", use_container_width=True):
            st.session_state.page = "discovery"
            st.rerun()


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
        st.warning("Please complete onboarding first")
        return

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

        st.info(
            "Discovered jobs are deduplicated, enriched, and scored on the "
            "**Pipeline** screen.",
            icon=None,
        )

    elif mode == "Job boards (API)":
        st.caption(
            "Structured results from real job-board APIs. The first four need "
            "**no key and no account**. The Muse works keyless at a lower rate "
            "limit; Adzuna needs ADZUNA_APP_ID / ADZUNA_APP_KEY."
        )
        bcol1, bcol2 = st.columns([1, 2])
        with bcol1:
            provider = st.selectbox("Provider", facade.AGGREGATOR_PROVIDERS)
        with bcol2:
            keywords = st.text_input(
                "Keywords (optional)", placeholder="machine learning"
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

        if provider in ("remotive", "remoteok"):
            st.caption(
                f"{provider} requires attribution: link back to the original "
                "posting (no redirects) when sharing these results."
            )
        if provider in ("arbeitnow", "himalayas", "remoteok"):
            st.caption(
                "This provider has no keyword filter — it returns its current "
                "board, which is then deduped, scored, and filtered for you."
            )

    elif mode == "Web Search (fallback)":
        st.caption(
            "Fallback only. Search results are unstructured snippets, not real "
            "postings - no salary, dates, or reliable company data. Prefer a "
            "careers URL when you have one. Requires the local LLM."
        )
        if not st.session_state.llm_client:
            st.error("Please initialize the LLM from the sidebar to use search.")
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
                        if job not in st.session_state.selected_jobs:
                            st.session_state.selected_jobs.append(job)
                            st.session_state.storage.save_job_posting(job)
                            st.success(f"Added {job.title}")
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
                st.error("Please initialize the LLM from the sidebar first.")
                return
            with st.spinner("Fetching job details..."):
                try:
                    finder = JobFinder(st.session_state.llm_client)
                    job = finder.fetch_job_details(job_url)

                    if job:
                        st.session_state.selected_jobs.append(job)
                        st.session_state.storage.save_job_posting(job)
                        st.success("Job added!")
                        st.rerun()
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
                st.session_state.selected_jobs.append(job)
                st.session_state.storage.save_job_posting(job)
                st.success("Job added!")
                st.rerun()
            else:
                st.warning("Please fill all fields")

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
        st.warning("Please select jobs first")
        return

    if not st.session_state.llm_client:
        st.error("Please initialize LLM first")
        return

    # For each selected job
    for idx, job in enumerate(st.session_state.selected_jobs):
        with st.expander(f"{job.title} at {job.company}", expanded=True):
            st.write(f"**Company:** {job.company}")
            st.write(f"**URL:** {job.url or 'N/A'}")

            col1, col2 = st.columns(2)

            with col1:
                if st.button("Search Contacts", key=f"search_contacts_{idx}"):
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
                        if name and email:
                            contact = ContactCandidate(
                                name=name,
                                email=email,
                                role=role,
                                email_confidence="confirmed",
                                source="manual",
                                confidence_score=1.0,
                            )
                            if job.company not in st.session_state.found_contacts:
                                st.session_state.found_contacts[job.company] = []
                            st.session_state.found_contacts[job.company].append(contact)
                            st.success(f"Added {name}")
                            st.rerun()

            # Show found contacts
            if job.company in st.session_state.found_contacts:
                contacts = st.session_state.found_contacts[job.company]

                if contacts:
                    st.write("**Found Contacts:**")

                    for i, contact in enumerate(contacts):
                        col1, col2, col3 = st.columns([3, 2, 1])

                        with col1:
                            confidence_indicator = (
                                "High"
                                if contact.confidence_score > 0.7
                                else "Med"
                                if contact.confidence_score > 0.4
                                else "Low"
                            )
                            st.write(
                                f"[{confidence_indicator}] **{contact.name}** - {contact.role or 'Unknown'}"
                            )

                        with col2:
                            if contact.email:
                                badge = (
                                    "[Verified]"
                                    if contact.email_confidence == "confirmed"
                                    else "[Unverified]"
                                )
                                st.caption(f"{badge} {contact.email}")
                            else:
                                st.caption("No email found")

                        with col3:
                            st.caption(f"{int(contact.confidence_score * 100)}%")

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
        st.warning("Please select jobs first")
        return

    if not st.session_state.llm_client:
        st.error("Please initialize LLM first")
        return

    # Job selector
    job_titles = [
        f"{job.title} at {job.company}" for job in st.session_state.selected_jobs
    ]
    if not job_titles:
        st.error("No jobs selected")
        return

    selected_idx = st.selectbox(
        "Select Job", range(len(job_titles)), format_func=lambda x: job_titles[x]
    )
    current_job = st.session_state.selected_jobs[selected_idx]

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
            )
            selected_contact = contacts[selected_contact_idx]

            recipient_name = selected_contact.name
            recipient_email = selected_contact.email
        else:
            recipient_name = st.text_input("Recipient Name", value="Hiring Manager")
            recipient_email = st.text_input(
                "Recipient Email", placeholder="hiring@company.com"
            )

    with col2:
        st.subheader("Draft")

        # Generation controls
        col_a, col_b, col_c = st.columns(3)

        with col_a:
            angle = st.selectbox("Angle", ["technical", "impact", "product"])

        with col_b:
            if st.button("Generate Email", type="primary"):
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
                        st.session_state.current_draft = draft
                        st.rerun()
                    except Exception as e:
                        st.error(f"Generation failed: {e}")

        with col_c:
            if st.session_state.current_draft:
                if st.button("Regenerate"):
                    with st.spinner("Regenerating..."):
                        try:
                            engine = PersonalizationEngine(st.session_state.llm_client)
                            draft = engine.regenerate_email_with_angle(
                                st.session_state.current_draft, angle=angle
                            )
                            draft.recipient_email = recipient_email
                            st.session_state.current_draft = draft
                            st.rerun()
                        except Exception as e:
                            st.error(f"Regeneration failed: {e}")

        # Show draft
        if st.session_state.current_draft:
            draft = st.session_state.current_draft

            # Editable subject
            subject = st.text_input("Subject", value=draft.subject, key="draft_subject")

            # Editable body
            body = st.text_area("Body", value=draft.body, height=300, key="draft_body")

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

            st.session_state.compliance_ok = False
            if st.button("Run compliance check"):
                try:
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
                    gate_draft = EmailDraft(
                        subject=subject,
                        body=body,
                        recipient_email=recipient_email,
                        company=current_job.company,
                    )
                    decision = facade.compliance_gate(gate_draft, cfg, lia)
                    if decision.allowed:
                        st.session_state.compliance_ok = True
                        st.success("Compliant. A footer was added:")
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
                    elif not st.session_state.get("compliance_ok"):
                        st.error("Run the compliance check first (required to send).")
                    else:
                        with st.spinner("Creating Gmail draft..."):
                            try:
                                if not st.session_state.gmail_client:
                                    gmail = GmailDraftClient()
                                    gmail.authenticate()
                                    st.session_state.gmail_client = gmail

                                draft_id = st.session_state.gmail_client.create_draft(
                                    to=recipient_email, subject=subject, body=body
                                )

                                draft.gmail_draft_id = draft_id
                                st.session_state.draft_history.append(draft)
                                st.session_state.storage.save_email_draft(draft)

                                st.success(f"Draft created: {draft_id}")
                            except Exception as e:
                                st.error(f"Gmail Error: {e}")

            with col2:
                if st.button("Save Local", use_container_width=True):
                    st.session_state.draft_history.append(draft)
                    st.session_state.storage.save_email_draft(draft)
                    st.success("Draft saved!")

            with col3:
                if st.button("WhatsApp Link", use_container_width=True):
                    engine = PersonalizationEngine(st.session_state.llm_client)
                    try:
                        wa_draft = engine.generate_whatsapp_message(
                            st.session_state.cv_profile, current_job, phone=None
                        )
                        st.session_state.current_wa_draft = wa_draft
                        st.session_state.storage.save_whatsapp_draft(wa_draft)
                    except Exception as e:
                        st.error(f"WhatsApp Error: {e}")

            if "current_wa_draft" in st.session_state:
                st.info("WhatsApp Draft:")
                st.code(st.session_state.current_wa_draft.message)
                st.markdown(
                    f"[Open in WhatsApp]({st.session_state.current_wa_draft.click_to_chat_url})"
                )


# Page 5: Export
def page_export():
    """Export screen"""
    st.title("Export & Logs")

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
                zip_path = st.session_state.storage.create_export_zip()
                st.success(f"Export created at: {zip_path}")
            except Exception as e:
                st.error(f"Export failed: {e}")

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


def page_pipeline():
    """Pipeline screen - API-first ingestion, scored matches, and tracking."""
    st.title("Pipeline")
    st.markdown(
        "Pull jobs directly from company ATS APIs, see explainable match "
        "scores against your CV, and track applications through the funnel."
    )

    # --- Ingest from an ATS public API --- #
    st.subheader("Ingest jobs from a company ATS")
    col1, col2, col3 = st.columns([2, 2, 1])
    with col1:
        slug = st.text_input(
            "Board slug",
            placeholder="e.g. the company's Greenhouse/Lever/Ashby board name",
        )
    with col2:
        ats_type = st.selectbox("ATS", ["greenhouse", "lever", "ashby"])
    with col3:
        company = st.text_input("Company name", placeholder="Display name")

    if st.button("Ingest", type="primary", disabled=not slug):
        with st.spinner(f"Pulling {slug} jobs from {ats_type}..."):
            try:
                result = facade.ingest_ats(ats_type, slug, company)
                if result.errors:
                    st.error(f"Ingestion error: {result.errors[0]}")
                else:
                    st.success(
                        f"Fetched {result.fetched}, stored {result.upserted} jobs."
                    )
                    if st.session_state.cv_profile:
                        facade.refresh_matches(st.session_state.cv_profile)
            except Exception as e:
                st.error(f"Ingestion failed: {e}")

    if st.session_state.cv_profile and st.button("Re-score matches"):
        with st.spinner("Dedup + score against your CV..."):
            facade.refresh_matches(st.session_state.cv_profile)
            st.success("Matches refreshed.")

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

            # --- Apply: open the real form, extension autofills it --- #
            target = facade.apply_target(job["id"])
            if target.get("url"):
                acol1, acol2 = st.columns([1, 1])
                with acol1:
                    st.link_button("Apply", target["url"], use_container_width=True)
                with acol2:
                    if st.button(
                        "I applied",
                        key=f"applied_{job['id']}",
                        use_container_width=True,
                    ):
                        res = facade.mark_applied(job["id"], st.session_state.cv_id)
                        if res["ok"]:
                            st.success(f"Tracked as {res['status']}.")
                            st.rerun()
                        else:
                            st.warning(res["error"])
                if target.get("autofill_supported"):
                    st.caption(f"✓ {target['note']}")
                else:
                    st.caption(target.get("note", ""))
            else:
                st.caption("No application link recorded for this posting.")

            if st.button("Add to pipeline", key=f"track_{job['id']}"):
                res = facade.add_to_pipeline(job["id"], st.session_state.cv_id)
                if res["ok"]:
                    st.success("Added to pipeline (Saved).")
                    st.rerun()
                else:
                    st.warning(res["error"])

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
    ]
    next_status = {
        "saved": "applied",
        "applied": "screening",
        "screening": "interview",
        "interview": "offer",
    }
    cols = st.columns(len(statuses))
    for col, status in zip(cols, statuses):
        with col:
            cards = board.get(status, [])
            st.markdown(f"**{status.title()}** ({len(cards)})")
            for card in cards:
                st.caption(f"{card['title']} — {card['company']}")
                if status in next_status:
                    if st.button(
                        f"→ {next_status[status]}",
                        key=f"adv_{card['application_id']}",
                    ):
                        facade.advance_application(
                            card["application_id"], next_status[status]
                        )
                        st.rerun()

    if f:
        st.divider()
        st.subheader("Funnel")
        m = st.columns(5)
        m[0].metric("Total", f["total"])
        m[1].metric("Applied", f["reached"].get("applied", 0))
        m[2].metric("Screening", f["reached"].get("screening", 0))
        m[3].metric("Interview", f["reached"].get("interview", 0))
        m[4].metric("Offer", f["reached"].get("offer", 0))


# Router
render_sidebar()

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
