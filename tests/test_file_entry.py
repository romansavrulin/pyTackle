"""Tests for common/FileEntry.py."""

from __future__ import annotations

import hashlib
import shutil
from datetime import datetime, timezone

import pytest

from common.FileEntry import FileEntry
from common.attr_map import CANONICAL_MAP, CORE_ATTRS, METADATA_ATTRS


# ------------------------------------------------------------------
# Factory: from_fs_path
# ------------------------------------------------------------------

class TestFromFsPath:
    """Tests for FileEntry.from_fs_path()."""

    def test_all_stat_fields_populated(self, tmp_file):
        entry = FileEntry.from_fs_path(tmp_file)
        assert entry.path == tmp_file
        assert entry.size is not None
        assert entry.creation is not None
        assert entry.access is not None
        assert entry.modify is not None
        assert entry.permissions is not None
        assert entry.uid is not None
        assert entry.gid is not None

    def test_checksum_is_none(self, tmp_file):
        entry = FileEntry.from_fs_path(tmp_file)
        assert entry.checksum is None


# ------------------------------------------------------------------
# Factory: from_listing_row
# ------------------------------------------------------------------

class TestFromListingRow:
    """Tests for FileEntry.from_listing_row()."""

    def test_canonical_attr_map_all_fields(self):
        now = datetime.now(tz=timezone.utc)
        cols = [
            "1024",                # 0: size
            now.isoformat(),       # 1: creation
            now.isoformat(),       # 2: access
            now.isoformat(),       # 3: modify
            "0o644",               # 4: permissions
            "1000",                # 5: uid
            "1000",                # 6: gid
            "md5:abcdef1234567890",  # 7: checksum
            "/tmp/test.txt",       # 8: path
        ]
        entry = FileEntry.from_listing_row(cols, CANONICAL_MAP)
        assert entry.path == "/tmp/test.txt"
        assert entry.size == 1024
        assert entry.creation == now
        assert entry.permissions == "0o644"
        assert entry.uid == 1000
        assert entry.gid == 1000
        assert entry.checksum == "md5:abcdef1234567890"

    def test_partial_attr_map(self):
        cols = ["/tmp/test.txt", "512"]
        attr_map = {"path": "0", "size": "1"}
        entry = FileEntry.from_listing_row(cols, attr_map)
        assert entry.path == "/tmp/test.txt"
        assert entry.size == 512
        assert entry.creation is None
        assert entry.access is None
        assert entry.modify is None
        assert entry.permissions is None
        assert entry.uid is None
        assert entry.gid is None
        assert entry.checksum is None

    def test_meta_selector_earliest(self):
        dt1 = datetime(2020, 1, 1, tzinfo=timezone.utc)
        dt2 = datetime(2021, 6, 15, tzinfo=timezone.utc)
        dt3 = datetime(2019, 3, 10, tzinfo=timezone.utc)
        cols = [
            "/tmp/test.txt",       # 0: path
            dt1.isoformat(),       # 1: creation
            dt2.isoformat(),       # 2: access
            dt3.isoformat(),       # 3: modify
        ]
        attr_map = {
            "path": "0",
            "creation": "1",
            "access": "earliest",
            "modify": "3",
        }
        entry = FileEntry.from_listing_row(cols, attr_map)
        # earliest should be min of creation (dt1) and modify (dt3) = dt3
        assert entry.access == dt3

    def test_meta_selector_latest(self):
        dt1 = datetime(2020, 1, 1, tzinfo=timezone.utc)
        dt2 = datetime(2021, 6, 15, tzinfo=timezone.utc)
        cols = [
            "/tmp/test.txt",
            dt1.isoformat(),
            dt2.isoformat(),
        ]
        attr_map = {
            "path": "0",
            "creation": "1",
            "modify": "2",
            "access": "latest",
        }
        entry = FileEntry.from_listing_row(cols, attr_map)
        # latest should be max of creation (dt1) and modify (dt2) = dt2
        assert entry.access == dt2


