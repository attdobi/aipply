"""Scan LinkedIn for Easy Apply jobs, tailor materials, and submit application."""
import json
import os
import random
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote_plus
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from playwright.sync_api import sync_playwright

PROFILE_DIR = str(Path.home() / ".aipply" / "chrome-profile")

# Remove stale lock
lock = Path(PROFILE_DIR) / "SingletonLock"
try:
    os.remove(lock)
except OSError:
    pass

# Load tracker
tracker_path = PROJECT_ROOT / "output" / "tracker.json"
already_applied_urls = set()
already_applied_keys = set()
if tracker_path.exists():
    with open(tracker_path) as f:
        for entry in json.load(f):
            already_applied_urls.add(entry.get("job_url", ""))
            already_applied_keys.add(f"{entry.get('company','').lower().strip()}|{entry.get('position','').lower().strip()}")

EXCLUDED_COMPANIES = {"pg&e", "pacific gas and electric", "pacific gas & electric"}

KEYWORDS_TO_TRY = [
    "senior compliance analyst",
    "compliance officer",
    "compliance analyst",
    "risk analyst",
    "audit analyst",
    "regulatory analyst",
    "governance analyst",
]

def is_excluded(company):
    c = company.lower().strip()
    return any(exc in c for exc in EXCLUDED_COMPANIES)

def is_already_applied(url, company="", title=""):
    if url in already_applied_urls:
        return True
    key = f"{company.lower().strip()}|{title.lower().strip()}"
    if key in already_applied_keys:
        return True
    return False

def is_relevant_role(title, description):
    title_lower = title.lower()
    desc_lower = description.lower()
    
    disqualifiers = [
        "product designer", "analytical development", "pharmaceutical",
        "drug substance", "drug product", "biologics", "clinical",
        "laboratory", "chemist", "scientist", "software engineer",
        "marketing manager", "sales manager", "recruiter", "nurse",
        "physician", "therapist", "teacher", "professor",
    ]
    for d in disqualifiers:
        if d in title_lower:
            return False
    
    financial_terms = [
        "banking", "bank", "fintech", "financial", "aml", "bsa", 
        "anti-money laundering", "kyc", "sanctions", "fraud",
        "regulatory", "compliance monitoring", "audit",
        "risk management", "consumer protection", "fair lending",
        "compliance program", "sox", "internal controls",
        "governance", "compliance officer", "cfpb", "occ",
        "fdic", "sec", "finra", "cams", "cfe",
        "compliance analyst", "risk analyst", "compliance review",
        "examination", "remediation", "policy", "regulation",
    ]
    
    matches = sum(1 for t in financial_terms if t in desc_lower)
    return matches >= 2


def extract_from_card(card):
    """Extract title, company, location from a card element."""
    title = ""
    for sel in [".job-card-list__title", ".artdeco-entity-lockup__title a", "a strong", "a"]:
        try:
            el = card.query_selector(sel)
            if el:
                t = el.inner_text().strip()
                if t and len(t) > 3:
                    title = t.split("\n")[0].strip()
                    break
        except Exception:
            continue

    company = ""
    for sel in [".job-card-container__primary-description", ".artdeco-entity-lockup__subtitle span", ".job-card-container__company-name"]:
        try:
            el = card.query_selector(sel)
            if el:
                c = el.inner_text().strip()
                if c:
                    company = c.strip()
                    break
        except Exception:
            continue

    loc = ""
    for sel in [".job-card-container__metadata-item", ".artdeco-entity-lockup__caption span"]:
        try:
            el = card.query_selector(sel)
            if el:
                l = el.inner_text().strip()
                if l:
                    loc = l.strip()
                    break
        except Exception:
            continue

    return title, company, loc


def get_description(page):
    """Extract job description from the detail pane."""
    for sel in [".jobs-description__content", ".jobs-description-content__text", "#job-details", ".jobs-box__html-content"]:
        try:
            el = page.query_selector(sel)
            if el:
                desc = el.inner_text().strip()
                if desc and len(desc) > 100:
                    return desc
        except Exception:
            continue
    
    # Fallback
    try:
        body_text = page.evaluate("() => document.body.innerText")
        marker = "About the job"
        idx = body_text.find(marker)
        if idx != -1:
            raw = body_text[idx + len(marker):].strip()
            for stop in ["Show less", "People you can reach", "Similar jobs", "More from this employer"]:
                si = raw.find(stop)
                if si != -1:
                    raw = raw[:si].strip()
            if len(raw) > 100:
                return raw
    except Exception:
        pass
    return ""


