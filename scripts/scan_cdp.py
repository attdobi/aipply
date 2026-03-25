"""Scan LinkedIn for Easy Apply jobs using real Chrome via CDP."""
import json
import os
import random
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote_plus

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from playwright.sync_api import sync_playwright

PROFILE_DIR = str(Path.home() / ".aipply" / "chrome-profile")
CDP_PORT = 9333

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

KEYWORDS = [
    "senior compliance analyst",
    "compliance officer",
    "compliance analyst",
    "risk analyst",
    "audit analyst",
    "regulatory analyst",
    "governance analyst",
]

def is_excluded(company):
    return any(exc in company.lower().strip() for exc in EXCLUDED_COMPANIES)

def is_already_applied(url, company="", title=""):
    if url in already_applied_urls:
        return True
    return f"{company.lower().strip()}|{title.lower().strip()}" in already_applied_keys

def is_relevant(title, desc):
    title_l = title.lower()
    desc_l = desc.lower()
    for d in ["product designer", "analytical development", "pharmaceutical", "drug", "biologics", 
              "clinical", "laboratory", "chemist", "scientist", "software engineer", "nurse", 
              "physician", "erisa", "benefits compliance"]:
        if d in title_l:
            return False
    terms = ["banking", "bank", "fintech", "financial", "aml", "bsa", "anti-money laundering", 
             "kyc", "sanctions", "fraud", "regulatory", "compliance monitoring", "audit",
             "risk management", "consumer protection", "fair lending", "compliance program", 
             "sox", "internal controls", "governance", "cfpb", "occ", "fdic", "sec", "finra",
             "compliance analyst", "risk analyst", "compliance review", "examination", 
             "remediation", "policy", "regulation", "compliance officer"]
    return sum(1 for t in terms if t in desc_l) >= 2


