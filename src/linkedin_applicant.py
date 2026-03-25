"""LinkedIn job applicant module.

Handles submitting LinkedIn Easy Apply applications via browser automation.
"""

import logging
import os
import random
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
        self.screenshots: list[str] = []

    def connect_browser(self, cdp_url=None):
        """Connect to existing Chrome via CDP or use persistent context.

        Uses a persistent browser context at ~/.aipply/chrome-profile/
        so LinkedIn session cookies are preserved across runs.

        Args:
            cdp_url: Optional Chrome DevTools Protocol URL. If provided,
                     connects to an existing Chrome instance instead.
        """
        # Remove stale SingletonLock to prevent "profile in use" errors
        lock_path = Path.home() / ".aipply" / "chrome-profile" / "SingletonLock"
        try:
            os.remove(lock_path)
        except OSError:
            pass

        try:
            self.playwright = sync_playwright().start()
        except Exception as e:
            logger.error(f"Failed to connect browser: {e}")
            raise RuntimeError(f"Browser connection failed: {e}")

        if cdp_url:
            self.browser = self.playwright.chromium.connect_over_cdp(cdp_url)
            contexts = self.browser.contexts
            if contexts and contexts[0].pages:
                self.page = contexts[0].pages[0]
            else:
                self.page = contexts[0].new_page() if contexts else self.browser.new_context().new_page()
        else:
            profile_dir = Path.home() / ".aipply" / "chrome-profile"
            profile_dir.mkdir(parents=True, exist_ok=True)
            context = self.playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                headless=False,
                slow_mo=0,
                args=["--disable-blink-features=AutomationControlled"],
            )
            self.browser = context
            self.page = context.pages[0] if context.pages else context.new_page()

        logger.info("Browser connected for applicant")

    def apply_to_job(self, job, resume_path, cover_letter_path=None):
        """Apply to a single job via LinkedIn Easy Apply.

        Handles the full multi-step Easy Apply dialog with human-like
        random delays between every action.

        Args:
            job: Job dict with url, title, company, etc.
            resume_path: Path to the tailored resume file.
            cover_letter_path: Optional path to cover letter file.

        Returns:
            Result dict with success, status, reason, and screenshots list.
        """
        self.screenshots = []
        job_url = job.get("url", "")
        company = job.get("company", "unknown")
        role = job.get("title", "unknown")
        output_dir = None

        try:
            # Set up output directory for this job
            date_str = datetime.now().strftime("%Y-%m-%d")
            safe_company = sanitize_filename(company)
            safe_role = sanitize_filename(role)
            output_dir = Path("output") / "applications" / f"{safe_company}_{safe_role}_{date_str}"

            logger.info(f"Navigating to job: {role} at {company}")
            self.page.goto(job_url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(random.uniform(2, 5))

            # Check for CAPTCHA — only VISIBLE challenges, not background reCAPTCHA iframes
            captcha_present = False
            try:
                # Only #captcha-internal is a real blocking CAPTCHA on LinkedIn
                captcha_locator = self.page.locator('#captcha-internal')
                if captcha_locator.count() > 0 and captcha_locator.first.is_visible():
                    captcha_present = True
            except Exception:
                pass

            if captcha_present:
                logger.warning(f"Visible CAPTCHA challenge detected for {role} at {company}")
                self._take_screenshot(self.page, job, output_dir, "captcha_detected")
                return {
                    "success": False,
                    "status": "manual_needed",
                    "reason": "captcha_detected",
                    "screenshots": list(self.screenshots),
                }

            self._take_screenshot(self.page, job, output_dir, "job_page")

            # Check for Easy Apply button
            easy_apply_btn = self.page.locator(
                'button:has-text("Easy Apply"), button[aria-label*="Easy Apply"]'
            ).first
            try:
                easy_apply_btn.wait_for(state="visible", timeout=5000)
            except Exception:
                logger.info(f"No Easy Apply button for {role} at {company}")
                return {
                    "success": False,
                    "status": "manual_needed",
                    "reason": "not_easy_apply",
                    "screenshots": list(self.screenshots),
                }

            # Click Easy Apply
            time.sleep(random.uniform(2, 5))
            easy_apply_btn.click()
            time.sleep(random.uniform(2, 5))

            # Handle "Share your profile?" consent dialog
            self._handle_share_profile_dialog(self.page)

            # Multi-step form handling loop
            max_steps = 8
            for step in range(max_steps):
                time.sleep(random.uniform(2, 4))
                self._take_screenshot(self.page, job, output_dir, f"step_{step}")

                # Check if we have a Submit button
                if self._has_submit_button(self.page):
                    self._take_screenshot(self.page, job, output_dir, "pre_submit")
                    self._click_submit(self.page)
                    time.sleep(random.uniform(2, 4))
                    self._take_screenshot(self.page, job, output_dir, "post_submit")
                    logger.info(f"Successfully applied to {role} at {company}")
                    return {
                        "success": True,
                        "status": "applied",
                        "reason": "easy_apply_submitted",
                        "screenshots": list(self.screenshots),
                    }

                # Fill form fields for this step
                self._fill_contact_info(self.page)
                self._upload_resume(self.page, resume_path)
                self._answer_common_questions(self.page)
                self._click_next_or_continue(self.page)

            # Exhausted all steps without finding Submit
            self._take_screenshot(self.page, job, output_dir, "exhausted_steps")
            logger.warning(f"Could not complete application for {role} at {company}")
            return {
                "success": False,
                "status": "apply_failed",
                "reason": "dialog_navigation_failed_after_max_steps",
                "screenshots": list(self.screenshots),
            }

        except Exception as e:
            logger.error(f"Error applying to {role} at {company}: {e}")
            try:
                self._take_screenshot(self.page, job, output_dir, "error")
            except Exception:
                pass
            return {
                "success": False,
                "status": "apply_failed",
                "reason": str(e),
                "screenshots": list(self.screenshots),
            }

    def _handle_share_profile_dialog(self, page: Page):
        """Handle the 'Share your profile?' consent dialog that may appear.

        LinkedIn sometimes shows a consent dialog after clicking Easy Apply.
        If detected, click the Continue/primary button to proceed.

        Args:
            page: Playwright Page instance.
        """
        try:
            # Look for dialog text containing share profile language
            dialog_text = page.locator(
                'div[role="dialog"], .artdeco-modal'
            )
            if dialog_text.count() == 0:
                return

            modal_content = dialog_text.first.text_content() or ""
            share_phrases = [
                "share your profile",
                "share profile",
                "sharing your full profile",
            ]

            if any(phrase in modal_content.lower() for phrase in share_phrases):
                logger.info("Detected 'Share your profile' consent dialog")
                # Click the primary/Continue button
                continue_btn = page.locator(
                    'div[role="dialog"] button[data-easy-apply-next-button], '
                    '.artdeco-modal button.artdeco-button--primary, '
                    'div[role="dialog"] button:has-text("Continue"), '
                    'div[role="dialog"] button:has-text("Submit")'
                ).first
                try:
                    continue_btn.wait_for(state="visible", timeout=3000)
                    time.sleep(random.uniform(1, 3))
                    continue_btn.click()
                    time.sleep(random.uniform(2, 4))
                    logger.info("Clicked through share profile dialog")
                except Exception:
                    logger.debug("Could not find continue button in share dialog")
        except Exception as e:
            logger.debug(f"Share profile dialog check failed: {e}")

    def _has_submit_button(self, page: Page) -> bool:
        """Check if the current step has a Submit application button.

        Also recognizes "Review" button (which should be treated as
        a Next button, not Submit). Only returns True for actual Submit.

        Args:
            page: Playwright Page instance.

        Returns:
            True if a Submit application button is visible.
        """
        try:
            submit_locator = page.locator(
                'button:has-text("Submit application"), '
                'button[aria-label*="Submit application"]'
            )
            return submit_locator.count() > 0 and submit_locator.first.is_visible()
        except Exception:
            return False

    def _click_submit(self, page: Page):
        """Click the Submit application button.

        Args:
            page: Playwright Page instance.
        """
        try:
            submit_btn = page.locator(
                'button:has-text("Submit application"), '
                'button[aria-label*="Submit application"]'
            ).first
            time.sleep(random.uniform(1, 3))
            submit_btn.click()
            logger.info("Clicked Submit application")
        except Exception as e:
            logger.error(f"Failed to click submit: {e}")

    def _click_next_or_continue(self, page: Page):
        """Click Next, Continue, or Review button to advance the form.

        Args:
            page: Playwright Page instance.
        """
        try:
            next_btn = page.locator(
                'button[data-easy-apply-next-button], '
                'button[aria-label*="Continue to next step"], '
                'button:has-text("Next"), '
                'button:has-text("Review"), '
                'button:has-text("Continue")'
            ).first
            if next_btn.is_visible(timeout=3000):
                time.sleep(random.uniform(1, 3))
                next_btn.click()
                time.sleep(random.uniform(2, 4))
                logger.debug("Clicked next/continue button")
            else:
                logger.warning("No next/continue button found")
        except Exception as e:
            logger.debug(f"Next/continue button click failed: {e}")

    def _fill_contact_info(self, page: Page):
        """Fill in email, phone fields if they appear in the Easy Apply modal.

        LinkedIn uses a <select> dropdown for email (not input) and
        text inputs for phone number. Only fills empty/unselected fields.

        Args:
            page: Playwright Page instance.
        """
        # Email — LinkedIn uses a <select> dropdown for email
        try:
            modal = page.locator('div[role="dialog"], .artdeco-modal').first
            email_select = modal.locator("select").first
            if email_select.is_visible(timeout=1000):
                # Check if the desired email is available as an option
                target_email = "danna.dobi@gmail.com"
                options = email_select.locator("option").all()
                already_selected = False
                for opt in options:
                    opt_text = (opt.text_content() or "").strip()
                    opt_value = opt.get_attribute("value") or ""
                    if target_email in opt_text or target_email in opt_value:
                        # Check if it's already selected
                        current_val = email_select.input_value()
                        if current_val and (target_email in current_val or target_email in (email_select.evaluate("el => el.options[el.selectedIndex]?.text") or "")):
                            already_selected = True
                        if not already_selected:
                            time.sleep(random.uniform(1, 2))
                            email_select.select_option(label=opt_text)
                            logger.debug(f"Selected email: {target_email}")
                        break
        except Exception as e:
            logger.debug(f"Email select handling: {e}")

        # Phone number — text input near phone/mobile label
        try:
            phone_target = "5103338812"
            # Try multiple selectors for phone input
            phone_selectors = [
                'input[id*="phoneNumber"]',
                'input[name*="phoneNumber"]',
                'input[aria-label*="phone" i]',
                'input[aria-label*="mobile" i]',
            ]
            for selector in phone_selectors:
                try:
                    phone_input = page.locator(selector).first
                    if phone_input.is_visible(timeout=500):
                        current_val = phone_input.input_value()
                        if not current_val or not current_val.strip():
                            time.sleep(random.uniform(1, 2))
                            phone_input.fill(phone_target)
                            logger.debug("Filled phone number")
                        break
                except Exception:
                    continue

            # Also try finding by label text
            labels = page.locator("label").all()
            for label_el in labels:
                label_text = (label_el.text_content() or "").lower()
                if "phone" in label_text or "mobile" in label_text:
                    label_for = label_el.get_attribute("for")
                    if label_for:
                        try:
                            inp = page.locator(f"#{label_for}")
                            if inp.is_visible(timeout=500):
                                tag = inp.evaluate("el => el.tagName.toLowerCase()")
                                if tag == "input":
                                    current_val = inp.input_value()
                                    if not current_val or not current_val.strip():
                                        time.sleep(random.uniform(1, 2))
                                        inp.fill(phone_target)
                                        logger.debug("Filled phone via label lookup")
                                break
                        except Exception:
                            continue
        except Exception as e:
            logger.debug(f"Phone input handling: {e}")

    def _upload_resume(self, page: Page, resume_path):
        """Find file input inside the modal and upload the resume.

        Args:
            page: Playwright Page instance.
            resume_path: Path to the resume file to upload.
        """
        try:
            modal = page.locator('div[role="dialog"], .artdeco-modal').first
            file_input = modal.locator('input[type="file"]').first
            if file_input.count() > 0:
                time.sleep(random.uniform(1, 2))
                file_input.set_input_files(str(resume_path))
                logger.debug(f"Uploaded resume: {resume_path}")
                time.sleep(random.uniform(2, 4))
        except Exception as e:
            logger.debug(f"Resume upload skipped or failed: {e}")

    def _answer_common_questions(self, page: Page):
        """Handle common Easy Apply questions with predefined answers.

        Handles radio buttons, select dropdowns, and text/number inputs
        for common questions like work authorization, sponsorship, etc.

        Args:
            page: Playwright Page instance.
        """
        # Pattern → answer mapping
        question_answers = {
            "authorized to work": "Yes",
            "work authorization": "Yes",
            "legally authorized": "Yes",
            "require sponsorship": "No",
            "sponsorship": "No",
            "visa sponsorship": "No",
            "years of experience": "9",
            "experience do you have": "9",
        }

        # Handle radio buttons (fieldset/legend based)
        try:
            fieldsets = page.locator("fieldset").all()
            for fieldset in fieldsets:
                try:
                    legend = fieldset.locator("legend, span.visually-hidden, span[aria-hidden='true']").first
                    legend_text = (legend.text_content() or "").lower().strip()
                    if not legend_text:
                        # Try getting all text from the fieldset label area
                        legend_text = (fieldset.locator("legend").text_content() or "").lower().strip()
                    if not legend_text:
                        continue

                    for pattern, answer in question_answers.items():
                        if pattern in legend_text:
                            # Find the matching radio option
                            radio_labels = fieldset.locator("label").all()
                            for radio_label in radio_labels:
                                label_text = (radio_label.text_content() or "").strip()
                                if label_text.lower() == answer.lower():
                                    radio_input = radio_label.locator("input[type='radio']")
                                    if radio_input.count() > 0 and not radio_input.is_checked():
                                        time.sleep(random.uniform(1, 2))
                                        radio_label.click()
                                        logger.debug(f"Selected radio '{label_text}' for '{pattern}'")
                                    break
                            break
                except Exception:
                    continue
        except Exception:
            pass

        # Handle select dropdowns
        try:
            selects = page.locator("select").all()
            for select_el in selects:
                try:
                    label_text = self._get_field_label(page, select_el)
                    if not label_text:
                        continue

                    for pattern, answer in question_answers.items():
                        if pattern in label_text:
                            options = select_el.locator("option").all()
                            for opt in options:
                                opt_text = (opt.text_content() or "").strip()
                                if opt_text.lower() == answer.lower():
                                    time.sleep(random.uniform(1, 2))
                                    select_el.select_option(label=opt_text)
                                    logger.debug(f"Selected '{opt_text}' for '{pattern}'")
                                    break
                            break
                except Exception:
                    continue
        except Exception:
            pass

        # Handle text and number inputs
        try:
            inputs = page.locator(
                "input[type='text'], input[type='number'], input:not([type])"
            ).all()
            for inp in inputs:
                try:
                    label_text = self._get_field_label(page, inp)
                    if not label_text:
                        continue

                    current_val = inp.input_value()
                    if current_val and current_val.strip():
                        continue  # Don't overwrite existing values

                    for pattern, answer in question_answers.items():
                        if pattern in label_text:
                            time.sleep(random.uniform(1, 2))
                            inp.fill(answer)
                            logger.debug(f"Filled '{answer}' for '{pattern}'")
                            break
                except Exception:
                    continue
        except Exception:
            pass

    def _get_field_label(self, page: Page, element) -> str:
        """Get the label text for a form element.

        Checks for associated <label>, aria-label, and placeholder.

        Args:
            page: Playwright Page instance.
            element: Playwright Locator for the form element.

        Returns:
            Lowercase label text, or empty string if not found.
        """
        try:
            # Try label[for=id]
            el_id = element.get_attribute("id") or ""
            if el_id:
                label = page.locator(f'label[for="{el_id}"]')
                if label.count() > 0:
                    return (label.text_content() or "").lower().strip()

            # Try aria-label
            aria = element.get_attribute("aria-label") or ""
            if aria:
                return aria.lower().strip()

            # Try aria-labelledby
            labelled_by = element.get_attribute("aria-labelledby") or ""
            if labelled_by:
                ref_el = page.locator(f"#{labelled_by}")
                if ref_el.count() > 0:
                    return (ref_el.text_content() or "").lower().strip()

            # Try placeholder
            placeholder = element.get_attribute("placeholder") or ""
            if placeholder:
                return placeholder.lower().strip()

        except Exception:
            pass
        return ""

    def _take_screenshot(self, page: Page, job: dict, output_dir=None, label="screenshot") -> str:
        """Take a screenshot and store the path in self.screenshots.

        Each screenshot gets a unique name: {label}_{timestamp}.png

        Args:
            page: Playwright Page instance.
            job: Job dict with company and title.
            output_dir: Optional custom output directory.
            label: Descriptive label for the screenshot filename.

        Returns:
            Path to the saved screenshot file.
        """
        try:
            if output_dir:
                screenshot_dir = Path(output_dir)
            else:
                company = sanitize_filename(job.get("company", "unknown"))
                role = sanitize_filename(job.get("title", "role"))
                date_str = datetime.now().strftime("%Y-%m-%d")
                screenshot_dir = (
                    Path("output")
                    / "applications"
                    / f"{company}_{role}_{date_str}"
                )

            ensure_dir(screenshot_dir)
            timestamp = datetime.now().strftime("%H%M%S_%f")
            filename = f"{label}_{timestamp}.png"
            screenshot_path = screenshot_dir / filename
            page.screenshot(path=str(screenshot_path))
            path_str = str(screenshot_path)
            self.screenshots.append(path_str)
            logger.info(f"Screenshot saved: {path_str}")
            return path_str
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
