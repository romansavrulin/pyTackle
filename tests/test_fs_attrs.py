"""Tests for common/fs_attrs.py."""

from __future__ import annotations

import os
import stat
from datetime import datetime, timezone

import pytest

from common.fs_attrs import (
    _stat_creation_time,
    apply_permissions,
    read_all,
    set_access_modify_time,
)


# ------------------------------------------------------------------
# read_all
# ------------------------------------------------------------------

class TestReadAll:
    """Tests for read_all() on a real temp file."""

    def test_all_expected_keys_present(self, tmp_file):
        attrs = read_all(tmp_file)
        expected_keys = {"size", "creation", "access", "modify",
                         "permissions", "uid", "gid", "entry_type"}
        assert set(attrs.keys()) == expected_keys

    def test_types_are_correct(self, tmp_file):
        attrs = read_all(tmp_file)
        assert isinstance(attrs["size"], int)
        assert isinstance(attrs["creation"], datetime)
        assert isinstance(attrs["access"], datetime)
        assert isinstance(attrs["modify"], datetime)
        assert isinstance(attrs["permissions"], str)
        assert isinstance(attrs["uid"], int)
        assert isinstance(attrs["gid"], int)

    def test_datetimes_have_timezone(self, tmp_file):
        attrs = read_all(tmp_file)
        for key in ("creation", "access", "modify"):
            assert attrs[key].tzinfo is not None, f"{key} should be tz-aware"

    def test_size_matches_content(self, tmp_file):
        attrs = read_all(tmp_file)
        assert attrs["size"] == len("Hello, FileEntry!\n".encode("utf-8"))


# ------------------------------------------------------------------
# _stat_creation_time
# ------------------------------------------------------------------

class TestStatCreationTime:
    """Tests for _stat_creation_time()."""

    def test_returns_tz_aware_datetime(self, tmp_file):
        st = os.lstat(tmp_file)
        result = _stat_creation_time(st)
        assert isinstance(result, datetime)
        assert result.tzinfo is not None


# ------------------------------------------------------------------
# apply_permissions
# ------------------------------------------------------------------

class TestApplyPermissions:
    """Tests for apply_permissions()."""

    def test_set_permissions_and_verify(self, tmp_file):
        apply_permissions(tmp_file, "0o755")
        mode = stat.S_IMODE(os.stat(tmp_file).st_mode)
        assert mode == 0o755

    def test_set_readonly_permissions(self, tmp_file):
        apply_permissions(tmp_file, "0o444")
        mode = stat.S_IMODE(os.stat(tmp_file).st_mode)
        assert mode == 0o444


# ------------------------------------------------------------------
# set_access_modify_time
# ------------------------------------------------------------------

class TestSetAccessModifyTime:
    """Tests for set_access_modify_time()."""

    def test_set_both_times(self, tmp_file):
        target_dt = datetime(2020, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        set_access_modify_time(tmp_file, access_dt=target_dt, modify_dt=target_dt)
        st = os.stat(tmp_file)
        # Allow 1-second tolerance for filesystem precision
        assert abs(st.st_atime - target_dt.timestamp()) < 1.0
        assert abs(st.st_mtime - target_dt.timestamp()) < 1.0

    def test_set_only_modify_time(self, tmp_file):
        target_dt = datetime(2019, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        st_before = os.stat(tmp_file)
        set_access_modify_time(tmp_file, modify_dt=target_dt)
        st_after = os.stat(tmp_file)
        assert abs(st_after.st_mtime - target_dt.timestamp()) < 1.0
        # Access time should remain approximately unchanged
        assert abs(st_after.st_atime - st_before.st_atime) < 1.0
