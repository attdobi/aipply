"""Cover letter generation module.

Creates a clean .docx cover letter matching the template's tone and formatting.
No API calls — the caller provides the letter text directly.
"""

import logging
import os
from pathlib import Path
from typing import Any

from docx import Document
from docx.shared import Pt, Inches

from src.utils import ensure_dir, sanitize_filename

logger = logging.getLogger(__name__)


class CoverLetterGenerator:
    """Generates a .docx cover letter from provided text."""

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}

    @staticmethod
    def read_example(path: str | Path = "templates/base_cover_letter.docx") -> str:
        """Read the example cover letter for reference."""
        path = Path(path)
        if not path.exists():
            return ""
        doc = Document(str(path))
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())

    @staticmethod
    def save_cover_letter(text: str, candidate_name: str, candidate_email: str,
                           candidate_phone: str, output_path: str | Path) -> Path:
        """Save cover letter text as a professionally formatted .docx."""
        output_path = Path(output_path)
        ensure_dir(output_path.parent)

        doc = Document()

        # Match template formatting
        style = doc.styles['Normal']
        style.font.name = 'Calibri'
        style.font.size = Pt(11)

        for section in doc.sections:
            section.top_margin = Inches(1)
            section.bottom_margin = Inches(1)
            section.left_margin = Inches(1)
            section.right_margin = Inches(1)

        # Split text into paragraphs and write
        paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
        for para_text in paragraphs:
            p = doc.add_paragraph(para_text)
            p.space_after = Pt(6)

        # Signature block
        p = doc.add_paragraph()
        p.space_before = Pt(6)
        p.add_run(candidate_name).bold = True

        contact = " | ".join(x for x in [candidate_email, candidate_phone] if x)
        if contact:
            doc.add_paragraph(contact)

        doc.save(str(output_path))
        logger.info("Saved cover letter to %s", output_path)
        return output_path

    def generate_and_save(self, text: str, candidate_profile: dict,
                           company: str, role: str,
                           output_dir: str | Path) -> Path:
        """Save a cover letter .docx."""
        output_dir = ensure_dir(output_dir)
        filename = sanitize_filename(f"cover_letter_{company}_{role}") + ".docx"
        output_path = output_dir / filename

        return self.save_cover_letter(
            text=text,
            candidate_name=candidate_profile.get("name", ""),
            candidate_email=candidate_profile.get("email", ""),
            candidate_phone=candidate_profile.get("phone", ""),
            output_path=output_path,
        )
