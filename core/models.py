"""
Pydantic data models for CareerAgent
All type-safe data structures for CV, jobs, contacts, emails, WhatsApp
"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, HttpUrl, validator
from datetime import datetime
import re


class Experience(BaseModel):
    """Single work experience entry from CV"""

    title: str
    company: str
    duration: str
    achievements: List[str] = []
    metrics: List[str] = []
    technologies: List[str] = []


class Project(BaseModel):
    """Project with links and description"""

    name: str
    description: str
    technologies: List[str] = []
    link: Optional[str] = None
    github: Optional[str] = None
    impact: Optional[str] = None


class CVProfile(BaseModel):
    """Parsed CV structure with all extracted information"""

    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    linkedin: Optional[str] = None
    github: Optional[str] = None
    portfolio: Optional[str] = None
    summary: Optional[str] = None
    experiences: List[Experience] = []
    projects: List[Project] = []
    skills: List[str] = []
    education: List[str] = []
    raw_text: str = ""


class JobPosting(BaseModel):
    """Job post structure with requirements and tech stack"""

    title: str
    company: str
    location: Optional[str] = None
    url: Optional[str] = None
    description: str = ""
    requirements: List[str] = []
    nice_to_have: List[str] = []
    tech_stack: List[str] = []
    problems: List[str] = []
    benefits: List[str] = []
    salary_range: Optional[str] = None
    relevance_score: float = 0.0


class ContactCandidate(BaseModel):
    """Potential contact person with email confidence"""

    name: str
    role: Optional[str] = None
    email: Optional[str] = None
    email_confidence: str = "unknown"  # confirmed, guessed, unknown
    linkedin: Optional[str] = None
    source: str = ""
    confidence_score: float = 0.0


class PersonalizationPlan(BaseModel):
    """Strategic plan for email personalization"""

    anchor_project: Optional[Project] = None
    technical_hook: str = ""
    impact_hook: str = ""
    company_hook: str = ""
    shared_technologies: List[str] = []
    relevant_metrics: List[str] = []
    angle: str = "technical"  # technical, impact, product


class EmailDraft(BaseModel):
    """Generated email draft with metadata"""

    subject: str
    body: str
    recipient_email: Optional[str] = None
    recipient_name: Optional[str] = None
    job_title: str = ""
    company: str = ""
    personalization_plan: Optional[PersonalizationPlan] = None
    word_count: int = 0
    created_at: datetime = Field(default_factory=datetime.now)
    gmail_draft_id: Optional[str] = None

    @validator("word_count", always=True)
    def calculate_word_count(cls, v, values):
        if "body" in values:
            return len(values["body"].split())
        return v


class WhatsAppDraft(BaseModel):
    """WhatsApp message template with click-to-chat URL"""

    message: str
    click_to_chat_url: str
    recipient_phone: Optional[str] = None
    job_title: str = ""
    company: str = ""
    character_count: int = 0
    created_at: datetime = Field(default_factory=datetime.now)

    @validator("character_count", always=True)
    def calculate_character_count(cls, v, values):
        if "message" in values:
            return len(values["message"])
        return v


class QualityCheck(BaseModel):
    """Draft quality validation results"""

    has_metric: bool = False
    has_project_link: bool = False
    has_company_hook: bool = False
    has_clear_cta: bool = False
    under_word_limit: bool = False
    no_emojis: bool = False
    no_bullet_dashes: bool = False
    score: float = 0.0
    issues: List[str] = []
    passed: bool = False

    @validator("score", always=True)
    def calculate_score(cls, v, values):
        checks = [
            values.get("has_metric", False),
            values.get("has_project_link", False),
            values.get("has_company_hook", False),
            values.get("has_clear_cta", False),
            values.get("under_word_limit", False),
            values.get("no_emojis", False),
            values.get("no_bullet_dashes", False),
        ]
        return sum(checks) / len(checks) * 100

    @validator("passed", always=True)
    def check_passed(cls, v, values):
        return values.get("score", 0) >= 70.0


class SearchQuery(BaseModel):
    """Job search query with filters"""

    query: str
    location: Optional[str] = None
    remote: bool = False
    last_n_days: Optional[int] = 30
    max_results: int = 20
