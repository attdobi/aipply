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

> Coming soon

### Installation

> Coming soon

### Configuration

> Coming soon

### Usage

> Coming soon

## License

MIT — see [LICENSE](LICENSE) for details.
