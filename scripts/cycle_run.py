#!/usr/bin/env python3
"""One-shot aipply cycle: search → filter → tailor → apply → track.

Rotated keyword: "regulatory analyst" / Remote
Goal: find and submit 1 Easy Apply job.
"""

import json
import logging
import os
import random
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.linkedin_scanner import LinkedInScanner
from src.linkedin_applicant import LinkedInApplicant
from src.resume_tailor import ResumeTailor
from src.cover_letter_gen import CoverLetterGenerator
from src.tracker import ApplicationTracker
from src.utils import load_config, ensure_dir, sanitize_filename

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(PROJECT_ROOT / "output" / "aipply.log"),
    ],
)
logger = logging.getLogger("aipply.cycle")

# --- Config ---
settings = load_config(PROJECT_ROOT / "config" / "settings.yaml")
profile = load_config(PROJECT_ROOT / "config" / "profile.yaml")
candidate = profile.get("candidate", {})

# Tracker
tracker = ApplicationTracker(tracker_path=str(PROJECT_ROOT / "output" / "tracker.json"))

# Keyword rotation — pick one not heavily used recently
SEARCH_KEYWORD = "risk analyst"
SEARCH_LOCATION = "San Francisco Bay Area"

# Filter config
positive_kw = settings.get("filter", {}).get("positive_keywords", [])
negative_kw = settings.get("filter", {}).get("negative_keywords", [])
excluded_companies = [c.lower() for c in settings.get("exclusions", {}).get("companies", [])]

BASE_RESUME = PROJECT_ROOT / "templates" / "base_resume.docx"
BASE_COVER = PROJECT_ROOT / "templates" / "base_cover_letter.docx"


def title_passes_filter(title: str) -> bool:
    """Check if job title passes the relevance filter."""
    t = title.lower()
    has_positive = any(kw in t for kw in positive_kw) if positive_kw else True
    has_negative = any(kw in t for kw in negative_kw) if negative_kw else False
    return has_positive and not has_negative


def company_excluded(company: str) -> bool:
    return any(exc in company.lower() for exc in excluded_companies)


