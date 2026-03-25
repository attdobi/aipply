#!/usr/bin/env python3
"""
Aipply Apply Loop — continuous job application bot.

Scans LinkedIn, finds Easy Apply jobs matching compliance/audit/risk profile,
tailors resume + cover letter, submits application, waits, repeats.

Usage:
    python scripts/apply_loop.py                # defaults
    python scripts/apply_loop.py --interval 600 # 10 min between apps
    python scripts/apply_loop.py --max-apps 20  # stop after 20

Stop gracefully by creating a .stop file in the project root:
    touch /Users/sacsimoto/GitHub/aipply/.stop
"""

import argparse
import json
import logging
import os
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

# Setup paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(str(PROJECT_ROOT))

from src.linkedin_scanner import LinkedInScanner
from src.linkedin_applicant import LinkedInApplicant
from src.resume_tailor import ResumeTailor
from src.cover_letter_gen import CoverLetterGenerator
from src.tracker import ApplicationTracker
from src.deslop import clean_docx
import importlib
import src.job_filter as _job_filter_mod
from src.job_filter import filter_job, is_relevant_title
from src.utils import ensure_dir, sanitize_filename

# Config
STOP_FILE = PROJECT_ROOT / ".stop"
TRACKER_PATH = PROJECT_ROOT / "output" / "tracker.json"
BASE_RESUME = PROJECT_ROOT / "templates" / "base_resume.docx"
LOG_FILE = PROJECT_ROOT / "output" / "apply_loop.log"

SEARCH_KEYWORDS = [
    "compliance analyst",
    "risk analyst",
    "audit analyst",
    "BSA AML analyst",
    "regulatory analyst",
    "compliance specialist",
    "fraud analyst",
    "governance analyst",
]

SEARCH_LOCATIONS = [
    "San Francisco Bay Area",
    "United States",  # for remote
]

CANDIDATE = {
    "name": "Danna Z. Dobi",
    "email": "danna.dobi@gmail.com",
    "phone": "510-333-8812",
}

# Setup logging
ensure_dir(PROJECT_ROOT / "output")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(str(LOG_FILE), mode="a"),
    ],
)
logger = logging.getLogger("apply_loop")


def should_stop() -> bool:
    """Check if the .stop file exists."""
    return STOP_FILE.exists()


def tailor_summary_local(company, title, description):
    """Generate tailored professional summary based on JD keywords."""
    desc_lower = description.lower()

    themes = []
    if any(w in desc_lower for w in ["aml", "anti-money laundering", "bsa", "bank secrecy"]):
        themes.append("aml_bsa")
    if any(w in desc_lower for w in ["fraud", "investigation", "suspicious activity"]):
        themes.append("fraud")
    if any(w in desc_lower for w in ["risk assessment", "risk management", "enterprise risk"]):
        themes.append("risk")
    if any(w in desc_lower for w in ["audit", "internal audit", "testing"]):
        themes.append("audit")
    if any(w in desc_lower for w in ["fintech", "digital banking", "financial technology"]):
        themes.append("fintech")
    if any(w in desc_lower for w in ["regulatory", "examination", "regulator", "occ", "fdic", "cfpb"]):
        themes.append("regulatory")
    if any(w in desc_lower for w in ["compliance monitoring", "monitoring program"]):
        themes.append("monitoring")
    if any(w in desc_lower for w in ["governance", "policy", "controls"]):
        themes.append("governance")

    base = (
        "Compliance professional with 9+ years of experience, including over four years "
        "as a federal bank examiner with the Office of the Comptroller of the Currency (OCC). "
        "That background means walking into any compliance environment with a regulator's eye: "
        "knowing what examiners look for, how monitoring programs get evaluated, "
        "and what makes documentation hold up."
    )

    if "aml_bsa" in themes or "fraud" in themes:
        middle = (
            " Since leaving the OCC, hands-on roles in fintech and banking have focused on "
            "compliance monitoring, fraud risk assessment, and BSA/AML program oversight, "
            "including transaction monitoring, suspicious activity reporting, and regulatory "
            "exam preparation."
        )
    elif "risk" in themes:
        middle = (
            " Since leaving the OCC, hands-on roles in fintech and banking have centered on "
            "risk assessment, compliance testing, and controls evaluation, with direct experience "
            "identifying emerging risk patterns, documenting findings, and keeping governance "
            "artifacts exam-ready."
        )
    elif "fintech" in themes:
        middle = (
            " Since leaving the OCC, hands-on roles at fintech-bank partnerships and digital "
            "banking institutions have focused on compliance monitoring, audit program management, "
            "and keeping governance artifacts exam-ready in fast-moving regulatory environments."
        )
    elif "audit" in themes:
        middle = (
            " Since leaving the OCC, hands-on roles in fintech and banking have focused on "
            "audit program management, compliance testing, and remediation validation, "
            "with a track record of keeping documentation in exam-ready condition."
        )
    else:
        middle = (
            " Since leaving the OCC, hands-on roles in fintech and banking have focused on "
            "compliance monitoring, reviewing customer-facing communications and marketing materials, "
            "validating remediation, and keeping governance artifacts exam-ready."
        )

    closing = (
        " Known for taking full ownership of assigned work and translating complex findings "
        "into summaries leadership can use."
    )

    return base + middle + closing


