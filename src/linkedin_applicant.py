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

            # Convert search URLs to direct job view URLs for reliable navigation
            import re
            job_id_match = re.search(r'currentJobId=(\d+)', job_url) or re.search(r'/jobs/view/(\d+)', job_url)
            if job_id_match:
                direct_url = f"https://www.linkedin.com/jobs/view/{job_id_match.group(1)}/"
                logger.info(f"Navigating to direct job URL: {direct_url}")
            else:
                direct_url = job_url
                logger.info(f"Navigating to job URL: {direct_url}")
            
            self.page.goto(direct_url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(random.uniform(3, 6))

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

            # Find Apply button — Easy Apply (stays on LinkedIn) or Apply (external)
            easy_apply_btn = None
            external_apply_btn = None
            is_easy_apply = False

            # First: look for Easy Apply
            for ea_selector in [
                'a[aria-label*="Easy Apply"]',
                'a:has-text("Easy Apply")',
                'button[aria-label*="Easy Apply"]',
                'button:has-text("Easy Apply")',
            ]:
                try:
                    loc = self.page.locator(ea_selector).first
                    if loc.is_visible(timeout=2000):
                        btn_text = loc.inner_text().strip()
                        if "Easy" in btn_text:
                            easy_apply_btn = loc
                            is_easy_apply = True
                            logger.info(f"Found Easy Apply: '{btn_text}'")
                            break
                except Exception:
                    continue

            # Second: if no Easy Apply, look for external Apply
            if not easy_apply_btn:
                for ap_selector in [
                    'a[aria-label*="Apply to this job"]',
                    'a:has-text("Apply")',
                    'button:has-text("Apply")',
                ]:
                    try:
                        loc = self.page.locator(ap_selector).first
                        if loc.is_visible(timeout=2000):
                            external_apply_btn = loc
                            logger.info(f"Found external Apply button")
                            break
                    except Exception:
                        continue

            if not easy_apply_btn and not external_apply_btn:
                logger.info(f"No Apply button found for {role} at {company}")
                return {
                    "success": False,
                    "status": "manual_needed",
                    "reason": "no_apply_button",
                    "screenshots": list(self.screenshots),
                }

            # Handle external Apply — open the career site and try to fill out the form
            if external_apply_btn and not easy_apply_btn:
                logger.info(f"External Apply for {role} at {company} — navigating to career site")
                time.sleep(random.uniform(2, 4))
                external_apply_btn.click()
                time.sleep(random.uniform(4, 7))

                # Switch to the new tab if one opened
                pages = self.page.context.pages
                ext_page = pages[-1] if len(pages) > 1 else self.page
                time.sleep(random.uniform(2, 4))
                self._take_screenshot(ext_page, job, output_dir, "external_career_site")
                logger.info(f"External career site: {ext_page.url}")

                # Try to fill out external application form
                try:
                    result = self._fill_external_application(ext_page, job, resume_path, cover_letter_path, output_dir)
                    if len(pages) > 1:
                        ext_page.close()
                    return result
                except Exception as e:
                    logger.warning(f"External application failed: {e}")
                    if len(pages) > 1:
                        ext_page.close()
                    return {
                        "success": False,
                        "status": "manual_needed",
                        "reason": f"external_apply_failed: {e}",
                        "screenshots": list(self.screenshots),
                    }

            # Click Easy Apply
            time.sleep(random.uniform(2, 5))
            easy_apply_btn.click()
            time.sleep(random.uniform(2, 5))

            # Handle "Share your profile?" consent dialog
            self._handle_share_profile_dialog(self.page)

            # Multi-step form handling loop
            max_steps = 15
            prev_page_text = ""
            stuck_count = 0

            for step in range(max_steps):
                time.sleep(random.uniform(2, 4))
                self._take_screenshot(self.page, job, output_dir, f"step_{step}")

                # Check for submission confirmation (dialog may have closed)
                try:
                    page_text = self.page.evaluate("() => document.body.innerText").lower()
                    if "application was sent" in page_text or "application submitted" in page_text:
                        self._take_screenshot(self.page, job, output_dir, "confirmed_submit")
                        logger.info(f"Application confirmed submitted for {role} at {company}")
                        return {
                            "success": True,
                            "status": "applied",
                            "reason": "easy_apply_confirmed",
                            "screenshots": list(self.screenshots),
                        }
                except Exception:
                    pass

                # Check if dialog was dismissed (application might have been submitted or closed)
                try:
                    dialog = self.page.locator('div[role="dialog"], .artdeco-modal')
                    if dialog.count() == 0:
                        # Dialog gone — check for confirmation text
                        body_text = self.page.evaluate("() => document.body.innerText").lower()
                        if "application was sent" in body_text or "application submitted" in body_text:
                            self._take_screenshot(self.page, job, output_dir, "dialog_closed_confirmed")
                            logger.info(f"Dialog closed with confirmation for {role} at {company}")
                            return {
                                "success": True,
                                "status": "applied",
                                "reason": "easy_apply_dialog_closed_confirmed",
                                "screenshots": list(self.screenshots),
                            }
                        else:
                            logger.warning(f"Dialog dismissed without confirmation for {role} at {company}")
                            return {
                                "success": False,
                                "status": "apply_failed",
                                "reason": "dialog_dismissed_without_confirmation",
                                "screenshots": list(self.screenshots),
                            }
                except Exception:
                    pass

                # Detect stuck step (same dialog content for 2+ iterations)
                try:
                    current_text = self.page.evaluate(
                        "() => document.querySelector('[role=\"dialog\"]')?.innerText || ''"
                    )
                    if current_text and current_text == prev_page_text:
                        stuck_count += 1
                        if stuck_count >= 2:
                            logger.warning(
                                f"Stuck on same step for {stuck_count} iterations, giving up on {role} at {company}"
                            )
                            self._take_screenshot(self.page, job, output_dir, "stuck_step")
                            break
                    else:
                        stuck_count = 0
                    prev_page_text = current_text
                except Exception:
                    pass

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
                self._handle_resume_step(self.page, resume_path)
                self._handle_cover_letter_upload(self.page, cover_letter_path)
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

        NOTE: Does NOT include "Submit application" — that is handled
        exclusively by _click_submit() to avoid race conditions.

        Args:
            page: Playwright Page instance.
        """
        try:
            next_btn = page.locator(
                'button[data-easy-apply-next-button], '
                'button[aria-label*="Continue to next step"], '
                'footer button.artdeco-button--primary, '
                '.jobs-easy-apply-modal button.artdeco-button--primary, '
                '[role="dialog"] footer button.artdeco-button--primary, '
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

    def _handle_resume_step(self, page: Page, resume_path):
        """Handle the resume step — upload if needed, skip if already present.

        Wrapper that checks for the resume upload area and delegates
        to _upload_resume for the actual upload.

        Args:
            page: Playwright Page instance.
            resume_path: Path to the resume file to upload.
        """
        self._upload_resume(page, resume_path)

    def _handle_cover_letter_upload(self, page: Page, cover_letter_path):
        """Upload cover letter if the form has a cover letter upload section.

        Args:
            page: Playwright Page instance.
            cover_letter_path: Path to the cover letter file.
        """
        if not cover_letter_path or not os.path.exists(str(cover_letter_path)):
            return
        try:
            modal = page.locator('div[role="dialog"], .artdeco-modal').first
            modal_text = (modal.text_content() or "").lower()
            if "cover letter" not in modal_text:
                return

            # Pattern 1: Direct file input for cover letter (second file input after resume)
            file_inputs = modal.locator('input[type="file"]').all()
            for fi in file_inputs:
                label = (fi.get_attribute("aria-label") or "").lower()
                # Some LinkedIn forms label the second file input for cover letters
                if "cover" in label:
                    fi.set_input_files(str(cover_letter_path))
                    time.sleep(random.uniform(2, 3))
                    logger.debug(f"Uploaded cover letter via labeled file input")
                    return

            # Pattern 2: "Upload cover letter" button
            cl_btn = modal.locator(
                'button:has-text("Upload cover letter"), '
                'label:has-text("Upload cover letter")'
            )
            if cl_btn.count() > 0 and cl_btn.first.is_visible():
                with page.expect_file_chooser(timeout=5000) as fc_info:
                    cl_btn.first.click()
                file_chooser = fc_info.value
                file_chooser.set_files(str(cover_letter_path))
                time.sleep(random.uniform(2, 3))
                logger.debug(f"Uploaded cover letter via button: {cover_letter_path}")
                return

            # Pattern 3: If there are exactly 2 file inputs, second one is likely cover letter
            if len(file_inputs) >= 2:
                file_inputs[1].set_input_files(str(cover_letter_path))
                time.sleep(random.uniform(2, 3))
                logger.debug(f"Uploaded cover letter via second file input")
                return

        except Exception as e:
            logger.debug(f"Cover letter upload: {e}")

    def _upload_resume(self, page: Page, resume_path):
        """Handle resume upload step — handles multiple LinkedIn patterns.

        Pattern 1: Direct file input visible in the modal.
        Pattern 2: "Upload resume" button that reveals a file input.
        Pattern 3: Resume already uploaded (filename visible in upload area).

        Args:
            page: Playwright Page instance.
            resume_path: Path to the resume file to upload.

        Returns:
            True if resume was uploaded or already present, False otherwise.
        """
        try:
            modal = page.locator('div[role="dialog"], .artdeco-modal').first

            # Pattern 1: Direct file input
            file_input = modal.locator('input[type="file"]')
            if file_input.count() > 0:
                time.sleep(random.uniform(1, 2))
                file_input.first.set_input_files(str(resume_path))
                time.sleep(random.uniform(2, 4))
                logger.debug(f"Uploaded resume via file input: {resume_path}")
                return True

            # Pattern 2: "Upload resume" button that reveals file input
            upload_btn = modal.locator(
                'button:has-text("Upload resume"), '
                'button:has-text("Upload"), '
                'label:has-text("Upload")'
            )
            if upload_btn.count() > 0 and upload_btn.first.is_visible():
                upload_btn.first.click()
                time.sleep(1)
                file_input = modal.locator('input[type="file"]')
                if file_input.count() > 0:
                    file_input.first.set_input_files(str(resume_path))
                    time.sleep(random.uniform(2, 4))
                    logger.debug(f"Uploaded resume via upload button: {resume_path}")
                    return True

            # Pattern 3: Resume already uploaded (check for resume filename text)
            resume_area = modal.locator(
                '.jobs-document-upload, [class*="document-upload"]'
            )
            if resume_area.count() > 0:
                area_text = resume_area.first.text_content() or ""
                if any(ext in area_text.lower() for ext in [".docx", ".pdf", "resume"]):
                    logger.debug("Resume appears to be already uploaded")
                    return True

        except Exception as e:
            logger.debug(f"Resume upload: {e}")
        return False

    def _answer_common_questions(self, page: Page):
        """Handle common Easy Apply questions with predefined answers.

        Comprehensive handler for radio buttons, select dropdowns,
        text/number inputs, and textareas — covering work authorization,
        sponsorship, experience, salary, location, EEO, and more.

        Ported from cycle_20260325_0732.py for full coverage.

        Args:
            page: Playwright Page instance.
        """
        self._answer_radio_questions(page)
        self._answer_text_inputs(page)
        self._answer_select_dropdowns(page)
        self._answer_textareas(page)

    def _answer_radio_questions(self, page: Page):
        """Handle radio button questions (fieldset/legend based).

        Covers: work authorization, sponsorship, commute/relocate,
        background check, and EEO questions (gender/race/veteran/disability).
        """
        try:
            fieldsets = page.locator("fieldset").all()
            for fieldset in fieldsets:
                try:
                    legend = fieldset.locator("legend")
                    legend_text = (legend.text_content() or "").lower().strip() if legend.count() > 0 else ""
                    if not legend_text:
                        # Try span inside the fieldset for visually-hidden legends
                        span = fieldset.locator("legend span, span.visually-hidden").first
                        legend_text = (span.text_content() or "").lower().strip() if span.count() > 0 else ""
                    if not legend_text:
                        continue

                    # Work authorization / legally authorized / eligible
                    if any(kw in legend_text for kw in ["authorized", "legally", "eligible"]):
                        yes_label = fieldset.locator("label:has-text('Yes')").first
                        if yes_label.is_visible(timeout=500):
                            time.sleep(random.uniform(1, 2))
                            yes_label.click()
                            logger.debug(f"Radio: Yes for '{legend_text[:40]}'")

                    # Sponsorship
                    elif any(kw in legend_text for kw in ["sponsorship", "sponsor"]):
                        no_label = fieldset.locator("label:has-text('No')").first
                        if no_label.is_visible(timeout=500):
                            time.sleep(random.uniform(1, 2))
                            no_label.click()
                            logger.debug(f"Radio: No for '{legend_text[:40]}'")

                    # Commute / relocate
                    elif any(kw in legend_text for kw in ["commute", "relocat"]):
                        yes_label = fieldset.locator("label:has-text('Yes')").first
                        if yes_label.is_visible(timeout=500):
                            time.sleep(random.uniform(1, 2))
                            yes_label.click()
                            logger.debug(f"Radio: Yes for '{legend_text[:40]}'")

                    # Background check / drug test
                    elif any(kw in legend_text for kw in ["background check", "drug"]):
                        yes_label = fieldset.locator("label:has-text('Yes')").first
                        if yes_label.is_visible(timeout=500):
                            time.sleep(random.uniform(1, 2))
                            yes_label.click()
                            logger.debug(f"Radio: Yes for '{legend_text[:40]}'")

                    # License/certification questions — always Yes
                    elif any(kw in legend_text for kw in [
                        "license", "certification", "certified",
                        "public accountant", "cpa",
                    ]):
                        yes_label = fieldset.locator("label:has-text('Yes')").first
                        if yes_label.is_visible(timeout=500):
                            time.sleep(random.uniform(1, 2))
                            yes_label.click()
                            logger.debug(f"Radio: Yes for '{legend_text[:40]}'")

                    # Experience / skill / proficiency / software questions — always Yes
                    elif any(kw in legend_text for kw in [
                        "experience", "proficien", "familiar", "skill",
                        "software", "knowledge", "ability", "capable",
                        "competent", "qualified", "do you have",
                    ]):
                        yes_label = fieldset.locator("label:has-text('Yes')").first
                        if yes_label.is_visible(timeout=500):
                            time.sleep(random.uniform(1, 2))
                            yes_label.click()
                            logger.debug(f"Radio: Yes for '{legend_text[:40]}'")

                    # EEO questions — decline to self-identify
                    elif any(kw in legend_text for kw in [
                        "gender", "race", "veteran", "disability", "ethnicity",
                    ]):
                        decline = fieldset.locator(
                            "label:has-text('Decline'), "
                            "label:has-text('decline'), "
                            "label:has-text('prefer not')"
                        ).first
                        if decline.is_visible(timeout=500):
                            time.sleep(random.uniform(1, 2))
                            decline.click()
                            logger.debug(f"Radio: Decline for EEO '{legend_text[:40]}'")

                    # CATCH-ALL: Any other Yes/No question — always say Yes
                    else:
                        yes_label = fieldset.locator("label:has-text('Yes')").first
                        if yes_label.is_visible(timeout=500):
                            time.sleep(random.uniform(1, 2))
                            yes_label.click()
                            logger.debug(f"Radio: Yes (catch-all) for '{legend_text[:40]}'")

                except Exception:
                    continue
        except Exception:
            pass

    def _answer_text_inputs(self, page: Page):
        """Handle text and number input questions.

        Covers: years of experience (domain-specific and generic), salary,
        city/location, LinkedIn URL, GPA, zip/postal, and address.
        """
        try:
            inputs = page.locator(
                'div[role="dialog"] input[type="text"], '
                'div[role="dialog"] input[type="number"]'
            ).all()
            for inp in inputs:
                try:
                    label_text = self._get_field_label(page, inp)
                    if not label_text:
                        continue

                    current_val = inp.input_value()
                    if current_val and current_val.strip():
                        continue  # Don't overwrite existing values

                    # Domain-specific experience years
                    if "year" in label_text and any(
                        w in label_text for w in [
                            "experience", "compliance", "audit", "risk",
                            "regulation", "banking", "financial", "aml",
                            "bsa", "fraud", "governance", "examination",
                        ]
                    ):
                        inp.fill("9")
                        logger.debug(f"Filled '9' for domain experience: '{label_text[:40]}'")
                    # Generic years
                    elif "year" in label_text:
                        inp.fill("9")
                        logger.debug(f"Filled '9' for generic years: '{label_text[:40]}'")
                    # Salary / compensation
                    elif any(kw in label_text for kw in ["salary", "compensation", "pay", "desired"]):
                        inp.fill("130000")
                        logger.debug(f"Filled '130000' for salary: '{label_text[:40]}'")
                    # City / location
                    elif any(kw in label_text for kw in ["city", "location"]):
                        inp.fill("San Francisco, CA")
                        logger.debug(f"Filled 'San Francisco, CA' for: '{label_text[:40]}'")
                    # LinkedIn URL
                    elif "linkedin" in label_text:
                        inp.fill("https://www.linkedin.com/in/dannadobi")
                        logger.debug(f"Filled LinkedIn URL for: '{label_text[:40]}'")
                    # GPA
                    elif "gpa" in label_text:
                        inp.fill("3.7")
                        logger.debug(f"Filled '3.7' for GPA: '{label_text[:40]}'")
                    # Zip / postal code
                    elif any(kw in label_text for kw in ["zip", "postal"]):
                        inp.fill("94102")
                        logger.debug(f"Filled '94102' for zip: '{label_text[:40]}'")
                    # Address
                    elif "address" in label_text:
                        inp.fill("San Francisco, CA")
                        logger.debug(f"Filled address for: '{label_text[:40]}'")
                    # Work authorization / sponsorship text inputs
                    elif any(kw in label_text for kw in ["authorized", "legally"]):
                        inp.fill("Yes")
                        logger.debug(f"Filled 'Yes' for: '{label_text[:40]}'")
                    elif "sponsorship" in label_text or "sponsor" in label_text:
                        inp.fill("No")
                        logger.debug(f"Filled 'No' for: '{label_text[:40]}'")

                    time.sleep(random.uniform(0.5, 1.5))
                except Exception:
                    continue
        except Exception:
            pass

    def _answer_select_dropdowns(self, page: Page):
        """Handle select dropdown questions.

        Covers: work authorization, sponsorship, education/degree level,
        experience/proficiency level, and EEO questions.
        """
        try:
            selects = page.locator('div[role="dialog"] select').all()
            for select_el in selects:
                try:
                    label_text = self._get_field_label(page, select_el)
                    if not label_text:
                        continue

                    current_val = select_el.input_value()
                    if current_val and current_val.strip() and current_val != "Select an option":
                        continue

                    opts = select_el.locator("option").all()

                    # Work authorization
                    if any(kw in label_text for kw in ["authorized", "legal"]):
                        for o in opts:
                            if "yes" in (o.text_content() or "").lower():
                                select_el.select_option(label=o.text_content().strip())
                                logger.debug(f"Select: Yes for '{label_text[:40]}'")
                                break

                    # Sponsorship
                    elif "sponsor" in label_text:
                        for o in opts:
                            if "no" in (o.text_content() or "").lower():
                                select_el.select_option(label=o.text_content().strip())
                                logger.debug(f"Select: No for '{label_text[:40]}'")
                                break

                    # Education / degree
                    elif any(kw in label_text for kw in ["education", "degree"]):
                        for o in opts:
                            if "bachelor" in (o.text_content() or "").lower():
                                select_el.select_option(label=o.text_content().strip())
                                logger.debug(f"Select: Bachelor's for '{label_text[:40]}'")
                                break

                    # Experience / proficiency level
                    elif any(kw in label_text for kw in ["experience", "proficiency"]):
                        for o in opts:
                            ot = (o.text_content() or "").lower()
                            if "expert" in ot or "advanced" in ot:
                                select_el.select_option(label=o.text_content().strip())
                                logger.debug(f"Select: Advanced/Expert for '{label_text[:40]}'")
                                break

                    # EEO (gender/race/veteran/disability)
                    elif any(kw in label_text for kw in [
                        "gender", "race", "veteran", "disability",
                    ]):
                        for o in opts:
                            ot = (o.text_content() or "").lower()
                            if "decline" in ot or "prefer not" in ot:
                                select_el.select_option(label=o.text_content().strip())
                                logger.debug(f"Select: Decline for EEO '{label_text[:40]}'")
                                break

                    time.sleep(random.uniform(0.5, 1.5))
                except Exception:
                    continue
        except Exception:
            pass

    def _answer_textareas(self, page: Page):
        """Handle textarea questions (cover letter, additional info).

        Args:
            page: Playwright Page instance.
        """
        try:
            textareas = page.locator('div[role="dialog"] textarea').all()
            for ta in textareas:
                try:
                    val = ta.input_value()
                    if val and val.strip():
                        continue

                    label_text = ""
                    ta_id = ta.get_attribute("id") or ""
                    if ta_id:
                        lbl = page.locator(f'label[for="{ta_id}"]')
                        if lbl.count() > 0:
                            label_text = (lbl.text_content() or "").lower()
                    if not label_text:
                        label_text = (ta.get_attribute("aria-label") or "").lower()

                    # Cover letter or additional info — provide professional summary
                    if any(kw in label_text for kw in ["cover letter", "additional", "summary", "about"]):
                        ta.fill(
                            "I bring 9+ years of compliance and regulatory experience, "
                            "including federal bank examination at the OCC and hands-on roles "
                            "in fintech and banking. I hold CFE and CAMS certifications."
                        )
                        logger.debug(f"Filled textarea for: '{label_text[:40]}'")
                    elif label_text:
                        # Generic professional answer for unknown textareas
                        ta.fill(
                            "I bring 9+ years of compliance and regulatory experience, "
                            "including federal bank examination at the OCC and hands-on roles "
                            "in fintech and banking."
                        )
                        logger.debug(f"Filled textarea (generic) for: '{label_text[:40]}'")

                    time.sleep(random.uniform(0.5, 1.5))
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

    def _fill_external_application(self, page, job, resume_path, cover_letter_path, output_dir):
        """Try to fill out an external career site application form.

        Uses common patterns across ATS systems (Greenhouse, Lever, Workday, etc.)
        to find and fill form fields, upload resume, and submit.

        Supports Workday iframe detection, login/signup page detection,
        LinkedIn URL fields, cover letter upload, and minimum-fields threshold.
        """
        company = job.get("company", "")
        role = job.get("title", "")
        logger.info(f"Attempting external application on {page.url}")

        # --- Login/signup detection ---
        try:
            page_text = page.evaluate("() => document.body.innerText").lower()
            if any(phrase in page_text for phrase in [
                "sign in", "create account", "sign up", "log in", "register",
            ]):
                login_forms = page.query_selector_all('form input[type="password"]')
                if login_forms:
                    logger.info("Login/signup page detected, marking as manual_needed")
                    self._take_screenshot(page, job, output_dir, "external_login_detected")
                    return {
                        "success": False,
                        "status": "manual_needed",
                        "reason": "login_required",
                        "screenshots": list(self.screenshots),
                    }
        except Exception as e:
            logger.debug(f"Login detection check failed: {e}")

        # --- Workday iframe detection ---
        workday_frame = None
        for frame_src_pattern in ["workday.com", "myworkdayjobs.com"]:
            try:
                frame = page.frame_locator(f'iframe[src*="{frame_src_pattern}"]')
                if frame.locator("body").count() > 0:
                    workday_frame = frame
                    logger.info(f"Detected Workday iframe ({frame_src_pattern})")
                    break
            except Exception:
                pass

        # Helper: query element — uses workday_frame if present, else page
        def _q(selector):
            """Query a single element, preferring Workday iframe context."""
            if workday_frame:
                loc = workday_frame.locator(selector)
                if loc.count() > 0:
                    return loc.first
                return None
            return page.query_selector(selector)

        def _q_all(selector):
            """Query all matching elements, preferring Workday iframe context."""
            if workday_frame:
                loc = workday_frame.locator(selector)
                return [loc.nth(i) for i in range(loc.count())]
            return page.query_selector_all(selector)

        # Common field patterns across ATS systems
        name_fields = [
            'input[name*="name" i]', 'input[placeholder*="name" i]',
            'input[aria-label*="name" i]', 'input#first_name', 'input#last_name',
            'input[name*="first" i]', 'input[name*="last" i]',
        ]
        email_fields = [
            'input[type="email"]', 'input[name*="email" i]',
            'input[placeholder*="email" i]', 'input[aria-label*="email" i]',
        ]
        phone_fields = [
            'input[type="tel"]', 'input[name*="phone" i]',
            'input[placeholder*="phone" i]', 'input[aria-label*="phone" i]',
        ]
        linkedin_fields = [
            'input[name*="linkedin" i]', 'input[placeholder*="linkedin" i]',
            'input[aria-label*="linkedin" i]', 'input[name*="url" i]',
            'input[placeholder*="URL" i]',
        ]
        resume_fields = [
            'input[type="file"]', 'input[accept*=".pdf" i]',
            'input[accept*=".doc" i]', 'input[name*="resume" i]',
        ]

        # Workday-specific selectors
        workday_name_fields = [
            'input[data-automation-id="name"]',
            'input[data-automation-id="legalNameSection_firstName"]',
            'input[data-automation-id="legalNameSection_lastName"]',
        ]
        workday_email_fields = ['input[data-automation-id="email"]']
        workday_phone_fields = ['input[data-automation-id="phone"]']

        filled_count = 0

        # --- Fill name fields (standard) ---
        for sel in name_fields:
            try:
                el = _q(sel)
                if el:
                    is_vis = el.is_visible() if hasattr(el, 'is_visible') else True
                    if is_vis:
                        val = el.input_value() or ""
                        if not val.strip():
                            field_name = ""
                            try:
                                field_name = (el.get_attribute("name") or el.get_attribute("placeholder") or "").lower()
                            except Exception:
                                pass
                            if "first" in field_name:
                                el.fill("Danna")
                            elif "last" in field_name:
                                el.fill("Dobi")
                            else:
                                el.fill("Danna Dobi")
                            time.sleep(random.uniform(1, 2))
                            filled_count += 1
                            logger.info(f"Filled name field: {sel}")
            except Exception:
                pass

        # --- Fill name fields (Workday-specific) ---
        if workday_frame:
            for sel in workday_name_fields:
                try:
                    el = _q(sel)
                    if el:
                        val = el.input_value() or ""
                        if not val.strip():
                            auto_id = ""
                            try:
                                auto_id = el.get_attribute("data-automation-id") or ""
                            except Exception:
                                pass
                            if "firstName" in auto_id:
                                el.fill("Danna")
                            elif "lastName" in auto_id:
                                el.fill("Dobi")
                            else:
                                el.fill("Danna Dobi")
                            time.sleep(random.uniform(1, 2))
                            filled_count += 1
                            logger.info(f"Filled Workday name field: {sel}")
                except Exception:
                    pass

        # --- Fill email (standard + Workday) ---
        all_email_sels = email_fields + (workday_email_fields if workday_frame else [])
        for sel in all_email_sels:
            try:
                el = _q(sel)
                if el:
                    is_vis = el.is_visible() if hasattr(el, 'is_visible') else True
                    if is_vis:
                        val = el.input_value() or ""
                        if not val.strip():
                            el.fill("danna.dobi@gmail.com")
                            time.sleep(random.uniform(1, 2))
                            filled_count += 1
                            logger.info(f"Filled email: {sel}")
            except Exception:
                pass

        # --- Fill phone (standard + Workday) ---
        all_phone_sels = phone_fields + (workday_phone_fields if workday_frame else [])
        for sel in all_phone_sels:
            try:
                el = _q(sel)
                if el:
                    is_vis = el.is_visible() if hasattr(el, 'is_visible') else True
                    if is_vis:
                        val = el.input_value() or ""
                        if not val.strip():
                            el.fill("5103338812")
                            time.sleep(random.uniform(1, 2))
                            filled_count += 1
                            logger.info(f"Filled phone: {sel}")
            except Exception:
                pass

        # --- Fill LinkedIn URL ---
        for sel in linkedin_fields:
            try:
                el = _q(sel)
                if el:
                    is_vis = el.is_visible() if hasattr(el, 'is_visible') else True
                    if is_vis:
                        val = el.input_value() or ""
                        if not val.strip():
                            el.fill("https://www.linkedin.com/in/dannadobi")
                            time.sleep(random.uniform(1, 2))
                            filled_count += 1
                            logger.info(f"Filled LinkedIn URL: {sel}")
            except Exception:
                pass

        # --- Upload resume ---
        for sel in resume_fields:
            try:
                el = _q(sel)
                if el:
                    if resume_path and os.path.exists(str(resume_path)):
                        el.set_input_files(str(resume_path))
                        time.sleep(random.uniform(2, 4))
                        filled_count += 1
                        logger.info(f"Uploaded resume via {sel}")
                    break
            except Exception:
                pass

        # --- Upload cover letter ---
        if cover_letter_path and os.path.exists(str(cover_letter_path)):
            cl_upload_sels = [
                'input[type="file"][name*="cover" i]',
                'input[type="file"][accept*=".pdf" i]',
            ]
            all_file_inputs = _q_all('input[type="file"]')
            cl_uploaded = False

            for sel in cl_upload_sels:
                try:
                    el = _q(sel)
                    if el:
                        el.set_input_files(str(cover_letter_path))
                        time.sleep(random.uniform(2, 4))
                        filled_count += 1
                        cl_uploaded = True
                        logger.info(f"Uploaded cover letter via {sel}")
                        break
                except Exception:
                    pass

            # Try second file input as fallback (first is usually resume)
            if not cl_uploaded and len(all_file_inputs) >= 2:
                try:
                    second_input = all_file_inputs[1]
                    second_input.set_input_files(str(cover_letter_path))
                    time.sleep(random.uniform(2, 4))
                    filled_count += 1
                    logger.info("Uploaded cover letter via second file input")
                except Exception as e:
                    logger.debug(f"Cover letter upload via second file input failed: {e}")

        time.sleep(random.uniform(2, 4))
        self._take_screenshot(page, job, output_dir, "external_form_filled")

        # --- Minimum fields threshold ---
        if filled_count < 2:
            logger.info(f"Only filled {filled_count} field(s), marking as manual_needed")
            return {
                "success": False,
                "status": "manual_needed",
                "reason": "external_form_too_few_fields_filled",
                "screenshots": list(self.screenshots),
            }

        # Try to find and click submit
        submitted = False
        for submit_sel in [
            'button[type="submit"]',
            'input[type="submit"]',
            'button:has-text("Submit")',
            'button:has-text("Apply")',
            'button:has-text("Send")',
            'a:has-text("Submit")',
        ]:
            try:
                btn = page.locator(submit_sel).first
                if btn.is_visible(timeout=2000):
                    self._take_screenshot(page, job, output_dir, "external_pre_submit")
                    time.sleep(random.uniform(2, 4))
                    btn.click()
                    time.sleep(random.uniform(3, 5))
                    self._take_screenshot(page, job, output_dir, "external_post_submit")
                    submitted = True
                    logger.info(f"Clicked submit on external site via {submit_sel}")
                    break
            except Exception:
                continue

        if submitted:
            return {
                "success": True,
                "status": "applied",
                "reason": "external_apply_submitted",
                "screenshots": list(self.screenshots),
            }
        else:
            return {
                "success": False,
                "status": "manual_needed",
                "reason": f"external_form_partially_filled ({filled_count} fields)",
                "screenshots": list(self.screenshots),
            }

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
