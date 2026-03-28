"""Main entry point for Aipply job application cycle.

Orchestrates: scan → filter → tailor → generate cover letter → apply → track → report
"""

import argparse
import json
import logging
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
from src.deslop import clean_docx
from src.utils import load_config, ensure_dir, sanitize_filename, get_timestamp

logger = logging.getLogger("aipply")


def setup_logging(verbose=False):
    """Configure logging to console and file.

    Args:
        verbose: If True, set DEBUG level; otherwise INFO.
    """
    level = logging.DEBUG if verbose else logging.INFO
    log_dir = PROJECT_ROOT / "output"
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_dir / "aipply.log"),
        ],
    )


def parse_args(args=None):
    """Parse command-line arguments.

    Args:
        args: Optional list of argument strings (for testing).

    Returns:
        Parsed argparse.Namespace.
    """
    parser = argparse.ArgumentParser(
        description="Aipply - Automated Job Application Cycle"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Scan only, don't apply"
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Max applications this cycle"
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Only generate report from existing data",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Verbose logging"
    )
    parser.add_argument(
        "--cdp-url", type=str, default=None, help="Chrome DevTools Protocol URL"
    )
    return parser.parse_args(args)


def run_cycle(args=None):
    """Execute one full application cycle.

    Args:
        args: Optional argparse.Namespace (for testing).
              If None, parses from sys.argv.
    """
    if args is None:
        args = parse_args()

    setup_logging(args.verbose)

    # Load configs
    settings = load_config(PROJECT_ROOT / "config" / "settings.yaml")
    profile = load_config(PROJECT_ROOT / "config" / "profile.yaml")

    # Initialize tracker
    tracker = ApplicationTracker(
        tracker_path=str(PROJECT_ROOT / "output" / "tracker.json")
    )

    # Report-only mode
    if args.report_only:
        report_path = tracker.generate_html_report(
            output_path=str(
                PROJECT_ROOT
                / "output"
                / "reports"
                / f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
            )
        )
        logger.info(f"Report generated: {report_path}")
        return

    # Initialize modules
    scanner = LinkedInScanner(config=settings)
    tailor = ResumeTailor(config=settings)
    cover_gen = CoverLetterGenerator(config=settings)
    applicant = (
        LinkedInApplicant(config=settings, profile=profile)
        if not args.dry_run
        else None
    )

    try:
        # Connect browser for scanner
        scanner.connect_browser(cdp_url=args.cdp_url)
        if applicant:
            applicant.connect_browser(cdp_url=args.cdp_url)

        # Search for jobs
        search_cfg = settings.get("search", {})
        all_jobs = []
        for keyword in search_cfg.get("keywords", []):
            for location in search_cfg.get("locations", []):
                logger.info(f"Searching: '{keyword}' in '{location}'")
                try:
                    results = scanner.search_jobs([keyword], location)
                    all_jobs.extend(results)
                    logger.info(f"  Found {len(results)} results")
                except Exception as e:
                    logger.error(f"  Search failed: {e}")
                    continue

        # Deduplicate by URL
        seen_urls = set()
        unique_jobs = []
        for job in all_jobs:
            url = job.get("url", "")
            if url not in seen_urls:
                seen_urls.add(url)
                unique_jobs.append(job)

        # Filter exclusions
        filtered_jobs = scanner.filter_results(
            unique_jobs, settings.get("exclusions", {})
        )
        logger.info(
            f"After filtering: {len(filtered_jobs)} jobs (from {len(all_jobs)} total)"
        )

        # Skip already-applied
        new_jobs = [
            j for j in filtered_jobs if not tracker.is_already_applied(j.get("url", ""))
        ]
        logger.info(f"New jobs to process: {len(new_jobs)}")

        # Get full details for each job
        detailed_jobs = []
        for job in new_jobs:
            try:
                details = scanner.get_job_details(job.get("url", ""))
                detailed_jobs.append(details)
            except Exception as e:
                logger.error(f"Failed to get details for {job.get('url')}: {e}")
                job["description"] = ""
                detailed_jobs.append(job)

        # Apply limit
        max_apps = args.limit or settings.get("application", {}).get(
            "max_applications_per_cycle", 10
        )
        jobs_to_process = detailed_jobs[:max_apps]

        base_resume = PROJECT_ROOT / "templates" / "base_resume.docx"
        example_cover_letter = PROJECT_ROOT / "templates" / "base_cover_letter.docx"
        candidate = profile.get("candidate", {})

        applied_count = 0
        failed_count = 0
        skipped_count = 0

        for i, job in enumerate(jobs_to_process, 1):
            company = job.get("company", "unknown")
            role = job.get("title", "role")
            job_url = job.get("url", "")
            description = job.get("description", "")

            logger.info(f"[{i}/{len(jobs_to_process)}] Processing: {role} at {company}")

            # Create output directory
            date_str = datetime.now().strftime("%Y-%m-%d")
            dir_name = sanitize_filename(f"{company}_{role}_{date_str}")
            job_dir = ensure_dir(PROJECT_ROOT / "output" / "applications" / dir_name)

            try:
                # A. Tailor resume
                logger.info("  Tailoring resume...")
                new_summary = ResumeTailor.tailor_summary(company, role, description)
                new_competencies = ResumeTailor.tailor_competencies(description)
                resume_path = tailor.tailor_and_save(
                    base_resume_path=base_resume,
                    new_summary=new_summary,
                    new_competencies=new_competencies,
                    company=company,
                    role=role,
                    output_dir=job_dir,
                )
                logger.info(f"  Resume saved: {resume_path}")

                # B. Generate cover letter
                logger.info("  Generating cover letter...")
                cl_text = CoverLetterGenerator.generate_text(company, role, description)
                cl_path = cover_gen.generate_and_save(
                    text=cl_text,
                    candidate_profile=candidate,
                    company=company,
                    role=role,
                    output_dir=job_dir,
                )
                logger.info(f"  Cover letter saved: {cl_path}")

                # C. Apply (unless dry run)
                if args.dry_run:
                    logger.info(f"  [DRY RUN] Would apply to {role} at {company}")
                    status = "dry_run"
                    notes = "Dry run - not applied"
                else:
                    logger.info("  Submitting application...")
                    result = applicant.apply_to_job(job, resume_path, cl_path)
                    status = result.get("status", "unknown")
                    notes = result.get("reason", "")
                    logger.info(f"  Result: {status} - {notes}")

                # D. Record in tracker
                tracker.add_application(
                    company=company,
                    position=role,
                    job_url=job_url,
                    location=job.get("location", ""),
                    status=status,
                    resume_path=str(resume_path) if resume_path else "",
                    cover_letter_path=str(cl_path) if cl_path else "",
                    notes=notes,
                )

                if status == "applied":
                    applied_count += 1
                elif status == "failed":
                    failed_count += 1
                else:
                    skipped_count += 1

            except Exception as e:
                logger.error(f"  Failed to process {role} at {company}: {e}")
                failed_count += 1
                tracker.add_application(
                    company=company,
                    position=role,
                    job_url=job_url,
                    status="failed",
                    notes=str(e),
                )
                continue

        # Generate report
        report_path = tracker.generate_html_report(
            output_path=str(
                PROJECT_ROOT
                / "output"
                / "reports"
                / f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
            )
        )

        logger.info(f"\n{'=' * 50}")
        logger.info("Cycle complete!")
        logger.info(f"  Applied: {applied_count}")
        logger.info(f"  Failed: {failed_count}")
        logger.info(f"  Skipped: {skipped_count}")
        logger.info(f"  Report: {report_path}")
        logger.info(f"{'=' * 50}")

    finally:
        scanner.close()
        if applicant:
            applicant.close()


if __name__ == "__main__":
    run_cycle()
