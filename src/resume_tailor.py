"""Resume tailoring module.

Clones the original .docx and surgically replaces the Professional Summary
and reorders Core Competencies. No API calls — the caller provides the
tailored text directly.
"""

import logging
import os
import shutil
from pathlib import Path
from typing import Any

from docx import Document

from src.utils import ensure_dir, sanitize_filename

logger = logging.getLogger(__name__)


class ResumeTailor:
    """Clones a .docx resume and replaces summary + competencies."""

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}

    @staticmethod
    def read_resume_text(path: str | Path) -> str:
        """Read all text from a .docx resume."""
        doc = Document(str(path))
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())

    @staticmethod
    def clone_and_tailor(base_path: str | Path, output_path: str | Path,
                          new_summary: str | None = None,
                          new_competencies: list[str] | None = None) -> Path:
        """Clone .docx and surgically replace summary and/or competencies.

        Preserves ALL original formatting — fonts, sizes, bold, bullets, spacing.
        Only the text content of targeted paragraphs is changed.
        """
        output_path = Path(output_path)
        ensure_dir(output_path.parent)

        # Byte-for-byte copy first
        shutil.copy2(str(base_path), str(output_path))

        doc = Document(str(output_path))
        current_section = None
        comp_idx = 0

        for p in doc.paragraphs:
            text = p.text.strip()
            if not text:
                continue

            # Detect section headers
            if "Professional Summary" in text:
                current_section = "summary"
                continue
            elif "Core Competencies" in text:
                current_section = "competencies"
                comp_idx = 0
                continue
            elif any(h in text for h in ["Professional Experience", "Education", "Certifications"]):
                current_section = None
                continue

            # Replace summary
            if current_section == "summary" and new_summary:
                _replace_paragraph_text(p, new_summary)
                current_section = None

            # Replace competencies (preserve bullet format)
            elif current_section == "competencies" and new_competencies and text.startswith("•"):
                if comp_idx < len(new_competencies):
                    _replace_paragraph_text(p, f"• {new_competencies[comp_idx]}")
                    comp_idx += 1

        doc.save(str(output_path))
        logger.info("Saved tailored resume to %s", output_path)
        return output_path

    def tailor_and_save(self, base_resume_path: str | Path,
                         new_summary: str, new_competencies: list[str],
                         company: str, role: str,
                         output_dir: str | Path) -> Path:
        """Clone template and apply tailored content."""
        output_dir = ensure_dir(output_dir)
        # Human-like filename: Danna_Dobi_Resume_ShortTitle.docx
        short_role = role.split(",")[0].split("|")[0].split("—")[0].split("/")[0].strip()[:30]
        filename = sanitize_filename(f"Danna_Dobi_Resume_{short_role}") + ".docx"
        output_path = output_dir / filename
        return self.clone_and_tailor(base_resume_path, output_path, new_summary, new_competencies)


def _replace_paragraph_text(paragraph, new_text: str):
    """Replace paragraph text while preserving formatting of the first run."""
    if not paragraph.runs:
        paragraph.text = new_text
        return
    first_run = paragraph.runs[0]
    for run in paragraph.runs[1:]:
        run.text = ""
    first_run.text = new_text
