"""Tests for common/checksum.py."""

from __future__ import annotations

import hashlib
import shutil

import pytest

from common.checksum import _run_external, _run_hashlib, calculate


# ------------------------------------------------------------------
# _run_hashlib
# ------------------------------------------------------------------

class TestRunHashlib:
    """Tests for the pure-Python hashlib backend."""

    def test_md5_known_content(self, tmp_path):
        p = tmp_path / "data.bin"
        content = b"Hello, FileEntry!\n"
        p.write_bytes(content)
        expected = hashlib.md5(content).hexdigest()
        assert _run_hashlib(str(p), "md5") == expected

    def test_sha256_known_content(self, tmp_path):
        p = tmp_path / "data.bin"
        content = b"Hello, FileEntry!\n"
        p.write_bytes(content)
        expected = hashlib.sha256(content).hexdigest()
        assert _run_hashlib(str(p), "sha256") == expected

    def test_invalid_algorithm_raises(self, tmp_path):
        p = tmp_path / "data.bin"
        p.write_bytes(b"x")
        with pytest.raises(ValueError, match="Unsupported hash algorithm"):
            _run_hashlib(str(p), "not_a_real_algo")


# ------------------------------------------------------------------
# calculate (hashlib fallback)
# ------------------------------------------------------------------

class TestCalculate:
    """Tests for the top-level calculate() dispatcher."""

    def test_without_utility_uses_hashlib(self, tmp_path):
        p = tmp_path / "data.bin"
        content = b"test content"
        p.write_bytes(content)
        expected = hashlib.md5(content).hexdigest()
        assert calculate(str(p), algorithm="md5") == expected

    @pytest.mark.skipif(
        shutil.which("md5sum") is None,
        reason="md5sum not available on this system",
    )
    def test_with_md5sum_utility(self, tmp_path):
        p = tmp_path / "data.bin"
        content = b"test content"
        p.write_bytes(content)
        expected = hashlib.md5(content).hexdigest()
        result = calculate(str(p), utility="md5sum")
        assert result == expected


# ------------------------------------------------------------------
# _run_external — error case
# ------------------------------------------------------------------

class TestRunExternal:
    """Tests for the external-utility backend."""

    def test_nonexistent_utility_raises(self, tmp_path):
        p = tmp_path / "data.bin"
        p.write_bytes(b"x")
        with pytest.raises(FileNotFoundError, match="not found"):
            _run_external(str(p), "absolutely_nonexistent_utility_xyz")
