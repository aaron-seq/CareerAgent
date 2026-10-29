"""LaTeX exports preserve facts and treat candidate input only as text."""

from __future__ import annotations

from copy import deepcopy
from io import BytesIO
from pathlib import Path, PurePosixPath
from zipfile import ZipFile

import pytest

from core.resume.render import render_latex, render_latex_project


def _document():
    return {
        "basics": {
            "name": "Synthetic Δοκιμή Кириллица",
            "email": "candidate@example.test",
            "phone": "+44 1234 567890",
            "summary": "Built factual data tools.",
            "url": "https://example.test/portfolio",
            "profiles": [{"network": "GitHub", "url": "https://example.test/code"}],
        },
        "skills": [{"name": "Python"}, {"name": "SQL"}],
        "work": [
            {
                "position": "Volunteer Engineer",
                "name": "Community Library",
                "endDate": "2023–present",
                "highlights": ["Catalogued 120 books", "Reduced lookup time by 25%"],
                "keywords": ["Python", "SQLite"],
            }
        ],
        "projects": [
            {
                "name": "Catalogue",
                "description": "Built a searchable catalogue",
                "keywords": ["SQL", "Docker"],
                "url": "https://example.test/demo",
                "x-github": "https://example.test/repository",
                "highlights": ["Used by 12 volunteers"],
            }
        ],
        "education": [{"institution": "Community computing course"}],
    }


def test_latex_preserves_facts_unicode_both_links_and_section_order():
    document = _document()
    before = deepcopy(document)
    source = render_latex(document)
    facts = source.replace(r"\allowbreak{}", "")
    assert document == before
    for fact in (
        "Synthetic Δοκιμή Кириллица",
        "candidate@example.test",
        "+44 1234 567890",
        "https://example.test/portfolio",
        "https://example.test/code",
        "Built factual data tools.",
        "Python, SQL",
        "Volunteer Engineer, Community Library (2023–present)",
        "Catalogued 120 books",
        r"Reduced lookup time by 25\%",
        "Tech: Python, SQLite",
        "Catalogue - Built a searchable catalogue",
        "Tech: SQL, Docker",
        "https://example.test/demo",
        "https://example.test/repository",
        "Used by 12 volunteers",
        "Community computing course",
    ):
        assert fact in facts
    headings = [
        source.index(r"\section*{" + name + "}")
        for name in ("Summary", "Skills", "Experience", "Projects", "Education")
    ]
    assert headings == sorted(headings)
    assert r"\documentclass[11pt,a4paper]{article}" in source
    assert r"\usepackage{fontspec}" in source
    assert "DejaVuSans.ttf" in source and "DejaVuSans-Bold.ttf" in source
    assert source.count(r"\begin{document}") == source.count(r"\end{document}") == 1


def test_every_tex_special_character_is_escaped_once():
    document = _document()
    document["basics"]["summary"] = "\\ % $ & # _ { } ^ ~"
    assert (
        r"\textbackslash{} \% \$ \& \# \_ \{ \} \textasciicircum{} \textasciitilde{}"
        in render_latex(document)
    )


@pytest.mark.parametrize("field", ["name", "email", "phone", "summary", "url"])
def test_candidate_basics_cannot_add_tex_commands(field):
    document = _document()
    document["basics"][field] = r"\input{private.tex}\write18{command}\end{document}"
    source = render_latex(document)
    assert r"\input{private.tex}" not in source
    assert r"\write18{command}" not in source
    assert r"\textbackslash{}input\{private.tex\}" in source
    assert source.count(r"\end{document}") == 1


def test_nested_facts_and_contact_labels_cannot_add_tex_commands():
    document = _document()
    hostile = r"\include{outside}%#&"
    document["basics"]["profiles"][0]["network"] = hostile
    document["skills"][0]["name"] = hostile
    document["work"][0]["highlights"] = [hostile]
    document["projects"][0]["x-github"] = hostile
    document["education"][0]["institution"] = hostile
    source = render_latex(document)
    assert r"\include{outside}" not in source
    assert source.count(r"\textbackslash{}include\{outside\}\%\#\&") == 5


def test_whitespace_preserves_words_and_paragraphs():
    document = _document()
    document["basics"]["summary"] = "First\twords\r\nnext line\r\rSecond paragraph"
    source = render_latex(document)
    assert "First words\\par\nnext line\\par\n\\par\nSecond paragraph" in source
    assert "Firstwords" not in source
    assert "\r" not in source and "\t" not in source


def test_long_unbroken_links_have_safe_breakpoints_without_losing_text():
    document = _document()
    link = "https://example.test/" + "A" * 220 + "?token=" + "7" * 180
    document["basics"]["url"] = link
    source = render_latex(document)
    assert r"\allowbreak{}" in source
    assert link in source.replace(r"\allowbreak{}", "")
    # Escaping happens to whole characters before breakpoints are inserted.
    document["basics"]["url"] = "_" * 130
    assert r"\_" * 130 in render_latex(document).replace(r"\allowbreak{}", "")
    document["basics"]["name"] = "W" * 40
    source = render_latex(document)
    assert "W" * 40 not in source  # even a short, wide name must wrap
    assert "W" * 40 in source.replace(r"\allowbreak{}", "")


@pytest.mark.parametrize("character", ["\x00", "\x07", "\x0b", "\x1b", "\x7f", "\x85"])
def test_illegal_control_characters_are_rejected_explicitly(character):
    document = _document()
    document["projects"][0]["description"] += character
    with pytest.raises(ValueError, match="control character"):
        render_latex(document)
    with pytest.raises(ValueError, match="control character"):
        render_latex_project(document)


def test_overleaf_zip_has_fixed_safe_paths_exact_source_fonts_and_notices():
    document = _document()
    document["basics"]["name"] = "../../never-an-entry-name"
    data = render_latex_project(document)
    fonts = Path(__file__).resolve().parents[1] / "assets" / "fonts"
    with ZipFile(BytesIO(data)) as archive:
        assert archive.namelist() == [
            "main.tex",
            "fonts/DejaVuSans.ttf",
            "fonts/DejaVuSans-Bold.ttf",
            "fonts/LICENSE.txt",
            "README.md",
        ]
        assert archive.read("main.tex").decode("utf-8") == render_latex(document)
        for filename in ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf", "LICENSE.txt"):
            assert archive.read("fonts/" + filename) == (fonts / filename).read_bytes()
        instructions = archive.read("README.md").decode("utf-8")
        assert "XeLaTeX" in instructions
        assert (
            "https://docs.overleaf.com/managing-projects-and-files/uploading-a-project"
            in instructions
        )
        assert "personal data" in instructions and "local" in instructions
        for entry in archive.infolist():
            path = PurePosixPath(entry.filename)
            assert not path.is_absolute() and ".." not in path.parts
            assert entry.date_time == (1980, 1, 1, 0, 0, 0)
            assert not entry.is_dir()


def test_source_and_zip_are_deterministic_without_timestamps_or_identifiers():
    document = _document()
    assert render_latex(document) == render_latex(deepcopy(document))
    assert render_latex_project(document) == render_latex_project(deepcopy(document))


def test_empty_document_remains_a_complete_project():
    source = render_latex({})
    assert r"\begin{document}" in source and r"\end{document}" in source
    assert "None" not in source
    with ZipFile(BytesIO(render_latex_project({}))) as archive:
        assert archive.read("main.tex").decode("utf-8") == source
