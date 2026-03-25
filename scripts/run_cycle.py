"""Main entry point for Aipply job application cycle.

Orchestrates the full workflow:
  1. Load configuration
  2. Scan LinkedIn for matching jobs
  3. Filter results (exclusions, already-applied)
  4. For each matching job:
     a. Tailor resume using AI
     b. Generate cover letter using AI
     c. Submit application
     d. Track the application
  5. Generate reports
"""

import json
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.cover_letter_gen import CoverLetterGenerator
from src.linkedin_applicant import LinkedInApplicant
from src.linkedin_scanner import LinkedInScanner
from src.resume_tailor import ResumeTailor
from src.utils import ensure_dir, get_timestamp, load_config, sanitize_filename


def run_cycle() -> None:
    """Execute one full application cycle."""

    # 1. Load configuration
    settings = load_config(PROJECT_ROOT / "config" / "settings.yaml")
    profile = load_config(PROJECT_ROOT / "config" / "profile.yaml")

    # 2. Initialize modules
    scanner = LinkedInScanner(config=settings)
    applicant = LinkedInApplicant(config=settings)
    tailor = ResumeTailor(config=settings)
    cover_gen = CoverLetterGenerator(config=settings)

    # 3. Load tracker
    tracker_path = PROJECT_ROOT / "output" / "tracker.json"
    tracker = json.loads(tracker_path.read_text()) if tracker_path.exists() else []
    applied_urls = {entry["url"] for entry in tracker if "url" in entry}

    # 4. Log in to LinkedIn
    applicant.login()

    # 5. Search and filter jobs
    all_jobs = []
    search_cfg = settings.get("search", {})
    for keyword in search_cfg.get("keywords", []):
        for location in search_cfg.get("locations", []):
            results = scanner.search_jobs([keyword], location)
            all_jobs.extend(results)

    filtered_jobs = scanner.filter_results(
        all_jobs, settings.get("exclusions", {})
    )

    # 6. Remove already-applied jobs
    new_jobs = [j for j in filtered_jobs if j.get("url") not in applied_urls]

    # 7. Apply to jobs (up to max per cycle)
    max_apps = settings.get("application", {}).get("max_applications_per_cycle", 10)
    base_resume = PROJECT_ROOT / "templates" / "base_resume.docx"
    candidate = profile.get("candidate", {})

    for job in new_jobs[:max_apps]:
        job_name = sanitize_filename(f"{job.get('company', 'unknown')}_{job.get('title', 'role')}")
        job_dir = ensure_dir(PROJECT_ROOT / "output" / "applications" / job_name)

        # Tailor resume
        resume_content = tailor.tailor_resume(base_resume, job.get("description", ""))
        resume_path = job_dir / "resume.docx"
        tailor.save_tailored_resume(resume_content, resume_path)

        # Generate cover letter
        cl_content = cover_gen.generate(job.get("description", ""), candidate)
        cl_path = job_dir / "cover_letter.docx"
        cover_gen.save_cover_letter(cl_content, cl_path)

        # Apply
        success = applicant.apply_to_job(job, resume_path, cl_path)

        # Track
        tracker.append({
            "url": job.get("url"),
            "title": job.get("title"),
            "company": job.get("company"),
            "applied_at": get_timestamp(),
            "success": success,
        })

    # 8. Save tracker
    tracker_path.write_text(json.dumps(tracker, indent=2))
    print(f"Cycle complete. Applied to {min(len(new_jobs), max_apps)} jobs.")


if __name__ == "__main__":
    run_cycle()
