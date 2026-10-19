"""
Contact discovery using web search
Generates email permutations when exact email not found
"""

import logging
import re
import time
from typing import List, Optional

from duckduckgo_search import DDGS

from .llm import LocalLLMClient
from .models import ContactCandidate
from .outreach.verification import verify_email
from .prompts import CONTACT_SEARCH_QUERIES_PROMPT

logger = logging.getLogger(__name__)


def _valid_contact_email(email: str) -> bool:
    local = email.partition("@")[0]
    return (
        verify_email(email, resolver=lambda _: None, require_mx=False).syntax_ok
        and not local.startswith(".")
        and not local.endswith(".")
        and ".." not in local
        and len(local) <= 64
    )


def create_manual_contact(name: str, email: str, role: str = "") -> ContactCandidate:
    """Validate supplied facts locally; syntax never verifies a mailbox."""
    name, email, role = name.strip(), email.strip(), role.strip()
    if not name:
        raise ValueError("Enter the contact's name.")
    if not _valid_contact_email(email):
        raise ValueError("Enter a valid email address, such as name@company.com.")
    return ContactCandidate(
        name=name,
        email=email,
        role=role or None,
        email_confidence="unknown",
        source="manual",
    )


def generate_contact_patterns(
    first_name: str, last_name: str, domain: str
) -> list[ContactCandidate]:
    """Generate unverified patterns only for an explicitly supplied domain."""
    first_name, last_name, domain = (
        first_name.strip(),
        last_name.strip(),
        domain.strip().lower(),
    )
    if not first_name or not last_name:
        raise ValueError("Enter both a first name and a last name.")
    if not verify_email(
        f"contact@{domain}", resolver=lambda _: None, require_mx=False
    ).syntax_ok:
        raise ValueError(
            "Enter the employer's known email domain, such as company.com, "
            "without an email address, URL, path or port."
        )
    first, last = first_name.lower(), last_name.lower()
    addresses = [
        f"{first}.{last}@{domain}",
        f"{first}@{domain}",
        f"{first}{last}@{domain}",
    ]
    if any(not _valid_contact_email(address) for address in addresses):
        raise ValueError(
            "These names do not form a supported email pattern. Add a known "
            "email address as a manual contact instead."
        )
    return [
        ContactCandidate(
            name=f"{first_name} {last_name}",
            email=address,
            email_confidence="guessed",
            source="email_permutation",
            confidence_score=0.7 - index * 0.1,
        )
        for index, address in enumerate(addresses)
    ]


def merge_contacts(
    existing: list[ContactCandidate], incoming: list[ContactCandidate]
) -> list[ContactCandidate]:
    """Keep existing reviewed records and append only new contact identities."""
    contacts = list(existing)
    identities = {
        (contact.email or contact.linkedin or contact.name).strip().casefold()
        for contact in existing
    }
    for contact in incoming:
        identity = (
            (contact.email or contact.linkedin or contact.name).strip().casefold()
        )
        if identity not in identities:
            contacts.append(contact)
            identities.add(identity)
    return contacts