def launch_chrome():
    """Launch real Chrome with remote debugging."""
    chrome_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    
    # Kill any existing Chrome instances using our profile
    subprocess.run(["pkill", "-f", f"user-data-dir={PROFILE_DIR}"], capture_output=True)
    time.sleep(2)
    
    Path(PROFILE_DIR).mkdir(parents=True, exist_ok=True)
    
    proc = subprocess.Popen([
        chrome_path,
        f"--remote-debugging-port={CDP_PORT}",
        f"--user-data-dir={PROFILE_DIR}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-sync",
        "about:blank",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    time.sleep(3)
    print(f"[CHROME] Launched with PID {proc.pid}, CDP on port {CDP_PORT}")
    return proc


def main():
    # Launch real Chrome
    chrome_proc = launch_chrome()
    
    pw = sync_playwright().start()
    
    try:
        browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{CDP_PORT}")
        context = browser.contexts[0]
        page = context.pages[0] if context.pages else context.new_page()
        
        print("[CDP] Connected to Chrome")
        
        found_job = None
        
        for keyword in KEYWORDS:
            if found_job:
                break
                
            for location in ["San Francisco Bay Area", "Remote"]:
                if found_job:
                    break
                    
                search_url = (
                    f"https://www.linkedin.com/jobs/search/"
                    f"?keywords={quote_plus(keyword)}"
                    f"&location={quote_plus(location)}"
                    f"&f_AL=true&sortBy=DD&f_TPR=r604800"
                )
                
                print(f"\n[SCAN] '{keyword}' in '{location}'")
                
                try:
                    page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
                    time.sleep(5)
                except Exception as e:
                    print(f"  Nav error: {e}")
                    continue
                
                # Check login
                if "login" in page.url.lower() or "authwall" in page.url.lower():
                    print("  Not logged in. Skipping.")
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
                    # Debug
                    try:
                        page.screenshot(path=str(PROJECT_ROOT / "output" / "debug_no_cards.png"))
                        body = page.evaluate("() => document.body.innerText.substring(0, 500)")
                        print(f"  Page text: {body[:200]}")
                    except Exception:
                        pass
                    continue
                
                print(f"  Found {len(cards)} cards")
                
                for i, card in enumerate(cards[:12]):
                    try:
                        card.scroll_into_view_if_needed()
                        time.sleep(random.uniform(0.8, 1.5))
                        card.click()
                        time.sleep(random.uniform(2.5, 4))
                        
                        # Extract info from card
                        title = ""
                        for sel in [".job-card-list__title", ".artdeco-entity-lockup__title a", "a strong"]:
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
                        for sel in [".job-card-container__primary-description", ".artdeco-entity-lockup__subtitle span"]:
                            try:
                                el = card.query_selector(sel)
                                if el:
                                    company = el.inner_text().strip()
                                    if company:
                                        break
                            except Exception:
                                continue
                        
                        loc = ""
                        for sel in [".job-card-container__metadata-item", ".artdeco-entity-lockup__caption span"]:
                            try:
                                el = card.query_selector(sel)
                                if el:
                                    loc = el.inner_text().strip()
                                    if loc:
                                        break
                            except Exception:
                                continue
                        
                        print(f"  [{i+1}] {title} @ {company}")
                        
                        if not title or is_excluded(company):
                            continue
                        
                        job_url = page.url
                        id_match = re.search(r'currentJobId=(\d+)', job_url)
                        if id_match:
                            job_url = f"https://www.linkedin.com/jobs/view/{id_match.group(1)}/"
                        
                        if is_already_applied(job_url, company, title):
                            print(f"      Already applied")
                            continue
                        
                        # Check Easy Apply
                        easy = False
                        for ea_sel in ['button:has-text("Easy Apply")', 'button[aria-label*="Easy Apply"]']:
                            try:
                                btn = page.locator(ea_sel).first
                                if btn.is_visible(timeout=2000):
                                    if "Easy" in (btn.inner_text() or ""):
                                        easy = True
                                        break
                            except Exception:
                                continue
                        
                        if not easy:
                            continue
                        
                        # Get description
                        desc = ""
                        for sel in [".jobs-description__content", "#job-details", ".jobs-box__html-content"]:
                            try:
                                el = page.query_selector(sel)
                                if el:
                                    desc = el.inner_text().strip()
                                    if desc and len(desc) > 100:
                                        break
                            except Exception:
                                continue
                        
                        if not desc:
                            try:
                                body = page.evaluate("() => document.body.innerText")
                                idx = body.find("About the job")
                                if idx != -1:
                                    raw = body[idx+13:].strip()
                                    for stop in ["Show less", "People you can reach", "Similar jobs"]:
                                        si = raw.find(stop)
                                        if si != -1:
                                            raw = raw[:si]
                                    if len(raw) > 100:
                                        desc = raw.strip()
                            except Exception:
                                pass
                        
                        if not is_relevant(title, desc):
                            print(f"      Not relevant")
                            continue
                        
                        print(f"      >>> MATCH!")
                        found_job = {
                            "title": title,
                            "company": company,
                            "location": loc,
                            "url": job_url,
                            "description": desc,
                            "keyword": keyword,
                        }
                        break
                        
                    except Exception as e:
                        print(f"      Error: {e}")
                        continue
        
        # Save result
        result_path = PROJECT_ROOT / "output" / "cycle_result.json"
        if found_job:
            with open(result_path, "w") as f:
                json.dump(found_job, f, indent=2)
            print(f"\n[RESULT] {found_job['title']} @ {found_job['company']}")
            print(f"  URL: {found_job['url']}")
            print(f"  Desc: {len(found_job['description'])} chars")
        else:
            with open(result_path, "w") as f:
                json.dump({"status": "no_jobs_found"}, f, indent=2)
            print("\n[RESULT] No relevant Easy Apply jobs found.")
        
    finally:
        try:
            browser.close()
        except Exception:
            pass
        pw.stop()
        chrome_proc.terminate()
        chrome_proc.wait(timeout=5)
        print("[DONE] Browser closed.")


if __name__ == "__main__":
    main()
