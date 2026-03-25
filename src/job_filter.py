"""Job relevance filter for compliance/audit/risk professional.

Enforces both positive (must match) and negative (must not match) title
filters to ensure only relevant jobs are processed.
"""

import re
import logging

logger = logging.getLogger(__name__)

# Title MUST contain at least one of these (case-insensitive)
POSITIVE_KEYWORDS = [
    "compliance",
    "risk",
    "audit",
    "fraud",
    "bsa",
    "aml",
    "regulatory",
    "governance",
    "monitoring",
    "examiner",
    "investigator",
    "quality control",
    # Compound terms — "analyst" alone is too broad (matches "Financial Analyst" etc.)
    "compliance analyst",
    "risk analyst",
    "audit analyst",
    "fraud analyst",
    "regulatory analyst",
    "operations analyst",
    "compliance specialist",
    "compliance officer",
    "compliance coordinator",
    "risk officer",
    "compliance testing",
    "controls testing",
]

# Title must NOT contain any of these (case-insensitive)
NEGATIVE_KEYWORDS = [
    "investment banking",
    "software engineer",
    "data scientist",
    "sales",
    "marketing",
    "product manager",
    "design",
    "machine learning",
    "devops",
    "frontend",
    "backend",
    "full stack",
    "fullstack",
    "web developer",
    "mobile developer",
    "ux ",
    "ui ",
    "graphic",
    "creative",
    "content writer",
    "recruiter",
    "recruiting",
    "talent acquisition",
    "accounting manager",
    "controller",
    "cfo",
    "cto",
    "cio",
    "oracle",
    "sap ",
    "hcm",
    "payroll specialist",
    "customer service",
    "customer support",
    "call center",
    "warehouse",
    "driver",
    "mechanic",
    "electrician",
    "nurse",
    "physician",
    "dental",
    "veterinary",
    "teacher",
    "professor",
    "instructor",
    "real estate",
    "property manager",
    "proposal strategist",
    "international payroll",
]

# Too-senior titles to skip
SENIOR_TITLE_KEYWORDS = [
    "director",
    "vice president",
    "vp ",
    "head of",
    "chief ",
    "managing director",
    "svp",
    "evp",
    "partner",
    "president",
    "founder",
    "c-suite",
]

# Companies to exclude
EXCLUDED_COMPANIES = {
    "pg&e",
    "pacific gas and electric",
    "pacific gas & electric",
}


def is_relevant_title(title: str) -> bool:
    """Check if a job title is relevant for compliance/audit/risk professional.

    Returns True only if title contains at least one positive keyword
    AND does not contain any negative keywords.
    """
    title_lower = title.lower().strip()

    # Check negative keywords first (fast reject)
    for neg in NEGATIVE_KEYWORDS:
        if neg in title_lower:
            logger.debug(f"Title rejected (negative match '{neg}'): {title}")
            return False

    # Check for too-senior titles
    for senior in SENIOR_TITLE_KEYWORDS:
        if senior in title_lower:
            logger.debug(f"Title rejected (too senior '{senior}'): {title}")
            return False

    # Must match at least one positive keyword
    for pos in POSITIVE_KEYWORDS:
        if pos in title_lower:
            logger.debug(f"Title accepted (positive match '{pos}'): {title}")
            return True

    logger.debug(f"Title rejected (no positive match): {title}")
    return False


def is_excluded_company(company: str) -> bool:
    """Check if company is in the exclusion list."""
    company_lower = company.lower().strip()
    return any(exc in company_lower for exc in EXCLUDED_COMPANIES)


def filter_job(job: dict) -> tuple[bool, str]:
    """Filter a single job dict. Returns (pass, reason).

    Args:
        job: dict with 'title', 'company', 'location' keys

    Returns:
        (True, "") if job passes filter
        (False, reason) if job is filtered out
    """
    title = job.get("title", "")
    company = job.get("company", "")

    # Normalize title (remove duplicate lines from LinkedIn scraping)
    title = title.split("\n")[0].strip()

    if is_excluded_company(company):
        return False, f"excluded_company:{company}"

    if not is_relevant_title(title):
        return False, f"irrelevant_title:{title}"

    return True, ""
