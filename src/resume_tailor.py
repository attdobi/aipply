"""Resume tailoring module.

Uses OpenAI to customize a base resume for each specific
job description, highlighting relevant experience and skills.
"""

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from docx import Document
from dotenv import load_dotenv
from openai import OpenAI

from src.utils import ensure_dir, sanitize_filename

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a professional resume writer. Your task is to tailor an existing resume \
to better match a specific job description.

RULES:
1. NEVER fabricate or invent experience, skills, or qualifications.
2. Only reorganize, reword, and emphasize existing content.
3. Adjust the professional summary to highlight relevance to the target role.
4. Reorder experience bullets to put the most relevant ones first.
5. Naturally integrate keywords from the job description where they truthfully apply.
6. Maintain professional formatting.
7. Output the tailored resume as clean text with clear section headers \
(SUMMARY, EXPERIENCE, EDUCATION, SKILLS, CERTIFICATIONS, etc.).
8. Use dashes (-) for bullet points under each section.
9. Keep the candidate's name as a top-level heading.
"""


class ResumeTailor:
    """Tailors a base resume to match a specific job description using AI."""

    def __init__(self, config: dict[str, Any] | None = None):
        """Initialize tailor with OpenAI configuration.

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
    # Reading
    # ------------------------------------------------------------------

    def read_base_resume(self, path: str | Path) -> str:
        """Read a ``.docx`` resume and return all text.

        Args:
            path: Path to the base resume file.

        Returns:
            Full text content of the resume.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Base resume not found: {path}")

        doc = Document(str(path))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        text = "\n".join(paragraphs)
        logger.info("Read base resume from %s (%d chars)", path, len(text))
        return text

    # ------------------------------------------------------------------
    # Tailoring
    # ------------------------------------------------------------------

    def tailor_resume(
        self,
        base_resume_path: str | Path,
        job_description: str,
        company: str = "",
        role: str = "",
    ) -> str:
        """Generate a tailored resume for a specific job.

        Args:
            base_resume_path: Path to the base ``.docx`` resume.
            job_description: Full text of the job description.
            company: Target company name (for context).
            role: Target role title (for context).

        Returns:
            Tailored resume content as plain text.
        """
        base_text = self.read_base_resume(base_resume_path)

        user_prompt = (
            f"Here is the candidate's current resume:\n\n"
            f"---BEGIN RESUME---\n{base_text}\n---END RESUME---\n\n"
            f"Here is the job description for the role of '{role}' at '{company}':\n\n"
            f"---BEGIN JOB DESCRIPTION---\n{job_description}\n---END JOB DESCRIPTION---\n\n"
            f"Please tailor the resume to better match this job description. "
            f"Remember: do NOT fabricate any experience. Only reorganize and "
            f"emphasize existing content."
        )

        logger.info("Requesting tailored resume from %s (company=%s, role=%s)", self.model, company, role)
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
            logger.info("Received tailored resume (%d chars)", len(content))
            return content.strip()
        except Exception as exc:
            logger.error("OpenAI API call failed: %s", exc)
            raise

    # ------------------------------------------------------------------
    # Saving
    # ------------------------------------------------------------------

    def save_tailored_resume(self, content: str, output_path: str | Path) -> Path:
        """Save tailored resume text to a ``.docx`` file.

        Creates a clean Word document with structured sections parsed
        from the AI output.

        Args:
            content: Tailored resume text (plain text with section headers).
            output_path: Destination ``.docx`` file path.

        Returns:
            :class:`Path` to the saved file.
        """
        output_path = Path(output_path)
        ensure_dir(output_path.parent)

        doc = Document()

        lines = content.split("\n")
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue

            # Detect section headers (ALL CAPS or lines ending with colon)
            if self._is_section_header(stripped):
                doc.add_heading(stripped.rstrip(":"), level=2)
            elif stripped.startswith("- ") or stripped.startswith("• "):
                # Bullet point
                doc.add_paragraph(stripped.lstrip("-•").strip(), style="List Bullet")
            elif self._looks_like_name(stripped, lines):
                # First non-empty line that looks like a name → top heading
                doc.add_heading(stripped, level=1)
            else:
                doc.add_paragraph(stripped)

        doc.save(str(output_path))
        logger.info("Saved tailored resume to %s", output_path)
        return output_path

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    def tailor_and_save(
        self,
        base_resume_path: str | Path,
        job_description: str,
        company: str,
        role: str,
        output_dir: str | Path | None = None,
    ) -> Path:
        """Tailor a resume and save it in one call.

        Args:
            base_resume_path: Path to the base ``.docx`` resume.
            job_description: Full job description text.
            company: Target company name.
            role: Target role title.
            output_dir: Directory to save the output. Defaults to
                        ``output/applications/{company}_{role}_{date}/``.

        Returns:
            :class:`Path` to the saved ``.docx`` file.
        """
        tailored_text = self.tailor_resume(base_resume_path, job_description, company, role)

        if output_dir is None:
            date_str = datetime.now().strftime("%Y%m%d")
            dir_name = sanitize_filename(f"{company}_{role}_{date_str}")
            output_dir = Path("output") / "applications" / dir_name

        output_dir = ensure_dir(output_dir)
        filename = sanitize_filename(f"resume_{company}_{role}") + ".docx"
        output_path = output_dir / filename

        return self.save_tailored_resume(tailored_text, output_path)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_section_header(line: str) -> bool:
        """Heuristic: treat ALL-CAPS lines or short lines ending with ':' as headers."""
        clean = line.rstrip(":")
        if clean.isupper() and len(clean.split()) <= 6:
            return True
        if line.endswith(":") and len(line.split()) <= 5:
            return True
        return False

    @staticmethod
    def _looks_like_name(line: str, all_lines: list[str]) -> bool:
        """Heuristic: first non-empty line with 2-4 title-case words is likely a name."""
        # Only match the very first non-empty line
        for l in all_lines:
            if l.strip():
                if l.strip() == line:
                    words = line.split()
                    return 1 <= len(words) <= 5 and all(w[0].isupper() for w in words if w.isalpha())
                return False
        return False
