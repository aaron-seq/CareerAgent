"""Local CV content readiness and transparent job-skill coverage.

``readiness_score`` is a fixed, 100-point *content completeness* checklist:
name 10, email 15, skills 15, experience/projects 25, supporting details 15,
education 10, complete entries 10. It does not inspect the exported layout or
predict an ATS vendor's ranking, interview, or hiring decision. Projects count
as valid evidence; numbers, a phone, and a photograph are never required.

``job_match.score`` is exact recognized-skill coverage, not semantic similarity
or a commercial ATS score. Its denominator is the useful job signals reported
in ``matched`` and ``missing``. Reordering/repeating facts cannot raise it.
"""

from __future__ import annotations

import re
from typing import Any

from ..models import CVProfile, JobPosting

# Aliases are deliberately explicit: no fuzzy matching, stemming or substring
# overlap (Java != JavaScript, C != C++ != C#, Node.js != JavaScript).
_SKILL_ALIASES: dict[str, tuple[str, ...]] = {
    "python": ("python",),
    "java": ("java",),
    "javascript": ("javascript", "java script", "js"),
    "typescript": ("typescript", "type script", "ts"),
    "c++": ("c++", "cplusplus"),
    "c#": ("c#", "csharp", "c sharp"),
    "c": ("c programming", "c language", "programming in c"),
    "go": ("golang", "go language", "go programming"),
    "rust": ("rust",),
    "ruby": ("ruby",),
    "php": ("php",),
    "swift": ("swift",),
    "kotlin": ("kotlin",),
    "scala": ("scala",),
    "r": ("r language", "r programming"),
    "sql": ("sql", "structured query language"),
    "html": ("html", "html5"),
    "css": ("css", "css3"),
    "bash": ("bash",),
    "powershell": ("powershell",),
    "node.js": ("node.js", "nodejs", "node js"),
    "react": ("react", "react.js", "reactjs"),
    "angular": ("angular", "angularjs"),
    "vue": ("vue", "vue.js", "vuejs"),
    "next.js": ("next.js", "nextjs", "next js"),
    "django": ("django",),
    "flask": ("flask",),
    "fastapi": ("fastapi", "fast api"),
    "spring": ("spring boot", "spring framework"),
    ".net": (".net", "dotnet", "asp.net"),
    "graphql": ("graphql",),
    "rest api": ("rest api", "rest apis", "restful api", "restful apis"),
    "postgresql": ("postgresql", "postgres", "postgre sql"),
    "mysql": ("mysql",),
    "sqlite": ("sqlite",),
    "mongodb": ("mongodb", "mongo db"),
    "redis": ("redis",),
    "elasticsearch": ("elasticsearch", "elastic search"),
    "docker": ("docker",),
    "kubernetes": ("kubernetes", "k8s"),
    "terraform": ("terraform",),
    "ansible": ("ansible",),
    "aws": ("aws", "amazon web services"),
    "azure": ("azure", "microsoft azure"),
    "gcp": ("gcp", "google cloud", "google cloud platform"),
    "linux": ("linux",),
    "git": ("git",),
    "github actions": ("github actions",),
    "jenkins": ("jenkins",),
    "ci/cd": ("ci/cd", "ci cd", "continuous integration", "continuous delivery"),
    "unit testing": ("unit testing", "unit tests"),
    "pytest": ("pytest",),
    "selenium": ("selenium",),
    "playwright": ("playwright",),
    "spark": ("apache spark", "pyspark"),
    "kafka": ("kafka", "apache kafka"),
    "airflow": ("airflow", "apache airflow"),
    "dbt": ("dbt",),
    "pandas": ("pandas",),
    "numpy": ("numpy",),
    "pytorch": ("pytorch",),
    "tensorflow": ("tensorflow", "tensor flow"),
    "scikit-learn": ("scikit-learn", "scikit learn", "sklearn"),
    "machine learning": ("machine learning",),
    "deep learning": ("deep learning",),
    "natural language processing": ("natural language processing", "nlp"),
    "computer vision": ("computer vision",),
    "data analysis": ("data analysis", "data analytics"),
    "data engineering": ("data engineering",),
    "data modeling": ("data modeling", "data modelling"),
    "etl": ("etl", "extract transform load"),
    "excel": ("excel", "microsoft excel"),
    "power bi": ("power bi", "powerbi"),
    "tableau": ("tableau",),
    "statistics": ("statistics", "statistical analysis"),
    "a/b testing": ("a/b testing", "ab testing", "split testing"),
    "figma": ("figma",),
    "ux research": ("ux research", "user research"),
    "ui design": ("ui design", "user interface design"),
    "product management": ("product management",),
    "project management": ("project management",),
    "stakeholder management": ("stakeholder management",),
    "customer service": ("customer service", "customer support"),
    "technical writing": ("technical writing",),
    "copywriting": ("copywriting",),
    "seo": ("seo", "search engine optimization"),
    "salesforce": ("salesforce",),
    "sap": ("sap",),
    "accounting": ("accounting",),
    "bookkeeping": ("bookkeeping",),
    "financial modeling": ("financial modeling", "financial modelling"),
}

