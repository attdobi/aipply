"""Tests for the apply safety module."""

import pytest


class TestCanSubmitLive:
    """Tests for can_submit_live()."""

    def test_none_config_returns_false(self):
        from src.apply_safety import can_submit_live
        assert can_submit_live(None) is False

    def test_empty_config_returns_false(self):
        from src.apply_safety import can_submit_live
        assert can_submit_live({}) is False

    def test_missing_application_key_returns_false(self):
        from src.apply_safety import can_submit_live
        assert can_submit_live({"other": "stuff"}) is False

    def test_live_submission_enabled_true(self):
        from src.apply_safety import can_submit_live
        config = {"application": {"live_submission_enabled": True}}
        assert can_submit_live(config) is True

    def test_live_submission_enabled_string_true(self):
        from src.apply_safety import can_submit_live
        config = {"application": {"live_submission_enabled": "true"}}
        assert can_submit_live(config) is True

    def test_submit_enabled_true(self):
        from src.apply_safety import can_submit_live
        config = {"application": {"submit_enabled": True}}
        assert can_submit_live(config) is True

    def test_mode_live(self):
        from src.apply_safety import can_submit_live
        config = {"application": {"mode": "live"}}
        assert can_submit_live(config) is True

    def test_mode_shadow_returns_false(self):
        from src.apply_safety import can_submit_live
        config = {"application": {"mode": "shadow"}}
        assert can_submit_live(config) is False

    def test_all_disabled_returns_false(self):
        from src.apply_safety import can_submit_live
        config = {"application": {"live_submission_enabled": False, "submit_enabled": False, "mode": "shadow"}}
        assert can_submit_live(config) is False

    def test_non_dict_application_returns_false(self):
        from src.apply_safety import can_submit_live
        config = {"application": "not_a_dict"}
        assert can_submit_live(config) is False


class TestGetSubmissionBlockReason:
    """Tests for get_submission_block_reason()."""

    def test_returns_reason_when_blocked(self):
        from src.apply_safety import get_submission_block_reason, LIVE_SUBMISSION_BLOCK_REASON
        reason = get_submission_block_reason({})
        assert reason == LIVE_SUBMISSION_BLOCK_REASON

    def test_returns_none_when_live(self):
        from src.apply_safety import get_submission_block_reason
        config = {"application": {"live_submission_enabled": True}}
        assert get_submission_block_reason(config) is None

    def test_returns_none_for_mode_live(self):
        from src.apply_safety import get_submission_block_reason
        config = {"application": {"mode": "live"}}
        assert get_submission_block_reason(config) is None


class TestConstants:
    """Test module constants."""

    def test_block_reason_is_string(self):
        from src.apply_safety import LIVE_SUBMISSION_BLOCK_REASON
        assert isinstance(LIVE_SUBMISSION_BLOCK_REASON, str)
        assert len(LIVE_SUBMISSION_BLOCK_REASON) > 0

    def test_enabled_reason_is_string(self):
        from src.apply_safety import LIVE_SUBMISSION_ENABLED_REASON
        assert isinstance(LIVE_SUBMISSION_ENABLED_REASON, str)