def check_easy_apply(page):
    """Check if the job detail pane shows an Easy Apply button."""
    for ea_sel in [
        'button.jobs-apply-button:has-text("Easy Apply")',
        'button[aria-label*="Easy Apply"]',
        'button:has-text("Easy Apply")',
    ]:
        try:
            btn = page.locator(ea_sel).first
            if btn.is_visible(timeout=1500):
                btn_text = btn.inner_text().strip()
                if "Easy" in btn_text:
                    return True
        except Exception:
            continue
    return False


def main():
    pw = sync_playwright().start()
    Path(PROFILE_DIR).mkdir(parents=True, exist_ok=True)

    ctx = pw.chromium.launch_persistent_context(
        user_data_dir=PROFILE_DIR,
        headless=False,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check",
        ],
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    
    found_job = None

    try:
        for keyword in KEYWORDS_TO_TRY:
            if found_job:
                break

            for location in ["San Francisco Bay Area", "Remote"]:
                if found_job:
                    break

                search_url = (
                    f"https://www.linkedin.com/jobs/search/"
                    f"?keywords={quote_plus(keyword)}"
                    f"&location={quote_plus(location)}"
                    f"&f_AL=true"
                    f"&sortBy=DD"
                    f"&f_TPR=r604800"
                )

                print(f"\n[SCAN] '{keyword}' in '{location}'")
                try:
                    page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
                    time.sleep(4)
                except Exception as e:
                    print(f"[SCAN] Navigation error: {e}")
                    # Try to get a new page
                    try:
                        page = ctx.new_page()
                        page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
                        time.sleep(4)
                    except Exception:
                        continue

                if "login" in page.url.lower() or "authwall" in page.url.lower():
                    print("[SCAN] ERROR: Not logged in.")
                    continue

                # Find cards
                cards = []
                for sel in [".job-card-container", ".jobs-search-results__list-item", ".scaffold-layout__list-item"]:
                    try:
                        cards = page.query_selector_all(sel)
                        if cards:
                            break
                    except Exception:
                        continue

                if not cards:
                    print(f"  No cards found")
                    continue

                print(f"  Found {len(cards)} cards")

                for i, card in enumerate(cards[:10]):
                    try:
                        card.scroll_into_view_if_needed()
                        time.sleep(random.uniform(0.5, 1))
                        card.click()
                        time.sleep(random.uniform(2.5, 4))

                        title, company, loc = extract_from_card(card)
                        print(f"  [{i+1}] {title} @ {company}")

                        if not title:
                            continue
                        if is_excluded(company):
                            print(f"      SKIP excluded")
                            continue

                        # Get URL
                        job_url = page.url
                        id_match = re.search(r'currentJobId=(\d+)', job_url)
                        if id_match:
                            job_url = f"https://www.linkedin.com/jobs/view/{id_match.group(1)}/"

                        if is_already_applied(job_url, company, title):
                            print(f"      SKIP already applied")
                            continue

                        if not check_easy_apply(page):
                            print(f"      No Easy Apply")
                            continue

                        description = get_description(page)
                        if not description:
                            print(f"      No description found")
                            continue

                        if not is_relevant_role(title, description):
                            print(f"      SKIP not relevant")
                            continue

                        print(f"      >>> MATCH: Easy Apply + Relevant!")
                        found_job = {
                            "title": title.split("\n")[0].strip(),
                            "company": company.strip(),
                            "location": loc.strip(),
                            "url": job_url,
                            "description": description,
                            "keyword": keyword,
                        }
                        break

                    except Exception as e:
                        print(f"      Error: {e}")
                        continue

        if not found_job:
            print("\n[SCAN] No relevant Easy Apply jobs found across all keywords.")
            # Save empty result
            with open(PROJECT_ROOT / "output" / "cycle_result.json", "w") as f:
                json.dump({"status": "no_jobs_found", "keywords_searched": KEYWORDS_TO_TRY}, f, indent=2)
        else:
            print(f"\n[SCAN] Selected job: {found_job['title']} @ {found_job['company']}")
            print(f"  URL: {found_job['url']}")
            print(f"  Description ({len(found_job['description'])} chars)")
            
            # Save the found job
            with open(PROJECT_ROOT / "output" / "cycle_result.json", "w") as f:
                json.dump(found_job, f, indent=2)

    finally:
        try:
            ctx.close()
        except Exception:
            pass
        try:
            pw.stop()
        except Exception:
            pass
        print("[SCAN] Browser closed.")


if __name__ == "__main__":
    main()