# Treat +/#/. as word constituents so a C token cannot match C++/C# and
# React cannot swallow React.js, while punctuation after a normal word works.
_LEFT_BOUNDARY = r"(?<![\w+#.])"
_RIGHT_BOUNDARY = r"(?![\w+#]|\.[\w])"
_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    canonical: tuple(
        re.compile(_LEFT_BOUNDARY + re.escape(alias) + _RIGHT_BOUNDARY, re.IGNORECASE)
        for alias in aliases
    )
    for canonical, aliases in _SKILL_ALIASES.items()
}

# Ambiguous one-word technologies are accepted when explicitly listed as a
# skill, not when ordinary prose happens to say "go", "spring", "R", etc.
_STRUCTURED_ALIASES = {
    "c": "c",
    "go": "go",
    "r": "r",
    "spring": "spring",
    "spark": "spark",
}
_NON_SKILL_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "at",
    "be",
    "benefits",
    "bonus",
    "competitive",
    "compensation",
    "company",
    "degree",
    "engineer",
    "experience",
    "for",
    "from",
    "full",
    "have",
    "hiring",
    "in",
    "is",
    "job",
    "join",
    "must",
    "no",
    "not",
    "never",
    "without",
    "of",
    "on",
    "or",
    "our",
    "per",
    "remote",
    "required",
    "requirements",
    "role",
    "salary",
    "senior",
    "skills",
    "software",
    "strong",
    "team",
    "the",
    "time",
    "to",
    "we",
    "with",
    "work",
    "year",
    "years",
    "you",
}
# A conservative common-address syntax check, without DNS/network access.
_EMAIL = re.compile(
    r"^[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+"
    r"(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*@"
    r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+"
    r"[A-Za-z]{2,63}$"
)


def _has_text(value: str | None) -> bool:
    return bool(value and value.strip())


def _has_detail(value: str | None) -> bool:
    """A substantive sentence/bullet, without demanding quantified outcomes."""
    if not value:
        return False
    return len(value.strip()) >= 20 and len(value.split()) >= 3


def _known_signals(text: str) -> set[str]:
    return {
        canonical
        for canonical, patterns in _PATTERNS.items()
        if any(pattern.search(text) for pattern in patterns)
    }


