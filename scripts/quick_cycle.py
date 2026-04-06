#!/usr/bin/env python3
"""Quick single-keyword cycle for Aipply.

Picks ONE keyword, searches TWO locations, finds new Easy Apply jobs, applies to 1.
Much faster than the full run_cycle.py which iterates all keywords.
"""

import json
import logging
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

logger = logging.getLogger("aipply.quick")

# Rotate keywords each cycle
KEYWORDS = [
    "compliance analyst",
    "senior compliance analyst",
    "compliance officer",
    "risk analyst",
    "audit analyst",
    "governance analyst",
    "regulatory analyst",
    "compliance specialist",
]

LOCATIONS = ["San Francisco Bay Area", "Remote"]

# Job-relevance filter
POSITIVE_WORDS = {
    "compliance", "risk", "audit", "fraud", "bsa", "aml", "regulatory",
    "governance", "monitoring", "analyst", "specialist", "examiner",
    "investigator", "testing", "quality control", "operations", "officer",
    "coordinator",
}
NEGATIVE_WORDS = {
    "investment banking", "software engineer", "data scientist", "sales rep",
    "marketing manager", "oracle cloud", "sap", "hcm", "payroll specialist",
    "customer service", "warehouse", "driver", "nurse", "teacher",
    "real estate", "proposal strategist", "medical coder",
}
EXCLUDE_COMPANIES = {"pge", "pg&e", "pacific gas", "pacific gas and electric"}


def pick_keyword():
    """Pick the next keyword to search based on a simple rotation file."""
    state_path = PROJECT_ROOT / "output" / "keyword_rotation.json"
    try:
        state = json.loads(state_path.read_text())
        last_idx = state.get("last_index", -1)
    except Exception:
        last_idx = -1
    next_idx = (last_idx + 1) % len(KEYWORDS)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({"last_index": next_idx, "keyword": KEYWORDS[next_idx]}))
    return KEYWORDS[next_idx]


def is_relevant(title: str) -> bool:
    """Check if a job title is relevant to the candidate's background."""
    t = title.lower()
    # Must not match negatives
    for neg in NEGATIVE_WORDS:
        if neg in t:
            return False
    # Must match at least one positive
    for pos in POSITIVE_WORDS:
        if pos in t:
            return True
    return False


def is_excluded_company(company: str) -> bool:
    c = company.lower()
    for exc in EXCLUDE_COMPANIES:
        if exc in c:
            return True
    return False


