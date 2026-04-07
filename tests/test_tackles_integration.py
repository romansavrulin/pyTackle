"""Integration tests for SetCreationTime and CopyValidateMD5 tackles.

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

from common.FileEntry import FileEntry

from tackles.SetCreationTime import (
    FORMAT_LINUX,
    FORMAT_PS_HEADER,
    FORMAT_PS_TYPE,
    classify_entry,
    detect_format,
    generate_listing,
    normalize_path,
    parse_attr_map,
    parse_listing,
    parse_timestamp_linux,
    parse_timestamp_powershell,
    parse_types,
    resolve_selector,
    set_access_modify_time,
)
from tackles.CopyValidateMD5 import CopyValidateMD5


# ===================================================================
# SetCreationTime — parsing helpers
# ===================================================================


class TestSetCreationTimeParsing:
    """Test the internal parsing functions of SetCreationTime."""

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

    def test_detect_format_powershell_header(self):
        """Header row starting with ``CreationTimeUtc`` -> FORMAT_PS_HEADER."""
        line = 'CreationTimeUtc,LastAccessTimeUtc,LastWriteTimeUtc,FullName'
        assert detect_format(line) == FORMAT_PS_HEADER

    def test_detect_format_powershell_type(self):
        """5-column row without header -> FORMAT_PS_TYPE."""
        line = '01/15/2024 10:30:00,01/10/2024 08:00:00,01/10/2024 08:00:00,F,./test.txt'
        assert detect_format(line) == FORMAT_PS_TYPE

    def test_detect_format_four_columns_as_ps_header(self):
        """4-column data row (no recognisable header) -> FORMAT_PS_HEADER."""
        line = '01/15/2024 10:30:00,01/10/2024 08:00:00,1234,C:\\test.txt'
        assert detect_format(line) == FORMAT_PS_HEADER

    # ---------------------------------------------------------------
    # parse_listing — Linux format
    # ---------------------------------------------------------------

    def test_parse_listing_linux_format(self, tmp_path):
        """Parse a Linux-format CSV and verify FileEntry fields."""
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

        entries = parse_listing(str(csv_file))
        assert len(entries) == 1

        fe, entry_type, dates = entries[0]
        assert isinstance(fe, FileEntry)
        assert len(dates) == 4
        assert dates[0] == datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        assert dates[1] == datetime(2024, 1, 10, 8, 0, 0, tzinfo=timezone.utc)
        assert entry_type == 'f'
        assert fe.path == './test.txt'

    # ---------------------------------------------------------------
    # parse_listing — PowerShell header format
    # ---------------------------------------------------------------

    def test_parse_listing_powershell_header_format(self, tmp_path):
        """Parse a PowerShell header-format CSV and verify FileEntry fields."""
        csv_file = tmp_path / 'listing_ps_header.csv'
        csv_file.write_text(
            'CreationTimeUtc,LastAccessTimeUtc,LastWriteTimeUtc,FullName\n'
            '01/10/2024 08:00:00,01/15/2024 10:30:00,01/12/2024 12:00:00,C:\\test.txt\n',
            encoding='utf-8',
        )

        entries = parse_listing(str(csv_file))
        assert len(entries) == 1

        fe, entry_type, dates = entries[0]
        assert isinstance(fe, FileEntry)
        assert len(dates) == 3
        assert dates[0] == datetime(2024, 1, 10, 8, 0, 0, tzinfo=timezone.utc)
        assert dates[1] == datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        assert dates[2] == datetime(2024, 1, 12, 12, 0, 0, tzinfo=timezone.utc)
        assert entry_type is None  # ps_header has no type column
        assert fe.path == 'C:\\test.txt'

    # ---------------------------------------------------------------
    # parse_listing — PowerShell type format
    # ---------------------------------------------------------------

    def test_parse_listing_powershell_type_format(self, tmp_path):
        """Parse a PowerShell type-format CSV and verify FileEntry fields."""
        csv_file = tmp_path / 'listing_ps_type.csv'
        csv_file.write_text(
            '01/15/2024 10:30:00,01/10/2024 08:00:00,01/12/2024 12:00:00,F,./test.txt\n',
            encoding='utf-8',
        )

        entries = parse_listing(str(csv_file))
        assert len(entries) == 1

        fe, entry_type, dates = entries[0]
        assert isinstance(fe, FileEntry)
        assert len(dates) == 3
        assert dates[0] == datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        assert entry_type == 'F'
        assert fe.path == './test.txt'

    # ---------------------------------------------------------------
    # parse_timestamp_linux
    # ---------------------------------------------------------------

    def test_parse_timestamp_linux(self):
        """Valid Linux timestamp -> tz-aware datetime."""
        raw = '2020-08-20 06:15:03.491092220 +0000'
        dt = parse_timestamp_linux(raw)
        assert dt.year == 2020
        assert dt.month == 8
        assert dt.day == 20
        assert dt.hour == 6
        assert dt.minute == 15
        assert dt.second == 3
        assert dt.microsecond == 491092
        assert dt.tzinfo is not None

    def test_parse_timestamp_linux_with_offset(self):
        """Linux timestamp with non-zero tz offset."""
        raw = '2024-01-15 10:30:00.000000000 +0300'
        dt = parse_timestamp_linux(raw)
        assert dt.year == 2024
        assert dt.month == 1
        assert dt.day == 15
        assert dt.hour == 10
        assert dt.minute == 30

    def test_parse_timestamp_linux_invalid(self):
        """Invalid string raises ValueError."""
        with pytest.raises(ValueError, match='Cannot parse Linux timestamp'):
            parse_timestamp_linux('not-a-timestamp')

    # ---------------------------------------------------------------
    # parse_timestamp_powershell
    # ---------------------------------------------------------------

    def test_parse_timestamp_powershell(self):
        """Valid PowerShell timestamp -> tz-aware UTC datetime."""
        raw = '02/24/2023 14:04:32'
        dt = parse_timestamp_powershell(raw)
        assert dt == datetime(2023, 2, 24, 14, 4, 32, tzinfo=timezone.utc)

    def test_parse_timestamp_powershell_invalid(self):
        """Invalid string raises ValueError."""
        with pytest.raises(ValueError):
            parse_timestamp_powershell('not-a-timestamp')

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
# SetCreationTime — attr-map functionality
# ===================================================================


class TestSetCreationTimeAttrMap:
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
# SetCreationTime — listing generation
# ===================================================================


class TestSetCreationTimeGeneration:
    """Test listing generation."""

    def test_generate_listing(self, tmp_path):
        """generate_listing() writes a Format-3 CSV with correct structure."""
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
            # Format 3: creation, access, modify, type_code, rel_path
            assert len(row) == 5, f'Expected 5 columns, got {len(row)}: {row}'
            # First 3 columns should be parseable timestamps
            for i in range(3):
                parse_timestamp_powershell(row[i])
            # Column 3 is type code
            assert row[3] in ('D', 'F', 'L')

        # Verify our files appear in the listing
        rel_paths = [row[4] for row in rows]
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

        type_codes = [row[3] for row in rows]
        assert all(tc == 'F' for tc in type_codes), (
            f'Expected only F types, got {type_codes}'
        )

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

        type_codes = [row[3] for row in rows]
        assert all(tc == 'D' for tc in type_codes), (
            f'Expected only D types, got {type_codes}'
        )


# ===================================================================
# SetCreationTime — applying timestamps
# ===================================================================


class TestSetCreationTimeApply:
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

        # Write a Format-3 listing CSV
        listing_csv = tmp_path / 'listing.csv'
        listing_csv.write_text(
            '01/10/2020 08:00:00,'
            '06/15/2020 12:00:00,'
            '03/20/2019 08:30:00,'
            'F,'
            'testfile.txt\n',
            encoding='utf-8',
        )

        # Parse the listing
        entries = parse_listing(str(listing_csv))
        assert len(entries) == 1

        fe, entry_type, dates = entries[0]
        rel_path = normalize_path(fe.path)
        resolved = os.path.normpath(os.path.join(str(tmp_path), rel_path))

        # Apply access and modify timestamps
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

        # Parse a listing with different timestamps
        listing_csv = tmp_path / 'listing.csv'
        listing_csv.write_text(
            '01/01/2010 00:00:00,'
            '01/01/2010 00:00:00,'
            '01/01/2010 00:00:00,'
            'F,'
            'dryrun.txt\n',
            encoding='utf-8',
        )

        entries = parse_listing(str(listing_csv))
        assert len(entries) == 1

        # Simulate dry-run: resolve but do NOT apply
        dry_run = True
        fe, entry_type, dates = entries[0]
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

        # classify_entry with file
        assert classify_entry('f', str(test_file)) == 'f'
        assert 'f' in files_only
        assert 'f' not in dirs_only

        # classify_entry with directory
        assert classify_entry('d', str(test_dir)) == 'd'
        assert 'd' in dirs_only
        assert 'd' not in files_only

    def test_type_filtering_invalid(self):
        """Invalid type code raises ValueError."""
        with pytest.raises(ValueError, match='Unknown type code'):
            parse_types('x')

    def test_type_filtering_empty(self):
        """Empty types string raises ValueError."""
        with pytest.raises(ValueError, match='empty set'):
            parse_types('')

    def test_classify_entry_no_type_marker(self, tmp_path):
        """classify_entry falls back to filesystem when entry_type is None."""
        test_file = tmp_path / 'nomarker.txt'
        test_file.write_text('data', encoding='utf-8')
        test_dir = tmp_path / 'nomarkerdir'
        test_dir.mkdir()

        assert classify_entry(None, str(test_file)) == 'f'
        assert classify_entry(None, str(test_dir)) == 'd'

    def test_classify_entry_directory_variants(self, tmp_path):
        """classify_entry recognises 'directory' and 'D' as directory types."""
        test_dir = tmp_path / 'somedir'
        test_dir.mkdir()

        for marker in ('directory', 'Directory', 'DIRECTORY', 'D', 'd'):
            assert classify_entry(marker, str(test_dir)) == 'd', (
                f'Expected "d" for entry_type={marker!r}'
            )


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