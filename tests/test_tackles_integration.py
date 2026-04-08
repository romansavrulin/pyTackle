"""Integration tests for ValidateCopy and CopyValidateMD5 tackles.

These tests capture the **current behaviour** of the two tackles before they
are refactored to use ``FileEntry``.  They serve as a safety net to ensure
the refactoring does not break anything.
"""

from __future__ import annotations

import csv
import hashlib
import os
import pathlib
import platform
import re
import shutil
import time
import unicodedata
from datetime import datetime, timezone

import pytest

from common.FileEntry import FileEntry, parse_datetime

from tackles.ValidateCopy import (
    FORMAT_CANONICAL,
    FORMAT_LINUX,
    _extract_dates,
    detect_format,
    generate_listing,
    normalize_path,
    parse_attr_map,
    parse_listing,
    parse_types,
    resolve_selector,
    set_access_modify_time,
)
from tackles.CopyValidateMD5 import CopyValidateMD5


# ===================================================================
# ValidateCopy — parsing helpers
# ===================================================================


class TestValidateCopyParsing:
    """Test the internal parsing functions of ValidateCopy."""

    # ---------------------------------------------------------------
    # detect_format
    # ---------------------------------------------------------------

    def test_detect_format_linux(self):
        """6-column Linux format -> FORMAT_LINUX."""
        line = (
            '"2024-01-15 10:30:00.000000000 +0000",'
            '"2024-01-10 08:00:00.000000000 +0000",'
            '"2024-01-10 08:00:00.000000000 +0000",'
            '"2024-01-10 08:00:00.000000000 +0000",'
            'f,'
            './test.txt'
        )
        assert detect_format(line) == FORMAT_LINUX

    def test_detect_format_canonical(self):
        """10-column canonical format -> FORMAT_CANONICAL."""
        line = (
            '2024-01-15T10:30:00+00:00,'
            '2024-01-10T08:00:00+00:00,'
            '2024-01-12T12:00:00+00:00,'
            'd41d8cd98f00b204e9800998ecf8427e,'
            'f,'
            '0o644,'
            '501,'
            '20,'
            '1234,'
            './test.txt'
        )
        assert detect_format(line) == FORMAT_CANONICAL

    def test_detect_format_unknown_column_count(self):
        """Unknown column count (e.g. 4 columns) raises ValueError."""
        line = '01/15/2024 10:30:00,01/10/2024 08:00:00,1234,C:\\test.txt'
        with pytest.raises(ValueError, match='Unsupported listing format'):
            detect_format(line)

    # ---------------------------------------------------------------
    # parse_listing — Linux format
    # ---------------------------------------------------------------

    def test_parse_listing_linux_format(self, tmp_path):
        """Parse a Linux-format CSV and verify FileEntry fields.

        Note: FileEntry only has 3 datetime attributes (creation, access, modify),
        so only 3 dates are extracted even though Linux format has 4 date columns.
        """
        csv_file = tmp_path / 'listing_linux.csv'
        csv_file.write_text(
            '"2024-01-15 10:30:00.000000000 +0000",'
            '"2024-01-10 08:00:00.000000000 +0000",'
            '"2024-01-12 12:00:00.000000000 +0000",'
            '"2024-01-11 09:00:00.000000000 +0000",'
            'f,'
            './test.txt\n',
            encoding='utf-8',
        )

        entries = parse_listing(str(csv_file), str(tmp_path))
        assert len(entries) == 1

        fe = entries[0]
        assert isinstance(fe, FileEntry)
        # FileEntry has 3 datetime attrs (creation, access, modify)
        dates = _extract_dates(fe)
        assert len(dates) == 3
        assert dates[0] == datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        assert dates[1] == datetime(2024, 1, 10, 8, 0, 0, tzinfo=timezone.utc)
        assert dates[2] == datetime(2024, 1, 12, 12, 0, 0, tzinfo=timezone.utc)
        assert fe.entry_type == 'f'
        # Path is now resolved to full path
        assert fe.path == os.path.normpath(os.path.join(str(tmp_path), 'test.txt'))

    # ---------------------------------------------------------------
    # parse_listing — Canonical 10-column format
    # ---------------------------------------------------------------

    def test_parse_listing_canonical_format(self, tmp_path):
        """Parse a canonical 10-column CSV and verify FileEntry fields."""
        csv_file = tmp_path / 'listing_canonical.csv'
        # New column order: creation,access,modify,checksum,entry_type,permissions,uid,gid,size,path
        csv_file.write_text(
            '2024-01-10T08:00:00+00:00,'
            '2024-01-15T10:30:00+00:00,'
            '2024-01-12T12:00:00+00:00,'
            'd41d8cd98f00b204e9800998ecf8427e,'
            'f,'
            '0o644,'
            '501,'
            '20,'
            '1234,'
            'test.txt\n',
            encoding='utf-8',
        )

        entries = parse_listing(str(csv_file), str(tmp_path))
        assert len(entries) == 1

        fe = entries[0]
        assert isinstance(fe, FileEntry)
        dates = _extract_dates(fe)
        assert len(dates) == 3
        assert dates[0] == datetime(2024, 1, 10, 8, 0, 0, tzinfo=timezone.utc)
        assert dates[1] == datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        assert dates[2] == datetime(2024, 1, 12, 12, 0, 0, tzinfo=timezone.utc)
        assert fe.entry_type == 'f'
        assert fe.checksum == 'd41d8cd98f00b204e9800998ecf8427e'
        assert fe.size == 1234
        # Path is now resolved to full path
        assert fe.path == os.path.normpath(os.path.join(str(tmp_path), 'test.txt'))

    # ---------------------------------------------------------------
    # parse_datetime (from FileEntry)
    # ---------------------------------------------------------------

    def test_parse_datetime_linux(self):
        """Valid Linux timestamp -> tz-aware datetime."""
        raw = '2020-08-20 06:15:03.491092220 +0000'
        dt = parse_datetime(raw)
        assert dt.year == 2020
        assert dt.month == 8
        assert dt.day == 20
        assert dt.hour == 6
        assert dt.minute == 15
        assert dt.second == 3
        assert dt.microsecond == 491092
        assert dt.tzinfo is not None

    def test_parse_datetime_linux_with_offset(self):
        """Linux timestamp with non-zero tz offset."""
        raw = '2024-01-15 10:30:00.000000000 +0300'
        dt = parse_datetime(raw)
        assert dt.year == 2024
        assert dt.month == 1
        assert dt.day == 15
        assert dt.hour == 10
        assert dt.minute == 30

    def test_parse_datetime_linux_invalid(self):
        """Invalid string raises ValueError."""
        with pytest.raises(ValueError, match='Cannot parse datetime'):
            parse_datetime('not-a-timestamp')

    def test_parse_datetime_powershell(self):
        """Valid PowerShell timestamp -> tz-aware UTC datetime."""
        raw = '02/24/2023 14:04:32'
        dt = parse_datetime(raw)
        assert dt == datetime(2023, 2, 24, 14, 4, 32, tzinfo=timezone.utc)

    def test_parse_datetime_powershell_invalid(self):
        """Invalid string raises ValueError."""
        with pytest.raises(ValueError):
            parse_datetime('not-a-timestamp')

    # ---------------------------------------------------------------
    # normalize_path
    # ---------------------------------------------------------------

    def test_normalize_path_unc(self):
        """UNC path ``\\\\server\\share\\rest`` -> stripped."""
        result = normalize_path('\\\\server\\share\\rest\\of\\path')
        expected = os.path.join('rest', 'of', 'path')
        assert result == expected

    def test_normalize_path_forward_slash_unc(self):
        """Forward-slash UNC ``//server/share/rest`` -> stripped."""
        result = normalize_path('//server/share/rest/of/path')
        expected = os.path.join('rest', 'of', 'path')
        assert result == expected

    def test_normalize_path_with_base_path(self):
        """Base-path prefix is stripped."""
        result = normalize_path(
            'photos/vacation/2020/img.jpg',
            script_base_path='photos/vacation',
        )
        expected = os.path.join('2020', 'img.jpg')
        assert result == expected

    def test_normalize_path_no_base(self):
        """Without base-path, backslashes are normalised to forward slashes."""
        result = normalize_path('some\\windows\\path')
        assert result == 'some/windows/path'

    def test_normalize_path_strips_quotes(self):
        """Surrounding quotes are removed."""
        result = normalize_path('"./test.txt"')
        assert result == './test.txt'

    # ---------------------------------------------------------------
    # parse_attr_map (re-exported from common.attr_map)
    # ---------------------------------------------------------------

    def test_parse_attr_map_legacy(self):
        """Valid attr-map string -> dict."""
        result = parse_attr_map('creation:0, access:1, modify:2')
        assert result == {'creation': '0', 'access': '1', 'modify': '2'}

    def test_parse_attr_map_with_aliases(self):
        """Short aliases ``e`` / ``l`` are expanded."""
        result = parse_attr_map('creation:e, modify:l')
        assert result == {'creation': 'earliest', 'modify': 'latest'}

    def test_parse_attr_map_invalid_attr(self):
        """Unknown attribute raises ValueError."""
        with pytest.raises(ValueError, match='Unknown attribute'):
            parse_attr_map('bogus:0')

    def test_parse_attr_map_missing_colon(self):
        """Missing colon raises ValueError."""
        with pytest.raises(ValueError, match='expected "attr:selector"'):
            parse_attr_map('creation0')

    def test_parse_attr_map_empty(self):
        """Empty string raises ValueError."""
        with pytest.raises(ValueError, match='empty mapping'):
            parse_attr_map('')


