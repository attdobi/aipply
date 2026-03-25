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
    def test_non_easy_apply_returns_no_apply_button(self, applicant, sample_job, tmp_path):
        """If neither Easy Apply nor external Apply button found, return no_apply_button."""
        mock_page = MagicMock()
        applicant.page = mock_page

        # CAPTCHA check — no captcha present
        captcha_locator = MagicMock()
        captcha_locator.count.return_value = 0
        captcha_locator.first.is_visible.return_value = False

        def locator_side_effect(selector):
            loc = MagicMock()
            if "captcha" in selector.lower():
                loc.count.return_value = 0
                loc.first.is_visible.return_value = False
                return loc
            # All apply buttons: .first.is_visible() raises (timeout = not visible)
            loc.first.is_visible.side_effect = Exception("Timeout")
            return loc

        mock_page.locator.side_effect = locator_side_effect

        with patch.object(applicant, "_take_screenshot", return_value="/tmp/ss.png"):
            result = applicant.apply_to_job(
                sample_job,
                str(tmp_path / "resume.docx"),
                str(tmp_path / "cover.docx"),
            )
        assert result["status"] == "manual_needed"
        assert result["reason"] == "no_apply_button"
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

        # Easy Apply button mock — visible, inner_text returns "Easy Apply"
        mock_easy_apply_btn = MagicMock()
        mock_easy_apply_btn.is_visible.return_value = True
        mock_easy_apply_btn.inner_text.return_value = "Easy Apply"

        # Non-visible button for non-matching selectors
        mock_not_visible = MagicMock()
        mock_not_visible.is_visible.side_effect = Exception("Timeout")

        def locator_side_effect(selector):
            loc = MagicMock()
            # CAPTCHA — not present
            if "captcha" in selector.lower():
                loc.count.return_value = 0
                loc.first.is_visible.return_value = False
                return loc
            # Easy Apply selectors
            if "Easy Apply" in selector:
                loc.first = mock_easy_apply_btn
                return loc
            # External Apply selectors — not visible
            if "Apply" in selector and "Easy" not in selector:
                loc.first = mock_not_visible
                return loc
            # Dialog check for form loop
            if "dialog" in selector or "artdeco-modal" in selector:
                loc.count.return_value = 1
                loc.first.text_content.return_value = "Form content"
                return loc
            # Default — not visible
            loc.first = mock_not_visible
            loc.count.return_value = 0
            loc.all.return_value = []
            return loc

        mock_page.locator.side_effect = locator_side_effect
        # page.evaluate — no confirmation text
        mock_page.evaluate.return_value = "some dialog text"

        with patch.object(applicant, "_take_screenshot", return_value="/tmp/screenshot.png"):
            with patch.object(applicant, "_handle_share_profile_dialog"):
                with patch.object(applicant, "_has_submit_button", return_value=True):
                    with patch.object(applicant, "_click_submit"):
                        with patch.object(applicant, "_fill_contact_info"):
                            with patch.object(applicant, "_handle_resume_step"):
                                with patch.object(applicant, "_handle_cover_letter_upload"):
                                    with patch.object(applicant, "_answer_common_questions"):
                                        with patch.object(applicant, "_click_next_or_continue"):
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

        # The candidate email from the profile fixture is "jane@example.com"
        # (or falls back to "danna.dobi@gmail.com" if not present).
        # The code uses self.candidate.get("email", "danna.dobi@gmail.com").
        target_email = applicant.candidate.get("email", "danna.dobi@gmail.com")

        # Build chained mock: page.locator('div[role="dialog"], .artdeco-modal').first.locator("select").first
        mock_modal = MagicMock()
        mock_email_select = MagicMock()
        mock_email_select.is_visible.return_value = True
        mock_email_select.input_value.return_value = ""
        mock_email_select.evaluate.return_value = ""

        # Mock option with the target email
        mock_option = MagicMock()
        mock_option.text_content.return_value = target_email
        mock_option.get_attribute.return_value = target_email
        mock_email_select.locator.return_value.all.return_value = [mock_option]

        # Chain: modal.locator("select").first -> mock_email_select
        mock_modal.locator.return_value.first = mock_email_select

        # page.locator(...).first -> mock_modal
        mock_page.locator.return_value.first = mock_modal

        # Should not raise any exceptions
        applicant._fill_contact_info(mock_page)
        mock_email_select.select_option.assert_called_once_with(label=target_email)


class TestUploadResume:
    def test_upload_resume_sets_file(self, applicant, tmp_path):
        """_upload_resume should call set_input_files when file input exists in modal."""
        mock_page = MagicMock()

        # Build mock chain:
        # page.locator('div[role="dialog"], .artdeco-modal').first → modal
        # modal.locator('input[type="file"]') → file_locator
        # file_locator.count() → 1
        # file_locator.first → file_input_element
        # file_input_element.set_input_files(path)
        mock_modal = MagicMock()
        mock_file_locator = MagicMock()
        mock_file_input_element = MagicMock()
        mock_file_locator.count.return_value = 1
        mock_file_locator.first = mock_file_input_element

        def modal_locator_side_effect(selector):
            if "file" in selector:
                return mock_file_locator
            # Default for other selectors (upload button, document area, etc.)
            other = MagicMock()
            other.count.return_value = 0
            other.first.is_visible.return_value = False
            return other

        mock_modal.locator.side_effect = modal_locator_side_effect
        mock_page.locator.return_value.first = mock_modal

        resume_path = tmp_path / "resume.docx"
        resume_path.touch()

        applicant._upload_resume(mock_page, str(resume_path))
        mock_file_input_element.set_input_files.assert_called_once_with(str(resume_path))


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