def run():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(PROJECT_ROOT / "output" / "aipply.log"),
        ],
    )

    settings = load_config(PROJECT_ROOT / "config" / "settings.yaml")
    profile = load_config(PROJECT_ROOT / "config" / "profile.yaml")
    tracker = ApplicationTracker(tracker_path=str(PROJECT_ROOT / "output" / "tracker.json"))

    # Load already-applied URLs
    applied_urls = set()
    try:
        existing = json.loads((PROJECT_ROOT / "output" / "tracker.json").read_text())
        for entry in existing:
            applied_urls.add(entry.get("job_url", ""))
    except Exception:
        pass

    keyword = pick_keyword()
    logger.info(f"=== Quick Cycle: keyword='{keyword}' ===")

    scanner = LinkedInScanner(config=settings)
    applicant = LinkedInApplicant(config=settings, profile=profile)
    tailor = ResumeTailor(config=settings)
    cover_gen = CoverLetterGenerator(config=settings)

    try:
        scanner_page = scanner.connect_browser()
        applicant.connect_browser(existing_page=scanner_page)

        # Search both locations for this keyword
        all_jobs = []
        for loc in LOCATIONS:
            logger.info(f"Searching: '{keyword}' in '{loc}'")
            try:
                results = scanner.search_jobs([keyword], loc, max_results=15)
                all_jobs.extend(results)
                logger.info(f"  Found {len(results)} results")
            except Exception as e:
                logger.error(f"  Search failed: {e}")

        # Deduplicate
        seen = set()
        unique = []
        for j in all_jobs:
            url = j.get("url", "")
            if url and url not in seen:
                seen.add(url)
                unique.append(j)

        logger.info(f"Unique jobs from search: {len(unique)}")

        # Filter: not applied, not excluded, relevant title
        candidates = []
        for j in unique:
            url = j.get("url", "")
            title = j.get("title", "")
            company = j.get("company", "")

            if url in applied_urls:
                logger.debug(f"  Skip (already applied): {title} at {company}")
                continue
            if is_excluded_company(company):
                logger.info(f"  Skip (excluded company): {title} at {company}")
                continue
            if not is_relevant(title):
                logger.info(f"  Skip (irrelevant title): {title} at {company}")
                continue
            candidates.append(j)

        logger.info(f"Candidates after filtering: {len(candidates)}")

        if not candidates:
            logger.info("No new relevant jobs found this cycle.")
            return {"status": "no_new_jobs", "keyword": keyword}

        # Get details for candidates and try to apply to the first Easy Apply one
        base_resume = PROJECT_ROOT / "templates" / "base_resume.docx"
        example_cover_letter = PROJECT_ROOT / "templates" / "base_cover_letter.docx"
        candidate_profile = profile.get("candidate", {})

        applied = False
        for i, job in enumerate(candidates):
            if i >= 5:  # Don't try more than 5
                break

            url = job.get("url", "")
            title = job.get("title", "")
            company = job.get("company", "")

            logger.info(f"[{i+1}/{min(len(candidates), 5)}] Getting details: {title} at {company}")

            try:
                details = scanner.get_job_details(url)
            except Exception as e:
                logger.error(f"  Failed to get details: {e}")
                continue

            description = details.get("description", "")
            if not description:
                logger.warning(f"  No description found, skipping")
                continue

            # Check if it's Easy Apply by navigating to the page
            # (the details page should still be loaded)
            is_easy = False
            try:
                for sel in [
                    'button[aria-label*="Easy Apply"]',
                    'button:has-text("Easy Apply")',
                ]:
                    loc = scanner._page.locator(sel).first
                    if loc.is_visible(timeout=2000):
                        btn_text = loc.inner_text().strip()
                        if "Easy" in btn_text:
                            is_easy = True
                            break
            except Exception:
                pass

            logger.info(f"  Easy Apply: {is_easy}")

            # Create output dir
            date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            dir_name = sanitize_filename(f"{company}_{title}_{date_str}")
            job_dir = ensure_dir(PROJECT_ROOT / "output" / "applications" / dir_name)

            # Save JD
            jd_path = job_dir / "job_description.txt"
            jd_path.write_text(description[:3000])

            # Tailor resume
            logger.info("  Tailoring resume...")
            try:
                new_summary = ResumeTailor.tailor_summary(company, title, description)
                new_competencies = ResumeTailor.tailor_competencies(description)
                resume_path = tailor.tailor_and_save(
                    base_resume_path=base_resume,
                    new_summary=new_summary,
                    new_competencies=new_competencies,
                    company=company,
                    role=title,
                    output_dir=job_dir,
                )
            except Exception as e:
                logger.error(f"  Resume tailoring failed: {e}")
                continue

            # Generate cover letter
            logger.info("  Generating cover letter...")
            try:
                cl_text = CoverLetterGenerator.generate_text(company, title, description)
                cl_path = cover_gen.generate_and_save(
                    text=cl_text,
                    candidate_profile=candidate_profile,
                    company=company,
                    role=title,
                    output_dir=job_dir,
                )
            except Exception as e:
                logger.error(f"  Cover letter generation failed: {e}")
                cl_path = None

            # Apply
            logger.info(f"  Applying to {title} at {company}...")
            result = applicant.apply_to_job(details, str(resume_path), str(cl_path) if cl_path else None)
            status = result.get("status", "unknown")
            notes = result.get("reason", "")
            screenshots = result.get("screenshots", [])

            logger.info(f"  Result: {status} — {notes}")

            tracker.add_application(
                company=company,
                position=title,
                job_url=url,
                location=details.get("location", job.get("location", "")),
                status=status,
                resume_path=str(resume_path) if resume_path else "",
                cover_letter_path=str(cl_path) if cl_path else "",
                jd_file_path=str(jd_path),
                job_description=description[:1000],
                notes=f"{notes} | screenshots: {','.join(screenshots)}" if screenshots else notes,
                screenshots=screenshots,
            )

            if status == "applied":
                applied = True
                logger.info(f"SUCCESS: Applied to {title} at {company}")
                return {
                    "status": "applied",
                    "company": company,
                    "title": title,
                    "url": url,
                    "keyword": keyword,
                    "is_easy_apply": is_easy,
                }

            # If this was Easy Apply but failed, keep trying
            # If external apply, mark and keep looking for Easy Apply
            if not is_easy:
                logger.info(f"  External apply — keeping materials, moving on to find Easy Apply")
                continue

        if not applied:
            return {"status": "no_easy_apply_found", "keyword": keyword, "tried": min(len(candidates), 5)}

    finally:
        scanner.close()


if __name__ == "__main__":
    result = run()
    print(f"\n{'='*50}")
    print(f"RESULT: {json.dumps(result, indent=2)}")
    print(f"{'='*50}")
