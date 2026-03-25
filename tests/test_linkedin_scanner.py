"""Tests for LinkedIn scanner module."""

import pytest
from unittest.mock import patch, MagicMock

from src.linkedin_scanner import LinkedInScanner


@pytest.fixture
def config():
    """Test config for scanner."""
    return {
        "search": {
            "keywords": ["compliance"],
            "locations": ["Remote"],
        },
        "exclusions": {
            "companies": ["BadCorp", "SkipMe Inc"],
        },
    }


@pytest.fixture
def scanner(config):
    """Create a LinkedInScanner with test config."""
    return LinkedInScanner(config=config)


class TestLinkedInScannerInit:
    def test_init_with_config(self, scanner, config):
        assert scanner.config == config
        assert scanner.search_config == config["search"]
        assert scanner.exclusions == config["exclusions"]

    def test_init_default_config(self):
        s = LinkedInScanner()
        assert s.config == {}
        assert s.search_config == {}
        assert s.exclusions == {}

    def test_init_none_config(self):
        s = LinkedInScanner(config=None)
        assert s.config == {}

    def test_browser_initially_none(self, scanner):
        assert scanner._playwright is None
        assert scanner._browser is None
        assert scanner._page is None


class TestFilterResults:
    def test_filter_excludes_companies_case_insensitive(self, scanner):
        """filter_results should exclude companies listed in exclusions (case-insensitive)."""
        jobs = [
            {"title": "Analyst", "company": "GoodCorp", "url": "http://a", "linkedin_job_id": "1"},
            {"title": "Manager", "company": "BadCorp", "url": "http://b", "linkedin_job_id": "2"},
            {"title": "Director", "company": "SkipMe Inc", "url": "http://c", "linkedin_job_id": "3"},
        ]
        result = scanner.filter_results(jobs)
        assert len(result) == 1
        assert result[0]["company"] == "GoodCorp"

    def test_filter_excludes_companies_substring_match(self, scanner):
        """filter_results should use substring matching for companies."""
        jobs = [
            {"title": "Analyst", "company": "The BadCorp International", "url": "http://a", "linkedin_job_id": "1"},
            {"title": "Manager", "company": "GoodCorp", "url": "http://b", "linkedin_job_id": "2"},
        ]
        result = scanner.filter_results(jobs)
        assert len(result) == 1
        assert result[0]["company"] == "GoodCorp"

    def test_filter_handles_empty_exclusions(self, scanner):
        """filter_results with empty exclusions should return all jobs."""
        jobs = [
            {"title": "Analyst", "company": "A", "url": "http://a", "linkedin_job_id": "1"},
            {"title": "Manager", "company": "B", "url": "http://b", "linkedin_job_id": "2"},
        ]
        result = scanner.filter_results(jobs, exclusions={})
        assert len(result) == 2

    def test_filter_removes_duplicates_by_id(self, scanner):
        """filter_results should deduplicate by linkedin_job_id."""
        jobs = [
            {"title": "Analyst", "company": "A", "url": "http://a", "linkedin_job_id": "1"},
            {"title": "Analyst", "company": "A", "url": "http://a2", "linkedin_job_id": "1"},
        ]
        result = scanner.filter_results(jobs, exclusions={})
        assert len(result) == 1

    def test_filter_removes_duplicates_by_url(self, scanner):
        """filter_results should deduplicate by URL."""
        jobs = [
            {"title": "Analyst", "company": "A", "url": "http://same", "linkedin_job_id": "1"},
            {"title": "Analyst Copy", "company": "A", "url": "http://same", "linkedin_job_id": "2"},
        ]
        result = scanner.filter_results(jobs, exclusions={})
        assert len(result) == 1

    def test_filter_empty_jobs(self, scanner):
        """filter_results with empty job list should return empty."""
        result = scanner.filter_results([], {})
        assert result == []

    def test_filter_keyword_exclusion(self):
        """filter_results should exclude jobs with excluded keywords in title."""
        s = LinkedInScanner(config={
            "exclusions": {
                "companies": [],
                "keywords": ["intern", "junior"],
            }
        })
        jobs = [
            {"title": "Compliance Intern", "company": "A", "url": "http://a", "linkedin_job_id": "1"},
            {"title": "Senior Compliance Manager", "company": "B", "url": "http://b", "linkedin_job_id": "2"},
            {"title": "Junior Analyst", "company": "C", "url": "http://c", "linkedin_job_id": "3"},
        ]
        result = s.filter_results(jobs)
        assert len(result) == 1
        assert result[0]["title"] == "Senior Compliance Manager"


class TestSearchJobs:
    def test_search_jobs_requires_browser(self, scanner):
        """search_jobs should raise if browser not connected."""
        with pytest.raises(RuntimeError, match="Browser not connected"):
            scanner.search_jobs(["compliance"], "Remote")

    def test_search_jobs_with_mock_browser(self, scanner):
        """search_jobs should work with a mocked browser page."""
        mock_page = MagicMock()
        scanner._page = mock_page

        # Mock page methods
        mock_page.wait_for_timeout.return_value = None
        mock_page.locator.return_value.count.return_value = 0
        mock_page.locator.return_value.all.return_value = []
        mock_page.evaluate.return_value = None

        # The search will find no job cards and return empty
        with patch.object(scanner, "_find_job_cards", return_value=[]), \
             patch.object(scanner, "_load_more_results", return_value=False):
            result = scanner.search_jobs(["compliance"], "Remote")

        assert isinstance(result, list)
        mock_page.goto.assert_called_once()

    def test_search_jobs_accepts_string_keywords(self, scanner):
        """search_jobs should accept a single string keyword."""
        mock_page = MagicMock()
        scanner._page = mock_page
        mock_page.locator.return_value.count.return_value = 0

        with patch.object(scanner, "_find_job_cards", return_value=[]), \
             patch.object(scanner, "_load_more_results", return_value=False):
            result = scanner.search_jobs("compliance manager", "Remote")

        assert isinstance(result, list)


class TestGetJobDetails:
    def test_get_job_details_requires_browser(self, scanner):
        """get_job_details should raise if browser not connected."""
        with pytest.raises(RuntimeError, match="Browser not connected"):
            scanner.get_job_details("https://linkedin.com/jobs/12345")


class TestClose:
    def test_close_without_browser(self, scanner):
        """close should not raise when no browser is connected."""
        scanner.close()  # Should not raise

    def test_close_with_mock_browser(self, scanner):
        """close should close browser and stop playwright."""
        mock_context = MagicMock()
        mock_playwright = MagicMock()
        scanner._context = mock_context
        scanner._playwright = mock_playwright
        scanner._browser = None  # persistent context mode

        scanner.close()
        mock_context.close.assert_called_once()
        mock_playwright.stop.assert_called_once()
