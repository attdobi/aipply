"""Tests for cover letter generator module."""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from docx import Document


@pytest.fixture
def mock_openai():
    """Mock the OpenAI client before CoverLetterGenerator is instantiated."""
    with patch("src.cover_letter_gen.OpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        yield mock_client


@pytest.fixture
def cover_gen(mock_openai):
    """Create a CoverLetterGenerator with test config and mocked OpenAI."""
    from src.cover_letter_gen import CoverLetterGenerator

    config = {
        "openai": {
            "model": "gpt-4",
            "temperature": 0.7,
        }
    }
    return CoverLetterGenerator(config=config)


@pytest.fixture
def cover_gen_no_config(mock_openai):
    """Create a CoverLetterGenerator with no config."""
    from src.cover_letter_gen import CoverLetterGenerator

    return CoverLetterGenerator()


@pytest.fixture
def candidate_profile():
    """Sample candidate profile for testing."""
    return {
        "name": "Jane Doe",
        "email": "jane@example.com",
        "location": "San Francisco",
        "summary": "Experienced compliance professional.",
        "strengths": ["Regulatory compliance", "Risk management"],
        "target_roles": ["Compliance Manager", "Risk Analyst"],
    }


class TestCoverLetterGenInit:
    def test_init_with_config(self, cover_gen):
        assert cover_gen.config is not None
        assert "openai" in cover_gen.config
        assert cover_gen.model == "gpt-4"
        assert cover_gen.temperature == 0.7

    def test_init_default_config(self, cover_gen_no_config):
        assert cover_gen_no_config.config == {}
        assert cover_gen_no_config.model == "gpt-4"

    def test_init_none_config(self, mock_openai):
        from src.cover_letter_gen import CoverLetterGenerator

        g = CoverLetterGenerator(config=None)
        assert g.config == {}


class TestGenerate:
    def test_generate_returns_string(self, cover_gen, mock_openai, candidate_profile):
        """generate should return cover letter text."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = (
            "Dear Hiring Manager,\n\n"
            "I am excited about the Compliance Manager position at Acme Corp. "
            "With my background in regulatory compliance and risk management, "
            "I believe I would be a strong fit.\n\n"
            "Sincerely,\nJane Doe"
        )
        mock_openai.chat.completions.create.return_value = mock_response

        result = cover_gen.generate(
            "Seeking a compliance manager with 5 years experience",
            candidate_profile,
            company="Acme Corp",
            role="Compliance Manager",
        )
        assert isinstance(result, str)
        assert "Compliance Manager" in result or "compliance" in result.lower()
        mock_openai.chat.completions.create.assert_called_once()

    def test_generate_with_empty_description(self, cover_gen, mock_openai, candidate_profile):
        """generate should handle empty job description gracefully."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Dear Hiring Manager,\n\nI am interested.\n\nSincerely,\nJane"
        mock_openai.chat.completions.create.return_value = mock_response

        result = cover_gen.generate("", candidate_profile)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_generate_with_empty_profile(self, cover_gen, mock_openai):
        """generate should handle empty candidate profile."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Dear Hiring Manager,\n\nCover letter.\n\nBest regards"
        mock_openai.chat.completions.create.return_value = mock_response

        result = cover_gen.generate("Job description text", {})
        assert isinstance(result, str)

    def test_generate_with_example_letter(self, cover_gen, mock_openai, candidate_profile, tmp_path):
        """generate should incorporate example letter when provided."""
        # Create example letter docx
        doc = Document()
        doc.add_paragraph("Example cover letter with professional tone.")
        example_path = tmp_path / "example.docx"
        doc.save(str(example_path))

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Generated letter matching style."
        mock_openai.chat.completions.create.return_value = mock_response

        result = cover_gen.generate(
            "Job desc", candidate_profile,
            company="Corp", role="Manager",
            example_letter_path=example_path,
        )
        assert isinstance(result, str)
        # Verify the call includes the user prompt (OpenAI was called)
        mock_openai.chat.completions.create.assert_called_once()


class TestSaveCoverLetter:
    def test_save_cover_letter_creates_docx(self, cover_gen, tmp_path):
        """save_cover_letter should create a valid .docx file."""
        output_path = tmp_path / "cover_letter.docx"
        content = "Dear Hiring Manager,\n\nI am writing to apply.\n\nSincerely,\nJane Doe"

        result = cover_gen.save_cover_letter(content, output_path)
        assert result == output_path
        assert output_path.exists()

        doc = Document(str(output_path))
        assert len(doc.paragraphs) >= 1

    def test_save_creates_parent_dirs(self, cover_gen, tmp_path):
        """save_cover_letter should create parent directories."""
        output_path = tmp_path / "subdir" / "deep" / "cover_letter.docx"
        content = "Cover letter content"

        result = cover_gen.save_cover_letter(content, output_path)
        assert output_path.exists()


class TestGenerateAndSave:
    def test_generate_and_save_end_to_end(self, cover_gen, mock_openai, candidate_profile, tmp_path):
        """End-to-end: generate_and_save produces a .docx file."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = (
            "Dear Hiring Manager,\n\n"
            "I am excited about this opportunity.\n\n"
            "Sincerely,\nJane Doe"
        )
        mock_openai.chat.completions.create.return_value = mock_response

        result = cover_gen.generate_and_save(
            job_description="Compliance manager role",
            candidate_profile=candidate_profile,
            company="Acme Corp",
            role="Compliance Manager",
            output_dir=output_dir,
        )
        assert Path(result).exists()
        assert str(result).endswith(".docx")

        doc = Document(str(result))
        assert len(doc.paragraphs) >= 1

    def test_generate_and_save_default_output_dir(self, cover_gen, mock_openai, candidate_profile):
        """generate_and_save should create default output dir when none specified."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Generated letter."
        mock_openai.chat.completions.create.return_value = mock_response

        result = cover_gen.generate_and_save(
            job_description="Job desc",
            candidate_profile=candidate_profile,
            company="TestCo",
            role="Analyst",
        )
        assert Path(result).exists()
        # Clean up
        Path(result).unlink(missing_ok=True)