# Negation is deliberately conservative: a mixed/ambiguous clause contributes
# no inferred skill evidence. Contrasts and sentence boundaries let independent
# positive clauses count. This is a bounded guard, not semantic verification.
_CLAUSE_BREAK = re.compile(
    r"\n+|(?<=[.!?;])\s+|\b(?:but|however|whereas|although|yet)\b", re.IGNORECASE
)
_NEGATION = re.compile(
    r"\b(?:no|not|none|without|never|neither|nor|lack|lacks|lacking|"
    r"unfamiliar|unsupported|unnecessary|unneeded|optional|avoid|avoided|"
    r"avoiding|exclude|excluded|excludes|cannot|can't|don't|doesn't|didn't|"
    r"won't|isn't|aren't|wasn't|weren't)\b|\b\w+n['’]t\b|[-–]free\b",
    re.IGNORECASE,
)
_CONTACT_TOKEN = re.compile(
    r"https?://\S+|www\.\S+|[\w.!#$%&'*+/=?^`{|}~-]+@[\w.-]+",
    re.IGNORECASE,
)


def _positive_clauses(text: str) -> list[str]:
    # Uploaded/editor text often uses smart apostrophes in ordinary denials.
    normalized = text.translate(str.maketrans("’‘ʼ", "'''"))
    cleaned = _CONTACT_TOKEN.sub(" ", normalized)
    return [
        clause
        for clause in _CLAUSE_BREAK.split(cleaned)
        if clause.strip() and not _NEGATION.search(clause)
    ]


def _positive_signals(text: str) -> set[str]:
    signals: set[str] = set()
    for clause in _positive_clauses(text):
        signals.update(_known_signals(clause))
    return signals


def _custom_technology(value: str) -> str | None:
    """Keep concise explicit technologies, never turn job prose into keywords."""
    normalized = " ".join(value.casefold().split())
    words = normalized.split()
    if (
        not normalized
        or len(normalized) > 50
        or len(words) > 3
        or any(word in _NON_SKILL_WORDS or word.isdigit() for word in words)
        or not re.fullmatch(r"[\w.+#/-]+(?: [\w.+#/-]+){0,2}", normalized)
        or not any(char.isalpha() for char in normalized)
    ):
        return None
    return normalized


def _structured_signals(values: list[str], *, custom: bool) -> set[str]:
    signals: set[str] = set()
    for value in values:
        normalized = " ".join(value.casefold().split())
        if _NEGATION.search(value):
            # A negated structured sentence is not an explicit skill claim.
            # Still allow independent positive clauses in requirements.
            signals.update(_positive_signals(value))
            continue
        known = _positive_signals(value)
        if normalized in _STRUCTURED_ALIASES:
            known.add(_STRUCTURED_ALIASES[normalized])
        if known:
            signals.update(known)
        elif custom and (technology := _custom_technology(value)):
            signals.add(technology)
    return signals


def _candidate_signals(cv: CVProfile, custom_targets: set[str]) -> set[str]:
    structured = list(cv.skills)
    # Raw extraction includes names, contacts and employer identifiers. Only
    # curated structured fields/prose can support a candidate skill claim.
    text = [cv.summary or ""]
    for experience in cv.experiences:
        structured.extend(experience.technologies)
        text.extend(experience.achievements + experience.metrics)
    for project in cv.projects:
        structured.extend(project.technologies)
        text.extend([project.description, project.impact or ""])
    signals = _structured_signals(structured, custom=True)
    source = "\n".join(text)
    clauses = _positive_clauses(source)
    for clause in clauses:
        signals.update(_known_signals(clause))
    # A custom explicit job technology may also be evidenced verbatim in a
    # candidate achievement. Exact punctuation-aware boundaries still apply.
    for technology in custom_targets:
        if any(
            re.search(
                _LEFT_BOUNDARY + re.escape(technology) + _RIGHT_BOUNDARY,
                clause,
                re.IGNORECASE,
            )
            for clause in clauses
        ):
            signals.add(technology)
    return signals


