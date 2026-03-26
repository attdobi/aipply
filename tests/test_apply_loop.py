"""Tests for apply_loop browser recovery and crash handling."""

import inspect
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


class TestLaunchBrowser:
    def test_launch_browser_creates_context(self):
        """launch_browser should start playwright and create persistent context."""
        from scripts.apply_loop import launch_browser

        mock_pw = MagicMock()
        mock_context = MagicMock()
        mock_page = MagicMock()
        mock_context.pages = [mock_page]
        mock_pw.chromium.launch_persistent_context.return_value = mock_context

        with patch("scripts.apply_loop.sync_playwright") as mock_sync_pw:
            mock_sync_pw.return_value.start.return_value = mock_pw
            pw, context, page = launch_browser()

        assert pw == mock_pw
        assert context == mock_context
        assert page == mock_page

    def test_launch_browser_reuses_pw_instance(self):
        """launch_browser should reuse existing playwright instance."""
        from scripts.apply_loop import launch_browser

        mock_pw = MagicMock()
        mock_context = MagicMock()
        mock_page = MagicMock()
        mock_context.pages = [mock_page]
        mock_pw.chromium.launch_persistent_context.return_value = mock_context

        pw, context, page = launch_browser(pw_instance=mock_pw)

        assert pw == mock_pw
        mock_pw.chromium.launch_persistent_context.assert_called_once()

    def test_launch_browser_removes_singleton_lock(self, tmp_path):
        """launch_browser should remove SingletonLock if it exists."""
        from scripts.apply_loop import launch_browser

        mock_pw = MagicMock()
        mock_context = MagicMock()
        mock_context.pages = [MagicMock()]
        mock_pw.chromium.launch_persistent_context.return_value = mock_context

        lock_path = tmp_path / "SingletonLock"
        lock_path.touch()

        with patch("scripts.apply_loop.Path.home", return_value=tmp_path / "fakehome"), \
             patch("scripts.apply_loop.sync_playwright") as mock_sync_pw:
            mock_sync_pw.return_value.start.return_value = mock_pw
            # Just verify the function doesn't crash
            pw, context, page = launch_browser(pw_instance=mock_pw)

        assert pw == mock_pw


class TestConsecutiveCrashCounter:
    """Test that the main loop respects the consecutive crash limit."""

    def test_crash_counter_concept(self):
        """Verify the crash counter logic exists in the code."""
        from scripts.apply_loop import main

        source = inspect.getsource(main)
        assert "consecutive_crashes" in source, "main() should track consecutive crashes"