# ------------------------------------------------------------------
# Factory: from_md5sum_line
# ------------------------------------------------------------------

class TestFromMd5sumLine:
    """Tests for FileEntry.from_md5sum_line()."""

    def test_valid_line(self):
        line = "d41d8cd98f00b204e9800998ecf8427e  /tmp/empty.txt"
        entry = FileEntry.from_md5sum_line(line)
        assert entry.path == "/tmp/empty.txt"
        assert entry.checksum == "md5:d41d8cd98f00b204e9800998ecf8427e"
        assert entry.size is None
        assert entry.creation is None

    def test_invalid_line_raises(self):
        with pytest.raises(ValueError, match="does not match md5sum format"):
            FileEntry.from_md5sum_line("not a valid line")


# ------------------------------------------------------------------
# get_attr / set_attr
# ------------------------------------------------------------------

class TestGetSetAttr:
    """Tests for get_attr() and set_attr()."""

    def test_get_attr_valid(self, sample_entry):
        assert sample_entry.get_attr("path") == sample_entry.path

    def test_get_attr_invalid_raises(self, sample_entry):
        with pytest.raises(ValueError, match="Unknown attribute"):
            sample_entry.get_attr("nonexistent")

    def test_set_attr_valid(self):
        entry = FileEntry(path="/tmp/test.txt")
        entry.set_attr("size", 42)
        assert entry.size == 42

    def test_set_attr_accepts_none(self):
        entry = FileEntry(path="/tmp/test.txt", size=100)
        entry.set_attr("size", None)
        assert entry.size is None

    def test_set_attr_checksum_raises(self):
        entry = FileEntry(path="/tmp/test.txt")
        with pytest.raises(ValueError, match="Cannot set 'checksum'"):
            entry.set_attr("checksum", "md5:abc")

    def test_set_attr_invalid_raises(self):
        entry = FileEntry(path="/tmp/test.txt")
        with pytest.raises(ValueError, match="Unknown attribute"):
            entry.set_attr("nonexistent", 42)


# ------------------------------------------------------------------
# copy_attrs_from
# ------------------------------------------------------------------

class TestCopyAttrsFrom:
    """Tests for copy_attrs_from()."""

    def test_metadata_copies_only_metadata(self):
        now = datetime.now(tz=timezone.utc)
        source = FileEntry(
            path="/src.txt", size=999, creation=now, access=now,
            modify=now, permissions="0o755", uid=500, gid=500,
        )
        target = FileEntry(path="/dst.txt", size=100)
        target.copy_attrs_from(source, attrs="metadata")

        # Metadata attrs should be copied
        assert target.creation == now
        assert target.access == now
        assert target.modify == now
        assert target.permissions == "0o755"
        assert target.uid == 500
        assert target.gid == 500

        # Core attrs should NOT be copied
        assert target.path == "/dst.txt"
        assert target.size == 100  # unchanged

    def test_all_copies_everything(self):
        now = datetime.now(tz=timezone.utc)
        source = FileEntry(
            path="/src.txt", size=999, creation=now, access=now,
            modify=now, permissions="0o755", uid=500, gid=500,
            checksum="md5:abc",
        )
        target = FileEntry(path="/dst.txt")
        target.copy_attrs_from(source, attrs="all")

        assert target.path == "/src.txt"
        assert target.size == 999
        assert target.creation == now

    def test_explicit_list(self):
        source = FileEntry(path="/src.txt", size=999, uid=500, gid=600)
        target = FileEntry(path="/dst.txt")
        target.copy_attrs_from(source, attrs=["uid", "gid"])

        assert target.uid == 500
        assert target.gid == 600
        assert target.size is None  # not in the list

    def test_skips_none_values(self):
        source = FileEntry(path="/src.txt", uid=None, gid=600)
        target = FileEntry(path="/dst.txt", uid=100)
        target.copy_attrs_from(source, attrs=["uid", "gid"])

        assert target.uid == 100  # unchanged because source.uid is None
        assert target.gid == 600


