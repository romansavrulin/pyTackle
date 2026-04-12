"""Tests for common/listing.py."""

from __future__ import annotations

import csv
import types
from datetime import datetime, timezone

import pytest

from common.FileEntry import FileEntry
from common.attr_map import CANONICAL_MAP, CANONICAL_HEADER
from common.listing import (
    iter_listing,
    iter_md5sum_listing,
    read_listing,
    read_md5sum_listing,
    write_listing,
)


# ------------------------------------------------------------------
# write_listing + read_listing round-trip
# ------------------------------------------------------------------

class TestWriteReadRoundTrip:
    """Test write_listing() + read_listing() round-trip."""

    def test_round_trip_multiple_entries(self, tmp_path):
        csv_path = str(tmp_path / "listing.csv")
        now = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        entries = [
            FileEntry(
                path=f"/tmp/file{i}.txt",
                size=100 + i,
                creation=now,
                access=now,
                modify=now,
                permissions="0o644",
                uid=1000,
                gid=1000,
                checksum=f"md5:{'ab' * 16}",
            )
            for i in range(5)
        ]

        count = write_listing(csv_path, entries)
        assert count == 5

        restored = read_listing(csv_path)
        assert len(restored) == 5
        for i, entry in enumerate(restored):
            assert entry.path == f"/tmp/file{i}.txt"
            assert entry.size == 100 + i


# ------------------------------------------------------------------
# iter_listing — generator behaviour
# ------------------------------------------------------------------

class TestIterListing:
    """Test that iter_listing() yields entries one at a time."""

    def test_is_a_generator(self, canonical_csv):
        result = iter_listing(canonical_csv)
        assert isinstance(result, types.GeneratorType)

    def test_yields_correct_count(self, canonical_csv):
        entries = list(iter_listing(canonical_csv))
        assert len(entries) == 3


# ------------------------------------------------------------------
# read_listing with custom attr_map
# ------------------------------------------------------------------

class TestReadListingCustomMap:
    """Test read_listing() with a custom attr_map."""

    def test_custom_attr_map(self, tmp_path):
        csv_path = str(tmp_path / "custom.csv")
        # Write a simple 2-column CSV: path, size
        with open(csv_path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["/tmp/a.txt", "100"])
            writer.writerow(["/tmp/b.txt", "200"])

        attr_map = {"path": "0", "size": "1"}
        entries = read_listing(csv_path, attr_map=attr_map)
        assert len(entries) == 2
        assert entries[0].path == "/tmp/a.txt"
        assert entries[0].size == 100
        assert entries[1].path == "/tmp/b.txt"
        assert entries[1].size == 200


# ------------------------------------------------------------------
# md5sum listing
# ------------------------------------------------------------------

class TestMd5sumListing:
    """Test write md5sum format manually, then read back."""

    def test_write_and_read_md5sum(self, tmp_path):
        md5_path = str(tmp_path / "checksums.md5")
        # Write md5sum format manually
        with open(md5_path, "w", encoding="utf-8") as fh:
            fh.write("d41d8cd98f00b204e9800998ecf8427e  /tmp/empty.txt\n")
            fh.write("0cc175b9c0f1b6a831c399e269772661  /tmp/a.txt\n")

        entries = read_md5sum_listing(md5_path)
        assert len(entries) == 2
        assert entries[0].path == "/tmp/empty.txt"
        assert entries[0].checksum == "md5:d41d8cd98f00b204e9800998ecf8427e"
        assert entries[1].path == "/tmp/a.txt"
        assert entries[1].checksum == "md5:0cc175b9c0f1b6a831c399e269772661"

    def test_iter_md5sum_is_generator(self, tmp_path):
        md5_path = str(tmp_path / "checksums.md5")
        with open(md5_path, "w", encoding="utf-8") as fh:
            fh.write("d41d8cd98f00b204e9800998ecf8427e  /tmp/empty.txt\n")

        result = iter_md5sum_listing(md5_path)
        assert isinstance(result, types.GeneratorType)
        entries = list(result)
        assert len(entries) == 1