def tailor_competencies_local(description):
    """Reorder core competencies based on JD."""
    desc_lower = description.lower()

    all_comps = [
        "Compliance Monitoring & Validation Execution",
        "Customer-Facing Channel Reviews (Communications, Marketing, Sales Practices)",
        "Findings Documentation, Classification & Escalation",
        "Remediation Follow-Up Testing & Confirmation Reviews",
        "Issue Intake, Tracking & Management",
        "Audit-Ready Evidence Preparation",
        "Regulatory Exam Support",
        "Policy Lifecycle Management",
        "Internal Controls & Testing",
        "Process Improvement & Documentation Quality",
    ]

    extras = {
        "aml": "BSA/AML Compliance & Transaction Monitoring",
        "fraud": "Fraud Risk Assessment & Investigation Support",
        "risk assessment": "Risk Assessment & Controls Evaluation",
        "governance": "Corporate Governance & Regulatory Reporting",
        "fintech": "Fintech & Digital Banking Compliance",
        "data analysis": "Data Analysis & Trend Identification",
        "third party": "Third-Party Risk Oversight",
        "vendor": "Third-Party Risk Oversight",
    }

    selected = []
    used = set()

    for keyword, comp in extras.items():
        if keyword in desc_lower and comp not in used and len(selected) < 2:
            selected.append(comp)
            used.add(comp)

    scored = []
    for comp in all_comps:
        score = sum(1 for word in comp.lower().split() if len(word) > 3 and word in desc_lower)
        scored.append((score, comp))
    scored.sort(key=lambda x: -x[0])

    for _, comp in scored:
        if comp not in used and len(selected) < 10:
            selected.append(comp)
            used.add(comp)

    return selected[:10]


