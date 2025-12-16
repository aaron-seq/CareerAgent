"""
CareerAgent - Main Streamlit Application
Complete UI with 5 screens: Onboarding, Discovery, Contacts, Draft Studio, Export
"""

import streamlit as st
import os
from pathlib import Path

# Core imports
from core.llm import LocalLLMClient
from core.cv_parser import CVParser
from core.job_finder import JobFinder
from core.contact_finder import ContactFinder
from core.personalization import PersonalizationEngine
from core.gmail_drafts import GmailDraftClient
from core.whatsapp import WhatsAppClient
from core.validators import DraftValidator
from core.storage import LocalStorage
from core.models import SearchQuery, CVProfile, JobPosting, ContactCandidate


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


init_session_state()


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
        st.subheader("Preferences")

        target_roles = st.text_area(
            "Target Roles (one per line)",
            value="Senior Software Engineer\nML Engineer\nFull Stack Developer",
            height=100,
        )

        target_locations = st.text_area(
            "Target Locations (one per line)",
            value="Remote\nSan Francisco\nBerlin",
            height=100,
        )

        industries = st.multiselect(
            "Preferred Industries",
            ["Tech/Software", "AI/ML", "Finance", "Healthcare", "E-commerce", "Other"],
            default=["Tech/Software", "AI/ML"],
        )

        seniority = st.select_slider(
            "Seniority Level",
            options=["Junior", "Mid-level", "Senior", "Staff", "Principal"],
            value="Senior",
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
            st.json(profile.dict())

        if st.button("Next: Job Discovery", type="primary", use_container_width=True):
            st.session_state.page = "discovery"
            st.rerun()


# Page 2: Job Discovery
def page_discovery():
    """Job discovery screen"""
    st.title("Job Discovery")
    st.markdown("Find relevant job postings using DuckDuckGo")

    if not st.session_state.llm_client:
        st.error("Please initialize LLM first")
        return

    if not st.session_state.cv_profile:
        st.warning("Please complete onboarding first")
        return

    # Search mode
    mode = st.radio(
        "Search Mode",
        ["Web Search (DuckDuckGo)", "Paste Job URL", "Paste Job Description"],
        horizontal=True,
    )

    st.divider()

    if mode == "Web Search (DuckDuckGo)":
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

                    if st.button(f"Select This Job", key=f"select_{i}"):
                        if job not in st.session_state.selected_jobs:
                            st.session_state.selected_jobs.append(job)
                            st.session_state.storage.save_job_posting(job)
                            st.success(f"Added {job.title}")
                            st.rerun()

    elif mode == "Paste Job URL":
        job_url = st.text_input(
            "Job Post URL", placeholder="https://company.com/careers/job-id"
        )

        if st.button("Fetch Job Details", type="primary"):
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
                if st.button(f"Search Contacts", key=f"search_contacts_{idx}"):
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

            if st.button(f"Generate Permutations", key=f"gen_perm_{idx}"):
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

            # Actions
            col1, col2, col3 = st.columns(3)

            with col1:
                if st.button("Create Gmail Draft", use_container_width=True):
                    if not recipient_email:
                        st.error("Please enter recipient email")
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


# Router
render_sidebar()

if st.session_state.get("page") == "onboarding":
    page_onboarding()
elif st.session_state.get("page") == "discovery":
    page_discovery()
elif st.session_state.get("page") == "contacts":
    page_contacts()
elif st.session_state.get("page") == "draft":
    page_draft_studio()
elif st.session_state.get("page") == "export":
    page_export()

if __name__ == "__main__":
    pass