class ContactFinder:
    """Find hiring managers and generate email permutations"""

    def __init__(self, llm_client: LocalLLMClient):
        self.llm = llm_client
        self.ddgs = DDGS()

    def find_contacts(
        self, company_name: str, job_title: str, max_results: int = 5
    ) -> List[ContactCandidate]:
        """Search for potential contacts at company"""

        # Generate search queries using LLM
        role_keyword = self._extract_role_keyword(job_title)

        prompt = CONTACT_SEARCH_QUERIES_PROMPT.format(
            company_name=company_name, job_title=job_title, role_keyword=role_keyword
        )

        try:
            query_data = self.llm.generate_json(prompt, temperature=0.3)
            queries = self._search_queries(query_data)
            if not queries:
                raise ValueError("The model did not return text search queries.")
        except Exception:
            # Fallback to default queries
            queries = [
                f"{company_name} hiring manager {role_keyword}",
                f"site:linkedin.com/in {company_name} recruiter",
                f"{company_name} engineering manager",
            ]

        contacts = []
        seen_names = set()

        for index, query in enumerate(queries[:3]):  # Limit to 3 queries
            try:
                results = self.ddgs.text(query, max_results=5)

                for result in results:
                    contact = self._extract_contact_from_result(result, company_name)

                    if contact and contact.name not in seen_names:
                        contacts.append(contact)
                        seen_names.add(contact.name)

                    if len(contacts) >= max_results:
                        break

                time.sleep(0.5)  # Rate limiting

            except Exception as e:
                logger.warning(
                    "Contact search query %d failed; skipping", index + 1, exc_info=e
                )
                continue

            if len(contacts) >= max_results:
                break

        return contacts

    @staticmethod
    def _search_queries(payload: object) -> list[str]:
        """Accept the query envelope and legacy keyed/list responses safely."""
        if isinstance(payload, dict):
            values = payload.get("queries")
            if values is None:
                values = list(payload.values())
        else:
            values = payload
        if not isinstance(values, list):
            return []
        return [
            query.strip()
            for query in values
            if isinstance(query, str) and query.strip()
        ]

    def generate_email_permutations(
        self, first_name: str, last_name: str, domain: str
    ) -> List[ContactCandidate]:
        """Compatibility entry point for locally validated, unverified patterns."""
        return generate_contact_patterns(first_name, last_name, domain)

    def _extract_role_keyword(self, job_title: str) -> str:
        """Extract key role keyword from job title"""
        keywords = [
            "engineer",
            "developer",
            "manager",
            "lead",
            "scientist",
            "analyst",
            "designer",
        ]

        title_lower = job_title.lower()
        for keyword in keywords:
            if keyword in title_lower:
                return keyword

        # Default to first significant word
        words = job_title.split()
        return words[0] if words else "manager"

    def _extract_contact_from_result(
        self, result: dict, company_name: str
    ) -> Optional[ContactCandidate]:
        """Extract contact info from search result"""

        title = result.get("title", "")
        snippet = result.get("body", "")
        url = result.get("href", "")

        # Extract name (basic heuristic)
        name = self._extract_name_from_title(title)

        if not name:
            return None

        # Extract email if present
        email = self._extract_email(f"{title} {snippet}")

        # Determine role
        role = self._extract_role(title, snippet)

        # LinkedIn detection
        linkedin_url = url if "linkedin.com" in url else None

        # Calculate confidence
        confidence = self._calculate_confidence(
            email, linkedin_url, company_name, snippet
        )

        return ContactCandidate(
            name=name,
            role=role,
            email=email,
            email_confidence="confirmed" if email else "unknown",
            linkedin=linkedin_url,
            source=url,
            confidence_score=confidence,
        )

    # Words that show up capitalized in recruiting-page titles but are never
    # part of a person's name (team labels, role words, generic CTAs). The
    # capitalized-first-letter heuristic below can't tell "Jane Smith" from
    # "Hiring Committee" without this.
    _NON_NAME_WORDS = {
        "hiring",
        "team",
        "committee",
        "talent",
        "acquisition",
        "recruiting",
        "recruiter",
        "careers",
        "jobs",
        "apply",
        "now",
        "join",
        "our",
        "we",
        "human",
        "resources",
        "people",
        "operations",
        "staffing",
        "department",
        "group",
        "manager",
        "director",
        "engineer",
        "developer",
        "lead",
        "senior",
        "staff",
        "officer",
        "executive",
        "specialist",
        "coordinator",
        "analyst",
        "associate",
        "president",
        "chief",
        "head",
        "position",
        "opening",
        "opportunity",
        "role",
        "job",
    }

    def _looks_like_name(self, candidate: str) -> bool:
        """Reject obvious non-names: shouting-case labels and role/recruiting words."""
        words = candidate.split()
        if not words:
            return False
        # "TALENT ACQUISITION" / "ENGINEERING MANAGER" -- all-caps titles are
        # team or role labels, not how a real name is capitalized in a title.
        if candidate.isupper():
            return False
        if any(w.strip(",.").lower() in self._NON_NAME_WORDS for w in words):
            return False
        return True

    def _extract_name_from_title(self, title: str) -> Optional[str]:
        """Extract person name from title"""
        # LinkedIn pattern: "Name - Position | LinkedIn"
        if "|" in title and "LinkedIn" in title:
            parts = title.split("|")[0].strip()
            if "-" in parts:
                name = parts.split("-")[0].strip()
                return name if self._looks_like_name(name) else None

        # General pattern: look for capitalized words
        words = title.split()
        if len(words) >= 2:
            # Check if first two words are capitalized (likely a name)
            if words[0][0].isupper() and words[1][0].isupper():
                candidate = f"{words[0]} {words[1]}"
                if self._looks_like_name(candidate):
                    return candidate

        return None

    def _extract_email(self, text: str) -> Optional[str]:
        """Extract email address from text"""
        email_pattern = r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"
        matches = re.findall(email_pattern, text)
        return matches[0] if matches else None

    def _extract_role(self, title: str, snippet: str) -> Optional[str]:
        """Extract job role/title"""
        role_keywords = [
            "Manager",
            "Director",
            "Lead",
            "Engineer",
            "Recruiter",
            "VP",
            "Head",
            "Chief",
            "Senior",
            "Principal",
        ]

        combined = f"{title} {snippet}"
        for keyword in role_keywords:
            if keyword in combined:
                # Try to extract full title
                words = title.split()
                for i, word in enumerate(words):
                    if keyword in word and i > 0:
                        return " ".join(words[max(0, i - 1) : i + 2])

        return "Unknown Role"

    def _calculate_confidence(
        self, email: Optional[str], linkedin: Optional[str], company: str, snippet: str
    ) -> float:
        """Calculate confidence score for contact"""
        score = 0.3  # Base score

        if email:
            score += 0.4
        if linkedin:
            score += 0.2
        if company.lower() in snippet.lower():
            score += 0.1

        return min(score, 1.0)
