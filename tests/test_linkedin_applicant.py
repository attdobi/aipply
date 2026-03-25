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
        """If Easy Apply button is not visible, should return manual_needed."""
        mock_page = MagicMock()
        applicant.page = mock_page

        # CAPTCHA check — no captcha present
        captcha_locator = MagicMock()
        captcha_locator.count.return_value = 0

        # Easy Apply button — wait_for raises to signal not visible
        mock_easy_apply_btn = MagicMock()
        mock_easy_apply_btn.wait_for.side_effect = Exception("Timeout")

        def locator_side_effect(selector):
            result = MagicMock()
            if "captcha" in selector.lower():
                return captcha_locator
            result.first = mock_easy_apply_btn
            return result

        mock_page.locator.side_effect = locator_side_effect

        with patch.object(applicant, "_take_screenshot", return_value="/tmp/ss.png"):
            result = applicant.apply_to_job(
                sample_job,
                str(tmp_path / "resume.docx"),
                str(tmp_path / "cover.docx"),
            )
        assert result["status"] == "manual_needed"
        assert result["reason"] == "not_easy_apply"
        assert result["success"] is False
        assert isinstance(result["screenshots"], list)

    def test_apply_to_job_handles_exception(self, applicant, sample_job, tmp_path):
        """apply_to_job should catch exceptions and return apply_failed."""
        mock_page = MagicMock()
        applicant.page = mock_page

        # Make goto raise an exception
        mock_page.goto.side_effect = Exception("Network error")

        result = applicant.apply_to_job(
            sample_job,
            str(tmp_path / "resume.docx"),
        )
        assert result["status"] == "apply_failed"
        assert result["success"] is False
        assert "Network error" in result["reason"]
        assert isinstance(result["screenshots"], list)

    def test_easy_apply_submit_flow(self, applicant, sample_job, tmp_path):
        """Full Easy Apply flow: click Easy Apply → Submit."""
        mock_page = MagicMock()
        applicant.page = mock_page

        # CAPTCHA check — no captcha
        captcha_locator = MagicMock()
        captcha_locator.count.return_value = 0

        # Easy Apply button IS visible (wait_for succeeds)
        mock_easy_apply_btn = MagicMock()

        def locator_side_effect(selector):
            result = MagicMock()
            if "captcha" in selector.lower():
                return captcha_locator
            if "Easy Apply" in selector:
                result.first = mock_easy_apply_btn
            else:
                mock_other = MagicMock()
                mock_other.is_visible.return_value = False
                mock_other.count.return_value = 0
                mock_other.all.return_value = []
                result.first = mock_other
            return result

        mock_page.locator.side_effect = locator_side_effect

        with patch.object(applicant, "_take_screenshot", return_value="/tmp/screenshot.png"):
            with patch.object(applicant, "_handle_share_profile_dialog"):
                with patch.object(applicant, "_has_submit_button", return_value=True):
                    with patch.object(applicant, "_click_submit"):
                        with patch.object(applicant, "_fill_contact_info"):
                            with patch.object(applicant, "_upload_resume"):
                                with patch.object(applicant, "_answer_common_questions"):
                                    result = applicant.apply_to_job(
                                        sample_job,
                                        str(tmp_path / "resume.docx"),
                                    )

        assert result["status"] == "applied"
        assert result["success"] is True
        assert isinstance(result["screenshots"], list)


class TestTakeScreenshot:
    def test_take_screenshot_creates_file(self, applicant, sample_job, tmp_path):
        """_take_screenshot should save a screenshot file with label."""
        mock_page = MagicMock()

        result = applicant._take_screenshot(
            mock_page, sample_job, output_dir=str(tmp_path), label="test"
        )
        # Verify screenshot was called on the page
        mock_page.screenshot.assert_called_once()
        assert "test_" in result
        assert result.endswith(".png")
        # Verify it was appended to the screenshots list
        assert result in applicant.screenshots

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
        """_fill_contact_info should handle email select dropdown without error."""
        mock_page = MagicMock()

        # Build chained mock: page.locator('div[role="dialog"], .artdeco-modal').first.locator("select").first
        mock_modal = MagicMock()
        mock_email_select = MagicMock()
        mock_email_select.is_visible.return_value = True
        mock_email_select.input_value.return_value = ""
        mock_email_select.evaluate.return_value = ""

        # Mock option with target email
        mock_option = MagicMock()
        mock_option.text_content.return_value = "danna.dobi@gmail.com"
        mock_option.get_attribute.return_value = "danna.dobi@gmail.com"
        mock_email_select.locator.return_value.all.return_value = [mock_option]

        # Chain: modal.locator("select").first -> mock_email_select
        mock_modal.locator.return_value.first = mock_email_select

        # page.locator(...).first -> mock_modal
        mock_page.locator.return_value.first = mock_modal

        # Should not raise any exceptions
        applicant._fill_contact_info(mock_page)
        mock_email_select.select_option.assert_called_once_with(label="danna.dobi@gmail.com")


class TestUploadResume:
    def test_upload_resume_sets_file(self, applicant, tmp_path):
        """_upload_resume should call set_input_files when file input exists in modal."""
        mock_page = MagicMock()

        # Chain: page.locator('div[role="dialog"], .artdeco-modal').first
        #            .locator('input[type="file"]').first
        mock_modal = MagicMock()
        mock_file_input = MagicMock()
        mock_file_input.count.return_value = 1
        mock_modal.locator.return_value.first = mock_file_input
        mock_page.locator.return_value.first = mock_modal

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