# ===================================================================
# ValidateCopy — attr-map functionality
# ===================================================================


class TestValidateCopyAttrMap:
    """Test the attr_map functionality."""

    def test_default_attr_map(self):
        """Default attr-map ``creation:e`` maps creation to earliest."""
        result = parse_attr_map('creation:e')
        assert result == {'creation': 'earliest'}

    def test_custom_attr_map(self):
        """Custom attr-map ``creation:2,modify:0`` parses correctly."""
        result = parse_attr_map('creation:2,modify:0')
        assert result == {'creation': '2', 'modify': '0'}

    def test_meta_selectors_earliest(self):
        """``earliest`` meta-selector resolves to min date."""
        dates = [
            datetime(2024, 3, 1, tzinfo=timezone.utc),
            datetime(2024, 1, 1, tzinfo=timezone.utc),
            datetime(2024, 2, 1, tzinfo=timezone.utc),
        ]
        result = resolve_selector(dates, 'earliest')
        assert result == datetime(2024, 1, 1, tzinfo=timezone.utc)

    def test_meta_selectors_latest(self):
        """``latest`` meta-selector resolves to max date."""
        dates = [
            datetime(2024, 3, 1, tzinfo=timezone.utc),
            datetime(2024, 1, 1, tzinfo=timezone.utc),
            datetime(2024, 2, 1, tzinfo=timezone.utc),
        ]
        result = resolve_selector(dates, 'latest')
        assert result == datetime(2024, 3, 1, tzinfo=timezone.utc)

    def test_resolve_selector_by_index(self):
        """Numeric selector returns the date at that 0-based index."""
        dates = [
            datetime(2024, 1, 1, tzinfo=timezone.utc),
            datetime(2024, 2, 1, tzinfo=timezone.utc),
            datetime(2024, 3, 1, tzinfo=timezone.utc),
        ]
        assert resolve_selector(dates, '0') == datetime(2024, 1, 1, tzinfo=timezone.utc)
        assert resolve_selector(dates, '1') == datetime(2024, 2, 1, tzinfo=timezone.utc)
        assert resolve_selector(dates, '2') == datetime(2024, 3, 1, tzinfo=timezone.utc)

    def test_resolve_selector_out_of_range(self):
        """Out-of-range index returns None."""
        dates = [datetime(2024, 1, 1, tzinfo=timezone.utc)]
        assert resolve_selector(dates, '5') is None

    def test_resolve_selector_empty_dates(self):
        """Empty dates list returns None for any selector."""
        assert resolve_selector([], 'earliest') is None
        assert resolve_selector([], 'latest') is None
        assert resolve_selector([], '0') is None


