"""Tests for the application tracker module."""
import json
import os
import tempfile

import pytest

from src.tracker import ApplicationTracker


@pytest.fixture
def tracker(tmp_path):
    """Create a tracker with a temporary file."""
    tracker_path = tmp_path / "tracker.json"
    return ApplicationTracker(tracker_path=str(tracker_path))


class TestApplicationTracker:
    def test_add_application(self, tracker):
        app = tracker.add_application(
            company="Acme Corp",
            position="Compliance Manager",
            job_url="https://linkedin.com/jobs/123",
            location="San Francisco, CA",
        )
        assert app["id"] == 1
        assert app["company"] == "Acme Corp"
        assert app["status"] == "applied"

    def test_duplicate_check(self, tracker):
        tracker.add_application(
            company="Acme Corp",
            position="Compliance Manager",
            job_url="https://linkedin.com/jobs/123",
        )
        assert tracker.is_already_applied("https://linkedin.com/jobs/123") is True
        assert tracker.is_already_applied("https://linkedin.com/jobs/456") is False

    def test_update_status(self, tracker):
        tracker.add_application(
            company="Acme Corp",
            position="Compliance Manager",
            job_url="https://linkedin.com/jobs/123",
        )
        updated = tracker.update_status(1, "interview", "Phone screen scheduled")
        assert updated["status"] == "interview"
        assert updated["notes"] == "Phone screen scheduled"

    def test_get_applications_filtered(self, tracker):
        tracker.add_application(company="A", position="P1", job_url="u1", status="applied")
        tracker.add_application(company="B", position="P2", job_url="u2", status="interview")
        tracker.add_application(company="C", position="P3", job_url="u3", status="applied")

        applied = tracker.get_applications(status="applied")
        assert len(applied) == 2

        all_apps = tracker.get_applications()
        assert len(all_apps) == 3

    def test_get_stats(self, tracker):
        tracker.add_application(company="A", position="P1", job_url="u1", status="applied")
        tracker.add_application(company="A", position="P2", job_url="u2", status="interview")
        tracker.add_application(company="B", position="P3", job_url="u3", status="applied")

        stats = tracker.get_stats()
        assert stats["total"] == 3
        assert stats["by_status"]["applied"] == 2
        assert stats["by_company"]["A"] == 2

    def test_generate_html_report(self, tracker, tmp_path):
        tracker.add_application(
            company="Test Corp",
            position="Risk Analyst",
            job_url="https://linkedin.com/jobs/789",
            location="Remote",
        )

        report_path = str(tmp_path / "report.html")
        result = tracker.generate_html_report(output_path=report_path)

        assert os.path.exists(result)
        with open(result) as f:
            content = f.read()
        assert "Test Corp" in content
        assert "Risk Analyst" in content

    def test_persistence(self, tmp_path):
        tracker_path = str(tmp_path / "tracker.json")

        t1 = ApplicationTracker(tracker_path=tracker_path)
        t1.add_application(company="A", position="P1", job_url="u1")

        t2 = ApplicationTracker(tracker_path=tracker_path)
        assert len(t2.applications) == 1
        assert t2.applications[0]["company"] == "A"
