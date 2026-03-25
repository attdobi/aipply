# Aipply

**AI-powered LinkedIn job application bot**

Aipply (AI + Apply) is an automated system that scans LinkedIn for job postings, auto-applies to matching positions, customizes your resume and cover letter per job using AI, and tracks all applications in one place.

---

## Features

- **Auto-search LinkedIn** — Continuously scans LinkedIn for jobs matching your criteria
- **Auto-apply to jobs** — Submits applications via browser automation
- **AI-powered resume tailoring** — Customizes your base resume for each job description using OpenAI
- **AI-powered cover letter generation** — Generates targeted cover letters per role
- **Application tracking** — Tracks every application with HTML and XLSX reports
- **Company exclusion list** — Skip companies you don't want to apply to
- **Configurable search criteria** — Keywords, locations, experience levels, job types

## Architecture

- **Language:** Python 3.10+
- **Browser Automation:** Playwright (with Selenium fallback)
- **AI Engine:** OpenAI API (GPT-4) for resume/cover letter customization
- **Document Processing:** python-docx for Word documents, openpyxl for Excel reports
- **Templating:** Jinja2 for HTML reports
- **Config:** YAML-based configuration

## Directory Structure

```
aipply/
├── config/
│   ├── settings.yaml          # Search criteria, exclusions, schedule
│   └── profile.yaml           # Candidate profile and strengths
├── templates/
│   ├── base_resume.docx       # Your base resume (not tracked in git)
│   └── base_cover_letter.docx # Your base cover letter (not tracked in git)
├── src/
│   ├── __init__.py
│   ├── linkedin_scanner.py    # Job search and filtering
│   ├── linkedin_applicant.py  # Application submission
│   ├── resume_tailor.py       # AI-powered resume customization
│   ├── cover_letter_gen.py    # AI-powered cover letter generation
│   └── utils.py               # Shared utilities
├── scripts/
│   └── run_cycle.py           # Main entry point
├── output/
│   ├── applications/          # Tailored resumes and cover letters per job
│   ├── reports/               # HTML/XLSX tracking reports
│   └── tracker.json           # Application history
├── tests/
├── requirements.txt
├── .gitignore
└── README.md
```

## Setup

### Prerequisites

- **Python 3.10+**
- **Google Chrome** (or Chromium) installed
- **OpenAI API key** with GPT-4 access
- **LinkedIn account** — you'll log in manually once; the bot reuses your session

### Installation

```bash
git clone https://github.com/attdobi/aipply.git
cd aipply
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

### Configuration

1. **Copy the example configs:**
   ```bash
   cp config/settings.example.yaml config/settings.yaml
   cp config/profile.example.yaml config/profile.yaml
   ```

2. **Edit `config/settings.yaml`** — set your search keywords, target locations, excluded companies, and application preferences.

3. **Edit `config/profile.yaml`** — fill in your name, email, phone, summary, strengths, and target roles. The AI uses this to tailor resumes and cover letters.

4. **Add your base documents to `templates/`:**
   - `templates/base_resume.docx` — your master resume (.docx format)
   - `templates/base_cover_letter.docx` — an example cover letter for tone/style reference

5. **Set your OpenAI API key:**
   ```bash
   echo "OPENAI_API_KEY=sk-your-key-here" > .env
   ```

### Usage

**Run a full application cycle:**
```bash
source .venv/bin/activate
python scripts/run_cycle.py
```

**Dry run (scan jobs, tailor materials, but don't submit):**
```bash
python scripts/run_cycle.py --dry-run
```

**Limit number of applications per cycle:**
```bash
python scripts/run_cycle.py --limit 5
```

**Generate report only (no scanning or applying):**
```bash
python scripts/run_cycle.py --report-only
```

### Output

Each application creates a directory under `output/applications/`:
```
output/applications/Acme_Corp_Compliance_Manager_2026-03-24/
├── tailored_resume.docx
├── cover_letter.docx
├── job_description.txt
└── screenshot.png       # Pre-submit screenshot for records
```

View all applications in the HTML report at `output/reports/applications_report.html`.

### Cron / Automation

To run every hour automatically, set up a cron job:
```bash
crontab -e
# Add:
0 * * * * cd /path/to/aipply && .venv/bin/python scripts/run_cycle.py >> output/cron.log 2>&1
```

Or use OpenClaw's built-in cron for agent-managed scheduling.

## Privacy

Personal data (resume, cover letter, configs with your name/email) is **gitignored by default** and never pushed to the repo. Only example configs ship publicly. See `.gitignore` for details.

## License

MIT — see [LICENSE](LICENSE) for details.