# ------------------------------------------------------------------
# Edge cases
# ------------------------------------------------------------------

class TestEdgeCases:
    """Test empty files and malformed rows."""

    def test_empty_file_returns_empty_list(self, tmp_path):
        csv_path = str(tmp_path / "empty.csv")
        with open(csv_path, "w", encoding="utf-8") as fh:
            pass  # empty file
        entries = read_listing(csv_path)
        assert entries == []

    def test_malformed_rows_skipped_with_warning(self, tmp_path, caplog):
        csv_path = str(tmp_path / "bad.csv")
        # Write rows where 'path' column (index 8) is missing entirely
        # This should cause from_listing_row to fail because path is required
        with open(csv_path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            # Only 2 columns — canonical map expects 9, and path at index 8
            writer.writerow(["100", "bad-row"])

        import logging
        with caplog.at_level(logging.WARNING):
            entries = read_listing(csv_path)

        # The malformed row should be skipped (not crash)
        assert len(entries) == 0


# ------------------------------------------------------------------
# Header support tests
# ------------------------------------------------------------------

class TestHeaderSupport:
    """Test header reading and writing functionality."""

    def test_iter_listing_explicit_has_header_true(self, tmp_path):
        """Test that has_header=True always skips the first row."""
        csv_path = str(tmp_path / "with_header.csv")
        now = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        
        # Write a file with a header
        entries = [
            FileEntry(
                path="/tmp/file1.txt",
                size=100,
                creation=now,
                access=now,
                modify=now,
                permissions="0o644",
                uid=1000,
                gid=1000,
                checksum="md5:" + "ab" * 16,
            )
        ]
        write_listing(csv_path, entries, include_header=True)
        
        # Read with explicit has_header=True
        restored = list(iter_listing(csv_path, has_header=True))
        assert len(restored) == 1
        assert restored[0].path == "/tmp/file1.txt"

    def test_iter_listing_has_header_false_reads_header_as_data(self, tmp_path, caplog):
        """Test that has_header=False tries to read header as data (should fail/skip)."""
        csv_path = str(tmp_path / "with_header.csv")
        now = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        
        # Write a file with a header
        entries = [
            FileEntry(
                path="/tmp/file1.txt",
                size=100,
                creation=now,
                access=now,
                modify=now,
                permissions="0o644",
                uid=1000,
                gid=1000,
                checksum="md5:" + "ab" * 16,
            )
        ]
        write_listing(csv_path, entries, include_header=True)
        
        import logging
        with caplog.at_level(logging.WARNING):
            # Read with has_header=False — should try to parse header as data
            restored = list(iter_listing(csv_path, has_header=False))
        
        # Only the data row should be successfully parsed,
        # the header row will fail because 'creation' is not a valid timestamp
        assert len(restored) == 1
        assert restored[0].path == "/tmp/file1.txt"

    def test_iter_listing_auto_detection(self, tmp_path):
        """Test that has_header=None auto-detects header row."""
        csv_path = str(tmp_path / "with_header.csv")
        now = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        
        # Write a file with a header
        entries = [
            FileEntry(
                path="/tmp/file1.txt",
                size=100,
                creation=now,
                access=now,
                modify=now,
            )
        ]
        write_listing(csv_path, entries, include_header=True)
        
        # Read with auto-detection (default)
        restored = list(iter_listing(csv_path))
        assert len(restored) == 1
        assert restored[0].path == "/tmp/file1.txt"

    def test_iter_listing_auto_detection_no_header(self, tmp_path):
        """Test that auto-detection correctly handles files without headers."""
        csv_path = str(tmp_path / "no_header.csv")
        now = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        
        # Write a file without a header
        entries = [
            FileEntry(
                path="/tmp/file1.txt",
                size=100,
                creation=now,
                access=now,
                modify=now,
            ),
            FileEntry(
                path="/tmp/file2.txt",
                size=200,
                creation=now,
                access=now,
                modify=now,
            ),
        ]
        write_listing(csv_path, entries, include_header=False)
        
        # Read with auto-detection — should not skip any rows
        restored = list(iter_listing(csv_path))
        assert len(restored) == 2
        assert restored[0].path == "/tmp/file1.txt"
        assert restored[1].path == "/tmp/file2.txt"

    def test_write_listing_include_header_true(self, tmp_path):
        """Test write_listing with include_header=True writes header row."""
        csv_path = str(tmp_path / "with_header.csv")
        now = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        
        entries = [
            FileEntry(
                path="/tmp/file1.txt",
                size=100,
                creation=now,
                access=now,
                modify=now,
            )
        ]
        write_listing(csv_path, entries, include_header=True)
        
        # Read raw CSV to verify header
        with open(csv_path, newline="", encoding="utf-8") as fh:
            reader = csv.reader(fh)
            rows = list(reader)
        
        assert len(rows) == 2  # header + 1 data row
        # Check that header row contains expected attribute names
        header_row = rows[0]
        assert "creation" in header_row
        assert "path" in header_row
        assert "size" in header_row

    def test_write_listing_include_header_false(self, tmp_path):
        """Test write_listing with include_header=False writes no header."""
        csv_path = str(tmp_path / "no_header.csv")
        now = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        
        entries = [
            FileEntry(
                path="/tmp/file1.txt",
                size=100,
                creation=now,
                access=now,
                modify=now,
            )
        ]
        write_listing(csv_path, entries, include_header=False)
        
        # Read raw CSV to verify no header
        with open(csv_path, newline="", encoding="utf-8") as fh:
            reader = csv.reader(fh)
            rows = list(reader)
        
        assert len(rows) == 1  # just data row, no header
        # First row should be data (path at index 9 for canonical map)
        assert rows[0][9] == "/tmp/file1.txt"

    def test_round_trip_with_headers(self, tmp_path):
        """Test full round-trip: write with header, read with auto-detection."""
        csv_path = str(tmp_path / "roundtrip.csv")
        now = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        
        original_entries = [
            FileEntry(
                path=f"/tmp/file{i}.txt",
                size=100 + i,
                creation=now,
                access=now,
                modify=now,
                permissions="0o644",
                uid=1000,
                gid=1000,
                checksum=f"md5:{'ab' * 16}",
            )
            for i in range(3)
        ]
        
        # Write with header
        count = write_listing(csv_path, original_entries, include_header=True)
        assert count == 3
        
        # Read with auto-detection (should skip header)
        restored = read_listing(csv_path)
        assert len(restored) == 3
        
        for i, entry in enumerate(restored):
            assert entry.path == f"/tmp/file{i}.txt"
            assert entry.size == 100 + i
            assert entry.creation == now
            assert entry.checksum == f"md5:{'ab' * 16}"

    def test_custom_attr_map_header(self, tmp_path):
        """Test header generation with custom attr_map."""
        csv_path = str(tmp_path / "custom_header.csv")
        now = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        
        # Custom mapping: path at 0, size at 1
        custom_map = {"path": "0", "size": "1"}
        
        entries = [
            FileEntry(
                path="/tmp/file1.txt",
                size=100,
                creation=now,
                access=now,
                modify=now,
            )
        ]
        write_listing(csv_path, entries, attr_map=custom_map, include_header=True)
        
        # Read raw CSV to verify header
        with open(csv_path, newline="", encoding="utf-8") as fh:
            reader = csv.reader(fh)
            rows = list(reader)
        
        assert len(rows) == 2
        header_row = rows[0]
        assert header_row[0] == "path"
        assert header_row[1] == "size"
        
        # Read back with custom map and auto-detection
        restored = read_listing(csv_path, attr_map=custom_map)
        assert len(restored) == 1
        assert restored[0].path == "/tmp/file1.txt"
        assert restored[0].size == 100