"""LinkedIn job scanner module.

Searches LinkedIn for job postings matching configured criteria
and filters results based on exclusion rules.
"""

import logging
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page

logger = logging.getLogger(__name__)

# Default persistent browser profile directory
DEFAULT_PROFILE_DIR = str(Path.home() / ".aipply" / "chrome-profile")

# Fallback CSS selectors for LinkedIn job cards (LinkedIn changes these frequently)
JOB_CARD_SELECTORS = [
    ".job-card-container",
    ".jobs-search-results__list-item",
    "li.ember-view.occludable-update",
    "[data-occludable-job-id]",
]

TITLE_SELECTORS = [
    ".job-card-list__title",
    ".job-card-list__title--link",
    ".job-card-container__link",
    "a.job-card-list__title--link",
    ".artdeco-entity-lockup__title a",
    "a[data-control-name='jobPosting_jobCardTitle']",
]

COMPANY_SELECTORS = [
    ".job-card-container__primary-description",
    ".artdeco-entity-lockup__subtitle span",
    ".job-card-container__company-name",
    ".job-card-list__company-name",
]

LOCATION_SELECTORS = [
    ".job-card-container__metadata-item",
    ".artdeco-entity-lockup__caption span",
    ".job-card-list__location",
    ".job-card-container__metadata-wrapper li",
]


