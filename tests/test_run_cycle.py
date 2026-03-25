"""Tests for run_cycle script."""

import sys
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, ANY
from datetime import datetime

# Ensure project root is on path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_cycle import parse_args, run_cycle, setup_logging


class TestParseArgs:
    def test_defaults(self):
        args = parse_args([])
        assert args.dry_run is False
        assert args.limit is None
        assert args.report_only is False
        assert args.verbose is False
        assert args.cdp_url is None

    def test_dry_run(self):
        args = parse_args(["--dry-run"])
        assert args.dry_run is True

    def test_limit(self):
        args = parse_args(["--limit", "5"])
        assert args.limit == 5

    def test_report_only(self):
        args = parse_args(["--report-only"])
        assert args.report_only is True

    def test_verbose(self):
        args = parse_args(["-v"])
        assert args.verbose is True
        args2 = parse_args(["--verbose"])
        assert args2.verbose is True

    def test_cdp_url(self):
        args = parse_args(["--cdp-url", "http://localhost:9222"])
        assert args.cdp_url == "http://localhost:9222"

    def test_combined_flags(self):
        args = parse_args(["--dry-run", "--limit", "3", "-v"])
        assert args.dry_run is True
        assert args.limit == 3
        assert args.verbose is True


class TestSetupLogging:
    def test_setup_logging_does_not_raise(self, tmp_path):
        """setup_logging should not raise."""
        with patch("scripts.run_cycle.PROJECT_ROOT", tmp_path):
            (tmp_path / "output").mkdir(exist_ok=True)
            # Just verify it doesn't throw
            setup_logging(verbose=False)
            setup_logging(verbose=True)


class TestRunCycleReportOnly:
    def test_report_only_generates_report(self, tmp_path):
        """--report-only should call generate_html_report and return."""
        args = parse_args(["--report-only"])

        mock_tracker = MagicMock()
        mock_tracker.generate_html_report.return_value = str(
            tmp_path / "report.html"
        )

        with patch("scripts.run_cycle.PROJECT_ROOT", tmp_path), \
             patch("scripts.run_cycle.load_config", return_value={}), \
             patch("scripts.run_cycle.ApplicationTracker", return_value=mock_tracker), \
             patch("scripts.run_cycle.setup_logging"):
            # Create required directories
            (tmp_path / "config").mkdir(exist_ok=True)
            (tmp_path / "output").mkdir(exist_ok=True)
            (tmp_path / "output" / "reports").mkdir(parents=True, exist_ok=True)

            run_cycle(args=args)
            mock_tracker.generate_html_report.assert_called_once()


