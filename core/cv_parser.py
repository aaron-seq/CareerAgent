"""
CV parser with PDF extraction and LLM-based structuring
Supports both PDF and plain text input
"""

import PyPDF2
import pdfplumber
from typing import Optional
from .models import CVProfile
from .llm import LocalLLMClient
from .prompts import CV_PARSE_PROMPT


class CVParser:
    """Parse CV from PDF or text and extract structured data"""

    def __init__(self, llm_client: LocalLLMClient):
        self.llm = llm_client

    def parse_pdf(self, pdf_path: str) -> CVProfile:
        """Parse CV from PDF file"""
        text = self._extract_text_from_pdf(pdf_path)
        return self.parse_text(text)

    def parse_text(self, cv_text: str) -> CVProfile:
        """Parse CV from plain text using LLM"""
        if not cv_text or len(cv_text.strip()) < 50:
            raise ValueError("CV text is too short or empty")

        # Truncate text to avoid token limits and reduce latency (approx 3000 tokens)
        if len(cv_text) > 12000:
            cv_text = cv_text[:12000]

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