def generate_cover_letter_local(company, title, description):
    """Generate tailored cover letter text."""
    desc_lower = description.lower()

    highlights = []
    if any(w in desc_lower for w in ["aml", "bsa", "anti-money laundering"]):
        highlights.append("BSA/AML compliance and transaction monitoring")
    if any(w in desc_lower for w in ["risk assessment", "risk management"]):
        highlights.append("risk assessment and controls evaluation")
    if any(w in desc_lower for w in ["audit", "testing", "quality control"]):
        highlights.append("audit program management and compliance testing")
    if any(w in desc_lower for w in ["regulatory", "examination", "examiner"]):
        highlights.append("regulatory examination support and exam-readiness")
    if any(w in desc_lower for w in ["monitoring", "surveillance"]):
        highlights.append("compliance monitoring and validation")
    if any(w in desc_lower for w in ["fraud", "investigation"]):
        highlights.append("fraud detection and investigation support")
    if any(w in desc_lower for w in ["governance", "policy"]):
        highlights.append("governance reporting and policy management")
    if any(w in desc_lower for w in ["fintech", "digital banking"]):
        highlights.append("fintech and digital banking compliance")
    if any(w in desc_lower for w in ["remediation", "corrective action"]):
        highlights.append("remediation tracking and confirmation testing")
    if any(w in desc_lower for w in ["documentation", "reporting"]):
        highlights.append("findings documentation and regulatory reporting")

    if not highlights:
        highlights = ["compliance monitoring and validation", "regulatory exam support"]

    highlights = highlights[:3]

    today = datetime.now().strftime("%B %d, %Y")

    letter = f"""{today}

Dear Hiring Manager,

I'm writing to apply for the {title} position at {company}. With 9+ years of compliance experience, including four years as a federal bank examiner with the OCC and subsequent roles in fintech and banking, I bring a practical understanding of what regulators expect and how to build programs that hold up under scrutiny.

My background maps directly to what this role requires. At the OCC, I conducted safety-and-soundness and compliance examinations of nationally chartered banks, covering {highlights[0]}. That examiner perspective carries into every role since: at Cross River Bank, I led compliance and operational risk audits; at Prime Trust, I managed audit and compliance monitoring programs across fintech operations.

"""
    if len(highlights) > 1:
        letter += (
            f"What I'd bring to {company} is hands-on experience in {highlights[1]}, "
            f"combined with the ability to translate complex findings into clear, actionable write-ups. "
        )

    if len(highlights) > 2:
        letter += (
            f"I also have direct experience with {highlights[2]}, "
            f"which I understand is central to this role. "
        )

    letter += f"""I hold both a CFE and CAMS certification, and my work consistently focuses on making compliance programs practical, well-documented, and ready for whatever questions come next.

I'd welcome the chance to discuss how my background fits what {company} is building.

Thank you for your time.

Best regards,"""

    return letter


