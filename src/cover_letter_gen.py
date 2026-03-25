"""Cover letter generation module.

Uses Claude Opus to generate company-specific cover letters,
then writes them as clean .docx files matching the candidate's style.
"""

import json
import logging
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import anthropic
from docx import Document
from docx.shared import Pt, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from dotenv import load_dotenv

from src.utils import ensure_dir, sanitize_filename

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a professional cover letter writer. Write a concise, compelling cover \
letter for a specific job application. Match the candidate's voice — direct, \
confident, no fluff. The letter should:

1. Be 3-4 paragraphs max (opening, experience match, why this company, closing).
2. Reference SPECIFIC experience from the candidate's background that matches the role.
3. Mention the company by name and show you understand what they do.
4. Sound like a real person, not a template. No generic phrases like "I am excited to apply."
5. Keep it under 350 words.
6. Do NOT fabricate experience or qualifications.

OUTPUT FORMAT (strict JSON):
{
  "greeting": "Dear Hiring Team,",
  "body_paragraphs": ["paragraph 1", "paragraph 2", "paragraph 3"],
  "closing": "Thank you for your time,",
  "notes": "Brief explanation of approach"
}

Return ONLY the JSON object."""


class CoverLetterGenerator:
    """Generates company-specific cover letters using AI."""

    def __init__(self, config: dict[str, Any] | None = None):
        load_dotenv()
        self.config = config or {}
        from openai import OpenAI
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.model = self.config.get("openai", {}).get("model", "gpt-4")

    def _call_ai(self, system: str, user: str) -> str:
        logger.info("Calling %s for cover letter", self.model)
        response = self.client.chat.completions.create(
            model=self.model,
            temperature=0.5,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return response.choices[0].message.content or ""

    def generate(self, job_description: str, candidate_profile: dict,
                 company: str, role: str) -> dict:
        """Generate cover letter content via AI."""
        # Build candidate context from profile
        name = candidate_profile.get("name", "")
        email = candidate_profile.get("email", "")
        phone = candidate_profile.get("phone", "")
        summary = candidate_profile.get("summary", "")
        strengths = candidate_profile.get("strengths", [])

            # Read the example cover letter for tone reference
        example_text = ""
        example_path = Path("templates/base_cover_letter.docx")
        if example_path.exists():
            try:
                from docx import Document as DocxDoc
                edoc = DocxDoc(str(example_path))
                example_text = "\n".join(p.text for p in edoc.paragraphs if p.text.strip())
            except Exception:
                pass

        user_prompt = (
            f"CANDIDATE:\n"
            f"Name: {name}\n"
            f"Email: {email}\n"
            f"Phone: {phone}\n"
            f"Summary: {summary}\n"
            f"Key strengths: {', '.join(strengths)}\n\n"
        )
        if example_text:
            user_prompt += (
                f"EXAMPLE COVER LETTER (match this tone and style):\n"
                f"{example_text}\n\n"
            )
        user_prompt += (
            f"TARGET: {role} at {company}\n\n"
            f"JOB DESCRIPTION:\n{job_description[:3000]}\n\n"
            f"Write a tailored cover letter. ONLY reference the candidate's ACTUAL experience "
            f"listed above and in the example letter. NEVER invent companies, roles, or experience. "
            f"The candidate worked at: OCC (federal bank examiner), Prime Trust, Cross River Bank, and PG&E (current)."
        )

        raw = self._call_ai(SYSTEM_PROMPT, user_prompt)

        try:
            clean = raw.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
                if clean.endswith("```"):
                    clean = clean[:-3]
            result = json.loads(clean)
            result.setdefault("greeting", "Dear Hiring Team,")
            result.setdefault("closing", "Thank you for your time,")
            return result
        except json.JSONDecodeError:
            logger.error("Failed to parse cover letter JSON: %s", raw[:200])
            return {
                "greeting": "Dear Hiring Team,",
                "body_paragraphs": [raw.strip()],
                "closing": f"Thank you for your time,\n{name}\n{email}" + (f" | {phone}" if phone else ""),
                "notes": "AI response was not JSON — used raw text",
            }

    def save_cover_letter(self, content: dict, candidate_profile: dict,
                           output_path: str | Path) -> Path:
        """Save cover letter as a professionally formatted .docx."""
        output_path = Path(output_path)
        ensure_dir(output_path.parent)

        doc = Document()

        # Set default font
        style = doc.styles['Normal']
        font = style.font
        font.name = 'Calibri'
        font.size = Pt(11)

        # Set margins
        for section in doc.sections:
            section.top_margin = Inches(1)
            section.bottom_margin = Inches(1)
            section.left_margin = Inches(1)
            section.right_margin = Inches(1)

        # Greeting
        greeting = content.get("greeting", "Dear Hiring Team,")
        p = doc.add_paragraph(greeting)
        p.space_after = Pt(6)

        # Body paragraphs
        for para_text in content.get("body_paragraphs", []):
            p = doc.add_paragraph(para_text)
            p.space_after = Pt(6)

        # Closing
        closing = content.get("closing", "Thank you for your time,")
        p = doc.add_paragraph()
        p.space_before = Pt(12)
        p.add_run(closing)

        # Signature
        name = candidate_profile.get("name", "")
        email = candidate_profile.get("email", "")
        phone = candidate_profile.get("phone", "")
        if name:
            p = doc.add_paragraph()
            p.add_run(name).bold = True
        contact_parts = [x for x in [email, phone] if x]
        if contact_parts:
            doc.add_paragraph(" | ".join(contact_parts))

        doc.save(str(output_path))
        logger.info("Saved cover letter to %s", output_path)
        return output_path

    def generate_and_save(self, job_description: str, candidate_profile: dict,
                           company: str, role: str,
                           output_dir: str | Path | None = None) -> Path:
        """Generate and save in one call."""
        logger.info("Generating cover letter for %s at %s", role, company)
        content = self.generate(job_description, candidate_profile, company, role)
        logger.info("Cover letter notes: %s", content.get("notes", ""))

        if output_dir is None:
            date_str = datetime.now().strftime("%Y%m%d")
            dir_name = sanitize_filename(f"{company}_{role}_{date_str}")
            output_dir = Path("output") / "applications" / dir_name

        output_dir = ensure_dir(output_dir)
        filename = sanitize_filename(f"cover_letter_{company}_{role}") + ".docx"
        output_path = output_dir / filename

        return self.save_cover_letter(content, candidate_profile, output_path)
