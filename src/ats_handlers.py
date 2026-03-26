"""ATS-specific application handlers.

Routes external career site pages to the correct handler based on URL patterns.
Supports Ashby, Greenhouse, and Lever; falls back to manual_needed for unknown ATS.
"""

import logging
import os
import random
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from playwright.sync_api import Page

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ATS Detection
# ---------------------------------------------------------------------------

def detect_ats(url: str) -> str:
    """Detect ATS platform from a URL.

    Returns:
        "ashby" | "greenhouse" | "lever" | "workday" | "unknown"
    """
    url_lower = url.lower()
    if "ashbyhq.com" in url_lower or "ashby" in url_lower:
        return "ashby"
    if "greenhouse.io" in url_lower:
        return "greenhouse"
    if "lever.co" in url_lower:
        return "lever"
    if "myworkdayjobs.com" in url_lower or "workday.com" in url_lower:
        return "workday"
    if "mercor.com" in url_lower or "work.mercor" in url_lower:
        return "mercor"
    return "unknown"


# ---------------------------------------------------------------------------
# Base Handler
# ---------------------------------------------------------------------------

class ATSHandler:
    """Base class with common form-filling utilities for ATS career sites."""

    def __init__(self, page: Page, profile: dict, resume_path: str, cover_letter_path: str | None = None):
        self.page = page
        self.profile = profile
        self.candidate = profile.get("candidate", {})
        self.resume_path = resume_path
        self.cover_letter_path = cover_letter_path
        self.screenshots: list[str] = []

    # -- Profile helpers -----------------------------------------------------

    def _get_profile_field(self, key: str, default: str = "") -> str:
        """Get a field from profile['candidate']."""
        return str(self.candidate.get(key, default))

    def _get_start_date(self) -> str:
        """Return a date 2 weeks from today as MM/DD/YYYY."""
        return (datetime.now() + timedelta(weeks=2)).strftime("%m/%d/%Y")

    # -- Form filling primitives ---------------------------------------------

    def _fill_field_by_label(self, label_text: str, value: str, exact: bool = False) -> bool:
        """Find input/select/textarea near a label and fill it.

        Uses multiple strategies: label[for], aria-label, placeholder,
        and text-based label proximity.

        Returns:
            True if a field was found and filled.
        """
        page = self.page
        try:
            # Strategy 1: find label element containing the text
            if exact:
                labels = page.locator(f'label:text-is("{label_text}")')
            else:
                labels = page.locator(f'label:has-text("{label_text}")')

            if labels.count() > 0:
                label_el = labels.first
                label_for = label_el.get_attribute("for") or ""
                if label_for:
                    target = page.locator(f"#{label_for}")
                    if target.count() > 0 and target.first.is_visible(timeout=1000):
                        tag = target.first.evaluate("el => el.tagName.toLowerCase()")
                        time.sleep(random.uniform(0.5, 1.5))
                        if tag == "select":
                            self._try_select_option(target.first, value)
                        else:
                            target.first.fill(value)
                        logger.debug(f"Filled '{label_text}' via label[for] with '{value}'")
                        return True

                # Try the next sibling input/select/textarea
                parent = label_el.locator("..")
                for field_tag in ["input", "select", "textarea"]:
                    field = parent.locator(field_tag).first
                    if field.count() > 0 and field.is_visible(timeout=500):
                        time.sleep(random.uniform(0.5, 1.5))
                        tag = field.evaluate("el => el.tagName.toLowerCase()")
                        if tag == "select":
                            self._try_select_option(field, value)
                        else:
                            field.fill(value)
                        logger.debug(f"Filled '{label_text}' via parent lookup with '{value}'")
                        return True

            # Strategy 2: aria-label
            for field_tag in ["input", "select", "textarea"]:
                loc = page.locator(f'{field_tag}[aria-label*="{label_text}" i]')
                if loc.count() > 0 and loc.first.is_visible(timeout=500):
                    time.sleep(random.uniform(0.5, 1.5))
                    tag = loc.first.evaluate("el => el.tagName.toLowerCase()")
                    if tag == "select":
                        self._try_select_option(loc.first, value)
                    else:
                        loc.first.fill(value)
                    logger.debug(f"Filled '{label_text}' via aria-label with '{value}'")
                    return True

            # Strategy 3: placeholder
            loc = page.locator(f'input[placeholder*="{label_text}" i]')
            if loc.count() > 0 and loc.first.is_visible(timeout=500):
                time.sleep(random.uniform(0.5, 1.5))
                loc.first.fill(value)
                logger.debug(f"Filled '{label_text}' via placeholder with '{value}'")
                return True

        except Exception as e:
            logger.debug(f"_fill_field_by_label('{label_text}') failed: {e}")
        return False

    def _try_select_option(self, select_locator, option_text: str):
        """Try to select an option by label text (case-insensitive partial match)."""
        try:
            options = select_locator.locator("option").all()
            for opt in options:
                opt_text = (opt.text_content() or "").strip()
                if option_text.lower() in opt_text.lower():
                    select_locator.select_option(label=opt_text)
                    return True
            # Fallback: try select by value
            select_locator.select_option(label=option_text)
        except Exception as e:
            logger.debug(f"_try_select_option('{option_text}') failed: {e}")
        return False

    def _select_option_by_label(self, label_text: str, option_text: str) -> bool:
        """Find a select near a label and choose an option."""
        page = self.page
        try:
            labels = page.locator(f'label:has-text("{label_text}")')
            if labels.count() > 0:
                label_el = labels.first
                label_for = label_el.get_attribute("for") or ""
                if label_for:
                    select = page.locator(f"select#{label_for}")
                    if select.count() > 0 and select.first.is_visible(timeout=1000):
                        time.sleep(random.uniform(0.5, 1.5))
                        self._try_select_option(select.first, option_text)
                        logger.debug(f"Selected '{option_text}' for '{label_text}'")
                        return True

                # Walk up to parent and find select
                parent = label_el.locator("..")
                select = parent.locator("select").first
                if select.count() > 0 and select.is_visible(timeout=500):
                    time.sleep(random.uniform(0.5, 1.5))
                    self._try_select_option(select, option_text)
                    logger.debug(f"Selected '{option_text}' for '{label_text}' via parent")
                    return True

            # Try by aria-label on the select
            select = page.locator(f'select[aria-label*="{label_text}" i]')
            if select.count() > 0 and select.first.is_visible(timeout=500):
                time.sleep(random.uniform(0.5, 1.5))
                self._try_select_option(select.first, option_text)
                logger.debug(f"Selected '{option_text}' for '{label_text}' via aria-label")
                return True

        except Exception as e:
            logger.debug(f"_select_option_by_label('{label_text}', '{option_text}') failed: {e}")
        return False

    def _click_radio_by_label(self, label_text: str, option_text: str) -> bool:
        """Find a radio group near label_text and click the option matching option_text."""
        page = self.page
        try:
            # Find fieldset or container with the question text
            fieldsets = page.locator(f'fieldset:has-text("{label_text}")')
            if fieldsets.count() > 0:
                fs = fieldsets.first
                option_label = fs.locator(f'label:has-text("{option_text}")')
                if option_label.count() > 0 and option_label.first.is_visible(timeout=1000):
                    time.sleep(random.uniform(0.5, 1.5))
                    option_label.first.click()
                    logger.debug(f"Clicked radio '{option_text}' for '{label_text}'")
                    return True

            # Broader search: div containing the question text
            containers = page.locator(f'div:has-text("{label_text}")')
            for i in range(min(containers.count(), 5)):
                container = containers.nth(i)
                option_label = container.locator(f'label:has-text("{option_text}")')
                if option_label.count() > 0 and option_label.first.is_visible(timeout=500):
                    time.sleep(random.uniform(0.5, 1.5))
                    option_label.first.click()
                    logger.debug(f"Clicked radio '{option_text}' for '{label_text}' via div")
                    return True

        except Exception as e:
            logger.debug(f"_click_radio_by_label('{label_text}', '{option_text}') failed: {e}")
        return False

    def _upload_file(self, button_text_or_selector: str, file_path: str) -> bool:
        """Handle file upload via input[type=file] or button that triggers file chooser."""
        page = self.page
        if not file_path or not os.path.exists(file_path):
            logger.warning(f"File not found for upload: {file_path}")
            return False

        try:
            # Strategy 1: Direct input[type=file]
            file_input = page.locator('input[type="file"]')
            if file_input.count() > 0 and file_input.first.is_visible(timeout=2000):
                file_input.first.set_input_files(file_path)
                time.sleep(random.uniform(2, 4))
                logger.debug(f"Uploaded file via visible input[type=file]: {file_path}")
                return True

            # Strategy 2: Hidden input[type=file] (set directly)
            if file_input.count() > 0:
                file_input.first.set_input_files(file_path)
                time.sleep(random.uniform(2, 4))
                logger.debug(f"Uploaded file via hidden input[type=file]: {file_path}")
                return True

            # Strategy 3: Button that triggers file chooser
            btn = page.locator(f'button:has-text("{button_text_or_selector}")')
            if btn.count() > 0 and btn.first.is_visible(timeout=2000):
                with page.expect_file_chooser(timeout=5000) as fc_info:
                    btn.first.click()
                file_chooser = fc_info.value
                file_chooser.set_files(file_path)
                time.sleep(random.uniform(2, 4))
                logger.debug(f"Uploaded file via button '{button_text_or_selector}': {file_path}")
                return True

        except Exception as e:
            logger.warning(f"_upload_file('{button_text_or_selector}') failed: {e}")
        return False

    def _take_screenshot(self, label: str = "screenshot") -> str:
        """Take a screenshot and append to self.screenshots."""
        try:
            timestamp = datetime.now().strftime("%H%M%S_%f")
            filename = f"ats_{label}_{timestamp}.png"
            screenshot_dir = Path("output") / "screenshots"
            screenshot_dir.mkdir(parents=True, exist_ok=True)
            path = screenshot_dir / filename
            self.page.screenshot(path=str(path))
            self.screenshots.append(str(path))
            logger.debug(f"Screenshot saved: {path}")
            return str(path)
        except Exception as e:
            logger.error(f"Screenshot failed: {e}")
            return ""

    def _answer_yes_no_question(self, question_text: str) -> str:
        """Determine the correct yes/no answer based on form-filling rules.

        Rules:
        - Experience, skills, qualifications → Yes
        - Sponsorship → No
        - Work authorization → Yes
        - Can work in office → Yes
        - Background check → Yes
        - Relocate → Yes

        Returns:
            "Yes" or "No"
        """
        q = question_text.lower()
        # Sponsorship questions → No
        if any(kw in q for kw in ["sponsor", "sponsorship", "visa sponsor"]):
            return "No"
        # Work auth, eligible, authorized → Yes
        if any(kw in q for kw in ["authorized", "authorization", "eligible", "legally"]):
            return "Yes"
        # Office, commute, relocate → Yes
        if any(kw in q for kw in ["office", "commute", "relocat", "on-site", "onsite", "in-person"]):
            return "Yes"
        # Background check → Yes
        if any(kw in q for kw in ["background check", "drug test", "drug screen"]):
            return "Yes"
        # Default: experience, skills, qualifications → Yes
        return "Yes"

    def _get_professional_summary(self) -> str:
        """Return a brief professional pitch from profile summary."""
        summary = self._get_profile_field("summary", "").strip()
        if summary:
            # Truncate to ~200 chars for textarea fields
            return summary[:200].strip()
        return (
            "Experienced compliance, risk, and governance professional with 9+ years "
            "of regulatory experience including federal bank examination at the OCC "
            "and hands-on roles in fintech and banking. CFE and CAMS certified."
        )

    def apply(self) -> dict:
        """Submit the application. Must be overridden by subclasses.

        Returns:
            {"success": bool, "status": str, "reason": str, "screenshots": list}
        """
        raise NotImplementedError("Subclasses must implement apply()")


