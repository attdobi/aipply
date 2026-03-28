"""Tests for shared utility functions."""

import os
import pytest
from pathlib import Path


class TestLoadConfig:
    """Tests for load_config()."""

    def test_loads_yaml_file(self, tmp_path):
        from src.utils import load_config
        config_file = tmp_path / "test.yaml"
        config_file.write_text("key: value\nnested:\n  a: 1\n")
        result = load_config(config_file)
        assert result == {"key": "value", "nested": {"a": 1}}

    def test_empty_yaml_returns_empty_dict(self, tmp_path):
        from src.utils import load_config
        config_file = tmp_path / "empty.yaml"
        config_file.write_text("")
        result = load_config(config_file)
        assert result == {}

    def test_missing_file_raises(self, tmp_path):
        from src.utils import load_config
        with pytest.raises(FileNotFoundError):
            load_config(tmp_path / "missing.yaml")


class TestEnsureDir:
    """Tests for ensure_dir()."""

    def test_creates_directory(self, tmp_path):
        from src.utils import ensure_dir
        new_dir = tmp_path / "a" / "b" / "c"
        result = ensure_dir(new_dir)
        assert new_dir.exists()
        assert result == new_dir

    def test_existing_directory_is_fine(self, tmp_path):
        from src.utils import ensure_dir
        result = ensure_dir(tmp_path)
        assert result == tmp_path


class TestSanitizeFilename:
    """Tests for sanitize_filename()."""

    def test_replaces_special_chars(self):
        from src.utils import sanitize_filename
        assert sanitize_filename("hello world!@#$") == "hello_world"

    def test_collapses_underscores(self):
        from src.utils import sanitize_filename
        assert sanitize_filename("a___b") == "a_b"

    def test_preserves_hyphens(self):
        from src.utils import sanitize_filename
        assert sanitize_filename("my-file-name") == "my-file-name"

    def test_strips_leading_trailing_underscores(self):
        from src.utils import sanitize_filename
        assert sanitize_filename("_test_") == "test"

    def test_normal_string_unchanged(self):
        from src.utils import sanitize_filename
        assert sanitize_filename("Danna_Dobi_Resume") == "Danna_Dobi_Resume"


class TestGetTimestamp:
    """Tests for get_timestamp()."""

    def test_returns_iso_format(self):
        from src.utils import get_timestamp
        ts = get_timestamp()
        assert ts.endswith("Z")
        assert "T" in ts

    def test_returns_string(self):
        from src.utils import get_timestamp
        assert isinstance(get_timestamp(), str)
