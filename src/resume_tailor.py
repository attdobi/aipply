"""Resume tailoring module.

Clones the original .docx resume and surgically modifies text content
using Claude Opus, preserving all original formatting (fonts, sizes,
spacing, bullet styles, headers).
"""

import copy
import json
import logging
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import anthropic
from docx import Document
from dotenv import load_dotenv

from src.utils import ensure_dir, sanitize_filename

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a professional resume tailoring assistant. You will receive a candidate's \
resume content and a job description. Your job is to suggest MINIMAL, TARGETED \
modifications to make the resume more relevant to the specific role.

CRITICAL RULES:
1. NEVER fabricate or invent experience, skills, qualifications, or job titles.
2. Only modify the Professional Summary and Core Competencies sections.
3. For Professional Summary: rewrite to emphasize aspects most relevant to the target role. \
   Keep the same length and tone. Reference specific skills from the JD that the candidate actually has.
4. For Core Competencies: reorder to put the most relevant ones first. You may rephrase \
   slightly to better match JD terminology, but ONLY if the candidate genuinely has that skill.
5. DO NOT modify job titles, company names, dates, education, or certifications.
6. DO NOT modify individual experience bullet points — they stay exactly as-is.

OUTPUT FORMAT (strict JSON):
{
  "professional_summary": "The rewritten professional summary paragraph",
  "core_competencies": ["Competency 1", "Competency 2", ...],
  "tailoring_notes": "Brief explanation of what you changed and why"
}

Return ONLY the JSON object. No markdown, no explanation outside the JSON."""


class ResumeTailor:
    """Tailors a base resume by cloning .docx and modifying key sections with AI."""

    def __init__(self, config: dict[str, Any] | None = None):
        load_dotenv()
        self.config = config or {}
        from openai import OpenAI
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.model = self.config.get("openai", {}).get("model", "gpt-4")

    def _call_ai(self, system: str, user: str) -> str:
        """Call OpenAI for resume tailoring."""
        logger.info("Calling %s for resume tailoring", self.model)
        response = self.client.chat.completions.create(
            model=self.model,
            temperature=0.4,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return response.choices[0].message.content or ""

    def read_resume_sections(self, path: str | Path) -> dict:
        """Read .docx and extract text by section."""
        doc = Document(str(path))
        sections = {
            "name": "",
            "contact": "",
            "summary": "",
            "competencies": [],
            "full_text": "",
        }

        paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
        sections["full_text"] = "\n".join(paragraphs)

        # Parse known sections
        current_section = None
        for p in doc.paragraphs:
            text = p.text.strip()
            if not text:
                continue

            # Detect sections by bold headers
            is_bold_header = any(r.bold for r in p.runs if r.text.strip()) and len(text.split()) <= 5

            if text.isupper() and len(text.split()) <= 5:
                # Name line
                if not sections["name"]:
                    sections["name"] = text
                    current_section = None
                    continue

            if "Professional Summary" in text:
                current_section = "summary"
                continue
            elif "Core Competencies" in text:
                current_section = "competencies"
                continue
            elif is_bold_header or text in ["Professional Experience", "Education", "Certifications"]:
                current_section = None
                continue

            if current_section == "summary":
                sections["summary"] = text
                current_section = None  # Summary is one paragraph
            elif current_section == "competencies":
                comp = text.lstrip("•·- ").strip()
                if comp:
                    sections["competencies"].append(comp)

        return sections

    def get_tailoring_suggestions(self, resume_path: str | Path, job_description: str,
                                   company: str, role: str) -> dict:
        """Get AI suggestions for tailoring (summary + competencies only)."""
        sections = self.read_resume_sections(resume_path)

        user_prompt = (
            f"CANDIDATE RESUME:\n"
            f"Name: {sections['name']}\n"
            f"Current Summary: {sections['summary']}\n"
            f"Current Competencies: {json.dumps(sections['competencies'])}\n\n"
            f"TARGET ROLE: {role} at {company}\n\n"
            f"JOB DESCRIPTION:\n{job_description[:3000]}\n\n"
            f"Please provide tailored Professional Summary and reordered Core Competencies."
        )

        raw = self._call_ai(SYSTEM_PROMPT, user_prompt)

        # Parse JSON from response
        try:
            # Strip markdown code fences if present
            clean = raw.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
                if clean.endswith("```"):
                    clean = clean[:-3]
            return json.loads(clean)
        except json.JSONDecodeError:
            logger.error("Failed to parse AI response as JSON: %s", raw[:200])
            return {"professional_summary": sections["summary"],
                    "core_competencies": sections["competencies"],
                    "tailoring_notes": "AI response was not valid JSON — using original content"}

    def clone_and_tailor(self, base_path: str | Path, suggestions: dict,
                          output_path: str | Path) -> Path:
        """Clone the .docx and surgically replace summary + competencies text."""
        output_path = Path(output_path)
        ensure_dir(output_path.parent)

        # Copy the original file to preserve ALL formatting
        shutil.copy2(str(base_path), str(output_path))

        # Now open the copy and modify only the targeted paragraphs
        doc = Document(str(output_path))

        new_summary = suggestions.get("professional_summary", "")
        new_competencies = suggestions.get("core_competencies", [])

        current_section = None
        comp_idx = 0

        for p in doc.paragraphs:
            text = p.text.strip()
            if not text:
                continue

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

            # Replace summary paragraph — preserve formatting of first run
            if current_section == "summary" and new_summary:
                self._replace_paragraph_text(p, new_summary)
                current_section = None  # Only one summary paragraph

            # Replace competencies — preserve bullet formatting
            elif current_section == "competencies" and text.startswith("•"):
                if comp_idx < len(new_competencies):
                    new_comp = new_competencies[comp_idx]
                    self._replace_paragraph_text(p, f"• {new_comp}")
                    comp_idx += 1

        doc.save(str(output_path))
        logger.info("Saved tailored resume to %s", output_path)
        return output_path

    @staticmethod
    def _replace_paragraph_text(paragraph, new_text: str):
        """Replace paragraph text while preserving the formatting of the first run."""
        if not paragraph.runs:
            paragraph.text = new_text
            return

        # Keep formatting from first run, clear the rest
        first_run = paragraph.runs[0]
        for run in paragraph.runs[1:]:
            run.text = ""
        first_run.text = new_text

    def tailor_and_save(self, base_resume_path: str | Path, job_description: str,
                         company: str, role: str,
                         output_dir: str | Path | None = None) -> Path:
        """Full pipeline: get AI suggestions → clone .docx → apply changes."""
        logger.info("Tailoring resume for %s at %s", role, company)

        suggestions = self.get_tailoring_suggestions(base_resume_path, job_description, company, role)
        logger.info("Tailoring notes: %s", suggestions.get("tailoring_notes", ""))

        if output_dir is None:
            date_str = datetime.now().strftime("%Y%m%d")
            dir_name = sanitize_filename(f"{company}_{role}_{date_str}")
            output_dir = Path("output") / "applications" / dir_name

        output_dir = ensure_dir(output_dir)
        filename = sanitize_filename(f"resume_{company}_{role}") + ".docx"
        output_path = output_dir / filename

        return self.clone_and_tailor(base_resume_path, suggestions, output_path)
