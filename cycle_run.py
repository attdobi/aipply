#!/usr/bin/env python3
"""AIPPLY Cycle — Search LinkedIn, find Easy Apply jobs, tailor materials, apply."""

import json
import logging
import random
import sys
import time
from datetime import datetime
from pathlib import Path

# Project imports
from src.linkedin_scanner import LinkedInScanner
from src.linkedin_applicant import LinkedInApplicant
from src.resume_tailor import ResumeTailor
from src.cover_letter_gen import CoverLetterGenerator
from src.tracker import ApplicationTracker
from src.job_filter import filter_job
from src.utils import ensure_dir, sanitize_filename

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("cycle")

# ── Config ───────────────────────────────────────────────────────────
BASE_RESUME = Path("templates/base_resume.docx")
BASE_COVER_LETTER = Path("templates/base_cover_letter.docx")
TRACKER_PATH = "output/tracker.json"
PROFILE_PATH = "config/profile.yaml"

# Rotate keywords — pick one that yields fresh results
KEYWORDS = [
    "compliance specialist",
    "governance analyst",
    "regulatory analyst",
    "compliance officer",
    "audit analyst",
    "risk analyst",
    "compliance analyst",
    "senior compliance analyst",
]

LOCATIONS = ["San Francisco Bay Area", "Remote"]

CANDIDATE = {
    "name": "Danna Z. Dobi",
    "email": "danna.dobi@gmail.com",
    "phone": "510-333-8812",
    "linkedin_url": "https://www.linkedin.com/in/danna-dobi/",
    "address": "9 Bordwell Court, Alameda CA 94502",
    "how_did_you_hear": "LinkedIn",
}


def load_profile():
    """Load candidate profile from YAML."""
    import yaml
    with open(PROFILE_PATH) as f:
        return yaml.safe_load(f)


