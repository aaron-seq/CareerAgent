"""Tests for JobFinder (DuckDuckGo-backed job discovery)

External APIs (DuckDuckGo, requests, LLM) are mocked per CLAUDE.md -- no
live network calls in the checked-in suite.
"""

from unittest.mock import Mock, patch

import pytest

from core.job_finder import JobFinder
from core.models import JobPosting, SearchQuery


def _finder():
    llm = Mock()
    finder = JobFinder(llm)
    finder.ddgs = Mock()
    return finder, llm


class TestBuildSearchQuery:
    def test_includes_location_and_remote(self):
        finder, _ = _finder()
        query = SearchQuery(query="backend engineer", location="Austin", remote=True)
        built = finder._build_search_query(query)
        assert "backend engineer" in built
        assert "Austin" in built
        assert "remote" in built
        assert "job OR careers OR hiring" in built

    def test_omits_location_when_absent(self):
        finder, _ = _finder()
        query = SearchQuery(query="backend engineer")
        built = finder._build_search_query(query)
        assert "None" not in built


class TestIsJobRelated:
    def test_true_for_job_keyword_in_title(self):
        finder, _ = _finder()
        result = {"title": "Backend Engineer job opening", "body": "", "href": ""}
        assert finder._is_job_related(result) is True

    def test_true_for_ats_domain_in_url(self):
        finder, _ = _finder()
        result = {
            "title": "Careers",
            "body": "",
            "href": "https://boards.greenhouse.io/x",
        }
        assert finder._is_job_related(result) is True

    def test_false_for_unrelated_result(self):
        finder, _ = _finder()
        result = {
            "title": "Best pizza recipes",
            "body": "Delicious pizza",
            "href": "https://food.test",
        }
        assert finder._is_job_related(result) is False


class TestExtractCompanyName:
    def test_extracts_from_title_at_pattern(self):
        finder, _ = _finder()
        assert (
            finder._extract_company_name("Software Engineer at Google", "") == "Google"
        )

    def test_falls_back_to_url_domain(self):
        finder, _ = _finder()
        name = finder._extract_company_name(
            "Software Engineer", "https://www.careers.acme.com/jobs/1"
        )
        assert name == "Acme"

    def test_unknown_when_neither_available(self):
        finder, _ = _finder()
        # url=None raises inside urlparse, which is the only path that
        # reaches the "Unknown Company" fallback (urlparse("") parses fine
        # and just yields an empty domain instead of raising).
        assert (
            finder._extract_company_name("Software Engineer", None) == "Unknown Company"
        )


class TestParseSearchResult:
    def test_builds_job_posting(self):
        finder, _ = _finder()
        result = {
            "title": "Backend Engineer at Anthropic",
            "body": "Build reliable systems.",
            "href": "https://anthropic.com/jobs/1",
        }
        job = finder._parse_search_result(result)
        assert isinstance(job, JobPosting)
        assert job.title == "Backend Engineer at Anthropic"
        assert job.company == "Anthropic"
        assert job.url == "https://anthropic.com/jobs/1"
        assert job.description == "Build reliable systems."


class TestSearchJobs:
    @patch("core.job_finder.time.sleep")
    def test_filters_and_parses_job_related_results(self, _sleep):
        finder, _ = _finder()
        finder.ddgs.text.return_value = [
            {
                "title": "Backend Engineer at Anthropic",
                "body": "hiring now",
                "href": "https://anthropic.com/jobs/1",
            },
            {
                "title": "Best pizza recipes",
                "body": "Delicious pizza",
                "href": "https://food.test",
            },
        ]
        query = SearchQuery(query="backend engineer")
        jobs = finder.search_jobs(query)
        assert len(jobs) == 1
        assert jobs[0].company == "Anthropic"

    @patch("core.job_finder.time.sleep")
    def test_skips_result_that_fails_to_parse(self, _sleep):
        finder, _ = _finder()
        finder.ddgs.text.return_value = [
            {"title": "Engineer job", "body": "", "href": "https://x.test"}
        ]
        with patch.object(
            finder, "_parse_search_result", side_effect=Exception("boom")
        ):
            jobs = finder.search_jobs(SearchQuery(query="engineer"))
        assert jobs == []

    def test_wraps_search_failure(self):
        finder, _ = _finder()
        finder.ddgs.text.side_effect = Exception("202 Ratelimit")
        with pytest.raises(Exception, match="Job search failed"):
            finder.search_jobs(SearchQuery(query="engineer"))


class TestFetchJobDetails:
    @patch("core.job_finder.requests.get")
    def test_parses_job_details_via_llm(self, mock_get):
        finder, llm = _finder()
        mock_get.return_value = Mock(
            status_code=200,
            text="<html><body>Great job posting text</body></html>",
        )
        mock_get.return_value.raise_for_status = Mock()
        llm.generate_json.return_value = {
            "title": "Backend Engineer",
            "company": "Anthropic",
            "requirements": ["Python"],
        }
        job = finder.fetch_job_details("https://anthropic.com/jobs/1")
        assert isinstance(job, JobPosting)
        assert job.title == "Backend Engineer"
        assert job.url == "https://anthropic.com/jobs/1"

    @patch("core.job_finder.requests.get", side_effect=Exception("timeout"))
    def test_returns_none_on_fetch_failure(self, _mock_get):
        finder, _llm = _finder()
        assert finder.fetch_job_details("https://x.test/1") is None

    @patch("core.job_finder.requests.get")
    def test_returns_none_on_llm_failure(self, mock_get):
        finder, llm = _finder()
        mock_get.return_value = Mock(status_code=200, text="<html></html>")
        mock_get.return_value.raise_for_status = Mock()
        llm.generate_json.side_effect = Exception("bad json")
        assert finder.fetch_job_details("https://x.test/1") is None