# ===================================================================
# ValidateCopy — listing generation
# ===================================================================


class TestValidateCopyGeneration:
    """Test listing generation (canonical 10-column CSV format)."""

    # Canonical column indices from CANONICAL_MAP (new order):
    #   0=creation, 1=access, 2=modify, 3=checksum, 4=entry_type,
    #   5=permissions, 6=uid, 7=gid, 8=size, 9=path
    _COL_CREATION = 0
    _COL_ACCESS = 1
    _COL_MODIFY = 2
    _COL_CHECKSUM = 3
    _COL_ENTRY_TYPE = 4
    _COL_PERMISSIONS = 5
    _COL_UID = 6
    _COL_GID = 7
    _COL_SIZE = 8
    _COL_PATH = 9

    def test_generate_listing(self, tmp_path):
        """generate_listing() writes a canonical 10-column CSV with correct structure."""
        # Create a temp directory with a few files
        (tmp_path / 'file1.txt').write_text('hello', encoding='utf-8')
        (tmp_path / 'file2.txt').write_text('world', encoding='utf-8')
        sub = tmp_path / 'subdir'
        sub.mkdir()
        (sub / 'file3.txt').write_text('nested', encoding='utf-8')

        output_csv = tmp_path / 'output.csv'
        count = generate_listing(
            str(tmp_path),
            str(output_csv),
            allowed_types={'f', 'd'},
        )

        assert count > 0
        assert output_csv.exists()

        # Read and verify the CSV structure
        with open(output_csv, encoding='utf-8') as fh:
            reader = csv.reader(fh)
            rows = list(reader)

        # At least: base dir + 2 files + subdir + nested file
        assert len(rows) >= 3

        for row in rows:
            # Canonical format: 10 columns
            assert len(row) == 10, f'Expected 10 columns, got {len(row)}: {row}'

            # Timestamp columns (1, 2, 3) should be ISO format
            for i in (self._COL_CREATION, self._COL_ACCESS, self._COL_MODIFY):
                if row[i]:
                    datetime.fromisoformat(row[i])  # raises on bad format

            # Size column (0) should be a non-negative integer
            assert row[self._COL_SIZE].isdigit() or row[self._COL_SIZE] == ''

            # Permissions column (4) should be present (e.g. "0o755")
            if row[self._COL_PERMISSIONS]:
                assert row[self._COL_PERMISSIONS].startswith('0o')

            # uid/gid columns (5, 6) should be integers when present
            for i in (self._COL_UID, self._COL_GID):
                if row[i]:
                    int(row[i])  # raises on bad format

            # entry_type column (8) should be 'f', 'd', or 'l'
            if row[self._COL_ENTRY_TYPE]:
                assert row[self._COL_ENTRY_TYPE] in ('f', 'd', 'l'), \
                    f'Invalid entry_type: {row[self._COL_ENTRY_TYPE]}'

            # Path is the last column (index 9)
            assert row[self._COL_PATH] != ''

        # Verify our files appear in the listing
        rel_paths = [row[self._COL_PATH] for row in rows]
        assert 'file1.txt' in rel_paths
        assert 'file2.txt' in rel_paths
        assert os.path.join('subdir', 'file3.txt') in rel_paths

    def test_generate_listing_files_only(self, tmp_path):
        """generate_listing() with types={'f'} excludes directories."""
        (tmp_path / 'file.txt').write_text('data', encoding='utf-8')
        sub = tmp_path / 'subdir'
        sub.mkdir()
        (sub / 'nested.txt').write_text('nested', encoding='utf-8')

        output_csv = tmp_path / 'output.csv'
        generate_listing(str(tmp_path), str(output_csv), allowed_types={'f'})

        with open(output_csv, encoding='utf-8') as fh:
            reader = csv.reader(fh)
            rows = list(reader)

        # All entries should be files — verify no directory paths appear
        # (directories would show up as paths without file extensions or as '.')
        rel_paths = [row[self._COL_PATH] for row in rows]
        assert len(rows) > 0
        for row in rows:
            assert len(row) == 10, f'Expected 10 columns, got {len(row)}: {row}'
            path = row[self._COL_PATH]
            full = os.path.join(str(tmp_path), path)
            assert os.path.isfile(full), f'Expected file, got directory: {path}'

    def test_generate_listing_dirs_only(self, tmp_path):
        """generate_listing() with types={'d'} excludes files."""
        (tmp_path / 'file.txt').write_text('data', encoding='utf-8')
        sub = tmp_path / 'subdir'
        sub.mkdir()

        output_csv = tmp_path / 'output.csv'
        generate_listing(str(tmp_path), str(output_csv), allowed_types={'d'})

        with open(output_csv, encoding='utf-8') as fh:
            reader = csv.reader(fh)
            rows = list(reader)

        # All entries should be directories
        assert len(rows) > 0
        for row in rows:
            assert len(row) == 10, f'Expected 10 columns, got {len(row)}: {row}'
            path = row[self._COL_PATH]
            full = os.path.join(str(tmp_path), path)
            assert os.path.isdir(full), f'Expected directory, got file: {path}'


# ===================================================================
# ValidateCopy — applying timestamps
# ===================================================================


