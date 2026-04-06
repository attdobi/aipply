"""Deterministic policy scaffolding for safe-first job filtering.

The policy layer is intentionally simple: given a company/title string and a set
of blocklists, it returns stable reason codes that higher-level flows can log,
report, or use to skip unsafe / low-quality jobs before spending time on detail
fetching or submission work.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

DEFAULT_COMPANY_BLOCKLISTS: dict[str, tuple[str, ...]] = {
    "recruiting_staffing": (
        "recruiting",
        "recruitment",
        "staffing",
        "staffing solutions",
        "talent acquisition",
        "talent solutions",
        "placement",
        "employment agency",
        "headhunting",
    ),
    "consulting": (
        "consulting",
        "consultants",
        "consultancy",
        "advisory services",
    ),
}

DEFAULT_TITLE_BLOCKLISTS: dict[str, tuple[str, ...]] = {
    "recruiting_staffing": (
        "recruiter",
        "recruiting",
        "talent acquisition",
        "staffing",
    ),
    "consulting": (
        "consultant",
        "consulting",
    ),
    "hourly_temp": (
        "hourly",
        "per hour",
        "/hr",
        "temp",
        "temporary",
        "seasonal",
        "contract to hire",
        "contract-to-hire",
        "1099",
        "w2 contract",
        "part time",
        "part-time",
        "commission only",
    ),
}


@dataclass(frozen=True)
class PolicyReason:
    """A stable, test-friendly explanation for a policy block."""

    scope: str
    category: str
    matched_term: str

    @property
    def code(self) -> str:
        return f"{self.scope}:{self.category}"

    @property
    def message(self) -> str:
        return (
            f"blocked by {self.scope} policy '{self.category}' "
            f"(matched '{self.matched_term}')"
        )


@dataclass(frozen=True)
class PolicyDecision:
    """Decision result for a company/title/job evaluation."""

    allowed: bool
    reasons: tuple[PolicyReason, ...] = ()

    def summary(self) -> str:
        if self.allowed:
            return "allowed"
        return "; ".join(reason.message for reason in self.reasons)


BlocklistMap = Mapping[str, Iterable[str]]


def normalize_policy_text(value: str | None) -> str:
    """Normalize text for deterministic substring matching."""
    if not value:
        return ""
    return " ".join(str(value).lower().split())


def _collect_reasons(
    text: str,
    scope: str,
    blocklists: BlocklistMap,
) -> tuple[PolicyReason, ...]:
    normalized_text = normalize_policy_text(text)
    reasons: list[PolicyReason] = []

    for category, raw_terms in blocklists.items():
        for raw_term in raw_terms:
            term = normalize_policy_text(raw_term)
            if term and term in normalized_text:
                reasons.append(
                    PolicyReason(
                        scope=scope,
                        category=category,
                        matched_term=term,
                    )
                )
                break

    return tuple(reasons)


def evaluate_company_quality(
    company: str | None,
    blocklists: BlocklistMap | None = None,
) -> PolicyDecision:
    """Evaluate company quality against configurable blocklists."""
    reasons = _collect_reasons(
        company or "",
        scope="company",
        blocklists=(
            DEFAULT_COMPANY_BLOCKLISTS if blocklists is None else blocklists
        ),
    )
    return PolicyDecision(allowed=not reasons, reasons=reasons)


def evaluate_title_quality(
    title: str | None,
    blocklists: BlocklistMap | None = None,
) -> PolicyDecision:
    """Evaluate title quality against configurable blocklists."""
    reasons = _collect_reasons(
        title or "",
        scope="title",
        blocklists=(DEFAULT_TITLE_BLOCKLISTS if blocklists is None else blocklists),
    )
    return PolicyDecision(allowed=not reasons, reasons=reasons)


def evaluate_job_policy(
    job: Mapping[str, str] | None,
    *,
    company_blocklists: BlocklistMap | None = None,
    title_blocklists: BlocklistMap | None = None,
) -> PolicyDecision:
    """Evaluate combined company/title policy for a job record."""
    job = job or {}
    company_decision = evaluate_company_quality(
        job.get("company", ""),
        blocklists=company_blocklists,
    )
    title_decision = evaluate_title_quality(
        job.get("title", ""),
        blocklists=title_blocklists,
    )
    reasons = company_decision.reasons + title_decision.reasons
    return PolicyDecision(allowed=not reasons, reasons=reasons)


def format_policy_reasons(reasons: Iterable[PolicyReason]) -> str:
    """Return a stable, concise log string for policy reasons."""
    collected = tuple(reasons)
    if not collected:
        return "allowed"
    return "; ".join(reason.message for reason in collected)