def run_single_cycle(scanner_page, tracker, tailor, cl_gen, keyword, location):
    """Run a single scan+apply cycle for one keyword/location combo.

    Returns:
        dict with result info, or None if no job found/applied.
    """
    # Hot-reload filter module so code changes take effect without restart
    global filter_job, is_relevant_title
    importlib.reload(_job_filter_mod)
    filter_job = _job_filter_mod.filter_job
    is_relevant_title = _job_filter_mod.is_relevant_title

    logger.info(f"Scanning: '{keyword}' in '{location}'")

    extra_params = ""
    if location == "United States":
        extra_params = "&f_WT=2"  # Remote filter

    search_url = (
        f"https://www.linkedin.com/jobs/search/"
        f"?keywords={quote_plus(keyword)}"
        f"&location={quote_plus(location)}"
        f"&f_AL=true"
        f"&sortBy=DD"
        f"{extra_params}"
    )

    scanner_page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
    time.sleep(random.uniform(4, 7))

    # Scroll to load cards
    for _ in range(4):
        scanner_page.evaluate("window.scrollBy(0, 600)")
        time.sleep(1.2)

    # Find job cards
    cards = []
    for sel in [
        ".job-card-container",
        ".jobs-search-results__list-item",
        "li.ember-view.occludable-update",
    ]:
        cards = scanner_page.query_selector_all(sel)
        if cards:
            break

    logger.info(f"Found {len(cards)} job cards")

    for card_idx, card in enumerate(cards):
        if should_stop():
            logger.info("Stop file detected, halting")
            return None

        # Extract title
        title_el = None
        for tsel in [
            ".job-card-list__title",
            ".job-card-list__title--link",
            "a.job-card-list__title--link",
            ".artdeco-entity-lockup__title a",
        ]:
            title_el = card.query_selector(tsel)
            if title_el:
                break

        # Extract company
        company_el = None
        for csel in [
            ".job-card-container__primary-description",
            ".artdeco-entity-lockup__subtitle span",
            ".job-card-container__company-name",
        ]:
            company_el = card.query_selector(csel)
            if company_el:
                break

        title_text = (title_el.inner_text().strip() if title_el else "").split("\n")[0].strip()
        company_text = company_el.inner_text().strip() if company_el else ""

        if not title_text or not company_text:
            continue

        # Apply job filter
        passes, reason = filter_job({"title": title_text, "company": company_text})
        if not passes:
            logger.info(f"  [{card_idx}] FILTERED ({reason}): {title_text} @ {company_text}")
            continue

        # Get URL
        link_el = card.query_selector("a[href*='/jobs/view/']") or card.query_selector("a")
        href = ""
        if link_el:
            href = link_el.get_attribute("href") or ""
            if href.startswith("/"):
                href = f"https://www.linkedin.com{href}"
            href = href.split("?")[0]

        if not href:
            continue

        # Dedup check
        if tracker.is_already_applied(job_url=href, company=company_text, position=title_text):
            logger.info(f"  [{card_idx}] SKIP (already applied): {title_text} @ {company_text}")
            continue

        logger.info(f"  [{card_idx}] Checking: {title_text} @ {company_text}")

        # Click card to load details
        try:
            card.click()
            time.sleep(random.uniform(2, 4))
        except Exception as e:
            logger.warning(f"Card click failed: {e}")
            continue

        # Read description
        description = ""
        try:
            show_more = scanner_page.query_selector(
                "button[aria-label='Show more'], button.jobs-description__footer-button"
            )
            if show_more and show_more.is_visible():
                show_more.click()
                time.sleep(1)
        except Exception:
            pass

        for dsel in [
            ".jobs-description__content",
            ".jobs-description-content__text",
            "#job-details",
            ".jobs-box__html-content",
        ]:
            el = scanner_page.query_selector(dsel)
            if el:
                description = el.inner_text().strip()
                if description:
                    break

        # Get location
        location_text = ""
        for lsel in [
            ".job-details-jobs-unified-top-card__bullet",
            ".jobs-unified-top-card__bullet",
        ]:
            el = scanner_page.query_selector(lsel)
            if el:
                location_text = el.inner_text().strip()
                if location_text:
                    break

        # Check for Easy Apply button
        easy_apply_btn = None
        for ea_sel in ['button[aria-label*="Easy Apply"]', 'button:has-text("Easy Apply")']:
            try:
                loc = scanner_page.locator(ea_sel).first
                if loc.is_visible(timeout=2000):
                    btn_text = loc.inner_text().strip()
                    if "Easy" in btn_text:
                        easy_apply_btn = loc
                        break
            except Exception:
                continue

        if not easy_apply_btn:
            logger.info(f"  No Easy Apply, skipping")
            continue

        # Found an Easy Apply job — tailor and apply
        logger.info(f">>> EASY APPLY: {title_text} @ {company_text}")

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = sanitize_filename(f"{company_text}_{title_text}"[:50])
        job_dir = ensure_dir(PROJECT_ROOT / "output" / "applications" / f"{safe_name}_{ts}")

        # Save JD
        jd_path = job_dir / "job_description.txt"
        jd_path.write_text(description or "No description available", encoding="utf-8")

        # Tailor resume
        new_summary = tailor_summary_local(company_text, title_text, description)
        new_comps = tailor_competencies_local(description)

        resume_path = tailor.tailor_and_save(
            base_resume_path=str(BASE_RESUME),
            new_summary=new_summary,
            new_competencies=new_comps,
            company=company_text,
            role=title_text,
            output_dir=str(job_dir),
        )
        clean_docx(resume_path)
        logger.info(f"  Resume: {resume_path}")

        # Generate cover letter
        cl_text = generate_cover_letter_local(company_text, title_text, description)
        cl_path = cl_gen.generate_and_save(
            text=cl_text,
            candidate_profile=CANDIDATE,
            company=company_text,
            role=title_text,
            output_dir=str(job_dir),
        )
        clean_docx(cl_path)
        logger.info(f"  Cover letter: {cl_path}")

        # Save job info
        job_info = {
            "title": title_text,
            "company": company_text,
            "location": location_text,
            "url": href,
            "description": description[:5000],
            "keyword": keyword,
            "found_at": datetime.now().isoformat(),
        }
        with open(job_dir / "job_info.json", "w") as f:
            json.dump(job_info, f, indent=2)

        # Submit application using LinkedInApplicant (reuses the same browser)
        applicant = LinkedInApplicant()
        applicant.page = scanner_page
        applicant.playwright = None  # Don't let close() try to stop playwright
        applicant.browser = None

        apply_result = applicant.apply_to_job(
            job={"url": href, "title": title_text, "company": company_text},
            resume_path=str(resume_path),
            cover_letter_path=str(cl_path),
        )

        status = apply_result.get("status", "apply_failed")
        screenshots = apply_result.get("screenshots", [])
        logger.info(f"  Apply result: {status} — {apply_result.get('reason', '')}")

        # Track application
        tracker.add_application(
            company=company_text,
            position=title_text,
            job_url=href,
            location=location_text,
            status=status,
            resume_path=str(resume_path),
            cover_letter_path=str(cl_path),
            job_description=description[:2000],
            jd_file_path=str(jd_path),
            notes=f"{apply_result.get('reason', '')}",
            screenshots=screenshots,
        )

        # If dialog is still open, dismiss it
        try:
            dismiss = scanner_page.locator(
                'button[aria-label="Dismiss"], button:has-text("Discard")'
            )
            if dismiss.count() > 0 and dismiss.first.is_visible():
                dismiss.first.click()
                time.sleep(1)
            discard = scanner_page.locator('button:has-text("Discard")')
            if discard.count() > 0 and discard.first.is_visible():
                discard.first.click()
                time.sleep(1)
        except Exception:
            pass

        return {
            "company": company_text,
            "title": title_text,
            "status": status,
            "job_dir": str(job_dir),
        }

    logger.info("No matching jobs found in this search")
    return None


