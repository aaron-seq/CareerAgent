"""
Job discovery using DuckDuckGo search (free, no API key)
Finds job postings from web search results
"""

from duckduckgo_search import DDGS
from typing import List, Optional
from .models import JobPosting, SearchQuery
from .llm import LocalLLMClient
from .prompts import JOB_PARSE_PROMPT
import requests
from bs4 import BeautifulSoup
import time


class JobFinder:
    """Search for job postings using DuckDuckGo"""

    def __init__(self, llm_client: LocalLLMClient):
        self.llm = llm_client
        self.ddgs = DDGS()

    def search_jobs(self, query: SearchQuery) -> List[JobPosting]:
        """Search for jobs using DuckDuckGo"""
        # Build search query
        search_query = self._build_search_query(query)

        try:
            # Use DuckDuckGo text search
            results = self.ddgs.text(search_query, max_results=query.max_results)

            job_postings = []

            for result in results:
                try:
                    # Filter for job-related results
                    if self._is_job_related(result):
                        job = self._parse_search_result(result)
                        if job:
                            job_postings.append(job)

                    # Rate limiting
                    time.sleep(0.5)

                except Exception as e:
                    print(f"Failed to parse result: {e}")
                    continue

            return job_postings

        except Exception as e:
            raise Exception(f"Job search failed: {str(e)}")

    def _build_search_query(self, query: SearchQuery) -> str:
        """Build optimized search query for jobs"""
        parts = [query.query]

        if query.location:
            parts.append(query.location)

        if query.remote:
            parts.append("remote")

        # Add job-related keywords
        parts.append("job OR careers OR hiring")

        return " ".join(parts)

    def _is_job_related(self, result: dict) -> bool:
        """Check if search result is job-related"""
        job_keywords = [
            "job",
            "career",
            "hiring",
            "position",
            "opening",
            "apply",
            "linkedin.com/jobs",
            "indeed",
            "glassdoor",
            "greenhouse.io",
            "lever.co",
            "workday",
            "full-time",
            "part-time",
        ]

        text = f"{result.get('title', '')} {result.get('body', '')} {result.get('href', '')}".lower()

        return any(keyword in text for keyword in job_keywords)

    def _parse_search_result(self, result: dict) -> Optional[JobPosting]:
        """Parse search result into JobPosting"""
        title = result.get("title", "")
        snippet = result.get("body", "")
        url = result.get("href", "")

        # Extract company name (basic heuristic)
        company = self._extract_company_name(title, url)

        return JobPosting(
            title=title,
            company=company,
            url=url,
            description=snippet,
            relevance_score=0.5,  # Default score
        )

    def _extract_company_name(self, title: str, url: str) -> str:
        """Extract company name from title or URL"""
        # Try to extract from title (e.g., "Software Engineer at Google")
        if " at " in title:
            parts = title.split(" at ")
            if len(parts) > 1:
                return parts[-1].strip()

        # Try to extract from URL domain
        try:
            from urllib.parse import urlparse

            domain = urlparse(url).netloc
            # Remove common prefixes
            domain = (
                domain.replace("www.", "").replace("jobs.", "").replace("careers.", "")
            )
            # Take first part before .com
            company = domain.split(".")
            return company[0].capitalize()
        except:
            pass

        return "Unknown Company"

    def fetch_job_details(self, job_url: str) -> Optional[JobPosting]:
        """Fetch and parse full job posting from URL"""
        try:
            # Fetch page content
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            response = requests.get(job_url, headers=headers, timeout=10)
            response.raise_for_status()

            # Parse HTML
            soup = BeautifulSoup(response.text, "html.parser")

            # Extract text (remove scripts and styles)
            for script in soup(["script", "style"]):
                script.decompose()

            text = soup.get_text(separator="\n", strip=True)

            # Limit text length for LLM
            text = text[:5000]

            # Use LLM to parse job posting
            prompt = JOB_PARSE_PROMPT.format(job_text=text, job_url=job_url)

            job_data = self.llm.generate_json(prompt, temperature=0.2)
            job_data["url"] = job_url
            job_data["description"] = text[:1000]  # Store snippet

            return JobPosting(**job_data)

        except Exception as e:
            print(f"Failed to fetch job details from {job_url}: {e}")
            return None
