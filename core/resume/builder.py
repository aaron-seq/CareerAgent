"""Create a CV from explicit user facts without a model or inferred claims."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from ..models import CVProfile
from ..outreach.verification import verify_email

_CONTACT_FIELDS = (
    "name",
    "email",
    "phone",
    "summary",
    "linkedin",
    "github",
    "portfolio",
)


def _text(value: Any, label: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{label} must be text.")
    return value.strip()


def _lines(value: Any, label: str) -> list[str]:
    """Accept form text or an existing model list; remove only exact duplicates."""
    if value is None:
        return []
    if isinstance(value, str):
        value = value.splitlines()
    if not isinstance(value, list):
        raise ValueError(f"{label} must be text or a list of text entries.")
    return list(dict.fromkeys(item for raw in value if (item := _text(raw, label))))


def _url(value: str, label: str) -> str | None:
    if not value:
        return None
    try:
        parsed = urlsplit(value)
        valid = (
            parsed.scheme in {"https", "http"}
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
            and not any(character.isspace() for character in value)
        )
        parsed.port  # reject malformed ports without making a network request
    except ValueError:
        valid = False
    if not valid:
        raise ValueError(
            f"{label} must be a complete HTTP or HTTPS URL without credentials."
        )
    return value


def _entries(data: dict[str, Any], field: str) -> list[dict[str, Any]]:
    values = data.get(field) or []
    if not isinstance(values, list) or len(values) > 30:
        raise ValueError(f"{field.title()} must be a list with at most 30 entries.")
    if not all(isinstance(entry, dict) for entry in values):
        raise ValueError(f"Each {field} entry must contain named fields.")
    return values


def build_cv_profile(data: dict[str, Any]) -> CVProfile:
    """Validate/normalize a builder draft, preserving facts and clearing stale OCR."""
    if not isinstance(data, dict):
        raise ValueError("CV details must contain named fields.")
    values: dict[str, Any] = {
        field: _text(data.get(field), field.title()) or None
        for field in _CONTACT_FIELDS
    }
    if not values["name"]:
        raise ValueError("Add your name before creating the CV.")
    if (
        values["email"]
        and not verify_email(
            values["email"], resolver=lambda _: None, require_mx=False
        ).syntax_ok
    ):
        raise ValueError("Enter a valid email address, or leave email blank for now.")
    for field in ("linkedin", "github", "portfolio"):
        values[field] = _url(values[field] or "", field.title())
    for field in ("skills", "education"):
        values[field] = _lines(data.get(field), field.title())

    experiences = []
    for index, entry in enumerate(_entries(data, "experiences"), 1):
        role: dict[str, Any] = {
            field: _text(entry.get(field), field)
            for field in ("title", "company", "duration")
        }
        role.update(
            {
                field: _lines(entry.get(field), field)
                for field in ("achievements", "metrics", "technologies")
            }
        )
        if not any(role.values()):
            continue
        if not all(role[field] for field in ("title", "company", "duration")):
            raise ValueError(
                f"Role {index}: add a title, employer, and the actual dates or duration."
            )
        experiences.append(role)
    values["experiences"] = experiences

    projects = []
    for index, entry in enumerate(_entries(data, "projects"), 1):
        project: dict[str, Any] = {
            field: _text(entry.get(field), field)
            for field in ("name", "description", "impact", "link", "github")
        }
        project["technologies"] = _lines(
            entry.get("technologies"), "Project technologies"
        )
        if not any(project.values()):
            continue
        if not project["name"] or not project["description"]:
            raise ValueError(f"Project {index}: add a name and a factual description.")
        for field in ("link", "github"):
            project[field] = _url(project[field], f"Project {index} {field}")
        project["impact"] = project["impact"] or None
        projects.append(project)
    values["projects"] = projects
    if not any(
        values[field]
        for field in ("summary", "skills", "education", "experiences", "projects")
    ):
        raise ValueError(
            "Add skills, education, a summary, work experience, or a project."
        )
    values["raw_text"] = ""  # removed/edited facts must not survive in old PDF text
    return CVProfile.model_validate(values)
