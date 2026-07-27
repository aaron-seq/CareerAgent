"""
CV parser with PDF extraction and LLM-based structuring
Supports both PDF and plain text input
"""

from typing import List, Optional

import pdfplumber
import PyPDF2

from .llm import LocalLLMClient
from .models import CVProfile
from .prompts import CV_PARSE_PROMPT


class CVParser:
    """Parse CV from PDF or text and extract structured data"""

    def __init__(self, llm_client: LocalLLMClient):
        self.llm = llm_client

    def parse_pdf(self, pdf_path: str) -> CVProfile:
        """Parse CV from PDF file"""
        text = self._extract_text_from_pdf(pdf_path)
        return self.parse_text(text, links=self._extract_hyperlinks_from_pdf(pdf_path))

    def parse_text(self, cv_text: str, links: Optional[List[str]] = None) -> CVProfile:
        """Parse CV from plain text using LLM.

        ``links`` carries URLs recovered from the PDF's annotation layer. They
        are appended *after* truncation so a long CV can never push the
        contact links out of the prompt.
        """
        if not cv_text or len(cv_text.strip()) < 50:
            raise ValueError("CV text is too short or empty")

        # Truncate text to avoid token limits and reduce latency (approx 3000 tokens)
        if len(cv_text) > 12000:
            cv_text = cv_text[:12000]

        if links:
            listed = "\n".join(f"- {url}" for url in links)
            cv_text += (
                "\n\nDOCUMENT LINKS (real URLs behind the hyperlink labels above; "
                "the visible text shows only labels such as 'Github'):\n" + listed
            )

        # Use LLM to extract structured data
        prompt = CV_PARSE_PROMPT.format(cv_text=cv_text)

        try:
            print(f"DEBUG: Sending {len(cv_text)} chars to LLM...")
            cv_data = self.llm.generate_json(prompt, temperature=0.2)
            print("DEBUG: LLM response received and parsed.")
            cv_data["raw_text"] = cv_text

            # Validate with Pydantic
            profile = CVProfile(**cv_data)
            return profile

        except Exception as e:
            print(f"ERROR: CV Parsing failed: {e}")
            # Fallback: create minimal profile with raw text
            return CVProfile(
                raw_text=cv_text,
                summary=f"CV parsing failed: {str(e)}. Using raw text.",
            )

    def _extract_text_from_pdf(self, pdf_path: str) -> str:
        """Extract text from PDF using multiple methods"""
        text = ""

        # Try pdfplumber first (better for complex layouts)
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n\n"

            if text.strip():
                return text.strip()
        except Exception as e:
            print(f"pdfplumber extraction failed: {e}")

        # Fallback to PyPDF2
        try:
            with open(pdf_path, "rb") as file:
                pdf_reader = PyPDF2.PdfReader(file)
                for page in pdf_reader.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n\n"

            if text.strip():
                return text.strip()
        except Exception as e:
            print(f"PyPDF2 extraction failed: {e}")

        raise ValueError(
            "Could not extract text from PDF. File may be scanned image or corrupted."
        )

    def _extract_hyperlinks_from_pdf(self, pdf_path: str) -> List[str]:
        """Recover URLs from the PDF's link-annotation layer.

        A CV usually renders contact links as anchor text -- the visible word
        is "Github" while the URL lives only in the annotation. extract_text()
        drops that layer, so without this the model is asked for a github
        field with no github URL anywhere in its input, and fills the gap by
        inventing one from the candidate's name. Fabricated credentials are a
        hard no (CLAUDE.md guardrail 4), so the real URLs must reach the model.
        """
        urls: List[str] = []
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages:
                    for link in page.hyperlinks or []:
                        uri = link.get("uri")
                        if uri and uri not in urls:
                            urls.append(uri)
        except Exception as e:  # non-fatal: parsing still works without links
            print(f"hyperlink extraction failed: {e}")

        return urls

    def extract_links(self, cv_profile: CVProfile) -> list:
        """Extract all URLs from CV profile"""
        links = []

        if cv_profile.github:
            links.append(cv_profile.github)
        if cv_profile.linkedin:
            links.append(cv_profile.linkedin)
        if cv_profile.portfolio:
            links.append(cv_profile.portfolio)

        for project in cv_profile.projects:
            if project.link:
                links.append(project.link)
            if project.github:
                links.append(project.github)

        return links

    def extract_metrics(self, cv_profile: CVProfile) -> list:
        """Extract all quantifiable metrics from CV"""
        metrics = []

        for exp in cv_profile.experiences:
            metrics.extend(exp.metrics)

        for project in cv_profile.projects:
            if project.impact:
                metrics.append(project.impact)

        return metrics
