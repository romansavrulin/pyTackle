"""Tests for common/listing.py."""

from __future__ import annotations

import csv
import types
from datetime import datetime, timezone

import pytest

from common.FileEntry import FileEntry
from common.attr_map import CANONICAL_MAP
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