class LinkedInScanner:
    """Scans LinkedIn for job postings and filters results."""

    def __init__(self, config: dict[str, Any] | None = None):
        """Initialize scanner with search configuration.

        Args:
            config: Search settings from config/settings.yaml.
        """
        self.config = config or {}
        self.search_config = self.config.get("search", {})
        self.exclusions = self.config.get("exclusions", {})
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    # ------------------------------------------------------------------
    # Browser management
    # ------------------------------------------------------------------

    def connect_browser(self, cdp_url: str | None = None) -> Page:
        """Connect to an existing Chrome via CDP or launch a persistent context.

        Args:
            cdp_url: Chrome DevTools Protocol URL (e.g. ``http://localhost:9222``).
                     If provided, connects over CDP.  Otherwise launches a
                     persistent Chromium context using a local user-data dir.

        Returns:
            A Playwright ``Page`` object ready for navigation.
        """
        self._playwright = sync_playwright().start()

        if cdp_url:
            logger.info("Connecting to Chrome via CDP at %s", cdp_url)
            try:
                self._browser = self._playwright.chromium.connect_over_cdp(cdp_url)
                contexts = self._browser.contexts
                if contexts:
                    self._context = contexts[0]
                    pages = self._context.pages
                    self._page = pages[0] if pages else self._context.new_page()
                else:
                    self._context = self._browser.new_context()
                    self._page = self._context.new_page()
                logger.info("Connected to existing Chrome instance via CDP")
                return self._page
            except Exception as exc:
                logger.warning("CDP connection failed (%s), falling back to persistent context", exc)

        # Fallback: persistent browser context
        profile_dir = self.config.get("browser", {}).get("profile_dir", DEFAULT_PROFILE_DIR)
        Path(profile_dir).mkdir(parents=True, exist_ok=True)
        logger.info("Launching persistent Chromium context at %s", profile_dir)

        self._context = self._playwright.chromium.launch_persistent_context(
            user_data_dir=profile_dir,
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--no-default-browser-check",
            ],
        )
        self._page = self._context.pages[0] if self._context.pages else self._context.new_page()
        return self._page

    # ------------------------------------------------------------------
    # Job search
    # ------------------------------------------------------------------

    def search_jobs(
        self,
        keywords: str | list[str],
        location: str,
        max_results: int = 25,
    ) -> list[dict[str, Any]]:
        """Search LinkedIn Jobs for postings matching *keywords* and *location*.

        Args:
            keywords: Search term(s).  If a list, joined with spaces.
            location: Target location string (e.g. ``"San Francisco Bay Area"``).
            max_results: Stop collecting after this many results (default 25).

        Returns:
            List of dicts with keys: ``title``, ``company``, ``location``,
            ``url``, ``linkedin_job_id``.
        """
        if self._page is None:
            raise RuntimeError("Browser not connected. Call connect_browser() first.")

        if isinstance(keywords, list):
            keywords = " ".join(keywords)

        search_url = (
            f"https://www.linkedin.com/jobs/search/"
            f"?keywords={quote_plus(keywords)}&location={quote_plus(location)}"
        )
        logger.info("Navigating to %s", search_url)
        self._page.goto(search_url, wait_until="domcontentloaded", timeout=30_000)
        # Give the SPA a moment to render
        self._page.wait_for_timeout(3000)

        all_jobs: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        max_pages = 5

        for page_num in range(max_pages):
            if len(all_jobs) >= max_results:
                break

            logger.info("Parsing results page %d (collected %d so far)", page_num + 1, len(all_jobs))
            cards = self._find_job_cards()

            for card in cards:
                if len(all_jobs) >= max_results:
                    break
                job = self._parse_job_card(card)
                if job and job.get("linkedin_job_id") not in seen_ids:
                    seen_ids.add(job["linkedin_job_id"])
                    all_jobs.append(job)

            # Paginate: scroll down and wait for more results
            if not self._load_more_results():
                logger.info("No more results to load.")
                break

        logger.info("Collected %d job(s) total", len(all_jobs))
        return all_jobs[:max_results]

    def _find_job_cards(self):
        """Try multiple selectors to locate job card elements."""
        for selector in JOB_CARD_SELECTORS:
            cards = self._page.query_selector_all(selector)
            if cards:
                logger.debug("Found %d cards with selector '%s'", len(cards), selector)
                return cards
        logger.warning("No job cards found with any known selector")
        return []

    def _parse_job_card(self, card) -> dict[str, Any] | None:
        """Extract structured data from a single job card element."""
        try:
            title = self._extract_text(card, TITLE_SELECTORS) or ""
            company = self._extract_text(card, COMPANY_SELECTORS) or ""
            location = self._extract_text(card, LOCATION_SELECTORS) or ""

            # Try to get the job URL from an anchor tag
            url = ""
            linkedin_job_id = ""
            link_el = card.query_selector("a[href*='/jobs/view/']") or card.query_selector("a")
            if link_el:
                href = link_el.get_attribute("href") or ""
                if href.startswith("/"):
                    href = f"https://www.linkedin.com{href}"
                url = href.split("?")[0]  # strip query params

                # Extract job ID from URL like /jobs/view/1234567890/
                id_match = re.search(r"/jobs/view/(\d+)", url)
                if id_match:
                    linkedin_job_id = id_match.group(1)

            # Fallback: data attribute for job ID
            if not linkedin_job_id:
                for attr in ("data-occludable-job-id", "data-job-id", "data-entity-urn"):
                    val = card.get_attribute(attr)
                    if val:
                        # URNs look like urn:li:jobPosting:1234567890
                        digits = re.search(r"(\d+)", val)
                        if digits:
                            linkedin_job_id = digits.group(1)
                            break

            if not title and not company:
                return None

            if not linkedin_job_id:
                linkedin_job_id = re.sub(r"\W", "", f"{title}_{company}")[:64]

            return {
                "title": title.strip(),
                "company": company.strip(),
                "location": location.strip(),
                "url": url,
                "linkedin_job_id": linkedin_job_id,
            }
        except Exception as exc:
            logger.debug("Failed to parse job card: %s", exc)
            return None

    def _extract_text(self, parent, selectors: list[str]) -> str | None:
        """Try each selector within *parent* and return inner text of the first match."""
        for sel in selectors:
            try:
                el = parent.query_selector(sel)
                if el:
                    text = el.inner_text()
                    if text and text.strip():
                        return text.strip()
            except Exception:
                continue
        return None

    def _load_more_results(self) -> bool:
        """Scroll down and/or click 'See more jobs' to load the next page."""
        try:
            # Scroll to the bottom of the results list
            self._page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            self._page.wait_for_timeout(2000)

            # Try clicking a "See more jobs" button
            see_more = self._page.query_selector(
                "button.infinite-scroller__show-more-button, "
                "button[aria-label='See more jobs'], "
                "button.see-more-jobs"
            )
            if see_more and see_more.is_visible():
                see_more.click()
                self._page.wait_for_timeout(2000)
                return True

            # Check if new content loaded after scroll
            self._page.wait_for_timeout(1500)
            return False  # No explicit load-more trigger found
        except Exception as exc:
            logger.debug("Load-more failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Filtering
    # ------------------------------------------------------------------

    def filter_results(
        self,
        jobs: list[dict[str, Any]],
        exclusions: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Filter out excluded companies and duplicates.

        Args:
            jobs: Raw job results from :meth:`search_jobs`.
            exclusions: Override exclusion config. Falls back to
                        ``self.exclusions`` from the constructor config.

        Returns:
            Filtered (deduplicated) list of job dicts.
        """
        exclusions = exclusions or self.exclusions
        excluded_companies = {c.lower() for c in exclusions.get("companies", [])}
        excluded_keywords = {k.lower() for k in exclusions.get("keywords", [])}

        seen_ids: set[str] = set()
        seen_urls: set[str] = set()
        filtered: list[dict[str, Any]] = []

        for job in jobs:
            # Deduplicate
            jid = job.get("linkedin_job_id", "")
            url = job.get("url", "")
            if jid in seen_ids or (url and url in seen_urls):
                logger.debug("Skipping duplicate: %s", job.get("title"))
                continue

            # Company exclusion (case-insensitive substring match)
            company_lower = job.get("company", "").lower()
            if any(exc in company_lower for exc in excluded_companies):
                logger.info("Excluding '%s' at '%s' (excluded company)", job.get("title"), job.get("company"))
                continue

            # Keyword exclusion in title
            title_lower = job.get("title", "").lower()
            if excluded_keywords and any(kw in title_lower for kw in excluded_keywords):
                logger.info("Excluding '%s' (excluded keyword in title)", job.get("title"))
                continue

            seen_ids.add(jid)
            if url:
                seen_urls.add(url)
            filtered.append(job)

        logger.info("Filtered %d → %d jobs", len(jobs), len(filtered))
        return filtered

    # ------------------------------------------------------------------
    # Job detail extraction
    # ------------------------------------------------------------------

    def get_job_details(
        self,
        job_url: str,
        page: Page | None = None,
    ) -> dict[str, Any]:
        """Navigate to a job posting and extract the full description.

        Args:
            job_url: LinkedIn job posting URL.
            page: Optional Playwright Page to use (defaults to internal page).

        Returns:
            Dict with ``title``, ``company``, ``location``, ``description``,
            ``url``, ``linkedin_job_id``.
        """
        target_page = page or self._page
        if target_page is None:
            raise RuntimeError("Browser not connected. Call connect_browser() first.")

        logger.info("Fetching job details from %s", job_url)
        target_page.goto(job_url, wait_until="domcontentloaded", timeout=30_000)
        target_page.wait_for_timeout(2000)

        # Scroll down to trigger lazy-loading of description section
        for _ in range(4):
            target_page.evaluate("window.scrollBy(0, 600)")
            target_page.wait_for_timeout(400)
        target_page.wait_for_timeout(1000)

        # Try to click "Show more" / "See more" to expand the description
        try:
            show_more = target_page.query_selector(
                "button[aria-label='Show more'], "
                "button.jobs-description__footer-button, "
                "button[data-control-name='see_more']"
            )
            if show_more and show_more.is_visible():
                show_more.click()
                target_page.wait_for_timeout(1000)
        except Exception:
            pass

        # Extract title
        title = ""
        for sel in [
            ".job-details-jobs-unified-top-card__job-title h1",
            ".jobs-unified-top-card__job-title",
            ".t-24.t-bold",
            "h1",
        ]:
            el = target_page.query_selector(sel)
            if el:
                title = el.inner_text().strip()
                if title:
                    break

        # Extract company
        company = ""
        for sel in [
            ".job-details-jobs-unified-top-card__company-name a",
            ".jobs-unified-top-card__company-name a",
            ".jobs-unified-top-card__company-name",
        ]:
            el = target_page.query_selector(sel)
            if el:
                company = el.inner_text().strip()
                if company:
                    break

        # Extract location
        location = ""
        for sel in [
            ".job-details-jobs-unified-top-card__bullet",
            ".jobs-unified-top-card__bullet",
            ".jobs-unified-top-card__workplace-type",
        ]:
            el = target_page.query_selector(sel)
            if el:
                location = el.inner_text().strip()
                if location:
                    break

        # Extract description
        description = ""
        for sel in [
            ".jobs-description__content",
            ".jobs-description-content__text",
            "#job-details",
            ".jobs-box__html-content",
            "article",
        ]:
            el = target_page.query_selector(sel)
            if el:
                description = el.inner_text().strip()
                if description:
                    break

        # Fallback: extract "About the job" section from page body text
        if not description:
            try:
                body_text = target_page.evaluate("() => document.body.innerText")
                marker = "About the job"
                idx = body_text.find(marker)
                if idx != -1:
                    raw = body_text[idx + len(marker):].strip()
                    # Truncate at common footer markers
                    for stop in [
                        "Show less",
                        "People you can reach out to",
                        "Similar jobs",
                        "More from this employer",
                    ]:
                        stop_idx = raw.find(stop)
                        if stop_idx != -1:
                            raw = raw[:stop_idx].strip()
                    if len(raw) > 100:
                        description = raw
                        logger.debug("Used body-text fallback for description (%d chars)", len(description))
            except Exception as exc:
                logger.debug("Body text fallback failed: %s", exc)

        # Extract job ID from URL
        linkedin_job_id = ""
        id_match = re.search(r"/jobs/view/(\d+)", job_url)
        if id_match:
            linkedin_job_id = id_match.group(1)

        return {
            "title": title,
            "company": company,
            "location": location,
            "description": description,
            "url": job_url,
            "linkedin_job_id": linkedin_job_id,
        }

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def close(self):
        """Close browser and Playwright resources."""
        try:
            if self._context:
                self._context.close()
        except Exception as exc:
            logger.debug("Error closing context: %s", exc)
        try:
            if self._browser:
                self._browser.close()
        except Exception as exc:
            logger.debug("Error closing browser: %s", exc)
        try:
            if self._playwright:
                self._playwright.stop()
        except Exception as exc:
            logger.debug("Error stopping playwright: %s", exc)
        self._context = None
        self._browser = None
        self._playwright = None
        self._page = None
        logger.info("Browser resources cleaned up")
