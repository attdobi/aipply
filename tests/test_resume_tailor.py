"""Tests for resume tailor module."""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from docx import Document


@pytest.fixture
def mock_openai():
    """Mock the OpenAI client before ResumeTailor is instantiated."""
    with patch("src.resume_tailor.OpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        yield mock_client


@pytest.fixture
def tailor(mock_openai):
    """Create a ResumeTailor with test config and mocked OpenAI."""
    from src.resume_tailor import ResumeTailor

    config = {
        "openai": {
            "model": "gpt-4",
            "temperature": 0.7,
        }
    }
    return ResumeTailor(config=config)


@pytest.fixture
def tailor_no_config(mock_openai):
    """Create a ResumeTailor with no config."""
    from src.resume_tailor import ResumeTailor

    return ResumeTailor()


class TestResumeTailorInit:
    def test_init_with_config(self, tailor):
        assert tailor.config is not None
        assert "openai" in tailor.config
        assert tailor.model == "gpt-4"
        assert tailor.temperature == 0.7

    def test_init_default_config(self, tailor_no_config):
        assert tailor_no_config.config == {}
        # Should use default model
        assert tailor_no_config.model == "gpt-4"

    def test_init_none_config(self, mock_openai):
        from src.resume_tailor import ResumeTailor

        t = ResumeTailor(config=None)
        assert t.config == {}


class TestReadBaseResume:
    def test_read_base_resume_docx(self, tailor, tmp_path):
        """Test that a .docx file can be read and returns text."""
        doc = Document()
        doc.add_paragraph("Test resume content for compliance manager.")
        doc.add_paragraph("Experience in regulatory oversight.")
        docx_path = tmp_path / "test_resume.docx"
        doc.save(str(docx_path))

        text = tailor.read_base_resume(docx_path)
        assert isinstance(text, str)
        assert "compliance" in text.lower()
        assert "regulatory" in text.lower()

    def test_read_base_resume_file_not_found(self, tailor, tmp_path):
        """Should raise FileNotFoundError for missing file."""
        with pytest.raises(FileNotFoundError):
            tailor.read_base_resume(tmp_path / "nonexistent.docx")


class TestTailorResume:
    def test_tailor_resume_returns_string(self, tailor, mock_openai, tmp_path):
        """tailor_resume should return tailored string content."""
        # Create a base resume docx
        doc = Document()
        doc.add_paragraph("Jane Doe - Compliance Professional")
        base_path = tmp_path / "resume.docx"
        doc.save(str(base_path))

        # Mock OpenAI response
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = (
            "JANE DOE\n\nSUMMARY\nExperienced compliance professional.\n\n"
            "EXPERIENCE\n- Led regulatory compliance team"
        )
        mock_openai.chat.completions.create.return_value = mock_response

        result = tailor.tailor_resume(base_path, "Compliance manager role", "Acme", "Manager")
        assert isinstance(result, str)
        assert "JANE DOE" in result

    def test_tailor_resume_calls_openai(self, tailor, mock_openai, tmp_path):
        """tailor_resume should call OpenAI chat completions."""
        doc = Document()
        doc.add_paragraph("Resume content")
        base_path = tmp_path / "resume.docx"
        doc.save(str(base_path))

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Tailored content"
        mock_openai.chat.completions.create.return_value = mock_response

        tailor.tailor_resume(base_path, "Job desc")
        mock_openai.chat.completions.create.assert_called_once()


class TestSaveTailoredResume:
    def test_save_tailored_resume_creates_docx(self, tailor, tmp_path):
        """save_tailored_resume should create a valid .docx file."""
        output_path = tmp_path / "tailored_resume.docx"
        content = "JANE DOE\n\nSUMMARY\nCompliance professional.\n\n- Risk management\n- Audit oversight"

        result = tailor.save_tailored_resume(content, output_path)
        assert result == output_path
        assert output_path.exists()

        doc = Document(str(output_path))
        assert len(doc.paragraphs) >= 1

    def test_save_creates_parent_dirs(self, tailor, tmp_path):
        """save_tailored_resume should create parent directories."""
        output_path = tmp_path / "sub" / "dir" / "resume.docx"
        content = "Resume content"

        result = tailor.save_tailored_resume(content, output_path)
        assert output_path.exists()


class TestTailorAndSave:
    def test_tailor_and_save_end_to_end(self, tailor, mock_openai, tmp_path):
        """End-to-end test: tailor_and_save produces a .docx file."""
        # Create base resume
        doc = Document()
        doc.add_paragraph("Base resume content for compliance role")
        base_path = tmp_path / "base_resume.docx"
        doc.save(str(base_path))

        output_dir = tmp_path / "output"
        output_dir.mkdir()

        # Mock OpenAI response
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = (
            "Jane Doe\n\nSUMMARY\nTailored for compliance role at Acme."
        )
        mock_openai.chat.completions.create.return_value = mock_response

        result = tailor.tailor_and_save(
            base_resume_path=base_path,
            job_description="Compliance manager needed",
            company="Acme",
            role="Compliance Manager",
            output_dir=output_dir,
        )
        assert Path(result).exists()
        assert str(result).endswith(".docx")

        # Verify it's a valid docx
        doc2 = Document(str(result))
        assert len(doc2.paragraphs) >= 1
