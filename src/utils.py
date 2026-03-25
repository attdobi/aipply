"""Shared utility functions for Aipply."""

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


def load_config(path: str | Path) -> dict[str, Any]:
    """Load a YAML configuration file.

    Args:
        path: Path to the YAML config file.

    Returns:
        Parsed config as a dictionary.
    """
    with open(path, "r") as f:
        return yaml.safe_load(f) or {}


def ensure_dir(path: str | Path) -> Path:
    """Create a directory (and parents) if it doesn't exist.

    Args:
        path: Directory path to create.

    Returns:
        The Path object for the directory.
    """
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def sanitize_filename(name: str) -> str:
    """Sanitize a string for use as a filename.

    Replaces non-alphanumeric characters (except hyphens and underscores)
    with underscores and collapses consecutive underscores.

    Args:
        name: Raw string to sanitize.

    Returns:
        Filesystem-safe filename string.
    """
    sanitized = re.sub(r"[^\w\-]", "_", name)
    sanitized = re.sub(r"_+", "_", sanitized).strip("_")
    return sanitized


def get_timestamp() -> str:
    """Get current UTC timestamp as an ISO 8601 string.

    Returns:
        Timestamp string, e.g. '2024-01-15T10:30:00Z'.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