def main():
    tracker = ApplicationTracker(TRACKER_PATH)
    profile_data = load_profile()
    tailor = ResumeTailor()
    cl_gen = CoverLetterGenerator()

    # Pick keyword for this cycle — rotate based on hour
    hour = datetime.now().hour
    keyword = KEYWORDS[hour % len(KEYWORDS)]
    location = random.choice(LOCATIONS)
    logger.info(f"=== CYCLE START: keyword='{keyword}', location='{location}' ===")

    scanner = LinkedInScanner()
    page = None
    applicant = None
    applied_count = 0
    results_summary = []

    try:
        # Launch browser
        page = scanner.connect_browser()
        logger.info("Browser launched")

        # Search
        jobs = scanner.search_jobs(keywords=keyword, location=location, max_results=25)
        logger.info(f"Found {len(jobs)} raw results")

        if not jobs:
            logger.warning("No jobs found in search results")
            return {"keyword": keyword, "location": location, "jobs_found": 0, "applied": 0, "results": []}

        # Filter
        filtered = []
        for job in jobs:
            passes, reason = filter_job(job)
            if passes:
                filtered.append(job)
            else:
                logger.debug(f"Filtered out: {job.get('title','')} @ {job.get('company','')} — {reason}")

        logger.info(f"After filter: {len(filtered)} relevant jobs from {len(jobs)} total")

        if not filtered:
            logger.warning("No relevant jobs after filtering")
            return {"keyword": keyword, "location": location, "jobs_found": len(jobs), "filtered": 0, "applied": 0, "results": []}

        # Set up applicant (reuse scanner's page)
        applicant = LinkedInApplicant(profile=profile_data)
        applicant.connect_browser(existing_page=page)

        # Process jobs — prioritize Easy Apply
        for job in filtered:
            job_url = job.get("url", "")
            company = job.get("company", "")
            title = job.get("title", "")

            # Skip already applied
            if tracker.is_already_applied(job_url=job_url, company=company, position=title):
                logger.info(f"Already applied: {title} @ {company}, skipping")
                continue

            logger.info(f"Processing: {title} @ {company}")

            # Get full job description
            try:
                details = scanner.get_job_details(job_url)
                description = details.get("description", "")
                if not description:
                    logger.warning(f"No description for {title} @ {company}, skipping")
                    continue
            except Exception as e:
                logger.error(f"Failed to get details for {title} @ {company}: {e}")
                continue

            # Check for Easy Apply before investing time in tailoring
            # IMPORTANT: Only check the top-card / main job actions area,
            # NOT sidebar recommendation cards which may show Easy Apply for other jobs.
            try:
                has_easy_apply = False
                # Scoped selectors: LinkedIn's main job apply button lives in
                # the top-card or jobs-apply-button container
                top_card_scopes = [
                    '.job-details-jobs-unified-top-card__container--two-pane',
                    '.jobs-unified-top-card',
                    '.jobs-apply-button',
                    '.jobs-s-apply',
                    '.job-details-jobs-unified-top-card',
                ]
                ea_btns = [
                    'button[aria-label*="Easy Apply"]',
                    'button:has-text("Easy Apply")',
                    'a[aria-label*="Easy Apply"]',
                ]

                for scope in top_card_scopes:
                    scope_loc = page.locator(scope)
                    if scope_loc.count() == 0:
                        continue
                    for ea_sel in ea_btns:
                        try:
                            loc = scope_loc.locator(ea_sel).first
                            if loc.is_visible(timeout=1500):
                                has_easy_apply = True
                                logger.info(f"Easy Apply confirmed in scope '{scope}' for {title} @ {company}")
                                break
                        except Exception:
                            continue
                    if has_easy_apply:
                        break

                # Fallback: check for Easy Apply button that's a direct child
                # of the page's main content (not inside job cards list)
                if not has_easy_apply:
                    try:
                        # The main job's apply button typically appears outside
                        # .jobs-search-results-list; check that the button text
                        # is short (just "Easy Apply", not a full job card)
                        for ea_sel in ea_btns:
                            loc = page.locator(ea_sel).first
                            if loc.is_visible(timeout=1500):
                                btn_text = loc.inner_text().strip()
                                # Real Easy Apply buttons have short text
                                if "Easy Apply" in btn_text and len(btn_text) < 30:
                                    has_easy_apply = True
                                    logger.info(f"Easy Apply confirmed (short text) for {title} @ {company}")
                                    break
                    except Exception:
                        pass

                if not has_easy_apply:
                    logger.info(f"No Easy Apply for {title} @ {company} — skipping to find Easy Apply jobs first")
                    continue
            except Exception:
                continue

            # Tailor materials
            logger.info(f"Easy Apply found! Tailoring materials for {title} @ {company}")

            date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_company = sanitize_filename(company)
            safe_role = sanitize_filename(title)
            output_dir = Path("output") / "applications" / f"{safe_company}_{safe_role[:30]}_{date_str}"
            ensure_dir(output_dir)

            # Save JD
            jd_path = output_dir / "job_description.txt"
            jd_path.write_text(f"Company: {company}\nTitle: {title}\nURL: {job_url}\nLocation: {job.get('location','')}\n\n{description}")

            # Tailor resume
            summary = tailor.tailor_summary(company, title, description)
            competencies = tailor.tailor_competencies(description)
            resume_path = tailor.tailor_and_save(
                base_resume_path=BASE_RESUME,
                new_summary=summary,
                new_competencies=competencies,
                company=company,
                role=title,
                output_dir=output_dir,
            )
            logger.info(f"Resume saved: {resume_path}")

            # Generate cover letter
            cl_text = cl_gen.generate_text(company, title, description)
            cl_path = cl_gen.generate_and_save(
                text=cl_text,
                candidate_profile=CANDIDATE,
                company=company,
                role=title,
                output_dir=output_dir,
            )
            logger.info(f"Cover letter saved: {cl_path}")

            # Apply
            result = applicant.apply_to_job(
                job={"url": job_url, "title": title, "company": company, "location": job.get("location", "")},
                resume_path=str(resume_path),
                cover_letter_path=str(cl_path),
            )

            status = result.get("status", "apply_failed")
            reason = result.get("reason", "")
            screenshots = result.get("screenshots", [])

            logger.info(f"Result for {title} @ {company}: status={status}, reason={reason}")

            # Track
            tracker.add_application(
                company=company,
                position=title,
                job_url=job_url,
                location=job.get("location", ""),
                status=status,
                resume_path=str(resume_path),
                cover_letter_path=str(cl_path),
                job_description=description[:500],
                jd_file_path=str(jd_path),
                notes=f"{reason} | screenshots: {','.join(screenshots)}" if screenshots else reason,
                screenshots=screenshots,
            )

            results_summary.append({
                "company": company,
                "title": title,
                "status": status,
                "reason": reason,
            })

            if status == "applied":
                applied_count += 1
                logger.info(f"SUCCESS: Applied to {title} @ {company}")
                break  # Goal: 1 Easy Apply per cycle

            # Human-like delay between attempts
            time.sleep(random.uniform(5, 10))

        summary = {
            "keyword": keyword,
            "location": location,
            "jobs_found": len(jobs),
            "filtered": len(filtered),
            "applied": applied_count,
            "results": results_summary,
        }
        logger.info(f"=== CYCLE COMPLETE: {json.dumps(summary, indent=2)} ===")
        return summary

    except Exception as e:
        logger.error(f"Cycle failed: {e}", exc_info=True)
        return {"error": str(e)}

    finally:
        # Close browser
        try:
            scanner.close()
        except Exception:
            pass
        logger.info("Browser closed")


if __name__ == "__main__":
    result = main()
    print(json.dumps(result, indent=2))
