#!/usr/bin/env python3
"""
Aipply quick run — scan LinkedIn, tailor materials, track & report.

The AI tailoring is done by the calling agent (Pista/OpenClaw), not by API calls.
This script handles scanning, file I/O, and tracking.
"""

import os
import sys
import json
import shutil
import yaml
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from src.linkedin_scanner import LinkedInScanner
from src.resume_tailor import ResumeTailor
from src.cover_letter_gen import CoverLetterGenerator
from src.tracker import ApplicationTracker
from src.deslop import clean_docx

STOP_FILE = Path('/Users/sacsimoto/GitHub/aipply/.stop')


def scan_jobs(keyword="compliance manager", location="San Francisco Bay Area", limit=5):
    """Scan LinkedIn and return jobs with full descriptions."""
    if STOP_FILE.exists():
        print("🛑 EMERGENCY STOP — .stop file detected")
        return []
    settings = yaml.safe_load(open('config/settings.yaml'))
    exclusions = [c.lower() for c in settings.get('exclusions', {}).get('companies', [])]
    exclusions += ['pg&e', 'pacific gas']

    scanner = LinkedInScanner(config=settings)
    scanner.connect_browser()

    # Get cards
    cards = scanner.search_jobs(keywords=keyword, location=location, max_results=limit + 5)
    cards = [j for j in cards if not any(ex in j.get('company', '').lower() for ex in exclusions)]

    # Fetch full descriptions
    tracker = ApplicationTracker('output/tracker.json')
    jobs = []
    for card in cards[:limit]:
        url = card.get('url', '')
        card_company = card.get('company', '').strip()
        card_title = card.get('title', '').split('\n')[0].strip()
        if not url or tracker.is_already_applied(job_url=url, company=card_company, position=card_title):
            print(f"  ⏭️  Skipping (already applied): {card_company} — {card_title}")
            continue
        try:
            details = scanner.get_job_details(url)
            if details.get('description'):
                jobs.append(details)
        except Exception as e:
            print(f"  ⚠️ Failed to get details for {card.get('company')}: {e}")

    scanner.close()
    return jobs


def save_application(job: dict, tailored_summary: str, competencies: list,
                      cover_letter_text: str, dry_run=False):
    """Save tailored materials and track the application."""
    if STOP_FILE.exists():
        print("🛑 STOP — .stop file detected")
        return None
    settings = yaml.safe_load(open('config/settings.yaml'))
    profile = yaml.safe_load(open('config/profile.yaml'))
    candidate = profile.get('candidate', {})

    company = (job.get('company') or 'Unknown').strip()
    title = (job.get('title') or 'Role').split('\n')[0].strip()
    location = job.get('location', '')
    url = job.get('url', '')
    desc = job.get('description', '')

    # Dedup check — skip if already applied (by URL or company+title)
    tracker_check = ApplicationTracker('output/tracker.json')
    if tracker_check.is_already_applied(job_url=url, company=company, position=title):
        print(f"⏭️  Already applied: {company} — {title}")
        return None

    co_safe = company.replace(' ', '_').replace('/', '_').replace(',', '')[:25]
    ti_safe = title.replace(' ', '_').replace('/', '_').replace(',', '')[:25]
    out_dir = Path(f"output/applications/{co_safe}_{ti_safe}_{datetime.now().strftime('%Y%m%d_%H%M')}")
    out_dir.mkdir(parents=True, exist_ok=True)

    # Save tailored resume
    tailor = ResumeTailor()
    resume_path = tailor.tailor_and_save(
        'templates/base_resume.docx', tailored_summary, competencies,
        company, title, str(out_dir)
    )

    # Save cover letter
    cl_gen = CoverLetterGenerator()
    cl_path = cl_gen.generate_and_save(
        cover_letter_text, candidate, company, title, str(out_dir)
    )

    # Save job description
    jd_path = out_dir / 'job_description.txt'
    jd_path.write_text(f"Company: {company}\nTitle: {title}\nLocation: {location}\nURL: {url}\n\n{desc}")

    # De-slop all generated docs
    if resume_path:
        clean_docx(resume_path)
    if cl_path:
        clean_docx(cl_path)

    # --- Easy Apply submission ---
    status = 'materials_ready'
    saved_screenshots = []
    if not dry_run:
        try:
            from src.linkedin_applicant import LinkedInApplicant
            applicant = LinkedInApplicant(config=settings, profile=profile)
            applicant.connect_browser()
            apply_result = applicant.apply_to_job(
                job={'url': url, 'title': title, 'company': company},
                resume_path=str(resume_path),
                cover_letter_path=str(cl_path) if cl_path else None,
            )
            applicant.close()

            # Copy screenshots to application output directory
            apply_screenshots = apply_result.get('screenshots', [])
            for ss_path in apply_screenshots:
                if ss_path and Path(ss_path).exists():
                    dest = out_dir / Path(ss_path).name
                    shutil.copy2(ss_path, dest)
                    saved_screenshots.append(str(dest.resolve()))

            # Map status — "applied" stays applied, everything else → manual_needed
            apply_status = apply_result.get('status', 'failed')
            if apply_status == 'applied':
                status = 'applied'
            elif apply_result.get('reason') == 'not_easy_apply':
                status = 'manual_needed'
            else:
                status = 'manual_needed'
        except Exception as e:
            print(f"  ⚠️ Easy Apply failed: {e}")
            status = 'manual_needed'

    # Build notes with screenshot paths
    apply_notes = ''
    if not dry_run:
        try:
            apply_notes = apply_result.get('reason', '')
        except NameError:
            apply_notes = ''
    if saved_screenshots:
        apply_notes += f" | screenshots: {','.join(saved_screenshots)}"

    # Track
    tracker = ApplicationTracker('output/tracker.json')
    tracker.add_application(
        company=company, position=title, job_url=url, location=location,
        status=status,
        resume_path=str(resume_path),
        cover_letter_path=str(cl_path),
        jd_file_path=str(jd_path),
        job_description=desc[:500],
        notes=apply_notes.strip(),
        screenshots=saved_screenshots,
    )

    # Regenerate report
    tracker.generate_html_report('output/reports/applications_report.html')

    return {
        'company': company, 'title': title,
        'resume': str(resume_path), 'cover_letter': str(cl_path),
        'job_description': str(jd_path),
        'screenshots': saved_screenshots,
        'apply_status': status,
    }


if __name__ == "__main__":
    keyword = sys.argv[1] if len(sys.argv) > 1 else "compliance manager"
    location = sys.argv[2] if len(sys.argv) > 2 else "San Francisco Bay Area"
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else 5

    jobs = scan_jobs(keyword, location, limit)
    print(json.dumps(jobs, indent=2, default=str))