def _job_alignment(cv: CVProfile, job: JobPosting) -> dict[str, Any]:
    targets = _structured_signals(job.tech_stack, custom=True)
    targets.update(_structured_signals(job.requirements, custom=False))
    if targets:
        source = "explicit tech stack and requirements"
    else:
        targets = _positive_signals(job.description)
        source = "recognized skills in the job description"
    if not targets:
        return {
            "score": None,
            "matched": [],
            "missing": [],
            "method": "No useful skill evidence found; add a job description or explicit technologies. No ATS ranking is estimated.",
        }
    evidence = _candidate_signals(cv, targets - set(_SKILL_ALIASES))
    matched = sorted(targets & evidence)
    missing = sorted(targets - evidence)
    return {
        "score": round(100 * len(matched) / len(targets), 1),
        "matched": matched,
        "missing": missing,
        "method": (
            f"Exact skill coverage from {source}: {len(matched)}/{len(targets)} "
            "recognized signals. Aliases are normalized; ordering and repetition "
            "do not affect coverage. Raw CV text, identity and contact fields "
            "are excluded; clearly negated clauses contribute no inferred evidence. "
            "Review context and proficiency yourself; "
            "this is not an ATS vendor score or hiring prediction."
        ),
    }


def assess_resume(cv: CVProfile, job: JobPosting | None = None) -> dict[str, Any]:
    """Assess supplied candidate facts without modifying them or adding claims.

    Each passed check contributes its documented weight; failed checks add
    zero. Source layout, external credential verification and vendor-specific
    ATS behavior are outside this content assessment. Missing skills remain
    gaps for review, never instructions to fabricate candidate experience.
    """
    experience = [
        entry
        for entry in cv.experiences
        if _has_text(entry.title) and _has_text(entry.company)
    ]
    projects = [
        entry
        for entry in cv.projects
        if _has_text(entry.name) and _has_text(entry.description)
    ]
    has_records = bool(experience or projects)
    details = any(
        _has_detail(value)
        for entry in experience
        for value in entry.achievements + entry.metrics
    ) or any(
        _has_detail(entry.description) or _has_detail(entry.impact)
        for entry in projects
    )
    complete = (
        has_records
        and all(
            _has_text(entry.title)
            and _has_text(entry.company)
            and _has_text(entry.duration)
            for entry in cv.experiences
        )
        and all(
            _has_text(entry.name) and _has_text(entry.description)
            for entry in cv.projects
        )
    )
    rules = [
        (
            "name",
            "Candidate name",
            _has_text(cv.name),
            10,
            "Include the name you use professionally.",
        ),
        (
            "email",
            "Usable email address",
            bool(_EMAIL.fullmatch((cv.email or "").strip())),
            15,
            "Add a complete email address, for example name@example.com. Syntax only is checked; no email or DNS request is made.",
        ),
        (
            "skills",
            "Stated skills",
            any(_has_text(skill) for skill in cv.skills),
            15,
            "List skills you can support with your real experience, projects or learning.",
        ),
        (
            "experience_or_projects",
            "Experience or projects",
            has_records,
            25,
            "Add a role with title and company, or a project with a name and description. Projects count fully for entry-level applicants.",
        ),
        (
            "evidence",
            "Supporting work or project details",
            details,
            15,
            "Describe what you did in at least one substantive accomplishment or project description (at least three words and 20 characters). Real unquantified accomplishments count; numbers are optional.",
        ),
        (
            "education",
            "Education or training",
            any(_has_text(item) for item in cv.education),
            10,
            "Include relevant education or training you actually completed or are pursuing; a university degree is not required.",
        ),
        (
            "complete_entries",
            "Complete role or project records",
            complete,
            10,
            "Fill in title, company and duration for every role, and name and description for every project. Project links are optional.",
        ),
    ]
    checks = [
        {
            "id": key,
            "label": label,
            "passed": bool(passed),
            "weight": weight,
            "detail": detail,
        }
        for key, label, passed, weight, detail in rules
    ]
    return {
        "readiness_score": sum(check["weight"] for check in checks if check["passed"]),
        "checks": checks,
        "actions": [check["detail"] for check in checks if not check["passed"]],
        "job_match": _job_alignment(cv, job) if job is not None else None,
    }