# ---------------------------------------------------------------------------
# Ashby Handler
# ---------------------------------------------------------------------------

class AshbyHandler(ATSHandler):
    """Handler for jobs.ashbyhq.com applications."""

    def apply(self) -> dict:
        page = self.page
        logger.info(f"AshbyHandler: starting application on {page.url}")

        try:
            self._take_screenshot("ashby_initial")

            # 1. Upload resume via "Autofill from resume" or file input
            uploaded = False
            try:
                # Look for "Autofill with resume" or similar button
                for btn_text in ["Autofill with resume", "Autofill from resume", "Upload file", "Upload resume"]:
                    btn = page.locator(f'button:has-text("{btn_text}"), label:has-text("{btn_text}")')
                    if btn.count() > 0 and btn.first.is_visible(timeout=2000):
                        try:
                            with page.expect_file_chooser(timeout=5000) as fc_info:
                                btn.first.click()
                            file_chooser = fc_info.value
                            file_chooser.set_files(self.resume_path)
                            uploaded = True
                            logger.info(f"Ashby: uploaded resume via '{btn_text}'")
                            break
                        except Exception as e:
                            logger.debug(f"Ashby: button '{btn_text}' file chooser failed: {e}")
                            continue

                # Fallback: direct input[type=file]
                if not uploaded:
                    file_input = page.locator('input[type="file"]')
                    if file_input.count() > 0:
                        file_input.first.set_input_files(self.resume_path)
                        uploaded = True
                        logger.info("Ashby: uploaded resume via input[type=file]")
            except Exception as e:
                logger.warning(f"Ashby: resume upload failed: {e}")

            if uploaded:
                # Wait for autofill to populate fields
                time.sleep(random.uniform(2, 4))

            self._take_screenshot("ashby_after_upload")

            # 2. Fill standard fields
            name = self._get_profile_field("name", "Danna Dobi")
            name_parts = name.split()
            first_name = name_parts[0] if name_parts else "Danna"
            last_name = name_parts[-1] if len(name_parts) > 1 else "Dobi"

            self._fill_field_by_label("First name", first_name)
            self._fill_field_by_label("Last name", last_name)
            self._fill_field_by_label("Full name", name)
            self._fill_field_by_label("Name", name)
            self._fill_field_by_label("Email", self._get_profile_field("email", "danna.dobi@gmail.com"))
            self._fill_field_by_label("Phone", self._get_profile_field("phone", "510-333-8812"))
            self._fill_field_by_label("LinkedIn", self._get_profile_field("linkedin_url", "https://www.linkedin.com/in/dannadobi"))

            time.sleep(random.uniform(1, 2))

            # 3. Fill custom questions
            start_date = self._get_start_date()
            self._fill_field_by_label("When can you start", start_date)
            self._fill_field_by_label("start date", start_date)
            self._fill_field_by_label("earliest start", start_date)

            # Sponsorship → No
            for label in ["sponsorship", "sponsor", "Will you require sponsorship"]:
                self._click_radio_by_label(label, "No")
                self._select_option_by_label(label, "No")
                self._fill_field_by_label(label, "No")

            # Office / work location → Yes
            for label in ["able to work from", "work from our", "office", "on-site", "in-person"]:
                self._click_radio_by_label(label, "Yes")
                self._select_option_by_label(label, "Yes")
                self._fill_field_by_label(label, "Yes")

            # Work authorization → Yes
            for label in ["authorized", "authorization", "legally", "eligible to work"]:
                self._click_radio_by_label(label, "Yes")
                self._select_option_by_label(label, "Yes")
                self._fill_field_by_label(label, "Yes")

            # Additional Information
            self._fill_field_by_label("Additional Information", self._get_professional_summary())
            self._fill_field_by_label("Additional info", self._get_professional_summary())
            self._fill_field_by_label("Cover letter", self._get_professional_summary())

            # Years of experience
            self._fill_field_by_label("years of experience", self._get_profile_field("years_of_experience", "9"))

            # Salary
            self._fill_field_by_label("salary", self._get_profile_field("salary_expectation", "130000"))
            self._fill_field_by_label("compensation", self._get_profile_field("salary_expectation", "130000"))

            time.sleep(random.uniform(1, 2))

            # 4. Handle EEO section with actual info
            gender = self._get_profile_field("gender", "Female")
            race = self._get_profile_field("race_ethnicity", "Hispanic or Latino")
            veteran = self._get_profile_field("veteran_status", "No")
            disability = self._get_profile_field("disability_status", "No")

            self._select_option_by_label("Gender", gender)
            self._click_radio_by_label("Gender", gender)
            self._select_option_by_label("Race", race)
            self._select_option_by_label("Ethnicity", race)
            self._click_radio_by_label("Race", race)
            self._click_radio_by_label("Ethnicity", race)

            # Veteran — look for the matching option text
            for vet_label in ["Veteran", "veteran status"]:
                self._click_radio_by_label(vet_label, "I am not")
                self._click_radio_by_label(vet_label, "No")
                self._select_option_by_label(vet_label, "I am not")
                self._select_option_by_label(vet_label, "No")

            # Disability
            for dis_label in ["Disability", "disability status"]:
                self._click_radio_by_label(dis_label, "I do not")
                self._click_radio_by_label(dis_label, "No")
                self._select_option_by_label(dis_label, "I do not")
                self._select_option_by_label(dis_label, "No")

            self._take_screenshot("ashby_form_filled")
            time.sleep(random.uniform(1, 3))

            # 5. Answer remaining yes/no questions generically
            self._answer_all_yes_no_questions()

            # 6. Click Submit
            submitted = False
            for submit_text in ["Submit Application", "Submit application", "Submit", "Apply"]:
                btn = page.locator(f'button:has-text("{submit_text}")')
                if btn.count() > 0 and btn.first.is_visible(timeout=2000):
                    self._take_screenshot("ashby_pre_submit")
                    time.sleep(random.uniform(1, 3))
                    btn.first.click()
                    submitted = True
                    logger.info(f"Ashby: clicked '{submit_text}'")
                    break

            if not submitted:
                # Try generic submit button
                submit_btn = page.locator('button[type="submit"]')
                if submit_btn.count() > 0 and submit_btn.first.is_visible(timeout=2000):
                    self._take_screenshot("ashby_pre_submit")
                    time.sleep(random.uniform(1, 3))
                    submit_btn.first.click()
                    submitted = True
                    logger.info("Ashby: clicked button[type=submit]")

            time.sleep(random.uniform(3, 5))
            self._take_screenshot("ashby_post_submit")

            # 7. Check for success message
            try:
                page_text = page.evaluate("() => document.body.innerText").lower()
                if "successfully submitted" in page_text or "application was submitted" in page_text or "thank you" in page_text:
                    logger.info("Ashby: application successfully submitted")
                    return {
                        "success": True,
                        "status": "applied",
                        "reason": "ashby_submitted",
                        "screenshots": self.screenshots,
                    }
            except Exception:
                pass

            if submitted:
                return {
                    "success": True,
                    "status": "applied",
                    "reason": "ashby_submit_clicked",
                    "screenshots": self.screenshots,
                }

            return {
                "success": False,
                "status": "manual_needed",
                "reason": "ashby_no_submit_button",
                "screenshots": self.screenshots,
            }

        except Exception as e:
            logger.error(f"AshbyHandler error: {e}")
            self._take_screenshot("ashby_error")
            return {
                "success": False,
                "status": "apply_failed",
                "reason": f"ashby_error: {e}",
                "screenshots": self.screenshots,
            }

    def _answer_all_yes_no_questions(self):
        """Scan for remaining unanswered fieldset radio questions and answer them."""
        try:
            fieldsets = self.page.locator("fieldset").all()
            for fs in fieldsets:
                try:
                    legend = fs.locator("legend")
                    legend_text = ""
                    if legend.count() > 0:
                        legend_text = (legend.first.text_content() or "").strip()
                    if not legend_text:
                        continue

                    answer = self._answer_yes_no_question(legend_text)
                    label = fs.locator(f'label:has-text("{answer}")').first
                    if label.is_visible(timeout=500):
                        # Check if already selected
                        radio = fs.locator('input[type="radio"]:checked')
                        if radio.count() == 0:
                            time.sleep(random.uniform(0.5, 1))
                            label.click()
                            logger.debug(f"Ashby: answered '{answer}' for '{legend_text[:50]}'")
                except Exception:
                    continue
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Greenhouse Handler
# ---------------------------------------------------------------------------