class TestRunCycleFullFlow:
    @pytest.fixture
    def mock_settings(self):
        return {
            "search": {
                "keywords": ["compliance"],
                "locations": ["Remote"],
            },
            "exclusions": {"companies": []},
            "application": {"max_applications_per_cycle": 5},
            "openai": {"model": "gpt-4"},
        }

    @pytest.fixture
    def mock_profile(self):
        return {
            "candidate": {
                "name": "Jane Doe",
                "email": "jane@example.com",
            }
        }

    @pytest.fixture
    def fake_jobs(self):
        return [
            {
                "title": "Compliance Manager",
                "company": "Acme Corp",
                "url": "https://linkedin.com/jobs/1",
                "location": "Remote",
                "description": "Great compliance role",
            },
            {
                "title": "Risk Analyst",
                "company": "Beta Inc",
                "url": "https://linkedin.com/jobs/2",
                "location": "San Francisco",
                "description": "Risk analysis position",
            },
        ]

    def test_full_cycle_with_mocks(
        self, tmp_path, mock_settings, mock_profile, fake_jobs
    ):
        """Full cycle: scanner returns jobs, tailor/cover_gen produce paths, applicant applies."""
        args = parse_args(["--limit", "2"])

        # Setup directory structure
        (tmp_path / "config").mkdir(exist_ok=True)
        (tmp_path / "output").mkdir(exist_ok=True)
        (tmp_path / "output" / "reports").mkdir(parents=True, exist_ok=True)
        (tmp_path / "output" / "applications").mkdir(parents=True, exist_ok=True)
        (tmp_path / "templates").mkdir(exist_ok=True)
        (tmp_path / "templates" / "base_resume.docx").touch()
        (tmp_path / "templates" / "base_cover_letter.docx").touch()

        mock_scanner = MagicMock()
        mock_scanner.search_jobs.return_value = fake_jobs
        mock_scanner.filter_results.return_value = fake_jobs
        mock_scanner.get_job_details.side_effect = lambda url: next(
            (j for j in fake_jobs if j["url"] == url), fake_jobs[0]
        )

        mock_tailor = MagicMock()
        mock_tailor.tailor_and_save.return_value = tmp_path / "resume.docx"

        mock_cover_gen = MagicMock()
        mock_cover_gen.generate_and_save.return_value = tmp_path / "cover.docx"

        mock_applicant = MagicMock()
        mock_applicant.apply_to_job.return_value = {
            "status": "applied",
            "reason": "easy_apply_submitted",
            "screenshot_path": "",
        }

        mock_tracker = MagicMock()
        mock_tracker.is_already_applied.return_value = False
        mock_tracker.generate_html_report.return_value = str(
            tmp_path / "report.html"
        )

        def load_config_side_effect(path):
            path_str = str(path)
            if "settings" in path_str:
                return mock_settings
            elif "profile" in path_str:
                return mock_profile
            return {}

        with patch("scripts.run_cycle.PROJECT_ROOT", tmp_path), \
             patch("scripts.run_cycle.load_config", side_effect=load_config_side_effect), \
             patch("scripts.run_cycle.LinkedInScanner", return_value=mock_scanner), \
             patch("scripts.run_cycle.ResumeTailor", return_value=mock_tailor), \
             patch("scripts.run_cycle.CoverLetterGenerator", return_value=mock_cover_gen), \
             patch("scripts.run_cycle.LinkedInApplicant", return_value=mock_applicant), \
             patch("scripts.run_cycle.ApplicationTracker", return_value=mock_tracker), \
             patch("scripts.run_cycle.setup_logging"):

            run_cycle(args=args)

        # Verify scanner was used
        mock_scanner.connect_browser.assert_called_once()
        mock_scanner.search_jobs.assert_called()
        mock_scanner.filter_results.assert_called()

        # Verify applicant was used
        mock_applicant.connect_browser.assert_called_once()
        assert mock_applicant.apply_to_job.call_count == 2

        # Verify tracker recorded applications
        assert mock_tracker.add_application.call_count == 2

        # Verify report was generated
        mock_tracker.generate_html_report.assert_called_once()

        # Verify cleanup
        mock_scanner.close.assert_called_once()
        mock_applicant.close.assert_called_once()

    def test_cycle_continues_on_job_failure(
        self, tmp_path, mock_settings, mock_profile, fake_jobs
    ):
        """Cycle should continue processing when one job fails."""
        args = parse_args(["--limit", "2"])

        (tmp_path / "config").mkdir(exist_ok=True)
        (tmp_path / "output").mkdir(exist_ok=True)
        (tmp_path / "output" / "reports").mkdir(parents=True, exist_ok=True)
        (tmp_path / "output" / "applications").mkdir(parents=True, exist_ok=True)
        (tmp_path / "templates").mkdir(exist_ok=True)
        (tmp_path / "templates" / "base_resume.docx").touch()
        (tmp_path / "templates" / "base_cover_letter.docx").touch()

        mock_scanner = MagicMock()
        mock_scanner.search_jobs.return_value = fake_jobs
        mock_scanner.filter_results.return_value = fake_jobs
        mock_scanner.get_job_details.side_effect = lambda url: next(
            (j for j in fake_jobs if j["url"] == url), fake_jobs[0]
        )

        mock_tailor = MagicMock()
        # First call raises, second succeeds
        mock_tailor.tailor_and_save.side_effect = [
            Exception("OpenAI API error"),
            tmp_path / "resume.docx",
        ]

        mock_cover_gen = MagicMock()
        mock_cover_gen.generate_and_save.return_value = tmp_path / "cover.docx"

        mock_applicant = MagicMock()
        mock_applicant.apply_to_job.return_value = {
            "status": "applied",
            "reason": "success",
            "screenshot_path": "",
        }

        mock_tracker = MagicMock()
        mock_tracker.is_already_applied.return_value = False
        mock_tracker.generate_html_report.return_value = str(
            tmp_path / "report.html"
        )

        def load_config_side_effect(path):
            path_str = str(path)
            if "settings" in path_str:
                return mock_settings
            elif "profile" in path_str:
                return mock_profile
            return {}

        with patch("scripts.run_cycle.PROJECT_ROOT", tmp_path), \
             patch("scripts.run_cycle.load_config", side_effect=load_config_side_effect), \
             patch("scripts.run_cycle.LinkedInScanner", return_value=mock_scanner), \
             patch("scripts.run_cycle.ResumeTailor", return_value=mock_tailor), \
             patch("scripts.run_cycle.CoverLetterGenerator", return_value=mock_cover_gen), \
             patch("scripts.run_cycle.LinkedInApplicant", return_value=mock_applicant), \
             patch("scripts.run_cycle.ApplicationTracker", return_value=mock_tracker), \
             patch("scripts.run_cycle.setup_logging"):

            run_cycle(args=args)

        # Both jobs should have been tracked (one failed, one succeeded)
        assert mock_tracker.add_application.call_count == 2

        # First call should record failure
        first_call_kwargs = mock_tracker.add_application.call_args_list[0]
        assert first_call_kwargs[1].get("status") == "failed" or \
               (len(first_call_kwargs[0]) > 0 and "failed" in str(first_call_kwargs))

    def test_dry_run_skips_application(
        self, tmp_path, mock_settings, mock_profile, fake_jobs
    ):
        """Dry run should scan but not apply."""
        args = parse_args(["--dry-run", "--limit", "1"])

        (tmp_path / "config").mkdir(exist_ok=True)
        (tmp_path / "output").mkdir(exist_ok=True)
        (tmp_path / "output" / "reports").mkdir(parents=True, exist_ok=True)
        (tmp_path / "output" / "applications").mkdir(parents=True, exist_ok=True)
        (tmp_path / "templates").mkdir(exist_ok=True)
        (tmp_path / "templates" / "base_resume.docx").touch()
        (tmp_path / "templates" / "base_cover_letter.docx").touch()

        mock_scanner = MagicMock()
        mock_scanner.search_jobs.return_value = fake_jobs[:1]
        mock_scanner.filter_results.return_value = fake_jobs[:1]
        mock_scanner.get_job_details.return_value = fake_jobs[0]

        mock_tailor = MagicMock()
        mock_tailor.tailor_and_save.return_value = tmp_path / "resume.docx"

        mock_cover_gen = MagicMock()
        mock_cover_gen.generate_and_save.return_value = tmp_path / "cover.docx"

        mock_tracker = MagicMock()
        mock_tracker.is_already_applied.return_value = False
        mock_tracker.generate_html_report.return_value = str(
            tmp_path / "report.html"
        )

        def load_config_side_effect(path):
            path_str = str(path)
            if "settings" in path_str:
                return mock_settings
            elif "profile" in path_str:
                return mock_profile
            return {}

        with patch("scripts.run_cycle.PROJECT_ROOT", tmp_path), \
             patch("scripts.run_cycle.load_config", side_effect=load_config_side_effect), \
             patch("scripts.run_cycle.LinkedInScanner", return_value=mock_scanner), \
             patch("scripts.run_cycle.ResumeTailor", return_value=mock_tailor), \
             patch("scripts.run_cycle.CoverLetterGenerator", return_value=mock_cover_gen), \
             patch("scripts.run_cycle.LinkedInApplicant") as MockApplicantClass, \
             patch("scripts.run_cycle.ApplicationTracker", return_value=mock_tracker), \
             patch("scripts.run_cycle.setup_logging"):

            run_cycle(args=args)

        # LinkedInApplicant should NOT have been instantiated in dry-run mode
        MockApplicantClass.assert_not_called()

        # Tracker should still record the dry run
        mock_tracker.add_application.assert_called_once()
        call_kwargs = mock_tracker.add_application.call_args[1]
        assert call_kwargs["status"] == "dry_run"