# ------------------------------------------------------------------
# Checksum
# ------------------------------------------------------------------

class TestChecksum:
    """Tests for calculate_checksum() and recalculate_checksum()."""

    def test_calculate_checksum(self, tmp_file):
        entry = FileEntry(path=tmp_file)
        hexdigest = entry.calculate_checksum(algorithm="md5")
        expected = hashlib.md5(b"Hello, FileEntry!\n").hexdigest()
        assert hexdigest == expected
        assert entry.checksum == f"md5:{expected}"

    def test_calculate_checksum_returns_cached(self, tmp_file):
        entry = FileEntry(path=tmp_file)
        first = entry.calculate_checksum(algorithm="md5")
        # Modify the file — cached value should still be returned
        with open(tmp_file, "w") as f:
            f.write("modified content")
        second = entry.calculate_checksum(algorithm="md5")
        assert first == second

    def test_recalculate_checksum_always_recomputes(self, tmp_file):
        entry = FileEntry(path=tmp_file)
        first = entry.calculate_checksum(algorithm="md5")

        # Modify the file
        with open(tmp_file, "w") as f:
            f.write("modified content")

        second = entry.recalculate_checksum(algorithm="md5")
        assert first != second
        expected = hashlib.md5(b"modified content").hexdigest()
        assert second == expected


# ------------------------------------------------------------------
# Serialisation: to_listing_row
# ------------------------------------------------------------------

class TestToListingRow:
    """Tests for to_listing_row()."""

    def test_canonical_map_correct_columns(self):
        now = datetime.now(tz=timezone.utc)
        entry = FileEntry(
            path="/tmp/test.txt", size=1024, creation=now, access=now,
            modify=now, permissions="0o644", uid=1000, gid=1000,
            checksum="md5:abc",
        )
        row = entry.to_listing_row(CANONICAL_MAP)
        assert len(row) == 9
        assert row[8] == "/tmp/test.txt"  # path is last

    def test_path_in_last_position(self):
        entry = FileEntry(path="/tmp/test.txt")
        row = entry.to_listing_row(CANONICAL_MAP)
        assert row[8] == "/tmp/test.txt"


# ------------------------------------------------------------------
# Round-trip: to_listing_row ↔ from_listing_row
# ------------------------------------------------------------------

class TestRoundTrip:
    """Test that to_listing_row / from_listing_row preserves data."""

    def test_round_trip_preserves_data(self):
        now = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        original = FileEntry(
            path="/tmp/test.txt",
            size=1024,
            creation=now,
            access=now,
            modify=now,
            permissions="0o644",
            uid=1000,
            gid=1000,
            checksum="md5:abcdef1234567890abcdef1234567890",
        )
        row = original.to_listing_row(CANONICAL_MAP)
        restored = FileEntry.from_listing_row(row, CANONICAL_MAP)

        assert restored.path == original.path
        assert restored.size == original.size
        assert restored.creation == original.creation
        assert restored.access == original.access
        assert restored.modify == original.modify
        assert restored.permissions == original.permissions
        assert restored.uid == original.uid
        assert restored.gid == original.gid
        assert restored.checksum == original.checksum


# ------------------------------------------------------------------
# apply_to_fs — smoke test
# ------------------------------------------------------------------

class TestApplyToFs:
    """Smoke test for apply_to_fs()."""

    def test_does_not_crash_with_timestamps(self, tmp_file):
        now = datetime.now(tz=timezone.utc)
        entry = FileEntry(
            path=tmp_file,
            access=now,
            modify=now,
            permissions="0o644",
        )
        # Should not raise — we only apply access/modify/permissions
        # (creation requires platform-specific support)
        entry.apply_to_fs(attrs=["access", "modify", "permissions"])
