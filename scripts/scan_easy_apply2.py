"""Scan LinkedIn for Easy Apply IC compliance jobs - round 2 with multiple keywords."""
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

# Load tracker to skip already-applied
tracker_path = PROJECT_ROOT / "output" / "tracker.json"
already_applied = set()
if tracker_path.exists():
    with open(tracker_path) as f:
        for entry in json.load(f):
            url = entry.get("job_url", "")
            already_applied.add(url)
            already_applied.add(f"{entry.get('company','').lower()}|{entry.get('position','').lower()}")

# Also skip what we found in round 1 that don't match
scan1_path = PROJECT_ROOT / "output" / "scan_results.json"
if scan1_path.exists():
    with open(scan1_path) as f:
        for entry in json.load(f):
            already_applied.add(entry.get("url", ""))

EXCLUDED_COMPANIES = {"pg&e", "pacific gas and electric", "pacific gas & electric"}

# Keywords to try in order - focused on financial/banking compliance
KEYWORDS_TO_TRY = [
    "senior compliance analyst",
    "compliance officer",
    "regulatory analyst",
    "compliance analyst",
    "governance analyst",
]

def is_excluded(company):
    c = company.lower().strip()
    return any(exc in c for exc in EXCLUDED_COMPANIES)

def is_already_applied(url, company="", title=""):
    if url in already_applied:
        return True
    key = f"{company.lower().strip()}|{title.lower().strip()}"
    if key in already_applied:
        return True
    return False

def is_relevant_role(title, description):
    """Check if the role is actually relevant to financial/banking/fintech compliance."""
    title_lower = title.lower()
    desc_lower = description.lower()
    
    # Disqualifiers - roles that are clearly not financial compliance
    disqualifiers = [
        "product designer", "analytical development", "pharmaceutical",
        "drug substance", "drug product", "biologics", "clinical",
        "laboratory", "chemist", "scientist", "engineer",
        "marketing", "sales", "recruiter",
    ]
    for d in disqualifiers:
        if d in title_lower:
            return False
    
    # Check if description mentions financial/banking/fintech terms
    financial_terms = [
        "banking", "bank", "fintech", "financial", "aml", "bsa", 
        "anti-money laundering", "kyc", "sanctions", "fraud",
        "regulatory", "compliance monitoring", "audit",
        "risk management", "consumer protection", "fair lending",
        "compliance program", "sox", "internal controls",
        "governance", "compliance officer", "cfpb", "occ",
        "fdic", "sec", "finra", "cams", "cfe",
    ]
    
    # Count matching terms
    matches = sum(1 for t in financial_terms if t in desc_lower)
    return matches >= 2  # At least 2 financial terms

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

    easy_apply_jobs = []

    for keyword in KEYWORDS_TO_TRY:
        if len(easy_apply_jobs) >= 3:
            break

        for location in ["San Francisco Bay Area", "Remote"]:
            if len(easy_apply_jobs) >= 3:
                break

            search_url = (
                f"https://www.linkedin.com/jobs/search/"
                f"?keywords={quote_plus(keyword)}"
                f"&location={quote_plus(location)}"
                f"&f_AL=true"
                f"&sortBy=DD"
                f"&f_TPR=r604800"  # Past week
            )

            print(f"\n[SCAN] Searching: '{keyword}' in '{location}'")
            page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(4)

            if "login" in page.url.lower() or "authwall" in page.url.lower():
                print("[SCAN] ERROR: Not logged into LinkedIn.")
                ctx.close()
                pw.stop()
                sys.exit(1)

            # Find job cards
            cards = []
            for sel in [
                ".job-card-container",
                ".jobs-search-results__list-item",
                "li.ember-view.occludable-update",
                ".scaffold-layout__list-item",
            ]:
                cards = page.query_selector_all(sel)
                if cards:
                    print(f"[SCAN] Found {len(cards)} cards")
                    break

            if not cards:
                print(f"[SCAN] No cards found for this search.")
                continue

            for i, card in enumerate(cards[:10]):
                if len(easy_apply_jobs) >= 3:
                    break
                try:
                    card.scroll_into_view_if_needed()
                    time.sleep(random.uniform(0.5, 1))
                    card.click()
                    time.sleep(random.uniform(2, 3.5))

                    # Extract title
                    title = ""
                    for sel in [".job-card-list__title", ".artdeco-entity-lockup__title a", "a strong", "a"]:
                        el = card.query_selector(sel)
                        if el:
                            t = el.inner_text().strip()
                            if t:
                                title = t
                                break

                    # Extract company
                    company = ""
                    for sel in [".job-card-container__primary-description", ".artdeco-entity-lockup__subtitle span"]:
                        el = card.query_selector(sel)
                        if el:
                            c = el.inner_text().strip()
                            if c:
                                company = c
                                break

                    # Extract location
                    loc = ""
                    for sel in [".job-card-container__metadata-item", ".artdeco-entity-lockup__caption span"]:
                        el = card.query_selector(sel)
                        if el:
                            l = el.inner_text().strip()
                            if l:
                                loc = l
                                break

                    print(f"  Card {i+1}: {title} @ {company}")

                    if is_excluded(company):
                        print(f"    -> SKIP (excluded)")
                        continue

                    job_url = page.url
                    id_match = re.search(r'currentJobId=(\d+)', job_url)
                    if id_match:
                        job_url = f"https://www.linkedin.com/jobs/view/{id_match.group(1)}/"

                    if is_already_applied(job_url, company, title):
                        print(f"    -> SKIP (already applied/seen)")
                        continue

                    # Check Easy Apply
                    easy_apply = False
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
                                    easy_apply = True
                                    break
                        except Exception:
                            continue

                    if not easy_apply:
                        print(f"    -> No Easy Apply")
                        continue

                    # Get description
                    description = ""
                    for sel in [".jobs-description__content", ".jobs-description-content__text", "#job-details", ".jobs-box__html-content"]:
                        el = page.query_selector(sel)
                        if el:
                            description = el.inner_text().strip()
                            if description:
                                break

                    if not description:
                        try:
                            body_text = page.evaluate("() => document.body.innerText")
                            marker = "About the job"
                            idx = body_text.find(marker)
                            if idx != -1:
                                raw = body_text[idx + len(marker):].strip()
                                for stop in ["Show less", "People you can reach", "Similar jobs"]:
                                    si = raw.find(stop)
                                    if si != -1:
                                        raw = raw[:si].strip()
                                if len(raw) > 100:
                                    description = raw
                        except Exception:
                            pass

                    # Check relevance
                    if not is_relevant_role(title, description):
                        print(f"    -> SKIP (not relevant to financial compliance)")
                        continue

                    print(f"    -> EASY APPLY + RELEVANT!")
                    easy_apply_jobs.append({
                        "title": title.split("\n")[0].strip(),  # Clean multi-line titles
                        "company": company.strip(),
                        "location": loc.strip(),
                        "url": job_url,
                        "easy_apply": True,
                        "description": description,
                        "keyword": keyword,
                    })

                except Exception as e:
                    print(f"    -> Error: {e}")
                    continue

    # Save results
    output_path = PROJECT_ROOT / "output" / "scan_results2.json"
    with open(output_path, "w") as f:
        json.dump(easy_apply_jobs, f, indent=2)

    print(f"\n[SCAN] Found {len(easy_apply_jobs)} relevant Easy Apply jobs")
    for j in easy_apply_jobs:
        print(f"  - {j['title']} @ {j['company']} ({j['location']})")
        print(f"    URL: {j['url']}")

    ctx.close()
    pw.stop()
    print("[SCAN] Done.")


if __name__ == "__main__":
    main()
