#!/usr/bin/env python3
"""Quick run: scan LinkedIn, fetch full descriptions, tailor materials, track & report."""

import os
import sys
import yaml

# Setup paths
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load env
from dotenv import load_dotenv
load_dotenv()

from datetime import datetime
from src.linkedin_scanner import LinkedInScanner
from src.resume_tailor import ResumeTailor
from src.cover_letter_gen import CoverLetterGenerator
from src.tracker import ApplicationTracker

LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 else 5
KEYWORD = sys.argv[2] if len(sys.argv) > 2 else "compliance manager"
LOCATION = sys.argv[3] if len(sys.argv) > 2 else "San Francisco Bay Area"

settings = yaml.safe_load(open('config/settings.yaml'))
profile = yaml.safe_load(open('config/profile.yaml'))

exclusions = [c.lower() for c in settings.get('exclusions', {}).get('companies', [])]
exclusions += ['pg&e', 'pacific gas']

# 1. SCAN
print(f'🔍 Scanning LinkedIn for "{KEYWORD}" in "{LOCATION}"...')
scanner = LinkedInScanner(config=settings)
scanner.connect_browser()
cards = scanner.search_jobs(keywords=KEYWORD, location=LOCATION, max_results=LIMIT + 5)

# Filter exclusions
cards = [j for j in cards if not any(ex in j.get('company', '').lower() for ex in exclusions)]
print(f'✅ Found {len(cards)} jobs (after exclusions)')

# 2. FETCH FULL DESCRIPTIONS for each job
tracker = ApplicationTracker('output/tracker.json')
jobs_with_details = []
for i, card in enumerate(cards[:LIMIT]):
    url = card.get('url', '')
    if not url or tracker.is_already_applied(url):
        print(f'  ⏭️  Skipping (already applied or no URL): {card.get("company")} — {card.get("title", "").split(chr(10))[0]}')
        continue
    print(f'  📖 [{i+1}] Fetching details: {card.get("company")} — {card.get("title", "").split(chr(10))[0]}')
    try:
        details = scanner.get_job_details(url)
        if details.get('description'):
            jobs_with_details.append(details)
            print(f'      ✅ Got {len(details["description"])} chars of description')
        else:
            # Fallback — use card data with minimal description
            card['description'] = f'{card.get("title", "")} at {card.get("company", "")}'
            jobs_with_details.append(card)
            print(f'      ⚠️  No description found, using title')
    except Exception as e:
        print(f'      ❌ Failed: {e}')

scanner.close()
print(f'\n📋 {len(jobs_with_details)} jobs ready for tailoring')

# 3. TAILOR & TRACK
tailor = ResumeTailor(config=settings)
cover_gen = CoverLetterGenerator(config=settings)

for i, job in enumerate(jobs_with_details):
    company = (job.get('company') or 'Unknown').strip()
    title = (job.get('title') or 'Role').split('\n')[0].strip()
    desc = job.get('description', '')
    location = job.get('location', '')
    url = job.get('url', '')

    co_safe = company.replace(' ', '_').replace('/', '_').replace(',', '')[:25]
    ti_safe = title.replace(' ', '_').replace('/', '_').replace(',', '')[:25]
    out_dir = f"output/applications/{co_safe}_{ti_safe}_{datetime.now().strftime('%Y%m%d_%H%M')}"
    os.makedirs(out_dir, exist_ok=True)

    print(f'\n📝 [{i+1}/{len(jobs_with_details)}] {company} — {title}')
    print(f'    Description: {desc[:100]}...' if len(desc) > 100 else f'    Description: {desc}')

    resume_path = cl_path = None

    # Tailor resume
    try:
        resume_path = str(tailor.tailor_and_save('templates/base_resume.docx', desc, company, title, out_dir))
        print(f'    ✅ Resume tailored')
    except Exception as e:
        print(f'    ❌ Resume: {e}')

    # Generate cover letter
    try:
        cl_path = str(cover_gen.generate_and_save(desc, profile.get('candidate', {}), company, title, out_dir))
        print(f'    ✅ Cover letter generated')
    except Exception as e:
        print(f'    ❌ Cover letter: {e}')

    # Save job description
    with open(os.path.join(out_dir, 'job_description.txt'), 'w') as f:
        f.write(f"Company: {company}\nTitle: {title}\nLocation: {location}\nURL: {url}\n\n{desc}")

    # Track
    tracker.add_application(
        company=company, position=title, job_url=url,
        location=location,
        status='materials_ready' if (resume_path and cl_path) else 'partial',
        resume_path=resume_path or '',
        cover_letter_path=cl_path or '',
        job_description=desc[:500],
    )
    print(f'    ✅ Tracked')

# 4. REPORT
report_path = tracker.generate_html_report('output/reports/applications_report.html')
stats = tracker.get_stats()
print(f"\n{'='*60}")
print(f"📊 Total applications: {stats['total']}")
print(f"📊 Dashboard: file:///Users/sacsimoto/GitHub/aipply/output/reports/applications_report.html")
print(f"📂 Artifacts: output/applications/")
print(f"{'='*60}")