class GreenhouseHandler(ATSHandler):
    """Handler for boards.greenhouse.io applications."""

    def apply(self) -> dict:
        page = self.page
        logger.info(f"GreenhouseHandler: starting application on {page.url}")

        try:
            self._take_screenshot("greenhouse_initial")

            name = self._get_profile_field("name", "Danna Dobi")
            name_parts = name.split()
            first_name = name_parts[0] if name_parts else "Danna"
            last_name = name_parts[-1] if len(name_parts) > 1 else "Dobi"
            email = self._get_profile_field("email", "danna.dobi@gmail.com")
            phone = self._get_profile_field("phone", "510-333-8812")

            # 1. Fill standard fields — Greenhouse uses #first_name, #last_name, etc.
            for selector, value in [
                ("#first_name", first_name),
                ("#last_name", last_name),
                ("#email", email),
                ("#phone", phone),
            ]:
                try:
                    field = page.locator(selector)
                    if field.count() > 0 and field.first.is_visible(timeout=2000):
                        current = field.first.input_value()
                        if not current or not current.strip():
                            time.sleep(random.uniform(0.5, 1.5))
                            field.first.fill(value)
                            logger.debug(f"Greenhouse: filled {selector} = '{value}'")
                except Exception as e:
                    logger.debug(f"Greenhouse: {selector} fill failed: {e}")

            # Also try label-based filling as fallback
            self._fill_field_by_label("First name", first_name)
            self._fill_field_by_label("Last name", last_name)
            self._fill_field_by_label("Email", email)
            self._fill_field_by_label("Phone", phone)
            self._fill_field_by_label("LinkedIn", self._get_profile_field("linkedin_url"))
            self._fill_field_by_label("Location", self._get_profile_field("location", "San Francisco Bay Area"))

            time.sleep(random.uniform(1, 2))

            # 2. Upload resume
            resume_uploaded = False
            try:
                # Greenhouse: input[type=file] with name containing "resume"
                resume_input = page.locator('input[type="file"][name*="resume" i], input[type="file"][id*="resume" i]')
                if resume_input.count() > 0:
                    resume_input.first.set_input_files(self.resume_path)
                    resume_uploaded = True
                    logger.info("Greenhouse: uploaded resume via named file input")
                else:
                    # Generic first file input
                    file_input = page.locator('input[type="file"]')
                    if file_input.count() > 0:
                        file_input.first.set_input_files(self.resume_path)
                        resume_uploaded = True
                        logger.info("Greenhouse: uploaded resume via first file input")
            except Exception as e:
                logger.warning(f"Greenhouse: resume upload failed: {e}")

            time.sleep(random.uniform(1, 3))

            # 3. Upload cover letter if available
            if self.cover_letter_path and os.path.exists(self.cover_letter_path):
                try:
                    cl_input = page.locator('input[type="file"][name*="cover" i], input[type="file"][id*="cover" i]')
                    if cl_input.count() > 0:
                        cl_input.first.set_input_files(self.cover_letter_path)
                        logger.info("Greenhouse: uploaded cover letter")
                    else:
                        # Try second file input
                        file_inputs = page.locator('input[type="file"]').all()
                        if len(file_inputs) >= 2:
                            file_inputs[1].set_input_files(self.cover_letter_path)
                            logger.info("Greenhouse: uploaded cover letter via second file input")
                except Exception as e:
                    logger.debug(f"Greenhouse: cover letter upload failed: {e}")

            time.sleep(random.uniform(1, 2))

            # 4. Fill custom questions
            self._fill_custom_questions()

            time.sleep(random.uniform(1, 2))

            # 5. Handle EEOC section
            gender = self._get_profile_field("gender", "Female")
            race = self._get_profile_field("race_ethnicity", "Hispanic or Latino")

            self._select_option_by_label("Gender", gender)
            self._select_option_by_label("Race", race)
            self._select_option_by_label("Ethnicity", race)

            for vet_label in ["Veteran", "veteran status"]:
                self._select_option_by_label(vet_label, "I am not")
                self._select_option_by_label(vet_label, "No")

            for dis_label in ["Disability", "disability status"]:
                self._select_option_by_label(dis_label, "No")
                self._select_option_by_label(dis_label, "I don't wish to answer")

            self._take_screenshot("greenhouse_form_filled")
            time.sleep(random.uniform(1, 3))

            # 6. Click submit
            submitted = False
            for submit_sel in [
                "#submit_app",
                'button[type="submit"]',
                'input[type="submit"]',
                'button:has-text("Submit Application")',
                'button:has-text("Submit application")',
                'button:has-text("Submit")',
                'button:has-text("Apply")',
            ]:
                try:
                    btn = page.locator(submit_sel)
                    if btn.count() > 0 and btn.first.is_visible(timeout=2000):
                        self._take_screenshot("greenhouse_pre_submit")
                        time.sleep(random.uniform(1, 3))
                        btn.first.click()
                        submitted = True
                        logger.info(f"Greenhouse: clicked submit via {submit_sel}")
                        break
                except Exception:
                    continue

            time.sleep(random.uniform(3, 5))
            self._take_screenshot("greenhouse_post_submit")

            # Check for success
            try:
                page_text = page.evaluate("() => document.body.innerText").lower()
                if any(phrase in page_text for phrase in [
                    "application has been submitted",
                    "thank you for applying",
                    "thanks for applying",
                    "successfully submitted",
                    "application received",
                ]):
                    logger.info("Greenhouse: application successfully submitted")
                    return {
                        "success": True,
                        "status": "applied",
                        "reason": "greenhouse_submitted",
                        "screenshots": self.screenshots,
                    }
            except Exception:
                pass

            if submitted:
                return {
                    "success": True,
                    "status": "applied",
                    "reason": "greenhouse_submit_clicked",
                    "screenshots": self.screenshots,
                }

            return {
                "success": False,
                "status": "manual_needed",
                "reason": "greenhouse_no_submit_button",
                "screenshots": self.screenshots,
            }

        except Exception as e:
            logger.error(f"GreenhouseHandler error: {e}")
            self._take_screenshot("greenhouse_error")
            return {
                "success": False,
                "status": "apply_failed",
                "reason": f"greenhouse_error: {e}",
                "screenshots": self.screenshots,
            }

    def _fill_custom_questions(self):
        """Fill custom Greenhouse questions using label matching."""
        page = self.page

        # Text/number inputs
        try:
            inputs = page.locator('input[type="text"], input[type="number"]').all()
            for inp in inputs:
                try:
                    current = inp.input_value()
                    if current and current.strip():
                        continue

                    label_text = self._get_input_label(inp)
                    if not label_text:
                        continue

                    lt = label_text.lower()

                    if "year" in lt and any(kw in lt for kw in ["experience", "compliance", "audit", "risk"]):
                        inp.fill("9")
                    elif "year" in lt:
                        inp.fill("9")
                    elif any(kw in lt for kw in ["salary", "compensation", "pay"]):
                        inp.fill(self._get_profile_field("salary_expectation", "130000"))
                    elif "linkedin" in lt:
                        inp.fill(self._get_profile_field("linkedin_url"))
                    elif any(kw in lt for kw in ["city", "location"]):
                        inp.fill(self._get_profile_field("location", "San Francisco Bay Area"))
                    elif any(kw in lt for kw in ["start date", "when can you start", "earliest"]):
                        inp.fill(self._get_start_date())
                    elif any(kw in lt for kw in ["authorized", "authorization"]):
                        inp.fill("Yes")
                    elif "sponsor" in lt:
                        inp.fill("No")

                    time.sleep(random.uniform(0.5, 1))
                except Exception:
                    continue
        except Exception:
            pass

        # Select dropdowns
        try:
            selects = page.locator("select").all()
            for sel in selects:
                try:
                    current = sel.input_value()
                    if current and current.strip() and current != "":
                        continue

                    label_text = self._get_input_label(sel)
                    if not label_text:
                        continue

                    lt = label_text.lower()
                    answer = self._answer_yes_no_question(lt)

                    if any(kw in lt for kw in ["authorized", "authorization", "legally"]):
                        self._try_select_option(sel, "Yes")
                    elif "sponsor" in lt:
                        self._try_select_option(sel, "No")
                    elif any(kw in lt for kw in ["experience", "proficiency"]):
                        self._try_select_option(sel, "Yes")
                    elif any(kw in lt for kw in ["education", "degree"]):
                        self._try_select_option(sel, "Bachelor")
                    else:
                        self._try_select_option(sel, answer)

                    time.sleep(random.uniform(0.5, 1))
                except Exception:
                    continue
        except Exception:
            pass

        # Radio buttons via fieldsets
        try:
            fieldsets = page.locator("fieldset").all()
            for fs in fieldsets:
                try:
                    legend = fs.locator("legend, span")
                    q_text = ""
                    if legend.count() > 0:
                        q_text = (legend.first.text_content() or "").strip()
                    if not q_text:
                        continue

                    answer = self._answer_yes_no_question(q_text)
                    label = fs.locator(f'label:has-text("{answer}")').first
                    if label.is_visible(timeout=500):
                        radio = fs.locator('input[type="radio"]:checked')
                        if radio.count() == 0:
                            time.sleep(random.uniform(0.5, 1))
                            label.click()
                            logger.debug(f"Greenhouse: radio '{answer}' for '{q_text[:50]}'")
                except Exception:
                    continue
        except Exception:
            pass

        # Textareas
        try:
            textareas = page.locator("textarea").all()
            for ta in textareas:
                try:
                    current = ta.input_value()
                    if current and current.strip():
                        continue
                    time.sleep(random.uniform(0.5, 1))
                    ta.fill(self._get_professional_summary())
                    logger.debug("Greenhouse: filled textarea with professional summary")
                except Exception:
                    continue
        except Exception:
            pass

    def _get_input_label(self, element) -> str:
        """Get label text for a form element."""
        try:
            el_id = element.get_attribute("id") or ""
            if el_id:
                label = self.page.locator(f'label[for="{el_id}"]')
                if label.count() > 0:
                    return (label.first.text_content() or "").strip()

            aria = element.get_attribute("aria-label") or ""
            if aria:
                return aria.strip()

            placeholder = element.get_attribute("placeholder") or ""
            if placeholder:
                return placeholder.strip()
        except Exception:
            pass
        return ""