def main():
    parser = argparse.ArgumentParser(description="Aipply continuous apply loop")
    parser.add_argument(
        "--interval",
        type=int,
        default=600,
        help="Seconds between applications (default: 600 = 10 min)",
    )
    parser.add_argument(
        "--max-apps",
        type=int,
        default=50,
        help="Stop after this many applications (default: 50)",
    )
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info(f"Aipply Apply Loop starting — interval={args.interval}s, max={args.max_apps}")
    logger.info("=" * 60)

    # Remove stop file if it exists from a previous run
    if STOP_FILE.exists():
        STOP_FILE.unlink()
        logger.info("Removed stale .stop file")

    # Launch browser once — reuse across all cycles
    from playwright.sync_api import sync_playwright

    PROFILE_DIR = str(Path.home() / ".aipply" / "chrome-profile")

    pw = sync_playwright().start()
    context = pw.chromium.launch_persistent_context(
        user_data_dir=PROFILE_DIR,
        headless=False,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check",
        ],
    )
    page = context.pages[0] if context.pages else context.new_page()

    tracker = ApplicationTracker(tracker_path=str(TRACKER_PATH))
    tailor = ResumeTailor()
    cl_gen = CoverLetterGenerator()

    apps_submitted = 0
    keyword_idx = 0

    try:
        while apps_submitted < args.max_apps:
            if should_stop():
                logger.info("Stop file detected — exiting loop")
                break

            # Rotate through keywords and locations
            keyword = SEARCH_KEYWORDS[keyword_idx % len(SEARCH_KEYWORDS)]
            location = SEARCH_LOCATIONS[
                (keyword_idx // len(SEARCH_KEYWORDS)) % len(SEARCH_LOCATIONS)
            ]
            keyword_idx += 1

            logger.info(f"\n{'=' * 60}")
            logger.info(f"Cycle {apps_submitted + 1}: keyword='{keyword}', location='{location}'")
            logger.info(f"{'=' * 60}")

            try:
                result = run_single_cycle(page, tracker, tailor, cl_gen, keyword, location)

                if result:
                    apps_submitted += 1
                    logger.info(
                        f"Application #{apps_submitted}: "
                        f"{result['company']} — {result['title']} ({result['status']})"
                    )

                    if apps_submitted < args.max_apps and not should_stop():
                        wait_time = args.interval + random.randint(-30, 60)  # Add jitter
                        logger.info(f"Waiting {wait_time}s before next application...")

                        # Check stop file during wait
                        for _ in range(wait_time):
                            if should_stop():
                                break
                            time.sleep(1)
                else:
                    # No job found in this search — short wait then try next keyword
                    logger.info("No match found, trying next keyword in 30s...")
                    time.sleep(30)

            except Exception as e:
                logger.error(f"Cycle error: {e}", exc_info=True)
                logger.info("Waiting 60s before retrying...")
                time.sleep(60)

    finally:
        logger.info(f"Loop finished. Total applications submitted: {apps_submitted}")
        try:
            context.close()
        except Exception:
            pass
        try:
            pw.stop()
        except Exception:
            pass


if __name__ == "__main__":
    main()
