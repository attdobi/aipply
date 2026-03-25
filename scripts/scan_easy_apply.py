"""Scan LinkedIn for Easy Apply IC compliance jobs, return details."""
import json
import os
import random
import re
import sys
import time
from pathlib import Path

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
            # Also track by company+position
            already_applied.add(f"{entry.get('company','').lower()}|{entry.get('position','').lower()}")

# Rotate keyword - pick an IC keyword
KEYWORDS = [
    "compliance analyst",
    "senior compliance analyst",
    "compliance officer",
    "risk analyst",
    "audit analyst",
    "regulatory analyst",
    "compliance specialist",
]

# Pick keyword based on day rotation
from datetime import datetime
day_of_year = datetime.now().timetuple().tm_yday
keyword_idx = day_of_year % len(KEYWORDS)
keyword = KEYWORDS[keyword_idx]
print(f"[SCAN] Using keyword: '{keyword}'")

LOCATIONS = ["San Francisco Bay Area"]
EXCLUDED_COMPANIES = {"pg&e", "pacific gas and electric", "pacific gas & electric"}


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

    results = []
    location = LOCATIONS[0]

    from urllib.parse import quote_plus
    # Add Easy Apply filter: f_AL=true
    search_url = (
        f"https://www.linkedin.com/jobs/search/"
        f"?keywords={quote_plus(keyword)}"
        f"&location={quote_plus(location)}"
        f"&f_AL=true"
        f"&sortBy=DD"
    )

    print(f"[SCAN] Navigating to: {search_url}")
    page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
    time.sleep(5)

    # Check if we need to log in
    if "login" in page.url.lower() or "authwall" in page.url.lower():
        print("[SCAN] ERROR: Not logged into LinkedIn. Please log in manually first.")
        page.screenshot(path=str(PROJECT_ROOT / "output" / "login_needed.png"))
        ctx.close()
        pw.stop()
        sys.exit(1)

    page.screenshot(path=str(PROJECT_ROOT / "output" / "search_results.png"))

    # Find job cards
    card_selectors = [
        ".job-card-container",
        ".jobs-search-results__list-item",
        "li.ember-view.occludable-update",
        "[data-occludable-job-id]",
        ".scaffold-layout__list-item",
    ]

    cards = []
    for sel in card_selectors:
        cards = page.query_selector_all(sel)
        if cards:
            print(f"[SCAN] Found {len(cards)} cards with selector '{sel}'")
            break

    if not cards:
        print("[SCAN] No job cards found. Taking screenshot for debugging.")
        page.screenshot(path=str(PROJECT_ROOT / "output" / "no_cards_debug.png"))
        # Try to get the page text for debugging
        body_text = page.evaluate("() => document.body.innerText")
        print(f"[SCAN] Page body (first 2000 chars):\n{body_text[:2000]}")
        ctx.close()
        pw.stop()
        sys.exit(1)

    # Click through cards looking for Easy Apply
    easy_apply_jobs = []
    for i, card in enumerate(cards[:15]):
        try:
            # Click the card to load job details in the right pane
            card.scroll_into_view_if_needed()
            time.sleep(random.uniform(0.5, 1.5))
            card.click()
            time.sleep(random.uniform(2, 4))

            # Extract title from the card
            title = ""
            for sel in [
                ".job-card-list__title",
                ".job-card-list__title--link",
                ".artdeco-entity-lockup__title a",
                "a[data-control-name='jobPosting_jobCardTitle']",
                "a strong",
                "a",
            ]:
                el = card.query_selector(sel)
                if el:
                    t = el.inner_text().strip()
                    if t:
                        title = t
                        break

            # Extract company
            company = ""
            for sel in [
                ".job-card-container__primary-description",
                ".artdeco-entity-lockup__subtitle span",
                ".job-card-container__company-name",
            ]:
                el = card.query_selector(sel)
                if el:
                    c = el.inner_text().strip()
                    if c:
                        company = c
                        break

            # Extract location
            loc = ""
            for sel in [
                ".job-card-container__metadata-item",
                ".artdeco-entity-lockup__caption span",
            ]:
                el = card.query_selector(sel)
                if el:
                    l = el.inner_text().strip()
                    if l:
                        loc = l
                        break

            print(f"[SCAN] Card {i+1}: {title} @ {company} ({loc})")

            if is_excluded(company):
                print(f"  -> SKIP (excluded company)")
                continue

            # Get job URL from the right pane
            job_url = page.url
            # Try to extract job ID
            id_match = re.search(r'currentJobId=(\d+)', job_url)
            if id_match:
                job_url = f"https://www.linkedin.com/jobs/view/{id_match.group(1)}/"

            if is_already_applied(job_url, company, title):
                print(f"  -> SKIP (already applied)")
                continue

            # Check if Easy Apply button is visible in the detail pane
            easy_apply = False
            for ea_sel in [
                'button.jobs-apply-button:has-text("Easy Apply")',
                'button[aria-label*="Easy Apply"]',
                '.jobs-apply-button--top-card:has-text("Easy Apply")',
                'button:has-text("Easy Apply")',
            ]:
                try:
                    btn = page.locator(ea_sel).first
                    if btn.is_visible(timeout=2000):
                        btn_text = btn.inner_text().strip()
                        if "Easy" in btn_text:
                            easy_apply = True
                            break
                except Exception:
                    continue

            if easy_apply:
                print(f"  -> EASY APPLY FOUND!")

                # Get full description
                description = ""
                for sel in [
                    ".jobs-description__content",
                    ".jobs-description-content__text",
                    "#job-details",
                    ".jobs-box__html-content",
                ]:
                    el = page.query_selector(sel)
                    if el:
                        description = el.inner_text().strip()
                        if description:
                            break

                # Fallback: body text
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

                easy_apply_jobs.append({
                    "title": title,
                    "company": company,
                    "location": loc,
                    "url": job_url,
                    "easy_apply": True,
                    "description": description,
                })

                # We found one Easy Apply - that's enough for this cycle
                if len(easy_apply_jobs) >= 3:
                    break
            else:
                print(f"  -> No Easy Apply (external)")

        except Exception as e:
            print(f"  -> Error processing card {i+1}: {e}")
            continue

    # Save results
    output_path = PROJECT_ROOT / "output" / "scan_results.json"
    with open(output_path, "w") as f:
        json.dump(easy_apply_jobs, f, indent=2)

    print(f"\n[SCAN] Found {len(easy_apply_jobs)} Easy Apply jobs")
    for j in easy_apply_jobs:
        print(f"  - {j['title']} @ {j['company']} ({j['location']})")
        print(f"    URL: {j['url']}")
        print(f"    Description length: {len(j.get('description', ''))} chars")

    # Don't close browser - we'll reuse it for applying
    # Just save the context info
    print(f"\n[SCAN] Browser still open. Results saved to {output_path}")
    
    # Close browser
    ctx.close()
    pw.stop()
    print("[SCAN] Browser closed.")


if __name__ == "__main__":
    main()
