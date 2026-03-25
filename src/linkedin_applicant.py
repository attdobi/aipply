"""LinkedIn job applicant module.

Handles submitting LinkedIn Easy Apply applications via browser automation.
"""

import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from playwright.sync_api import sync_playwright, Page, Browser

from src.utils import ensure_dir, sanitize_filename

logger = logging.getLogger(__name__)


class LinkedInApplicant:
    """Automates LinkedIn Easy Apply application submission."""

    def __init__(self, config=None, profile=None):
        """Initialize applicant with configuration.

        Args:
            config: Application settings from config/settings.yaml.
            profile: Candidate profile from config/profile.yaml.
        """
        self.config = config or {}
        self.profile = profile or {}
        self.candidate = self.profile.get("candidate", {})
        self.browser = None
        self.page = None
        self.playwright = None

    def connect_browser(self, cdp_url=None):
        """Connect to existing Chrome via CDP or use persistent context.

        Uses a persistent browser context at ~/.aipply/chrome-profile/
        so LinkedIn session cookies are preserved across runs.

        Args:
            cdp_url: Optional Chrome DevTools Protocol URL. If provided,
                     connects to an existing Chrome instance instead.
        """
        self.playwright = sync_playwright().start()

        if cdp_url:
            self.browser = self.playwright.chromium.connect_over_cdp(cdp_url)
            self.page = self.browser.contexts[0].pages[0] if self.browser.contexts and self.browser.contexts[0].pages else self.browser.contexts[0].new_page()
        else:
            profile_dir = Path.home() / ".aipply" / "chrome-profile"
            profile_dir.mkdir(parents=True, exist_ok=True)
            context = self.playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                headless=False,
                args=["--disable-blink-features=AutomationControlled"],
            )
            self.browser = context
            self.page = context.pages[0] if context.pages else context.new_page()

        logger.info("Browser connected for applicant")

    def apply_to_job(self, job, resume_path, cover_letter_path=None):
        """Apply to a single job via LinkedIn Easy Apply.

        Steps:
            1. Navigate to job URL
            2. Check if Easy Apply button exists
            3. Click Easy Apply and handle multi-step dialog
            4. Upload resume, fill contact info, handle questions
            5. Take screenshot before final submit
            6. Click Submit application

        Args:
            job: Job dict with url, title, company, etc.
            resume_path: Path to the tailored resume file.
            cover_letter_path: Optional path to cover letter file.

        Returns:
            Result dict with status, reason, and screenshot_path.
        """
        job_url = job.get("url", "")
        company = job.get("company", "unknown")
        role = job.get("title", "unknown")

        try:
            logger.info(f"Navigating to job: {role} at {company}")
            self.page.goto(job_url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(2)

            # Check for Easy Apply button
            easy_apply_btn = self.page.locator(
                'button:has-text("Easy Apply"), button[aria-label*="Easy Apply"]'
            ).first
            if not easy_apply_btn.is_visible(timeout=5000):
                logger.info(f"No Easy Apply button for {role} at {company}")
                return {
                    "status": "skipped",
                    "reason": "not_easy_apply",
                    "screenshot_path": "",
                }

            # Click Easy Apply
            easy_apply_btn.click()
            time.sleep(2)

            # Handle multi-step dialog
            max_steps = 10
            for step in range(max_steps):
                logger.debug(f"Processing dialog step {step + 1}")

                # Fill contact info if fields are present
                self._fill_contact_info(self.page)

                # Upload resume if file input appears
                self._upload_resume(self.page, resume_path)

                # Handle common questions
                self._handle_questions(self.page)

                # Check for Submit button
                submit_btn = self.page.locator(
                    'button:has-text("Submit application"), '
                    'button[aria-label*="Submit application"]'
                ).first
                if submit_btn.is_visible(timeout=2000):
                    # Take screenshot before submitting
                    screenshot_path = self._take_screenshot(self.page, job)
                    submit_btn.click()
                    time.sleep(2)
                    logger.info(f"Successfully applied to {role} at {company}")
                    return {
                        "status": "applied",
                        "reason": "easy_apply_submitted",
                        "screenshot_path": screenshot_path,
                    }

                # Check for Next / Review button
                next_btn = self.page.locator(
                    'button:has-text("Next"), button:has-text("Review"), '
                    'button[aria-label*="Continue"]'
                ).first
                if next_btn.is_visible(timeout=2000):
                    next_btn.click()
                    time.sleep(1)
                else:
                    # No navigation button found — might be stuck
                    logger.warning(f"No navigation button found at step {step + 1}")
                    break

            # If we get here, we didn't find Submit
            screenshot_path = self._take_screenshot(self.page, job)
            logger.warning(f"Could not complete application for {role} at {company}")
            return {
                "status": "failed",
                "reason": "dialog_navigation_failed",
                "screenshot_path": screenshot_path,
            }

        except Exception as e:
            logger.error(f"Error applying to {role} at {company}: {e}")
            return {
                "status": "failed",
                "reason": str(e),
                "screenshot_path": "",
            }

    def _fill_contact_info(self, page):
        """Fill in email, phone, and name fields if they appear.

        Looks for common LinkedIn Easy Apply form fields and fills them
        with data from the candidate profile.

        Args:
            page: Playwright Page instance.
        """
        candidate = self.candidate

        # Email field
        try:
            email_input = page.locator(
                'input[name*="email"], input[aria-label*="Email"], '
                'input[id*="email"]'
            ).first
            if email_input.is_visible(timeout=1000):
                current_val = email_input.input_value()
                if not current_val:
                    email_input.fill(candidate.get("email", ""))
                    logger.debug("Filled email field")
        except Exception:
            pass

        # Phone field
        try:
            phone_input = page.locator(
                'input[name*="phone"], input[aria-label*="Phone"], '
                'input[id*="phone"]'
            ).first
            if phone_input.is_visible(timeout=1000):
                current_val = phone_input.input_value()
                if not current_val:
                    phone_input.fill(candidate.get("phone", ""))
                    logger.debug("Filled phone field")
        except Exception:
            pass

        # Name fields
        try:
            first_name = page.locator(
                'input[name*="firstName"], input[aria-label*="First name"]'
            ).first
            if first_name.is_visible(timeout=1000):
                current_val = first_name.input_value()
                if not current_val:
                    full_name = candidate.get("name", "")
                    parts = full_name.split() if full_name else []
                    first_name.fill(parts[0] if parts else "")
                    logger.debug("Filled first name field")
        except Exception:
            pass

        try:
            last_name = page.locator(
                'input[name*="lastName"], input[aria-label*="Last name"]'
            ).first
            if last_name.is_visible(timeout=1000):
                current_val = last_name.input_value()
                if not current_val:
                    full_name = candidate.get("name", "")
                    parts = full_name.split() if full_name else []
                    last_name.fill(parts[-1] if len(parts) > 1 else "")
                    logger.debug("Filled last name field")
        except Exception:
            pass

    def _upload_resume(self, page, resume_path):
        """Find file input for resume upload and set the file.

        Looks for input[type='file'] elements near resume/CV labels.

        Args:
            page: Playwright Page instance.
            resume_path: Path to the resume file to upload.
        """
        try:
            file_input = page.locator('input[type="file"]').first
            if file_input.count() > 0:
                file_input.set_input_files(str(resume_path))
                logger.debug(f"Uploaded resume: {resume_path}")
                time.sleep(1)
        except Exception as e:
            logger.debug(f"Resume upload not needed or failed: {e}")

    def _handle_questions(self, page):
        """Handle common Easy Apply questions.

        Looks for dropdowns and text inputs with known labels like
        years of experience, work authorization, sponsorship, and education.
        Fills with reasonable defaults from the candidate profile.

        Args:
            page: Playwright Page instance.
        """
        # Common question patterns and their answers
        question_answers = {
            "years of experience": "5",
            "work authorization": "Yes",
            "authorized to work": "Yes",
            "sponsorship": "No",
            "require sponsorship": "No",
            "visa": "No",
        }

        # Handle text inputs with labels
        try:
            text_inputs = page.locator("input[type='text'], input[type='number']").all()
            for inp in text_inputs:
                try:
                    label_text = ""
                    # Try to get associated label
                    input_id = inp.get_attribute("id") or ""
                    if input_id:
                        label = page.locator(f'label[for="{input_id}"]')
                        if label.count() > 0:
                            label_text = label.text_content().lower()

                    if not label_text:
                        # Try aria-label
                        label_text = (inp.get_attribute("aria-label") or "").lower()

                    if not label_text:
                        continue

                    current_val = inp.input_value()
                    if current_val:
                        continue

                    for pattern, answer in question_answers.items():
                        if pattern in label_text:
                            inp.fill(answer)
                            logger.debug(f"Answered '{pattern}' with '{answer}'")
                            break
                except Exception:
                    continue
        except Exception:
            pass

        # Handle select dropdowns
        try:
            selects = page.locator("select").all()
            for select in selects:
                try:
                    label_text = ""
                    select_id = select.get_attribute("id") or ""
                    if select_id:
                        label = page.locator(f'label[for="{select_id}"]')
                        if label.count() > 0:
                            label_text = label.text_content().lower()

                    if not label_text:
                        label_text = (select.get_attribute("aria-label") or "").lower()

                    if not label_text:
                        continue

                    for pattern, answer in question_answers.items():
                        if pattern in label_text:
                            # Try to select matching option
                            options = select.locator("option").all()
                            for opt in options:
                                opt_text = (opt.text_content() or "").strip()
                                if opt_text.lower() == answer.lower():
                                    select.select_option(label=opt_text)
                                    logger.debug(
                                        f"Selected '{opt_text}' for '{pattern}'"
                                    )
                                    break
                            break
                except Exception:
                    continue
        except Exception:
            pass

    def _take_screenshot(self, page, job, output_dir=None):
        """Take screenshot before submitting an application.

        Saves to output/applications/{company}_{role}/screenshot.png.

        Args:
            page: Playwright Page instance.
            job: Job dict with company and title.
            output_dir: Optional custom output directory.

        Returns:
            Path to the saved screenshot file.
        """
        try:
            company = sanitize_filename(job.get("company", "unknown"))
            role = sanitize_filename(job.get("title", "role"))
            date_str = datetime.now().strftime("%Y-%m-%d")

            if output_dir:
                screenshot_dir = Path(output_dir)
            else:
                screenshot_dir = (
                    Path("output")
                    / "applications"
                    / f"{company}_{role}_{date_str}"
                )

            ensure_dir(screenshot_dir)
            screenshot_path = screenshot_dir / "screenshot.png"
            page.screenshot(path=str(screenshot_path))
            logger.info(f"Screenshot saved: {screenshot_path}")
            return str(screenshot_path)
        except Exception as e:
            logger.error(f"Failed to take screenshot: {e}")
            return ""

    def close(self):
        """Close browser resources and clean up."""
        try:
            if self.browser:
                self.browser.close()
            if self.playwright:
                self.playwright.stop()
            logger.info("Browser resources closed")
        except Exception as e:
            logger.error(f"Error closing browser: {e}")