# ---------------------------------------------------------------------------
# Lever Handler
# ---------------------------------------------------------------------------

class LeverHandler(ATSHandler):
    """Handler for jobs.lever.co applications."""

    def apply(self) -> dict:
        page = self.page
        logger.info(f"LeverHandler: starting application on {page.url}")

        try:
            self._take_screenshot("lever_initial")

            name = self._get_profile_field("name", "Danna Dobi")
            email = self._get_profile_field("email", "danna.dobi@gmail.com")
            phone = self._get_profile_field("phone", "510-333-8812")
            linkedin = self._get_profile_field("linkedin_url", "https://www.linkedin.com/in/dannadobi")

            # 1. Fill fields — Lever uses input[name="name"], input[name="email"], etc.
            field_map = {
                'input[name="name"]': name,
                'input[name="email"]': email,
                'input[name="phone"]': phone,
                'input[name="urls[LinkedIn]"]': linkedin,
                'input[name="urls\\[LinkedIn\\]"]': linkedin,
            }

            for selector, value in field_map.items():
                try:
                    field = page.locator(selector)
                    if field.count() > 0 and field.first.is_visible(timeout=2000):
                        current = field.first.input_value()
                        if not current or not current.strip():
                            time.sleep(random.uniform(0.5, 1.5))
                            field.first.fill(value)
                            logger.debug(f"Lever: filled {selector}")
                except Exception as e:
                    logger.debug(f"Lever: {selector} failed: {e}")

            # Also try label-based
            self._fill_field_by_label("Full name", name)
            self._fill_field_by_label("Name", name)
            self._fill_field_by_label("Email", email)
            self._fill_field_by_label("Phone", phone)
            self._fill_field_by_label("LinkedIn", linkedin)
            self._fill_field_by_label("Current company", "")  # Leave blank if unknown

            time.sleep(random.uniform(1, 2))

            # 2. Upload resume
            try:
                # Lever: look for file input
                file_input = page.locator('input[type="file"]')
                if file_input.count() > 0:
                    file_input.first.set_input_files(self.resume_path)
                    logger.info("Lever: uploaded resume via file input")
                else:
                    # Try button that opens file chooser
                    upload_btn = page.locator('button:has-text("Upload"), a:has-text("Upload")')
                    if upload_btn.count() > 0 and upload_btn.first.is_visible(timeout=2000):
                        with page.expect_file_chooser(timeout=5000) as fc_info:
                            upload_btn.first.click()
                        fc_info.value.set_files(self.resume_path)
                        logger.info("Lever: uploaded resume via upload button")
            except Exception as e:
                logger.warning(f"Lever: resume upload failed: {e}")

            time.sleep(random.uniform(1, 3))

            # 3. Fill custom additional questions
            self._fill_custom_questions()

            self._take_screenshot("lever_form_filled")
            time.sleep(random.uniform(1, 3))

            # 4. Click submit
            submitted = False
            for submit_text in ["Submit application", "Submit Application", "Submit", "Apply"]:
                btn = page.locator(f'button:has-text("{submit_text}")')
                if btn.count() > 0 and btn.first.is_visible(timeout=2000):
                    self._take_screenshot("lever_pre_submit")
                    time.sleep(random.uniform(1, 3))
                    btn.first.click()
                    submitted = True
                    logger.info(f"Lever: clicked '{submit_text}'")
                    break

            if not submitted:
                submit_btn = page.locator('button[type="submit"], input[type="submit"]')
                if submit_btn.count() > 0 and submit_btn.first.is_visible(timeout=2000):
                    self._take_screenshot("lever_pre_submit")
                    time.sleep(random.uniform(1, 3))
                    submit_btn.first.click()
                    submitted = True
                    logger.info("Lever: clicked generic submit button")

            time.sleep(random.uniform(3, 5))
            self._take_screenshot("lever_post_submit")

            # Check for success
            try:
                page_text = page.evaluate("() => document.body.innerText").lower()
                if any(phrase in page_text for phrase in [
                    "application has been submitted",
                    "thanks for applying",
                    "thank you for applying",
                    "application received",
                ]):
                    logger.info("Lever: application successfully submitted")
                    return {
                        "success": True,
                        "status": "applied",
                        "reason": "lever_submitted",
                        "screenshots": self.screenshots,
                    }
            except Exception:
                pass

            if submitted:
                return {
                    "success": True,
                    "status": "applied",
                    "reason": "lever_submit_clicked",
                    "screenshots": self.screenshots,
                }

            return {
                "success": False,
                "status": "manual_needed",
                "reason": "lever_no_submit_button",
                "screenshots": self.screenshots,
            }

        except Exception as e:
            logger.error(f"LeverHandler error: {e}")
            self._take_screenshot("lever_error")
            return {
                "success": False,
                "status": "apply_failed",
                "reason": f"lever_error: {e}",
                "screenshots": self.screenshots,
            }

    def _fill_custom_questions(self):
        """Fill Lever custom questions (text, select, radio, textarea)."""
        page = self.page

        # Text inputs
        try:
            cards = page.locator('.application-additional, .custom-questions, [class*="custom"]').all()
            # Also try all inputs/selects on the page
            inputs = page.locator('input[type="text"], input[type="number"]').all()
            for inp in inputs:
                try:
                    current = inp.input_value()
                    if current and current.strip():
                        continue

                    label_text = ""
                    el_id = inp.get_attribute("id") or ""
                    if el_id:
                        lbl = page.locator(f'label[for="{el_id}"]')
                        if lbl.count() > 0:
                            label_text = (lbl.first.text_content() or "").strip()
                    if not label_text:
                        label_text = inp.get_attribute("aria-label") or inp.get_attribute("placeholder") or ""

                    lt = label_text.lower()
                    if not lt:
                        continue

                    if "year" in lt:
                        inp.fill("9")
                    elif any(kw in lt for kw in ["salary", "compensation"]):
                        inp.fill(self._get_profile_field("salary_expectation", "130000"))
                    elif "linkedin" in lt:
                        inp.fill(self._get_profile_field("linkedin_url"))
                    elif any(kw in lt for kw in ["start date", "when can you", "earliest"]):
                        inp.fill(self._get_start_date())
                    elif any(kw in lt for kw in ["authorized", "authorization"]):
                        inp.fill("Yes")
                    elif "sponsor" in lt:
                        inp.fill("No")
                    elif any(kw in lt for kw in ["city", "location"]):
                        inp.fill(self._get_profile_field("location", "San Francisco Bay Area"))

                    time.sleep(random.uniform(0.5, 1))
                except Exception:
                    continue
        except Exception:
            pass

        # Select dropdowns
        try:
            selects = page.locator("select").all()
            for sel in selects:
                try:
                    current = sel.input_value()
                    if current and current.strip():
                        continue

                    label_text = ""
                    el_id = sel.get_attribute("id") or ""
                    if el_id:
                        lbl = page.locator(f'label[for="{el_id}"]')
                        if lbl.count() > 0:
                            label_text = (lbl.first.text_content() or "").strip()
                    if not label_text:
                        label_text = sel.get_attribute("aria-label") or ""

                    lt = label_text.lower()
                    if not lt:
                        continue

                    answer = self._answer_yes_no_question(lt)
                    self._try_select_option(sel, answer)
                    time.sleep(random.uniform(0.5, 1))
                except Exception:
                    continue
        except Exception:
            pass

        # Textareas
        try:
            textareas = page.locator("textarea").all()
            for ta in textareas:
                try:
                    current = ta.input_value()
                    if current and current.strip():
                        continue
                    time.sleep(random.uniform(0.5, 1))
                    ta.fill(self._get_professional_summary())
                except Exception:
                    continue
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Mercor Handler (work.mercor.com)
# ---------------------------------------------------------------------------

