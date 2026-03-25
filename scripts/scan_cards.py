#!/usr/bin/env python3
"""
Scan LinkedIn jobs by clicking cards to load side panel descriptions.
Uses persistent browser context (headless=False).
"""

import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote_plus

from playwright.sync_api import sync_playwright

PROFILE_DIR = str(Path.home() / ".aipply" / "chrome-profile")
TRACKER_PATH = Path(__file__).parent.parent / "output" / "tracker.json"

# Already applied (company|title pairs from tracker)
def load_applied():
    if not TRACKER_PATH.exists():
        return set()
    data = json.loads(TRACKER_PATH.read_text())
    pairs = set()
    for a in data:
        c = a.get("company", "").strip().lower()
        t = a.get("position", "").strip().lower()
        if c and t:
            pairs.add((c, t))
        url = a.get("job_url", "")
        if url:
            pairs.add(url)
    return pairs


def scan(keyword="compliance manager", location="San Francisco Bay Area", limit=10):
    applied = load_applied()
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

    url = (
        f"https://www.linkedin.com/jobs/search/"
        f"?keywords={quote_plus(keyword)}&location={quote_plus(location)}"
        f"&sortBy=DD"  # sort by date
    )
    print(f"Navigating to: {url}", file=sys.stderr)
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(4000)

    # Collect job cards
    card_selectors = [
        ".job-card-container",
        ".jobs-search-results__list-item",
        "li.ember-view.occludable-update",
        "[data-occludable-job-id]",
    ]
    
    cards = []
    for sel in card_selectors:
        cards = page.query_selector_all(sel)
        if cards:
            print(f"Found {len(cards)} cards with '{sel}'", file=sys.stderr)
            break

    if not cards:
        print("No job cards found!", file=sys.stderr)
        ctx.close()
        pw.stop()
        return []

    results = []
    exclusions = ["pg&e", "pacific gas"]

    for i, card in enumerate(cards[:limit]):
        try:
            # Click the card to load the side panel
            card.scroll_into_view_if_needed()
            page.wait_for_timeout(500)
            card.click()
            page.wait_for_timeout(2500)

            # Extract title from side panel
            title = ""
            for sel in [
                ".job-details-jobs-unified-top-card__job-title h1",
                ".job-details-jobs-unified-top-card__job-title",
                ".jobs-unified-top-card__job-title",
                ".t-24.t-bold",
                "h1",
            ]:
                el = page.query_selector(sel)
                if el:
                    t = el.inner_text().strip()
                    if t:
                        title = t.split("\n")[0].strip()
                        break

            # Extract company
            company = ""
            for sel in [
                ".job-details-jobs-unified-top-card__company-name a",
                ".job-details-jobs-unified-top-card__company-name",
                ".jobs-unified-top-card__company-name a",
                ".jobs-unified-top-card__company-name",
            ]:
                el = page.query_selector(sel)
                if el:
                    c = el.inner_text().strip()
                    if c:
                        company = c
                        break

            # Extract location
            location_text = ""
            for sel in [
                ".job-details-jobs-unified-top-card__bullet",
                ".jobs-unified-top-card__bullet",
            ]:
                el = page.query_selector(sel)
                if el:
                    loc = el.inner_text().strip()
                    if loc:
                        location_text = loc
                        break

            # Try "Show more" button
            try:
                show_more = page.query_selector(
                    "button[aria-label='Show more'], "
                    "button.jobs-description__footer-button"
                )
                if show_more and show_more.is_visible():
                    show_more.click()
                    page.wait_for_timeout(1000)
            except Exception:
                pass

            # Extract description from side panel
            description = ""
            for sel in [
                ".jobs-description__content",
                ".jobs-description-content__text",
                "#job-details",
                ".jobs-box__html-content",
                "article",
            ]:
                el = page.query_selector(sel)
                if el:
                    desc = el.inner_text().strip()
                    if desc and len(desc) > 50:
                        description = desc
                        break

            # Fallback: body text extraction
            if not description:
                try:
                    body = page.evaluate("() => document.body.innerText")
                    marker = "About the job"
                    idx = body.find(marker)
                    if idx != -1:
                        raw = body[idx + len(marker):].strip()
                        for stop in ["Show less", "People you can reach", "Similar jobs"]:
                            si = raw.find(stop)
                            if si != -1:
                                raw = raw[:si].strip()
                        if len(raw) > 100:
                            description = raw
                except Exception:
                    pass

            # Extract URL from current page or card link
            job_url = ""
            link = card.query_selector("a[href*='/jobs/view/']") or card.query_selector("a")
            if link:
                href = link.get_attribute("href") or ""
                if href.startswith("/"):
                    href = f"https://www.linkedin.com{href}"
                job_url = href.split("?")[0]

            if not title and not company:
                continue

            # Check exclusions
            comp_lower = company.lower()
            if any(ex in comp_lower for ex in exclusions):
                print(f"  ⛔ Excluding {company} (blocked)", file=sys.stderr)
                continue

            # Check already applied
            title_clean = title.split("\n")[0].strip()
            pair = (comp_lower.strip(), title_clean.lower().strip())
            if pair in applied or job_url in applied:
                print(f"  ⏭️ Already applied: {company} — {title_clean}", file=sys.stderr)
                continue

            results.append({
                "title": title_clean,
                "company": company,
                "location": location_text,
                "url": job_url,
                "description": description,
            })
            print(f"  ✅ [{len(results)}] {company} — {title_clean}", file=sys.stderr)

        except Exception as e:
            print(f"  ⚠️ Card {i} error: {e}", file=sys.stderr)
            continue

    ctx.close()
    pw.stop()
    return results


if __name__ == "__main__":
    kw = sys.argv[1] if len(sys.argv) > 1 else "compliance manager"
    loc = sys.argv[2] if len(sys.argv) > 2 else "San Francisco Bay Area"
    lim = int(sys.argv[3]) if len(sys.argv) > 3 else 10

    jobs = scan(kw, loc, lim)
    print(json.dumps(jobs, indent=2))
