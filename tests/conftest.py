"""Shared fixtures for the common/ test suite."""

from __future__ import annotations

import csv
import os
import tempfile
from datetime import datetime, timezone

import pytest

from common.FileEntry import FileEntry
from common.attr_map import CANONICAL_MAP


@pytest.fixture()
def tmp_file(tmp_path):
    """Create a temp file with known content, yield its path."""
    p = tmp_path / "hello.txt"
    p.write_text("Hello, FileEntry!\n", encoding="utf-8")
    yield str(p)


@pytest.fixture()
def sample_entry(tmp_file):
    """Create a FileEntry from the tmp_file fixture."""
    return FileEntry.from_fs_path(tmp_file)


@pytest.fixture()
def canonical_csv(tmp_path):
    """Create a temp CSV file with a few canonical-format rows, yield its path."""
    csv_path = tmp_path / "listing.csv"
    now = datetime.now(tz=timezone.utc)
    rows = []
    for i in range(3):
        entry = FileEntry(
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
        rows.append(entry.to_listing_row(CANONICAL_MAP))

    with open(str(csv_path), "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        for row in rows:
            writer.writerow(row)

    yield str(csv_path)