class MercorHandler(ATSHandler):
    """Handler for Mercor career site (work.mercor.com)."""

    def apply(self) -> dict:
        logger.info(f"MercorHandler: starting application on {self.page.url}")
        filled_count = 0
        try:
            time.sleep(random.uniform(2, 4))

            # Fill name
            filled_count += self._fill_field_by_label(
                "full name", self.candidate.get("name", "")
            )

            # Fill email
            filled_count += self._fill_field_by_label(
                "email", self.candidate.get("email", "")
            )

            # Fill phone (Mercor has a +1 prefix, just fill the number part)
            phone = self.candidate.get("phone", "").replace("-", "").replace(" ", "")
            if phone.startswith("1"):
                phone = phone[1:]
            filled_count += self._fill_field_by_label("phone", phone)

            # Fill LinkedIn URL
            filled_count += self._fill_field_by_label(
                "linkedin", self.candidate.get("linkedin_url", "")
            )

            # Upload resume if there's a file input or upload button
            try:
                file_input = self.page.locator('input[type="file"]')
                if file_input.count() > 0:
                    file_input.first.set_input_files(self.resume_path)
                    time.sleep(random.uniform(2, 3))
                    filled_count += 1
                    logger.debug("Uploaded resume via file input")
                else:
                    # Look for upload/resume button
                    for btn_text in ["Upload", "Resume", "Upload resume", "Attach"]:
                        btn = self.page.locator(f'button:has-text("{btn_text}")').first
                        if btn.is_visible(timeout=1000):
                            with self.page.expect_file_chooser(timeout=5000) as fc:
                                btn.click()
                            fc.value.set_files(self.resume_path)
                            time.sleep(random.uniform(2, 3))
                            filled_count += 1
                            logger.debug(f"Uploaded resume via '{btn_text}' button")
                            break
            except Exception as e:
                logger.debug(f"Resume upload: {e}")

            # Work authorization — look for radio/select
            self._click_radio_by_label("authorized", "yes")
            self._click_radio_by_label("sponsorship", "no")

            # Any other yes/no questions → Yes
            try:
                fieldsets = self.page.locator("fieldset").all()
                for fs in fieldsets:
                    try:
                        legend = fs.locator("legend, label").first
                        legend_text = (legend.text_content() or "").lower() if legend.count() > 0 else ""
                        if not legend_text:
                            continue
                        if "sponsor" in legend_text:
                            continue  # Already handled
                        yes_opt = fs.locator("label:has-text('Yes'), input[value='Yes']").first
                        if yes_opt.is_visible(timeout=300):
                            yes_opt.click()
                            time.sleep(0.5)
                    except Exception:
                        continue
            except Exception:
                pass

            time.sleep(random.uniform(1, 2))

            if filled_count < 2:
                return {
                    "success": False,
                    "status": "manual_needed",
                    "reason": f"mercor_too_few_fields_filled:{filled_count}",
                    "screenshots": [],
                }

            # Submit
            submitted = False
            for submit_text in ["Submit", "Apply", "Submit Application", "Send"]:
                try:
                    btn = self.page.locator(f'button:has-text("{submit_text}")').first
                    if btn.is_visible(timeout=2000):
                        time.sleep(random.uniform(1, 3))
                        btn.click()
                        time.sleep(random.uniform(3, 5))
                        submitted = True
                        logger.info(f"MercorHandler: clicked submit via '{submit_text}'")
                        break
                except Exception:
                    continue

            if submitted:
                return {
                    "success": True,
                    "status": "applied",
                    "reason": "mercor_submitted",
                    "screenshots": [],
                }
            else:
                return {
                    "success": False,
                    "status": "manual_needed",
                    "reason": "mercor_no_submit_button",
                    "screenshots": [],
                }

        except Exception as e:
            logger.error(f"MercorHandler error: {e}")
            return {
                "success": False,
                "status": "manual_needed",
                "reason": f"mercor_error:{e}",
                "screenshots": [],
            }


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

def route_to_handler(page: Page, profile: dict, resume_path: str, cover_letter_path: str | None = None) -> dict:
    """Route a page to the correct ATS handler and run the application.

    Args:
        page: Playwright Page on the ATS career site.
        profile: Candidate profile dict (from config/profile.yaml).
        resume_path: Path to tailored resume file.
        cover_letter_path: Optional path to cover letter file.

    Returns:
        {"success": bool, "status": str, "reason": str, "screenshots": list}
    """
    url = page.url
    ats = detect_ats(url)

    handler_map = {
        "ashby": AshbyHandler,
        "greenhouse": GreenhouseHandler,
        "lever": LeverHandler,
        "mercor": MercorHandler,
    }

    handler_class = handler_map.get(ats)
    if not handler_class:
        return {
            "success": False,
            "status": "manual_needed",
            "reason": f"unsupported_ats:{ats}",
            "screenshots": [],
        }

    handler = handler_class(page, profile, resume_path, cover_letter_path)
    return handler.apply()
