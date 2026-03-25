"""Cover letter generation module.

Uses OpenAI to generate a targeted cover letter for each job
based on the job description and candidate profile.
"""

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from docx import Document
from docx.shared import Pt, Inches
from dotenv import load_dotenv
from openai import OpenAI

from src.utils import ensure_dir, sanitize_filename

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a professional cover letter writer. Your task is to generate a \
compelling, genuine cover letter for a specific job application.

RULES:
1. Keep it concise — 3 to 4 paragraphs maximum.
2. Reference specific requirements from the job description and explain \
how the candidate meets them.
3. Use the candidate's actual strengths and experience — never fabricate.
4. Match the candidate's writing style if an example letter is provided.
5. Be genuine and specific, not generic. Avoid clichés like "I am writing \
to express my interest…" — start with something engaging.
6. Close with a confident but not arrogant call to action.
7. Output ONLY the letter body (no headers, addresses, or "Dear …" / \
"Sincerely," — those will be added by the formatting step). Actually, \
DO include the salutation ("Dear Hiring Manager,") and sign-off \
("Sincerely, {name}").
"""


class CoverLetterGenerator:
    """Generates tailored cover letters using AI."""

    def __init__(self, config: dict[str, Any] | None = None):
        """Initialize generator with OpenAI configuration.

        Args:
            config: Full settings dict (expects ``openai`` sub-key).
        """
        load_dotenv()
        self.config = config or {}
        openai_config = self.config.get("openai", {})
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.model: str = openai_config.get("model", "gpt-4")
        self.temperature: float = openai_config.get("temperature", 0.7)

    # ------------------------------------------------------------------
    # Reading example letter
    # ------------------------------------------------------------------

    def read_example_cover_letter(self, path: str | Path) -> str:
        """Read a ``.docx`` example cover letter for tone/style reference.

        Args:
            path: Path to the example letter file.

        Returns:
            Full text content of the example letter.
        """
        path = Path(path)
        if not path.exists():
            logger.warning("Example cover letter not found at %s — skipping", path)
            return ""

        doc = Document(str(path))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        text = "\n".join(paragraphs)
        logger.info("Read example cover letter from %s (%d chars)", path, len(text))
        return text

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------

    def generate(
        self,
        job_description: str,
        candidate_profile: dict[str, Any],
        company: str = "",
        role: str = "",
        example_letter_path: str | Path | None = None,
    ) -> str:
        """Generate a cover letter for a specific job.

        Args:
            job_description: Full text of the job description.
            candidate_profile: Candidate info dict from ``config/profile.yaml``
                               (expects keys: ``name``, ``email``, ``summary``,
                               ``strengths``, ``target_roles``).
            company: Target company name.
            role: Target role title.
            example_letter_path: Optional path to an example ``.docx`` letter
                                 to match tone/style.

        Returns:
            Generated cover letter text.
        """
        # Build context from candidate profile
        name = candidate_profile.get("name", "")
        summary = candidate_profile.get("summary", "")
        strengths = candidate_profile.get("strengths", [])
        target_roles = candidate_profile.get("target_roles", [])
        email = candidate_profile.get("email", "")
        location = candidate_profile.get("location", "")

        strengths_str = ", ".join(strengths) if strengths else "N/A"
        target_str = ", ".join(target_roles) if target_roles else "N/A"

        # Optionally incorporate example letter style
        style_context = ""
        if example_letter_path:
            example_text = self.read_example_cover_letter(example_letter_path)
            if example_text:
                style_context = (
                    f"\n\nHere is an example of the candidate's writing style "
                    f"(match this tone and voice):\n\n"
                    f"---BEGIN EXAMPLE---\n{example_text}\n---END EXAMPLE---"
                )

        user_prompt = (
            f"Generate a cover letter for the following application:\n\n"
            f"**Role:** {role}\n"
            f"**Company:** {company}\n\n"
            f"**Candidate:**\n"
            f"- Name: {name}\n"
            f"- Email: {email}\n"
            f"- Location: {location}\n"
            f"- Summary: {summary}\n"
            f"- Key Strengths: {strengths_str}\n"
            f"- Target Roles: {target_str}\n\n"
            f"**Job Description:**\n\n"
            f"---BEGIN JOB DESCRIPTION---\n{job_description}\n---END JOB DESCRIPTION---"
            f"{style_context}"
        )

        logger.info("Requesting cover letter from %s (company=%s, role=%s)", self.model, company, role)
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                temperature=self.temperature,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
            )
            content = response.choices[0].message.content or ""
            logger.info("Received cover letter (%d chars)", len(content))
            return content.strip()
        except Exception as exc:
            logger.error("OpenAI API call failed: %s", exc)
            raise

    # ------------------------------------------------------------------
    # Saving
    # ------------------------------------------------------------------

    def save_cover_letter(self, content: str, output_path: str | Path) -> Path:
        """Save a cover letter to a ``.docx`` file with clean formatting.

        Args:
            content: Cover letter text.
            output_path: Destination ``.docx`` file path.

        Returns:
            :class:`Path` to the saved file.
        """
        output_path = Path(output_path)
        ensure_dir(output_path.parent)

        doc = Document()

        # Set default font
        style = doc.styles["Normal"]
        font = style.font
        font.name = "Calibri"
        font.size = Pt(11)

        # Set margins
        for section in doc.sections:
            section.top_margin = Inches(1)
            section.bottom_margin = Inches(1)
            section.left_margin = Inches(1)
            section.right_margin = Inches(1)

        # Add date
        doc.add_paragraph(datetime.now().strftime("%B %d, %Y"))
        doc.add_paragraph("")  # blank line

        # Add letter body
        paragraphs = content.split("\n\n")
        for para_text in paragraphs:
            cleaned = para_text.strip()
            if cleaned:
                doc.add_paragraph(cleaned)

        doc.save(str(output_path))
        logger.info("Saved cover letter to %s", output_path)
        return output_path

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    def generate_and_save(
        self,
        job_description: str,
        candidate_profile: dict[str, Any],
        company: str,
        role: str,
        output_dir: str | Path | None = None,
        example_letter_path: str | Path | None = None,
    ) -> Path:
        """Generate a cover letter and save it in one call.

        Args:
            job_description: Full job description text.
            candidate_profile: Candidate profile dict.
            company: Target company name.
            role: Target role title.
            output_dir: Directory to save the output. Defaults to
                        ``output/applications/{company}_{role}_{date}/``.
            example_letter_path: Optional example letter for tone matching.

        Returns:
            :class:`Path` to the saved ``.docx`` file.
        """
        letter_text = self.generate(
            job_description=job_description,
            candidate_profile=candidate_profile,
            company=company,
            role=role,
            example_letter_path=example_letter_path,
        )

        if output_dir is None:
            date_str = datetime.now().strftime("%Y%m%d")
            dir_name = sanitize_filename(f"{company}_{role}_{date_str}")
            output_dir = Path("output") / "applications" / dir_name

        output_dir = ensure_dir(output_dir)
        filename = sanitize_filename(f"cover_letter_{company}_{role}") + ".docx"
        output_path = output_dir / filename

        return self.save_cover_letter(letter_text, output_path)