def main():
    scanner = LinkedInScanner(config=settings)
    applicant = LinkedInApplicant(config=settings, profile=profile)
    tailor = ResumeTailor(config=settings)
    cover_gen = CoverLetterGenerator(config=settings)

    easy_apply_done = False

    try:
        # Both scanner and applicant share same persistent context
        page = scanner.connect_browser()
        # Share the same browser context with applicant
        applicant.playwright = scanner._playwright
        applicant.browser = scanner._context
        applicant.page = scanner._page

        logger.info(f"Searching: '{SEARCH_KEYWORD}' in '{SEARCH_LOCATION}'")
        jobs = scanner.search_jobs([SEARCH_KEYWORD], SEARCH_LOCATION, max_results=25)
        logger.info(f"Found {len(jobs)} raw results")

        # Filter
        filtered = []
        for j in jobs:
            title = j.get("title", "")
            company = j.get("company", "")
            url = j.get("url", "")

            if company_excluded(company):
                logger.info(f"  SKIP (excluded company): {company}")
                continue
            if not title_passes_filter(title):
                logger.info(f"  SKIP (title filter): {title}")
                continue
            if tracker.is_already_applied(job_url=url, company=company, position=title):
                logger.info(f"  SKIP (already applied): {title} at {company}")
                continue
            filtered.append(j)

        logger.info(f"After filtering: {len(filtered)} candidates")

        if not filtered:
            logger.info("No new jobs found this cycle.")
            print("CYCLE_RESULT: no_new_jobs")
            return

        # Process jobs — prioritize Easy Apply
        for i, job in enumerate(filtered):
            if easy_apply_done:
                break

            title = job.get("title", "")
            company = job.get("company", "")
            url = job.get("url", "")

            logger.info(f"[{i+1}/{len(filtered)}] Checking: {title} at {company}")

            # Navigate to job to get details and check apply type
            try:
                details = scanner.get_job_details(url)
                description = details.get("description", "")
                location = details.get("location", "")

                if not description or len(description) < 50:
                    logger.info(f"  SKIP: no description found")
                    continue

                # Use detail title if available, fall back to card title
                actual_title = details.get("title", "").strip() or title
                if not title_passes_filter(actual_title):
                    logger.info(f"  SKIP (detail title filter): {actual_title}")
                    continue

            except Exception as e:
                logger.error(f"  Failed to get details: {e}")
                continue

            # Check for Easy Apply button — must be the actual apply button in the
            # job detail panel, NOT sidebar card badges that also say "Easy Apply"
            time.sleep(random.uniform(1, 3))
            has_easy_apply = False
            for sel in [
                'button.jobs-apply-button:has-text("Easy Apply")',
                'button[aria-label*="Easy Apply to"]',
                '.jobs-details-top-card button:has-text("Easy Apply")',
                '.job-details-jobs-unified-top-card__apply-button button:has-text("Easy Apply")',
                'button[aria-label*="Easy Apply"]',
            ]:
                try:
                    loc = scanner._page.locator(sel).first
                    if loc.is_visible(timeout=2000):
                        tag = loc.evaluate("el => el.tagName").lower()
                        if tag == "button":
                            has_easy_apply = True
                            break
                except Exception:
                    continue

            # Create output dir and tailor materials
            date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            dir_name = sanitize_filename(f"{company}_{actual_title[:40]}_{date_str}")
            job_dir = ensure_dir(PROJECT_ROOT / "output" / "applications" / dir_name)

            # Save JD
            jd_path = job_dir / "job_description.txt"
            jd_path.write_text(description)

            # Tailor resume
            logger.info("  Tailoring resume...")
            summary = tailor.tailor_summary(company, actual_title, description)
            competencies = tailor.tailor_competencies(description)
            resume_path = tailor.tailor_and_save(
                base_resume_path=BASE_RESUME,
                new_summary=summary,
                new_competencies=competencies,
                company=company,
                role=actual_title,
                output_dir=job_dir,
            )

            # Generate cover letter
            logger.info("  Generating cover letter...")
            cl_text = cover_gen.generate_text(company, actual_title, description)
            cl_path = cover_gen.generate_and_save(
                text=cl_text,
                candidate_profile=candidate,
                company=company,
                role=actual_title,
                output_dir=job_dir,
            )

            if has_easy_apply:
                logger.info(f"  EASY APPLY available! Submitting...")
                result = applicant.apply_to_job(
                    {"url": url, "title": actual_title, "company": company, "location": location},
                    resume_path,
                    cl_path,
                )
                status = result.get("status", "unknown")
                notes = result.get("reason", "")
                screenshots = result.get("screenshots", [])

                tracker.add_application(
                    company=company,
                    position=actual_title,
                    job_url=url,
                    location=location,
                    status=status,
                    resume_path=str(resume_path),
                    cover_letter_path=str(cl_path),
                    job_description=description[:500],
                    jd_file_path=str(jd_path),
                    notes=notes,
                    screenshots=screenshots,
                )

                if status == "applied":
                    easy_apply_done = True
                    logger.info(f"  SUCCESS: Easy Apply submitted for {actual_title} at {company}")
                    print(f"CYCLE_RESULT: applied|{company}|{actual_title}|easy_apply")
                else:
                    logger.info(f"  Easy Apply failed ({status}): {notes}")
            else:
                # External apply — save materials, mark manual_needed, keep looking
                logger.info(f"  External Apply only. Materials saved. Marking manual_needed.")
                tracker.add_application(
                    company=company,
                    position=actual_title,
                    job_url=url,
                    location=location,
                    status="manual_needed",
                    resume_path=str(resume_path),
                    cover_letter_path=str(cl_path),
                    job_description=description[:500],
                    jd_file_path=str(jd_path),
                    notes="external_apply_only_materials_saved",
                )
                logger.info(f"  Continuing search for Easy Apply...")

        if not easy_apply_done:
            logger.info("No Easy Apply submission this cycle.")
            print("CYCLE_RESULT: no_easy_apply_found")

    except Exception as e:
        logger.error(f"Cycle failed: {e}", exc_info=True)
        print(f"CYCLE_RESULT: error|{e}")
    finally:
        try:
            scanner.close()
        except Exception:
            pass
        logger.info("Cycle complete. Browser closed.")


if __name__ == "__main__":
    main()
