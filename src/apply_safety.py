"""Central safety policy for live job submission.

Live submission is disabled by default. Callers must explicitly opt in via
config before any final submit click is allowed.
"""

from __future__ import annotations

from typing import Any

LIVE_SUBMISSION_BLOCK_REASON = "shadow_mode_no_submit"
LIVE_SUBMISSION_ENABLED_REASON = "live_submission_enabled"


def _application_settings(config: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(config, dict):
        return {}
    app_cfg = config.get("application", {})
    return app_cfg if isinstance(app_cfg, dict) else {}


def _is_enabled(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "enabled", "live"}
    if isinstance(value, (int, float)):
        return bool(value)
    return False


def can_submit_live(config: dict[str, Any] | None) -> bool:
    """Return True only when live submission is explicitly enabled.

    Supported opt-in flags:
    - application.live_submission_enabled: true
    - application.submit_enabled: true
    - application.mode: "live"

    Missing config defaults to False (shadow mode).
    """
    app_cfg = _application_settings(config)

    if _is_enabled(app_cfg.get("live_submission_enabled")):
        return True
    if _is_enabled(app_cfg.get("submit_enabled")):
        return True

    mode = str(app_cfg.get("mode", "")).strip().lower()
    return mode == "live"


def get_submission_block_reason(config: dict[str, Any] | None) -> str | None:
    """Return a human-readable policy reason for the current config."""
    if can_submit_live(config):
        return None
    return LIVE_SUBMISSION_BLOCK_REASON
