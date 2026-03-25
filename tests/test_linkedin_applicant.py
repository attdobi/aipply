"""Tests for LinkedIn applicant module."""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, PropertyMock

from src.linkedin_applicant import LinkedInApplicant


@pytest.fixture
def profile():
    """Sample candidate profile."""
    return {
        "candidate": {
            "name": "Jane Doe",
            "email": "jane@example.com",
            "phone": "555-123-4567",
            "location": "San Francisco",
            "summary": "Experienced compliance professional.",
            "strengths": ["Regulatory compliance", "Risk management"],
        }
    }


@pytest.fixture
def config():
    """Sample application config."""
    return {
        "application": {
            "email": "jane@example.com",
            "auto_apply": True,
            "max_applications_per_cycle": 10,
        }
    }


@pytest.fixture
def applicant(config, profile):
    """Create a LinkedInApplicant with test config and profile."""
    return LinkedInApplicant(config=config, profile=profile)


@pytest.fixture
def sample_job():
    """Sample job dict."""
    return {
        "title": "Compliance Manager",
        "company": "Acme Corp",
        "url": "https://linkedin.com/jobs/12345",
        "location": "San Francisco, CA",
        "description": "Looking for an experienced compliance manager.",
    }


class TestLinkedInApplicantInit:
    def test_init_with_config_and_profile(self, applicant, config, profile):
        assert applicant.config == config
        assert applicant.profile == profile
        assert applicant.candidate == profile["candidate"]

    def test_init_defaults(self):
        a = LinkedInApplicant()
        assert a.config == {}
        assert a.profile == {}
        assert a.candidate == {}
        assert a.browser is None
        assert a.page is None
        assert a.playwright is None

    def test_init_none_values(self):
        a = LinkedInApplicant(config=None, profile=None)
        assert a.config == {}
        assert a.profile == {}

    def test_candidate_extracted_from_profile(self, profile):
        a = LinkedInApplicant(profile=profile)
        assert a.candidate["name"] == "Jane Doe"
        assert a.candidate["email"] == "jane@example.com"


class TestApplyToJob:
    def test_non_easy_apply_returns_skipped(self, applicant, sample_job, tmp_path):
        """If Easy Apply button is not visible, should return skipped."""
        mock_page = MagicMock()
        applicant.page = mock_page

        # Easy Apply button is NOT visible
        mock_btn = MagicMock()
        mock_btn.is_visible.return_value = False
        mock_page.locator.return_value.first = mock_btn

        result = applicant.apply_to_job(
            sample_job,
            str(tmp_path / "resume.docx"),
            str(tmp_path / "cover.docx"),
        )
        assert result["status"] == "skipped"
        assert result["reason"] == "not_easy_apply"

    def test_apply_to_job_handles_exception(self, applicant, sample_job, tmp_path):
        """apply_to_job should catch exceptions and return failed."""
        mock_page = MagicMock()
        applicant.page = mock_page

        # Make goto raise an exception
        mock_page.goto.side_effect = Exception("Network error")

        result = applicant.apply_to_job(
            sample_job,
            str(tmp_path / "resume.docx"),
        )
        assert result["status"] == "failed"
        assert "Network error" in result["reason"]

    def test_easy_apply_submit_flow(self, applicant, sample_job, tmp_path):
        """Full Easy Apply flow: click Easy Apply → Submit."""
        mock_page = MagicMock()
        applicant.page = mock_page

        # Easy Apply button IS visible
        mock_easy_apply_btn = MagicMock()
        mock_easy_apply_btn.is_visible.return_value = True

        # Submit button IS visible on first dialog step
        mock_submit_btn = MagicMock()
        mock_submit_btn.is_visible.return_value = True

        # Track which locator query is being made
        call_count = [0]

        def locator_side_effect(selector):
            result = MagicMock()
            if "Easy Apply" in selector:
                result.first = mock_easy_apply_btn
            elif "Submit application" in selector:
                result.first = mock_submit_btn
            else:
                mock_other = MagicMock()
                mock_other.is_visible.return_value = False
                mock_other.count.return_value = 0
                mock_other.all.return_value = []
                result.first = mock_other
            return result

        mock_page.locator.side_effect = locator_side_effect

        # Mock screenshot
        with patch.object(applicant, "_take_screenshot", return_value="/tmp/screenshot.png"):
            with patch.object(applicant, "_fill_contact_info"):
                with patch.object(applicant, "_upload_resume"):
                    with patch.object(applicant, "_handle_questions"):
                        result = applicant.apply_to_job(
                            sample_job,
                            str(tmp_path / "resume.docx"),
                        )

        assert result["status"] == "applied"
        assert result["screenshot_path"] == "/tmp/screenshot.png"


class TestTakeScreenshot:
    def test_take_screenshot_creates_file(self, applicant, sample_job, tmp_path):
        """_take_screenshot should save a screenshot file."""
        mock_page = MagicMock()

        result = applicant._take_screenshot(
            mock_page, sample_job, output_dir=str(tmp_path)
        )
        # Verify screenshot was called on the page
        mock_page.screenshot.assert_called_once()
        assert "screenshot.png" in result

    def test_take_screenshot_handles_error(self, applicant, sample_job, tmp_path):
        """_take_screenshot should return empty string on error."""
        mock_page = MagicMock()
        mock_page.screenshot.side_effect = Exception("Screenshot failed")

        result = applicant._take_screenshot(
            mock_page, sample_job, output_dir=str(tmp_path)
        )
        assert result == ""


class TestFillContactInfo:
    def test_fill_contact_info_fills_email(self, applicant):
        """_fill_contact_info should fill email field when present."""
        mock_page = MagicMock()
        mock_email = MagicMock()
        mock_email.is_visible.return_value = True
        mock_email.input_value.return_value = ""

        # First call returns email input, rest return invisible mocks
        def locator_side_effect(selector):
            result = MagicMock()
            if "email" in selector.lower():
                result.first = mock_email
            else:
                mock_hidden = MagicMock()
                mock_hidden.is_visible.return_value = False
                result.first = mock_hidden
            return result

        mock_page.locator.side_effect = locator_side_effect

        applicant._fill_contact_info(mock_page)
        mock_email.fill.assert_called_once_with("jane@example.com")


class TestUploadResume:
    def test_upload_resume_sets_file(self, applicant, tmp_path):
        """_upload_resume should call set_input_files when file input exists."""
        mock_page = MagicMock()
        mock_file_input = MagicMock()
        mock_file_input.count.return_value = 1
        mock_page.locator.return_value.first = mock_file_input

        resume_path = tmp_path / "resume.docx"
        resume_path.touch()

        applicant._upload_resume(mock_page, str(resume_path))
        mock_file_input.set_input_files.assert_called_once_with(str(resume_path))


class TestClose:
    def test_close_cleans_up(self, applicant):
        """close should close browser and playwright."""
        applicant.browser = MagicMock()
        applicant.playwright = MagicMock()

        applicant.close()
        applicant.browser.close.assert_called_once()
        applicant.playwright.stop.assert_called_once()

    def test_close_handles_none(self):
        """close should not raise when browser/playwright are None."""
        a = LinkedInApplicant()
        a.close()  # Should not raise
