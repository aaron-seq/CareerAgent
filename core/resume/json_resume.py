"""
Convert between our ``CVProfile`` and the open JSON Resume schema.

JSON Resume (jsonresume.org) is a git-versionable standard with a large theme
ecosystem and converters (e.g. to RenderCV). Using it as the interchange format
keeps rendering and tooling decoupled from our internal model.
"""

from __future__ import annotations

from typing import Any

from ..models import CVProfile, Experience, Project


def to_json_resume(cv: CVProfile) -> dict[str, Any]:
    """Map a CVProfile onto a JSON Resume document."""
    profiles = []
    if cv.linkedin:
        profiles.append({"network": "LinkedIn", "url": cv.linkedin})
    if cv.github:
        profiles.append({"network": "GitHub", "url": cv.github})

    basics = {
        "name": cv.name or "",
        "email": cv.email or "",
        "phone": cv.phone or "",
        "summary": cv.summary or "",
        "url": cv.portfolio or "",
        "profiles": profiles,
    }

    work = [
        {
            "name": exp.company,
            "position": exp.title,
            "startDate": "",
            "endDate": exp.duration,
            "highlights": list(exp.achievements) + list(exp.metrics),
            "keywords": list(exp.technologies),
        }
        for exp in cv.experiences
    ]

    projects = [
        {
            "name": proj.name,
            "description": proj.description,
            "keywords": list(proj.technologies),
            "url": proj.link or proj.github or "",
            "highlights": [proj.impact] if proj.impact else [],
        }
        for proj in cv.projects
    ]

    skills = [{"name": s} for s in cv.skills]
    education = [{"institution": e} for e in cv.education]

    return {
        "$schema": "https://raw.githubusercontent.com/jsonresume/resume-schema/v1.0.0/schema.json",
        "basics": basics,
        "work": work,
        "projects": projects,
        "skills": skills,
        "education": education,
    }


def from_json_resume(doc: dict[str, Any]) -> CVProfile:
    """Map a JSON Resume document back onto a CVProfile."""
    basics = doc.get("basics", {})
    profiles = {
        p.get("network", "").lower(): p.get("url") for p in basics.get("profiles", [])
    }

    experiences = [
        Experience(
            title=w.get("position", ""),
            company=w.get("name", ""),
            duration=w.get("endDate", "") or "",
            achievements=list(w.get("highlights", [])),
            technologies=list(w.get("keywords", [])),
        )
        for w in doc.get("work", [])
    ]

    projects = [
        Project(
            name=p.get("name", ""),
            description=p.get("description", ""),
            technologies=list(p.get("keywords", [])),
            link=p.get("url") or None,
            impact=(p.get("highlights") or [None])[0],
        )
        for p in doc.get("projects", [])
    ]

    return CVProfile(
        name=basics.get("name") or None,
        email=basics.get("email") or None,
        phone=basics.get("phone") or None,
        linkedin=profiles.get("linkedin"),
        github=profiles.get("github"),
        portfolio=basics.get("url") or None,
        summary=basics.get("summary") or None,
        experiences=experiences,
        projects=projects,
        skills=[s.get("name", "") for s in doc.get("skills", []) if s.get("name")],
        education=[
            e.get("institution", "")
            for e in doc.get("education", [])
            if e.get("institution")
        ],
    )