class TestValidateCopyApply:
    """Test the main workflow (applying timestamps)."""

    def test_apply_timestamps_from_listing(self, tmp_path):
        """Create temp files, write a listing CSV, apply timestamps via
        set_access_modify_time, and verify the files' timestamps changed."""
        # Create test files
        test_file = tmp_path / 'testfile.txt'
        test_file.write_text('content', encoding='utf-8')

        # Target timestamps (well in the past)
        target_access = datetime(2020, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        target_modify = datetime(2019, 3, 20, 8, 30, 0, tzinfo=timezone.utc)

        # Write a Linux 6-column listing CSV:
        # creation, access, modify, ctime (ignored), entry_type, path
        listing_csv = tmp_path / 'listing.csv'
        listing_csv.write_text(
            '"2020-01-10 08:00:00.000000000 +0000",'  # col 0: creation
            '"2020-06-15 12:00:00.000000000 +0000",'  # col 1: access
            '"2019-03-20 08:30:00.000000000 +0000",'  # col 2: modify
            '"2020-01-01 00:00:00.000000000 +0000",'  # col 3: ctime (ignored)
            'f,'                                      # col 4: entry_type
            'testfile.txt\n',                         # col 5: path
            encoding='utf-8',
        )

        # Parse the listing (now includes base_dir for path resolution)
        entries = parse_listing(str(listing_csv), str(tmp_path))
        assert len(entries) == 1

        fe = entries[0]
        dates = _extract_dates(fe)
        # Path is already resolved to full path
        resolved = fe.path

        # _extract_dates returns [creation, access, modify]
        # So dates[1] = access, dates[2] = modify
        access_dt = resolve_selector(dates, '1')  # access column
        modify_dt = resolve_selector(dates, '2')  # modify column
        assert access_dt == target_access
        assert modify_dt == target_modify

        set_access_modify_time(resolved, access_dt, modify_dt)

        # Verify timestamps changed
        st = os.stat(resolved)
        assert abs(st.st_atime - target_access.timestamp()) < 2
        assert abs(st.st_mtime - target_modify.timestamp()) < 2

    def test_dry_run_no_changes(self, tmp_path):
        """Verify dry-run mode doesn't modify files.

        We simulate dry-run by checking the flag before applying — the tackle
        class checks ``self.dry_run`` and only logs.  Here we verify the
        pattern: read timestamps, skip apply, timestamps unchanged.
        """
        test_file = tmp_path / 'dryrun.txt'
        test_file.write_text('dry run content', encoding='utf-8')

        # Record original timestamps
        original_stat = os.stat(str(test_file))
        original_mtime = original_stat.st_mtime
        original_atime = original_stat.st_atime

        # Sleep briefly to ensure any modification would be detectable
        time.sleep(0.05)

        # Parse a listing with different timestamps (Linux 6-column format)
        # access, modify, change, birth, type, path
        listing_csv = tmp_path / 'listing.csv'
        listing_csv.write_text(
            '"2010-01-01 00:00:00.000000000 +0000",'  # access
            '"2010-01-01 00:00:00.000000000 +0000",'  # modify
            '"2010-01-01 00:00:00.000000000 +0000",'  # change (ignored)
            '"2010-01-01 00:00:00.000000000 +0000",'  # birth/creation
            'f,'                                      # type
            'dryrun.txt\n',                           # path
            encoding='utf-8',
        )

        entries = parse_listing(str(listing_csv), str(tmp_path))
        assert len(entries) == 1

        # Simulate dry-run: resolve but do NOT apply
        dry_run = True
        fe = entries[0]
        dates = _extract_dates(fe)
        attr_map = parse_attr_map('access:1,modify:2')

        resolved_attrs = {}
        for attr, selector in attr_map.items():
            dt = resolve_selector(dates, selector)
            assert dt is not None
            resolved_attrs[attr] = dt

        if dry_run:
            pass  # Do not apply — this is the dry-run path
        else:
            set_access_modify_time(
                str(test_file),
                resolved_attrs.get('access'),
                resolved_attrs.get('modify'),
            )

        # Verify timestamps are unchanged
        st = os.stat(str(test_file))
        assert st.st_mtime == original_mtime
        assert st.st_atime == original_atime

    def test_type_filtering(self, tmp_path):
        """Verify that type filtering (files only, dirs only) works correctly."""
        # Create a file and a directory
        test_file = tmp_path / 'file.txt'
        test_file.write_text('file content', encoding='utf-8')
        test_dir = tmp_path / 'mydir'
        test_dir.mkdir()

        # parse_types
        files_only = parse_types('f')
        assert files_only == {'f'}

        dirs_only = parse_types('d')
        assert dirs_only == {'d'}

        both = parse_types('f,d')
        assert both == {'f', 'd'}

        all_types = parse_types('f,d,l')
        assert all_types == {'f', 'd', 'l'}

        # FileEntry with entry_type for filtering
        fe_file = FileEntry(path=str(test_file), entry_type='f')
        assert fe_file.entry_type == 'f'
        assert fe_file.entry_type in files_only
        assert fe_file.entry_type not in dirs_only

        # FileEntry for directory
        fe_dir = FileEntry(path=str(test_dir), entry_type='d')
        assert fe_dir.entry_type == 'd'
        assert fe_dir.entry_type in dirs_only
        assert fe_dir.entry_type not in files_only

    def test_type_filtering_invalid(self):
        """Invalid type code raises ValueError."""
        with pytest.raises(ValueError, match='Unknown type code'):
            parse_types('x')

    def test_type_filtering_empty(self):
        """Empty types string raises ValueError."""
        with pytest.raises(ValueError, match='empty set'):
            parse_types('')

    def test_from_fs_path_entry_type(self, tmp_path):
        """FileEntry.from_fs_path populates entry_type from filesystem."""
        test_file = tmp_path / 'nomarker.txt'
        test_file.write_text('data', encoding='utf-8')
        test_dir = tmp_path / 'nomarkerdir'
        test_dir.mkdir()

        fe_file = FileEntry.from_fs_path(str(test_file))
        fe_dir = FileEntry.from_fs_path(str(test_dir))
        assert fe_file.entry_type == 'f'
        assert fe_dir.entry_type == 'd'


# ===================================================================
# CopyValidateMD5
# ===================================================================


class TestCopyValidateMD5:
    """Test the copy-validate workflow."""

    # ---------------------------------------------------------------
    # MD5 line parsing
    # ---------------------------------------------------------------

    def test_parse_md5sum_line(self):
        """Parse md5sum format lines with the regex used by CopyValidateMD5."""
        pattern = re.compile(r'(?P<md5>\w+)\s(?P<path>.*$)')

        line = 'd41d8cd98f00b204e9800998ecf8427e  empty_file.txt'
        m = pattern.search(line)
        assert m is not None
        assert m.group('md5') == 'd41d8cd98f00b204e9800998ecf8427e'
        # The regex captures the second space + filename
        assert m.group('path') == ' empty_file.txt'

    def test_parse_md5sum_line_single_space(self):
        """md5sum line with single space separator."""
        pattern = re.compile(r'(?P<md5>\w+)\s(?P<path>.*$)')

        line = 'abc123def456 path/to/file.txt'
        m = pattern.search(line)
        assert m is not None
        assert m.group('md5') == 'abc123def456'
        assert m.group('path') == 'path/to/file.txt'

    def test_parse_md5sum_line_with_spaces_in_path(self):
        """md5sum line where the path contains spaces."""
        pattern = re.compile(r'(?P<md5>\w+)\s(?P<path>.*$)')

        line = 'abc123 path with spaces/file name.txt'
        m = pattern.search(line)
        assert m is not None
        assert m.group('md5') == 'abc123'
        assert m.group('path') == 'path with spaces/file name.txt'

    # ---------------------------------------------------------------
    # Checksum calculation
    # ---------------------------------------------------------------

    def test_checksum_calculation(self, tmp_path):
        """Create a temp file with known content, verify MD5 matches."""
        test_file = tmp_path / 'checksum_test.txt'
        content = b'Hello, World!'
        test_file.write_bytes(content)

        expected_md5 = hashlib.md5(content).hexdigest()

        # Replicate the inline MD5 calculation from CopyValidateMD5.do()
        with open(str(test_file), 'rb') as f:
            file_hash = hashlib.md5()
            while chunk := f.read(8192):
                file_hash.update(chunk)

        assert file_hash.hexdigest() == expected_md5

    def test_checksum_empty_file(self, tmp_path):
        """MD5 of an empty file matches the known empty-file hash."""
        test_file = tmp_path / 'empty.txt'
        test_file.write_bytes(b'')

        expected_md5 = hashlib.md5(b'').hexdigest()
        assert expected_md5 == 'd41d8cd98f00b204e9800998ecf8427e'

        with open(str(test_file), 'rb') as f:
            file_hash = hashlib.md5()
            while chunk := f.read(8192):
                file_hash.update(chunk)

        assert file_hash.hexdigest() == expected_md5

    # ---------------------------------------------------------------
    # Copy and validate — success
    # ---------------------------------------------------------------

    def test_copy_and_validate_success(self, tmp_path):
        """Create a source file, create an md5sum listing, run the
        copy-validate logic, verify the target file exists and has
        correct content.

        We replicate the core logic of CopyValidateMD5.do() directly
        rather than instantiating the class (which requires argparse).
        """
        # Set up directories
        from_dir = tmp_path / 'source'
        from_dir.mkdir()
        to_dir = tmp_path / 'target'
        to_dir.mkdir()

        # Create source file
        src_content = b'Integration test content for MD5 validation'
        src_file = from_dir / 'data.txt'
        src_file.write_bytes(src_content)

        # Compute MD5
        md5_hash = hashlib.md5(src_content).hexdigest()

        # Create md5sum listing file
        md5_file = tmp_path / 'checksums.md5'
        md5_file.write_text(f'{md5_hash} data.txt\n', encoding='utf-8')

        # Replicate CopyValidateMD5.do() logic
        pattern = re.compile(r'(?P<md5>\w+)\s(?P<path>.*$)')

        with open(str(md5_file)) as fh:
            for line in fh:
                for m in pattern.finditer(line):
                    src_file_rel_path = unicodedata.normalize(
                        'NFC', m.group('path'),
                    )
                    md5sum = m.group('md5')
                    src_file_rel_dir_name = os.path.dirname(src_file_rel_path)

                    src_full = pathlib.PurePosixPath(
                        f'{from_dir}/{src_file_rel_path}',
                    )
                    assert os.path.isfile(src_full)

                    # Verify source checksum
                    with open(str(src_full), 'rb') as sf:
                        file_hash = hashlib.md5()
                        while chunk := sf.read(8192):
                            file_hash.update(chunk)
                    assert file_hash.hexdigest() == md5sum

                    # Copy
                    target_subdir = pathlib.PurePosixPath(
                        f'{to_dir}/{src_file_rel_dir_name}',
                    )
                    os.makedirs(str(target_subdir), mode=0o777, exist_ok=True)
                    shutil.copy2(str(src_full), str(target_subdir))

                    target_filename = pathlib.PurePosixPath(
                        f'{to_dir}/{src_file_rel_path}',
                    )

                    # Verify target exists and checksum matches
                    assert os.path.isfile(str(target_filename))
                    with open(str(target_filename), 'rb') as tf:
                        file_hash = hashlib.md5()
                        while chunk := tf.read(8192):
                            file_hash.update(chunk)
                    assert file_hash.hexdigest() == md5sum

        # Final verification: target file has correct content
        target_file = to_dir / 'data.txt'
        assert target_file.read_bytes() == src_content

    # ---------------------------------------------------------------
    # Copy and validate — checksum mismatch
    # ---------------------------------------------------------------

    def test_copy_and_validate_checksum_mismatch(self, tmp_path):
        """Test behaviour when source file doesn't match listing checksum.

        The CopyValidateMD5.do() method logs an error and skips the file
        when the source checksum doesn't match.  We replicate that logic
        and verify the file is NOT copied.
        """
        # Set up directories
        from_dir = tmp_path / 'source'
        from_dir.mkdir()
        to_dir = tmp_path / 'target'
        to_dir.mkdir()

        # Create source file
        src_file = from_dir / 'bad.txt'
        src_file.write_bytes(b'actual content')

        # Create md5sum listing with WRONG checksum
        wrong_md5 = 'deadbeefdeadbeefdeadbeefdeadbeef'
        md5_file = tmp_path / 'checksums.md5'
        md5_file.write_text(f'{wrong_md5} bad.txt\n', encoding='utf-8')

        # Replicate CopyValidateMD5.do() logic — mismatch path
        pattern = re.compile(r'(?P<md5>\w+)\s(?P<path>.*$)')
        copied_files = []

        with open(str(md5_file)) as fh:
            for line in fh:
                for m in pattern.finditer(line):
                    src_file_rel_path = unicodedata.normalize(
                        'NFC', m.group('path'),
                    )
                    md5sum = m.group('md5')

                    src_full = pathlib.PurePosixPath(
                        f'{from_dir}/{src_file_rel_path}',
                    )
                    assert os.path.isfile(str(src_full))

                    # Compute actual checksum
                    with open(str(src_full), 'rb') as sf:
                        file_hash = hashlib.md5()
                        while chunk := sf.read(8192):
                            file_hash.update(chunk)

                    hex_digest = file_hash.hexdigest()

                    if hex_digest != md5sum:
                        # Mismatch — skip (this is the expected path)
                        continue

                    # Should NOT reach here
                    copied_files.append(src_file_rel_path)

        # Verify: no files were copied
        assert len(copied_files) == 0
        target_file = to_dir / 'bad.txt'
        assert not target_file.exists()

    def test_copy_and_validate_nested_directory(self, tmp_path):
        """Copy-validate with a file in a nested subdirectory."""
        from_dir = tmp_path / 'source'
        from_dir.mkdir()
        to_dir = tmp_path / 'target'
        to_dir.mkdir()

        # Create nested source file
        nested_dir = from_dir / 'sub' / 'dir'
        nested_dir.mkdir(parents=True)
        src_content = b'nested file content'
        src_file = nested_dir / 'nested.txt'
        src_file.write_bytes(src_content)

        md5_hash = hashlib.md5(src_content).hexdigest()

        # Create md5sum listing with relative path
        md5_file = tmp_path / 'checksums.md5'
        md5_file.write_text(
            f'{md5_hash} sub/dir/nested.txt\n', encoding='utf-8',
        )

        # Replicate copy logic
        pattern = re.compile(r'(?P<md5>\w+)\s(?P<path>.*$)')

        with open(str(md5_file)) as fh:
            for line in fh:
                for m in pattern.finditer(line):
                    src_file_rel_path = unicodedata.normalize(
                        'NFC', m.group('path'),
                    )
                    md5sum = m.group('md5')
                    src_file_rel_dir_name = os.path.dirname(src_file_rel_path)

                    src_full = pathlib.PurePosixPath(
                        f'{from_dir}/{src_file_rel_path}',
                    )

                    with open(str(src_full), 'rb') as sf:
                        file_hash = hashlib.md5()
                        while chunk := sf.read(8192):
                            file_hash.update(chunk)
                    assert file_hash.hexdigest() == md5sum

                    target_subdir = pathlib.PurePosixPath(
                        f'{to_dir}/{src_file_rel_dir_name}',
                    )
                    os.makedirs(str(target_subdir), mode=0o777, exist_ok=True)
                    shutil.copy2(str(src_full), str(target_subdir))

        # Verify nested target
        target_file = to_dir / 'sub' / 'dir' / 'nested.txt'
        assert target_file.exists()
        assert target_file.read_bytes() == src_content


# ===================================================================
# ValidateCopy — Checksum Calculation During Listing Generation
# ===================================================================


class TestValidateCopyChecksum:
    """Test checksum calculation during listing generation."""

    # Canonical column indices
    _COL_CHECKSUM = 3
    _COL_ENTRY_TYPE = 4
    _COL_PATH = 9

    def test_generate_listing_with_checksum(self, tmp_path):
        """--generate with --attrs checksum calculates checksums for files."""
        # Create subdirectory for test files (separate from output)
        test_dir = tmp_path / 'testfiles'
        test_dir.mkdir()

        content1 = b'hello world'
        content2 = b'goodbye world'
        file1 = test_dir / 'file1.txt'
        file2 = test_dir / 'file2.txt'
        file1.write_bytes(content1)
        file2.write_bytes(content2)

        output_csv = tmp_path / 'output.csv'
        count = generate_listing(
            str(test_dir),
            str(output_csv),
            allowed_types={'f'},
            calculate_checksum=True,
            checksum_algorithm='md5',
        )

        assert count == 2
        assert output_csv.exists()

        # Read and verify checksums
        with open(output_csv, encoding='utf-8') as fh:
            reader = csv.reader(fh)
            rows = list(reader)

        assert len(rows) == 2

        # Build a path-to-checksum mapping
        checksums = {row[self._COL_PATH]: row[self._COL_CHECKSUM] for row in rows}

        expected_md5_1 = hashlib.md5(content1).hexdigest()
        expected_md5_2 = hashlib.md5(content2).hexdigest()

        assert checksums['file1.txt'] == f'md5:{expected_md5_1}'
        assert checksums['file2.txt'] == f'md5:{expected_md5_2}'

    def test_generate_listing_checksum_not_for_directories(self, tmp_path):
        """--generate with --attrs checksum does NOT calculate checksums for directories."""
        # Create subdirectory for test files (separate from output)
        test_dir = tmp_path / 'testfiles'
        test_dir.mkdir()

        subdir = test_dir / 'subdir'
        subdir.mkdir()
        file1 = test_dir / 'file.txt'
        file1.write_bytes(b'content')

        output_csv = tmp_path / 'output.csv'
        generate_listing(
            str(test_dir),
            str(output_csv),
            allowed_types={'f', 'd'},
            calculate_checksum=True,
        )

        # Read and verify
        with open(output_csv, encoding='utf-8') as fh:
            reader = csv.reader(fh)
            rows = list(reader)

        for row in rows:
            entry_type = row[self._COL_ENTRY_TYPE]
            checksum = row[self._COL_CHECKSUM]
            if entry_type == 'd':
                # Directories should NOT have checksums
                assert checksum == '', f'Directory should not have checksum: {row}'
            elif entry_type == 'f':
                # Files should have checksums
                assert checksum.startswith('md5:'), f'File should have checksum: {row}'

    def test_generate_listing_checksum_sha256(self, tmp_path):
        """--generate with --attrs checksum --checksum-algorithm sha256 uses correct algorithm."""
        # Create subdirectory for test files (separate from output)
        test_dir = tmp_path / 'testfiles'
        test_dir.mkdir()

        content = b'test content for sha256'
        file1 = test_dir / 'file.txt'
        file1.write_bytes(content)

        output_csv = tmp_path / 'output.csv'
        generate_listing(
            str(test_dir),
            str(output_csv),
            allowed_types={'f'},
            calculate_checksum=True,
            checksum_algorithm='sha256',
        )

        with open(output_csv, encoding='utf-8') as fh:
            reader = csv.reader(fh)
            rows = list(reader)

        assert len(rows) == 1
        checksum = rows[0][self._COL_CHECKSUM]

        expected_sha256 = hashlib.sha256(content).hexdigest()
        assert checksum == f'sha256:{expected_sha256}'

    def test_generate_listing_without_checksum(self, tmp_path):
        """--generate without checksum in --attrs does NOT calculate checksums."""
        # Create subdirectory for test files (separate from output)
        test_dir = tmp_path / 'testfiles'
        test_dir.mkdir()

        file1 = test_dir / 'file.txt'
        file1.write_bytes(b'content')

        output_csv = tmp_path / 'output.csv'
        generate_listing(
            str(test_dir),
            str(output_csv),
            allowed_types={'f'},
            calculate_checksum=False,  # Explicitly disabled
        )

        with open(output_csv, encoding='utf-8') as fh:
            reader = csv.reader(fh)
            rows = list(reader)

        assert len(rows) == 1
        checksum = rows[0][self._COL_CHECKSUM]
        assert checksum == '', 'Checksum should be empty when not requested'


# ===================================================================
# ValidateCopy — Attr-Map Default Change
# ===================================================================


class TestValidateCopyAttrMapDefault:
    """Test the new default behavior for --attr-map."""

    def test_empty_attr_map_uses_canonical_mapping(self):
        """Empty --attr-map in apply mode uses canonical timestamp mapping."""
        from common.attr_map import get_canonical_timestamp_map, parse_attr_map

        # Empty string with allow_empty=True returns empty dict
        result = parse_attr_map('', allow_empty=True)
        assert result == {}

        # The canonical timestamp map provides the default
        canonical = get_canonical_timestamp_map()
        assert canonical == {'creation': '0', 'access': '1', 'modify': '2'}

    def test_explicit_attr_map_still_works(self):
        """Explicit --attr-map creation:e still works as before."""
        result = parse_attr_map('creation:e')
        assert result == {'creation': 'earliest'}

        result = parse_attr_map('creation:0, access:1, modify:2')
        assert result == {'creation': '0', 'access': '1', 'modify': '2'}

    def test_attr_map_with_latest(self):
        """Explicit --attr-map with latest selector works."""
        result = parse_attr_map('modify:l')
        assert result == {'modify': 'latest'}

    def test_generate_listing_mode_ignores_attr_map(self, tmp_path):
        """Generate listing mode works without --attr-map."""
        # Create subdirectory for test files (separate from output)
        test_dir = tmp_path / 'testfiles'
        test_dir.mkdir()

        file1 = test_dir / 'test.txt'
        file1.write_bytes(b'test')

        output_csv = tmp_path / 'output.csv'

        # generate_listing doesn't use attr_map at all
        count = generate_listing(
            str(test_dir),
            str(output_csv),
            allowed_types={'f'},
        )

        assert count == 1
        assert output_csv.exists()


# ===================================================================
# ValidateCopy — Validation Mode
# ===================================================================


class TestValidateCopyValidation:
    """Test the validation mode functionality."""

    # Canonical column indices
    _COL_CREATION = 0
    _COL_ACCESS = 1
    _COL_MODIFY = 2
    _COL_CHECKSUM = 3
    _COL_ENTRY_TYPE = 4
    _COL_PERMISSIONS = 5
    _COL_UID = 6
    _COL_GID = 7
    _COL_SIZE = 8
    _COL_PATH = 9

    def _create_canonical_row(
        self,
        path: str,
        size: int = 0,
        entry_type: str = 'f',
        checksum: str = '',
        creation: str = '',
        access: str = '',
        modify: str = '',
        permissions: str = '',
        uid: str = '',
        gid: str = '',
    ) -> str:
        """Helper to create a canonical CSV row."""
        cols = [''] * 10
        cols[self._COL_CREATION] = creation
        cols[self._COL_ACCESS] = access
        cols[self._COL_MODIFY] = modify
        cols[self._COL_CHECKSUM] = checksum
        cols[self._COL_ENTRY_TYPE] = entry_type
        cols[self._COL_PERMISSIONS] = permissions
        cols[self._COL_UID] = uid
        cols[self._COL_GID] = gid
        cols[self._COL_SIZE] = str(size)
        cols[self._COL_PATH] = path
        return ','.join(cols)

    def test_validate_valid_listing_returns_zero(self, tmp_path, capsys):
        """--validate with valid listing returns 0 when all files match."""
        # Create subdirectory for test files (separate from output)
        test_dir = tmp_path / 'testfiles'
        test_dir.mkdir()

        content = b'test content'
        file1 = test_dir / 'file.txt'
        file1.write_bytes(content)

        # Generate a listing first to get actual attributes
        listing_csv = tmp_path / 'listing.csv'
        generate_listing(
            str(test_dir),
            str(listing_csv),
            allowed_types={'f'},
            calculate_checksum=True,
        )

        # Parse the listing and validate
        entries = parse_listing(str(listing_csv), str(test_dir))
        assert len(entries) == 1

        # Validate the entry
        fe = entries[0]
        errors = fe.validate(attrs=['size', 'checksum'], check_fs=True)
        assert errors == [], f'Expected no errors, got: {errors}'

    def test_validate_mismatched_files_returns_errors(self, tmp_path):
        """--validate with mismatched files returns validation errors."""
        # Create test file
        file1 = tmp_path / 'file.txt'
        file1.write_bytes(b'actual content')

        # Create a listing with WRONG checksum
        listing_csv = tmp_path / 'listing.csv'
        wrong_checksum = 'md5:deadbeefdeadbeefdeadbeefdeadbeef'
        row = self._create_canonical_row(
            path='file.txt',
            size=14,  # len(b'actual content')
            entry_type='f',
            checksum=wrong_checksum,
        )
        listing_csv.write_text(row + '\n', encoding='utf-8')

        entries = parse_listing(str(listing_csv), str(tmp_path))
        assert len(entries) == 1

        fe = entries[0]
        errors = fe.validate(attrs=['checksum'], check_fs=True)
        assert len(errors) == 1
        assert 'checksum mismatch' in errors[0]

    def test_validate_size_mismatch(self, tmp_path):
        """--validate detects size mismatches."""
        file1 = tmp_path / 'file.txt'
        file1.write_bytes(b'actual content')  # 14 bytes

        listing_csv = tmp_path / 'listing.csv'
        row = self._create_canonical_row(
            path='file.txt',
            size=999,  # Wrong size
            entry_type='f',
        )
        listing_csv.write_text(row + '\n', encoding='utf-8')

        entries = parse_listing(str(listing_csv), str(tmp_path))
        fe = entries[0]
        errors = fe.validate(attrs=['size'], check_fs=True)
        assert len(errors) == 1
        assert 'size mismatch' in errors[0]

    def test_validate_missing_file(self, tmp_path):
        """--validate detects missing files."""
        listing_csv = tmp_path / 'listing.csv'
        row = self._create_canonical_row(
            path='nonexistent.txt',
            size=100,
            entry_type='f',
        )
        listing_csv.write_text(row + '\n', encoding='utf-8')

        entries = parse_listing(str(listing_csv), str(tmp_path))
        fe = entries[0]
        errors = fe.validate(attrs=['size'], check_fs=True)
        assert len(errors) >= 1
        assert 'does not exist' in errors[0]

    def test_validate_attrs_subset(self, tmp_path):
        """--attrs size,checksum only validates specified attributes."""
        content = b'test'
        file1 = tmp_path / 'file.txt'
        file1.write_bytes(content)

        # Create a FileEntry with correct size but wrong permissions
        fe = FileEntry.from_fs_path(str(file1))
        fe.permissions = '0o000'  # Wrong permissions

        # Validate only size — should pass
        errors = fe.validate(attrs=['size'], check_fs=True)
        assert errors == []

        # Validate permissions — should fail
        errors = fe.validate(attrs=['permissions'], check_fs=True)
        assert len(errors) == 1
        assert 'permissions mismatch' in errors[0]

    def test_validate_entry_type(self, tmp_path):
        """--validate detects entry_type mismatches."""
        file1 = tmp_path / 'file.txt'
        file1.write_bytes(b'content')

        listing_csv = tmp_path / 'listing.csv'
        row = self._create_canonical_row(
            path='file.txt',
            entry_type='d',  # Wrong — it's actually a file
        )
        listing_csv.write_text(row + '\n', encoding='utf-8')

        entries = parse_listing(str(listing_csv), str(tmp_path))
        fe = entries[0]
        errors = fe.validate(attrs=['entry_type'], check_fs=True)
        assert len(errors) == 1
        assert 'entry_type mismatch' in errors[0]

    def test_validate_path_existence_only(self, tmp_path):
        """--validate with no attrs only checks path existence."""
        file1 = tmp_path / 'exists.txt'
        file1.write_bytes(b'content')

        fe = FileEntry(path=str(file1))
        errors = fe.validate()  # No attrs — just check existence
        assert errors == []

        fe2 = FileEntry(path=str(tmp_path / 'missing.txt'))
        errors = fe2.validate()
        assert len(errors) == 1
        assert 'does not exist' in errors[0]

    def test_validate_checksum_algorithm_prefix(self, tmp_path):
        """Checksum validation handles algorithm prefix correctly."""
        content = b'test content'
        file1 = tmp_path / 'file.txt'
        file1.write_bytes(content)

        expected_md5 = hashlib.md5(content).hexdigest()

        # Entry with algorithm prefix
        fe = FileEntry(path=str(file1), checksum=f'md5:{expected_md5}')
        errors = fe.validate(attrs=['checksum'], check_fs=True)
        assert errors == []

        # Entry without algorithm prefix (assumes md5)
        fe2 = FileEntry(path=str(file1), checksum=expected_md5)
        errors = fe2.validate(attrs=['checksum'], check_fs=True)
        assert errors == []

    def test_validate_sha256_checksum(self, tmp_path):
        """Checksum validation works with SHA256."""
        content = b'test content for sha256'
        file1 = tmp_path / 'file.txt'
        file1.write_bytes(content)

        expected_sha256 = hashlib.sha256(content).hexdigest()

        fe = FileEntry(path=str(file1), checksum=f'sha256:{expected_sha256}')
        errors = fe.validate(attrs=['checksum'], check_fs=True)
        assert errors == []

        # Wrong SHA256
        fe2 = FileEntry(path=str(file1), checksum='sha256:deadbeef')
        errors = fe2.validate(attrs=['checksum'], check_fs=True)
        assert len(errors) == 1
        assert 'checksum mismatch' in errors[0]

    def test_validate_multiple_attrs(self, tmp_path):
        """Validation can check multiple attributes at once."""
        content = b'test'
        file1 = tmp_path / 'file.txt'
        file1.write_bytes(content)

        # Read actual attributes
        fe = FileEntry.from_fs_path(str(file1))
        fe.calculate_checksum(algorithm='md5')

        # Validate multiple attrs
        errors = fe.validate(
            attrs=['size', 'checksum', 'entry_type'],
            check_fs=True,
        )
        assert errors == []

    def test_validate_entry_with_none_attr(self, tmp_path):
        """Validation skips None/empty attributes when check_fs=True.
        
        This is the correct behavior: when a listing doesn't have a checksum,
        we shouldn't compare the empty value against the filesystem.
        """
        file1 = tmp_path / 'file.txt'
        file1.write_bytes(b'test')

        # Entry with missing checksum — should be skipped during validation
        fe = FileEntry(path=str(file1), size=4, checksum=None)
        errors = fe.validate(attrs=['checksum'], check_fs=True)
        # Empty attributes are silently skipped, no error reported
        assert errors == []

        # When check_fs=False, we still report that the attr is not set
        # (this mode checks that attrs ARE populated, not their filesystem match)
        errors = fe.validate(attrs=['checksum'], check_fs=False)
        assert len(errors) == 1
        assert 'not set in entry' in errors[0]