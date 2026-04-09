"""Tests for tackles/FclonesDuplicates.py."""

from __future__ import annotations

import csv
import io
import os
import tempfile
from typing import Generator

import pytest

from common.FileEntry import FileEntry
from tackles.FclonesDuplicates import (
    DuplicateGroup,
    ReportMetadata,
    RE_GROUP_HEADER,
    RE_PATH_LINE,
    RE_FCLONES_VERSION,
    RE_TIMESTAMP,
    RE_COMMAND,
    RE_BASE_DIR,
    RE_TOTAL,
    RE_REDUNDANT,
    RE_MISSING,
    normalize_fclones_path,
    parse_header_line,
    parse_fclones_report,
    duplicate_group_to_entries,
    generate_entries_from_report,
)


# ---------------------------------------------------------------------------
# Sample test data
# ---------------------------------------------------------------------------

SAMPLE_REPORT = '''# Report by fclones 0.35.0
# Timestamp: 2026-03-30 04:31:29.522 +0300
# Command: '.\\fclones.exe' group --no-ignore --hidden 'Q:\\1T-0-no-recycle-skip-err'
# Base dir: Q:\\\\
# Total: 1268686168746 B (1.3 TB) in 62263 files in 29099 groups
# Redundant: 652430768023 B (652.4 GB) in 33164 files
# Missing: 0 B (0 B) in 0 files
8593af76cd7c0818f0e6f8c0c3cc0e7d, 10248846420 B (10.2 GB) * 2:
    Q:\\\\20T-0-no-recycle-skip-err\\\\folder\\\\GX015735.MP4
    Q:\\\\20T-0-no-recycle-skip-err\\\\folder2\\\\GX015735.MP4
aebab6d5c723236dee40b8fe466fab9f, 4515595719 B (4.5 GB) * 2:
    Q:\\\\path\\\\Папка\\\\file1.mp4
    Q:\\\\path\\\\Папка2\\\\file1.mp4
'''

SAMPLE_REPORT_HEADERS_ONLY = '''# Report by fclones 0.35.0
# Timestamp: 2026-03-30 04:31:29.522 +0300
# Command: '.\\fclones.exe' group --no-ignore --hidden 'Q:\\test'
# Base dir: Q:\\\\
# Total: 0 B (0 B) in 0 files in 0 groups
# Redundant: 0 B (0 B) in 0 files
# Missing: 0 B (0 B) in 0 files
'''

SAMPLE_REPORT_SINGLE_FILE_GROUPS = '''# Report by fclones 0.35.0
# Timestamp: 2026-03-30 04:31:29.522 +0300
# Base dir: Q:\\\\
# Total: 100 B (100 B) in 1 files in 1 groups
# Redundant: 0 B (0 B) in 0 files
# Missing: 0 B (0 B) in 0 files
abc123def456789012345678abcdef01, 100 B (100 B) * 1:
    Q:\\\\single\\\\file.txt
'''

SAMPLE_REPORT_LARGE_FILES = '''# Report by fclones 0.35.0
# Timestamp: 2026-03-30 04:31:29.522 +0300
# Base dir: Q:\\\\
# Total: 10995116277760 B (10 TB) in 2 files in 1 groups
# Redundant: 5497558138880 B (5 TB) in 1 files
# Missing: 0 B (0 B) in 0 files
deadbeefcafe1234567890abcdef0123, 5497558138880 B (5 TB) * 2:
    Q:\\\\large\\\\huge_file_1.bin
    Q:\\\\large\\\\huge_file_2.bin
'''

SAMPLE_REPORT_SPECIAL_CHARS = '''# Report by fclones 0.35.0
# Timestamp: 2026-03-30 04:31:29.522 +0300
# Base dir: Q:\\\\
# Total: 200 B (200 B) in 4 files in 2 groups
# Redundant: 100 B (100 B) in 2 files
# Missing: 0 B (0 B) in 0 files
1111111111111111111111111111111a, 100 B (100 B) * 2:
    Q:\\\\special\\\\file with spaces.txt
    Q:\\\\special\\\\file-with-dashes.txt
2222222222222222222222222222222b, 100 B (100 B) * 2:
    Q:\\\\special\\\\файл_кириллица.txt
    Q:\\\\special\\\\文件中文.txt
'''


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_report_file(tmp_path) -> Generator[str, None, None]:
    """Create a temp file with sample fclones report."""
    report_path = tmp_path / "fclones_report.txt"
    report_path.write_text(SAMPLE_REPORT, encoding='utf-8')
    yield str(report_path)


@pytest.fixture
def empty_report_file(tmp_path) -> Generator[str, None, None]:
    """Create a temp file with headers-only fclones report."""
    report_path = tmp_path / "empty_report.txt"
    report_path.write_text(SAMPLE_REPORT_HEADERS_ONLY, encoding='utf-8')
    yield str(report_path)


@pytest.fixture
def single_file_report(tmp_path) -> Generator[str, None, None]:
    """Create a temp file with single-file group report."""
    report_path = tmp_path / "single_report.txt"
    report_path.write_text(SAMPLE_REPORT_SINGLE_FILE_GROUPS, encoding='utf-8')
    yield str(report_path)


@pytest.fixture
def large_files_report(tmp_path) -> Generator[str, None, None]:
    """Create a temp file with large file sizes report."""
    report_path = tmp_path / "large_report.txt"
    report_path.write_text(SAMPLE_REPORT_LARGE_FILES, encoding='utf-8')
    yield str(report_path)


@pytest.fixture
def special_chars_report(tmp_path) -> Generator[str, None, None]:
    """Create a temp file with special characters in paths."""
    report_path = tmp_path / "special_report.txt"
    report_path.write_text(SAMPLE_REPORT_SPECIAL_CHARS, encoding='utf-8')
    yield str(report_path)


@pytest.fixture
def sample_duplicate_group() -> DuplicateGroup:
    """Create a sample DuplicateGroup for testing."""
    return DuplicateGroup(
        hash='8593af76cd7c0818f0e6f8c0c3cc0e7d',
        size=10248846420,
        count=3,
        paths=[
            'Q:/20T/folder/file1.mp4',
            'Q:/20T/folder/file2.mp4',
            'Q:/20T/folder/file3.mp4',
        ],
        group_id=1,
    )


# ===========================================================================
# A. Parser Tests
# ===========================================================================


# ---------------------------------------------------------------------------
# A.1 Header Parsing Tests
# ---------------------------------------------------------------------------

class TestParseHeaderVersion:
    """Tests for parsing fclones version line."""

    def test_parse_header_version_basic(self):
        """Parse standard version line: # Report by fclones 0.35.0"""
        m = RE_FCLONES_VERSION.match('# Report by fclones 0.35.0')
        assert m is not None
        assert m.group(1) == '0.35.0'

    def test_parse_header_version_different_versions(self):
        """Parse various version formats."""
        test_cases = [
            ('# Report by fclones 1.0.0', '1.0.0'),
            ('# Report by fclones 0.34.0-beta', '0.34.0-beta'),
            ('# Report by fclones 2.0.0-rc1', '2.0.0-rc1'),
        ]
        for line, expected in test_cases:
            m = RE_FCLONES_VERSION.match(line)
            assert m is not None, f"Failed to match: {line}"
            assert m.group(1) == expected

    def test_parse_header_version_updates_metadata(self):
        """parse_header_line correctly updates metadata.fclones_version."""
        metadata = ReportMetadata()
        result = parse_header_line('# Report by fclones 0.35.0', metadata)
        assert result is True
        assert metadata.fclones_version == '0.35.0'


class TestParseHeaderTimestamp:
    """Tests for parsing timestamp line."""

    def test_parse_header_timestamp_basic(self):
        """Parse standard timestamp: # Timestamp: 2026-03-30 04:31:29.522 +0300"""
        m = RE_TIMESTAMP.match('# Timestamp: 2026-03-30 04:31:29.522 +0300')
        assert m is not None
        assert m.group(1) == '2026-03-30 04:31:29.522 +0300'

    def test_parse_header_timestamp_utc(self):
        """Parse timestamp with UTC offset."""
        m = RE_TIMESTAMP.match('# Timestamp: 2026-03-30 04:31:29.522 +0000')
        assert m is not None
        assert '+0000' in m.group(1)

    def test_parse_header_timestamp_negative_offset(self):
        """Parse timestamp with negative UTC offset."""
        m = RE_TIMESTAMP.match('# Timestamp: 2026-03-30 04:31:29.522 -0500')
        assert m is not None
        assert '-0500' in m.group(1)

    def test_parse_header_timestamp_updates_metadata(self):
        """parse_header_line correctly updates metadata.timestamp."""
        metadata = ReportMetadata()
        result = parse_header_line('# Timestamp: 2026-03-30 04:31:29.522 +0300', metadata)
        assert result is True
        assert metadata.timestamp == '2026-03-30 04:31:29.522 +0300'


class TestParseHeaderCommand:
    """Tests for parsing command line."""

    def test_parse_header_command_basic(self):
        """Parse command line with Windows path and arguments."""
        line = "# Command: '.\\fclones.exe' group --no-ignore --hidden 'Q:\\1T-0-no-recycle-skip-err'"
        m = RE_COMMAND.match(line)
        assert m is not None
        assert 'fclones.exe' in m.group(1)
        assert '--no-ignore' in m.group(1)

    def test_parse_header_command_unix_path(self):
        """Parse command line with Unix-style path."""
        line = "# Command: /usr/bin/fclones group --hidden /data/backup"
        m = RE_COMMAND.match(line)
        assert m is not None
        assert '/usr/bin/fclones' in m.group(1)

    def test_parse_header_command_updates_metadata(self):
        """parse_header_line correctly updates metadata.command."""
        metadata = ReportMetadata()
        line = "# Command: '.\\fclones.exe' group --no-ignore --hidden"
        result = parse_header_line(line, metadata)
        assert result is True
        assert "'.\\fclones.exe'" in metadata.command


class TestParseHeaderBaseDir:
    """Tests for parsing base directory line."""

    def test_parse_header_base_dir_windows(self):
        """Parse Windows-style base directory."""
        m = RE_BASE_DIR.match('# Base dir: Q:\\\\')
        assert m is not None
        assert m.group(1) == 'Q:\\\\'

    def test_parse_header_base_dir_unix(self):
        """Parse Unix-style base directory."""
        m = RE_BASE_DIR.match('# Base dir: /home/user/data')
        assert m is not None
        assert m.group(1) == '/home/user/data'

    def test_parse_header_base_dir_updates_metadata(self):
        """parse_header_line correctly updates metadata.base_dir."""
        metadata = ReportMetadata()
        result = parse_header_line('# Base dir: Q:\\\\', metadata)
        assert result is True
        assert metadata.base_dir == 'Q:\\\\'


class TestParseHeaderStatistics:
    """Tests for parsing statistics lines (Total, Redundant, Missing)."""

    def test_parse_header_total_basic(self):
        """Parse Total statistics line."""
        line = '# Total: 1268686168746 B (1.3 TB) in 62263 files in 29099 groups'
        m = RE_TOTAL.match(line)
        assert m is not None
        assert m.group(1) == '1268686168746'  # bytes
        assert m.group(2) == '62263'          # files
        assert m.group(3) == '29099'          # groups

    def test_parse_header_total_updates_metadata(self):
        """parse_header_line correctly updates total statistics."""
        metadata = ReportMetadata()
        line = '# Total: 1268686168746 B (1.3 TB) in 62263 files in 29099 groups'
        result = parse_header_line(line, metadata)
        assert result is True
        assert metadata.total_bytes == 1268686168746
        assert metadata.total_files == 62263
        assert metadata.total_groups == 29099

    def test_parse_header_redundant_basic(self):
        """Parse Redundant statistics line."""
        line = '# Redundant: 652430768023 B (652.4 GB) in 33164 files'
        m = RE_REDUNDANT.match(line)
        assert m is not None
        assert m.group(1) == '652430768023'  # bytes
        assert m.group(2) == '33164'         # files

    def test_parse_header_redundant_updates_metadata(self):
        """parse_header_line correctly updates redundant statistics."""
        metadata = ReportMetadata()
        line = '# Redundant: 652430768023 B (652.4 GB) in 33164 files'
        result = parse_header_line(line, metadata)
        assert result is True
        assert metadata.redundant_bytes == 652430768023
        assert metadata.redundant_files == 33164

    def test_parse_header_missing_basic(self):
        """Parse Missing statistics line."""
        line = '# Missing: 0 B (0 B) in 0 files'
        m = RE_MISSING.match(line)
        assert m is not None
        assert m.group(1) == '0'  # bytes
        assert m.group(2) == '0'  # files

    def test_parse_header_missing_updates_metadata(self):
        """parse_header_line correctly updates missing statistics."""
        metadata = ReportMetadata()
        line = '# Missing: 0 B (0 B) in 0 files'
        result = parse_header_line(line, metadata)
        assert result is True
        assert metadata.missing_bytes == 0
        assert metadata.missing_files == 0

    def test_parse_header_missing_nonzero(self):
        """Parse Missing statistics with non-zero values."""
        metadata = ReportMetadata()
        line = '# Missing: 1024 B (1 KB) in 2 files'
        result = parse_header_line(line, metadata)
        assert result is True
        assert metadata.missing_bytes == 1024
        assert metadata.missing_files == 2


class TestParseHeaderLineReturns:
    """Tests for parse_header_line return values."""

    def test_parse_header_line_returns_true_for_headers(self):
        """parse_header_line returns True for any line starting with #."""
        metadata = ReportMetadata()
        assert parse_header_line('# Unknown header line', metadata) is True
        assert parse_header_line('# Some random comment', metadata) is True

    def test_parse_header_line_returns_false_for_non_headers(self):
        """parse_header_line returns False for lines not starting with #."""
        metadata = ReportMetadata()
        assert parse_header_line('abc123, 100 B * 2:', metadata) is False
        assert parse_header_line('    Q:\\\\path\\\\file.txt', metadata) is False
        assert parse_header_line('', metadata) is False


# ---------------------------------------------------------------------------
# A.2 Duplicate Group Parsing Tests
# ---------------------------------------------------------------------------

class TestParseGroupHeader:
    """Tests for parsing duplicate group header lines."""

    def test_parse_group_header_basic(self):
        """Parse standard group header: hash, size, count."""
        line = '8593af76cd7c0818f0e6f8c0c3cc0e7d, 10248846420 B (10.2 GB) * 2:'
        m = RE_GROUP_HEADER.match(line)
        assert m is not None
        assert m.group(1) == '8593af76cd7c0818f0e6f8c0c3cc0e7d'  # hash
        assert m.group(2) == '10248846420'                       # size in bytes
        assert m.group(3) == '2'                                 # count

    def test_parse_group_header_lowercase_hash(self):
        """Parse group header with lowercase hex hash."""
        line = 'aebab6d5c723236dee40b8fe466fab9f, 4515595719 B (4.5 GB) * 2:'
        m = RE_GROUP_HEADER.match(line)
        assert m is not None
        assert m.group(1) == 'aebab6d5c723236dee40b8fe466fab9f'

    def test_parse_group_header_uppercase_hash(self):
        """Parse group header with uppercase hex hash."""
        line = 'AEBAB6D5C723236DEE40B8FE466FAB9F, 4515595719 B (4.5 GB) * 2:'
        m = RE_GROUP_HEADER.match(line)
        assert m is not None
        assert m.group(1) == 'AEBAB6D5C723236DEE40B8FE466FAB9F'

    def test_parse_group_header_large_size(self):
        """Parse group header with large file size (TB range)."""
        line = 'deadbeefcafe1234567890abcdef0123, 5497558138880 B (5 TB) * 2:'
        m = RE_GROUP_HEADER.match(line)
        assert m is not None
        assert m.group(2) == '5497558138880'

    def test_parse_group_header_small_size(self):
        """Parse group header with small file size."""
        line = 'abc123def456789012345678abcdef01, 100 B (100 B) * 1:'
        m = RE_GROUP_HEADER.match(line)
        assert m is not None
        assert m.group(2) == '100'
        assert m.group(3) == '1'

    def test_parse_group_header_high_count(self):
        """Parse group header with high duplicate count."""
        line = 'abc123def456789012345678abcdef01, 1000 B (1 KB) * 999:'
        m = RE_GROUP_HEADER.match(line)
        assert m is not None
        assert m.group(3) == '999'


class TestParsePathLine:
    """Tests for parsing indented path lines."""

    def test_parse_path_line_basic(self):
        """Parse path line with 4-space indentation."""
        line = '    Q:\\\\20T-0-no-recycle-skip-err\\\\folder\\\\GX015735.MP4'
        m = RE_PATH_LINE.match(line)
        assert m is not None
        assert m.group(1) == 'Q:\\\\20T-0-no-recycle-skip-err\\\\folder\\\\GX015735.MP4'

    def test_parse_path_line_unicode(self):
        """Parse path line with Unicode (Cyrillic) characters."""
        line = '    Q:\\\\path\\\\Папка\\\\file1.mp4'
        m = RE_PATH_LINE.match(line)
        assert m is not None
        assert 'Папка' in m.group(1)

    def test_parse_path_line_spaces_in_path(self):
        """Parse path line with spaces in the filename."""
        line = '    Q:\\\\path\\\\file with spaces.txt'
        m = RE_PATH_LINE.match(line)
        assert m is not None
        assert 'file with spaces.txt' in m.group(1)

    def test_parse_path_line_does_not_match_header(self):
        """Path line regex should not match group headers."""
        line = '8593af76cd7c0818f0e6f8c0c3cc0e7d, 10248846420 B (10.2 GB) * 2:'
        m = RE_PATH_LINE.match(line)
        assert m is None

    def test_parse_path_line_does_not_match_comment(self):
        """Path line regex should not match header comments."""
        line = '# Report by fclones 0.35.0'
        m = RE_PATH_LINE.match(line)
        assert m is None


class TestParseMultipleGroups:
    """Tests for parsing multiple groups in one report."""

    def test_parse_multiple_groups(self, sample_report_file):
        """Parse report with multiple duplicate groups."""
        metadata, groups = parse_fclones_report(sample_report_file)
        assert len(groups) == 2
        
        # First group
        assert groups[0].hash == '8593af76cd7c0818f0e6f8c0c3cc0e7d'
        assert groups[0].size == 10248846420
        assert groups[0].count == 2
        assert len(groups[0].paths) == 2
        
        # Second group
        assert groups[1].hash == 'aebab6d5c723236dee40b8fe466fab9f'
        assert groups[1].size == 4515595719
        assert groups[1].count == 2
        assert len(groups[1].paths) == 2

    def test_parse_groups_have_sequential_ids(self, sample_report_file):
        """Parsed groups should have sequential group IDs."""
        metadata, groups = parse_fclones_report(sample_report_file)
        assert groups[0].group_id == 1
        assert groups[1].group_id == 2


# ---------------------------------------------------------------------------
# A.3 Edge Cases
# ---------------------------------------------------------------------------

class TestEdgeCasesEmptyReport:
    """Tests for empty report (headers only)."""

    def test_empty_report_parses_metadata(self, empty_report_file):
        """Empty report still parses metadata correctly."""
        metadata, groups = parse_fclones_report(empty_report_file)
        assert metadata.fclones_version == '0.35.0'
        assert metadata.total_files == 0
        assert metadata.total_groups == 0

    def test_empty_report_returns_no_groups(self, empty_report_file):
        """Empty report returns empty groups list."""
        metadata, groups = parse_fclones_report(empty_report_file)
        assert groups == []


class TestEdgeCasesSingleFileGroups:
    """Tests for single file groups (count=1)."""

    def test_single_file_group_parses(self, single_file_report):
        """Parse group with only one file (count=1)."""
        metadata, groups = parse_fclones_report(single_file_report)
        assert len(groups) == 1
        assert groups[0].count == 1
        assert len(groups[0].paths) == 1

    def test_single_file_group_path_normalized(self, single_file_report):
        """Single file group path is correctly normalized."""
        metadata, groups = parse_fclones_report(single_file_report)
        # Path should be normalized with forward slashes
        assert '/' in groups[0].paths[0]
        assert '\\\\' not in groups[0].paths[0]


class TestEdgeCasesLargeFiles:
    """Tests for large file sizes."""

    def test_large_file_sizes_parsed(self, large_files_report):
        """Parse group with very large file sizes (TB range)."""
        metadata, groups = parse_fclones_report(large_files_report)
        assert len(groups) == 1
        # 5 TB in bytes
        assert groups[0].size == 5497558138880

    def test_large_total_stats_parsed(self, large_files_report):
        """Parse total statistics with large values."""
        metadata, groups = parse_fclones_report(large_files_report)
        # 10 TB in bytes
        assert metadata.total_bytes == 10995116277760


class TestEdgeCasesSpecialCharacters:
    """Tests for special characters in paths."""

    def test_spaces_in_paths(self, special_chars_report):
        """Parse paths containing spaces."""
        metadata, groups = parse_fclones_report(special_chars_report)
        # Find the group with spaces
        group = groups[0]
        has_space_path = any('file with spaces' in p for p in group.paths)
        assert has_space_path

    def test_unicode_cyrillic_in_paths(self, special_chars_report):
        """Parse paths containing Cyrillic (Russian) characters."""
        metadata, groups = parse_fclones_report(special_chars_report)
        # Find the group with Cyrillic
        group = groups[1]
        has_cyrillic = any('кириллица' in p for p in group.paths)
        assert has_cyrillic

    def test_unicode_chinese_in_paths(self, special_chars_report):
        """Parse paths containing Chinese characters."""
        metadata, groups = parse_fclones_report(special_chars_report)
        # Find the group with Chinese
        group = groups[1]
        has_chinese = any('中文' in p for p in group.paths)
        assert has_chinese


# ===========================================================================
# B. Path Normalization Tests
# ===========================================================================

class TestPathNormalizationBackslash:
    """Tests for Windows backslash conversion."""

    def test_double_backslash_to_forward_slash(self):
        """Convert double backslashes to forward slashes."""
        raw = 'Q:\\\\path\\\\to\\\\file.txt'
        normalized = normalize_fclones_path(raw)
        assert normalized == 'Q:/path/to/file.txt'

    def test_single_backslash_to_forward_slash(self):
        """Convert single backslashes to forward slashes."""
        raw = 'Q:\\path\\to\\file.txt'
        normalized = normalize_fclones_path(raw)
        assert normalized == 'Q:/path/to/file.txt'

    def test_mixed_backslashes(self):
        """Handle mixed double and single backslashes."""
        raw = 'Q:\\\\path\\to\\\\file.txt'
        normalized = normalize_fclones_path(raw)
        assert normalized == 'Q:/path/to/file.txt'

    def test_forward_slashes_preserved(self):
        """Forward slashes should be preserved."""
        raw = '/unix/path/to/file.txt'
        normalized = normalize_fclones_path(raw)
        assert normalized == '/unix/path/to/file.txt'


class TestPathNormalizationStripPrefix:
    """Tests for strip prefix functionality."""

    def test_strip_prefix_basic(self):
        """Strip simple prefix from path."""
        raw = 'Q:\\\\path\\\\to\\\\file.txt'
        normalized = normalize_fclones_path(raw, strip_prefix='Q:\\\\')
        assert normalized == 'path/to/file.txt'

    def test_strip_prefix_double_backslash(self):
        """Strip prefix with double backslashes."""
        raw = 'Q:\\\\path\\\\to\\\\file.txt'
        normalized = normalize_fclones_path(raw, strip_prefix='Q:\\\\path\\\\')
        assert normalized == 'to/file.txt'

    def test_strip_prefix_no_match(self):
        """Prefix that doesn't match should leave path unchanged."""
        raw = 'Q:\\\\path\\\\to\\\\file.txt'
        normalized = normalize_fclones_path(raw, strip_prefix='D:\\\\')
        assert normalized == 'Q:/path/to/file.txt'

    def test_strip_prefix_removes_leading_slash(self):
        """After stripping, leading slash should be removed."""
        raw = 'Q:\\\\path\\\\to\\\\file.txt'
        normalized = normalize_fclones_path(raw, strip_prefix='Q:')
        # Should not have leading slash
        assert not normalized.startswith('/')


class TestPathNormalizationUnicode:
    """Tests for Unicode path preservation."""

    def test_unicode_cyrillic_preserved(self):
        """Cyrillic characters in path are preserved."""
        raw = 'Q:\\\\path\\\\Папка\\\\файл.txt'
        normalized = normalize_fclones_path(raw)
        assert 'Папка' in normalized
        assert 'файл' in normalized

    def test_unicode_chinese_preserved(self):
        """Chinese characters in path are preserved."""
        raw = 'Q:\\\\path\\\\文件夹\\\\文件.txt'
        normalized = normalize_fclones_path(raw)
        assert '文件夹' in normalized
        assert '文件' in normalized

    def test_unicode_with_strip_prefix(self):
        """Unicode paths work correctly with strip_prefix."""
        raw = 'Q:\\\\path\\\\Папка\\\\файл.txt'
        normalized = normalize_fclones_path(raw, strip_prefix='Q:\\\\path\\\\')
        assert normalized == 'Папка/файл.txt'


class TestPathNormalizationWhitespace:
    """Tests for whitespace handling."""

    def test_strips_leading_trailing_whitespace(self):
        """Leading and trailing whitespace should be stripped."""
        raw = '  Q:\\\\path\\\\file.txt  '
        normalized = normalize_fclones_path(raw)
        assert normalized == 'Q:/path/file.txt'

    def test_preserves_internal_spaces(self):
        """Spaces within the path should be preserved."""
        raw = 'Q:\\\\path with spaces\\\\file name.txt'
        normalized = normalize_fclones_path(raw)
        assert 'path with spaces' in normalized
        assert 'file name.txt' in normalized


# ===========================================================================
# C. FileEntry Generation Tests
# ===========================================================================

class TestFileEntryChecksum:
    """Tests for checksum format in generated FileEntry objects."""

    def test_checksum_format_metrohash(self, sample_duplicate_group):
        """Checksum should be in format 'metrohash:<hash>'."""
        entries = list(duplicate_group_to_entries(sample_duplicate_group))
        assert len(entries) > 0
        for entry in entries:
            assert entry.checksum.startswith('metrohash:')
            assert entry.checksum == f"metrohash:{sample_duplicate_group.hash}"

    def test_checksum_preserves_hash(self, sample_duplicate_group):
        """Hash value should be preserved in checksum."""
        entries = list(duplicate_group_to_entries(sample_duplicate_group))
        expected_hash = sample_duplicate_group.hash
        for entry in entries:
            assert expected_hash in entry.checksum


class TestFileEntrySizeMapping:
    """Tests for size mapping in generated FileEntry objects."""

    def test_size_mapped_correctly(self, sample_duplicate_group):
        """Size should be mapped from group to all entries."""
        entries = list(duplicate_group_to_entries(sample_duplicate_group))
        for entry in entries:
            assert entry.size == sample_duplicate_group.size

    def test_size_large_value(self):
        """Large size values should be handled correctly."""
        group = DuplicateGroup(
            hash='abc123',
            size=5497558138880,  # 5 TB
            count=2,
            paths=['path1', 'path2'],
        )
        entries = list(duplicate_group_to_entries(group))
        for entry in entries:
            assert entry.size == 5497558138880


class TestFileEntryType:
    """Tests for entry_type in generated FileEntry objects."""

    def test_entry_type_always_file(self, sample_duplicate_group):
        """entry_type should always be 'f' for fclones entries."""
        entries = list(duplicate_group_to_entries(sample_duplicate_group))
        for entry in entries:
            assert entry.entry_type == 'f'


class TestFileEntryNoneFields:
    """Tests for fields that should be None in generated FileEntry objects."""

    def test_mtime_is_none(self, sample_duplicate_group):
        """modify time should be None (not available in fclones)."""
        entries = list(duplicate_group_to_entries(sample_duplicate_group))
        for entry in entries:
            assert entry.modify is None

    def test_atime_is_none(self, sample_duplicate_group):
        """access time should be None (not available in fclones)."""
        entries = list(duplicate_group_to_entries(sample_duplicate_group))
        for entry in entries:
            assert entry.access is None

    def test_ctime_is_none(self, sample_duplicate_group):
        """creation time should be None (not available in fclones)."""
        entries = list(duplicate_group_to_entries(sample_duplicate_group))
        for entry in entries:
            assert entry.creation is None

    def test_permissions_is_none(self, sample_duplicate_group):
        """permissions should be None (not available in fclones)."""
        entries = list(duplicate_group_to_entries(sample_duplicate_group))
        for entry in entries:
            assert entry.permissions is None

    def test_uid_is_none(self, sample_duplicate_group):
        """uid should be None (not available in fclones)."""
        entries = list(duplicate_group_to_entries(sample_duplicate_group))
        for entry in entries:
            assert entry.uid is None

    def test_gid_is_none(self, sample_duplicate_group):
        """gid should be None (not available in fclones)."""
        entries = list(duplicate_group_to_entries(sample_duplicate_group))
        for entry in entries:
            assert entry.gid is None


class TestFileEntryPath:
    """Tests for path mapping in generated FileEntry objects."""

    def test_paths_mapped_correctly(self, sample_duplicate_group):
        """Paths should be mapped from group to individual entries."""
        entries = list(duplicate_group_to_entries(sample_duplicate_group))
        assert len(entries) == len(sample_duplicate_group.paths)
        for i, entry in enumerate(entries):
            assert entry.path == sample_duplicate_group.paths[i]


# ===========================================================================
# D. Include Filter Tests
# ===========================================================================

class TestIncludeAll:
    """Tests for --include all filter."""

    def test_include_all_returns_all_paths(self):
        """include='all' should return all files from all groups."""
        group = DuplicateGroup(
            hash='abc123',
            size=100,
            count=3,
            paths=['path1', 'path2', 'path3'],
        )
        entries = list(duplicate_group_to_entries(group, include='all'))
        assert len(entries) == 3

    def test_include_all_preserves_order(self):
        """include='all' should preserve path order."""
        group = DuplicateGroup(
            hash='abc123',
            size=100,
            count=3,
            paths=['first', 'second', 'third'],
        )
        entries = list(duplicate_group_to_entries(group, include='all'))
        assert entries[0].path == 'first'
        assert entries[1].path == 'second'
        assert entries[2].path == 'third'


class TestIncludeFirst:
    """Tests for --include first filter."""

    def test_include_first_returns_one_entry(self):
        """include='first' should return only the first file per group."""
        group = DuplicateGroup(
            hash='abc123',
            size=100,
            count=3,
            paths=['canonical', 'dup1', 'dup2'],
        )
        entries = list(duplicate_group_to_entries(group, include='first'))
        assert len(entries) == 1

    def test_include_first_returns_canonical(self):
        """include='first' should return the first (canonical) file."""
        group = DuplicateGroup(
            hash='abc123',
            size=100,
            count=3,
            paths=['canonical', 'dup1', 'dup2'],
        )
        entries = list(duplicate_group_to_entries(group, include='first'))
        assert entries[0].path == 'canonical'

    def test_include_first_with_single_file_group(self):
        """include='first' with single-file group returns that file."""
        group = DuplicateGroup(
            hash='abc123',
            size=100,
            count=1,
            paths=['only_file'],
        )
        entries = list(duplicate_group_to_entries(group, include='first'))
        assert len(entries) == 1
        assert entries[0].path == 'only_file'


class TestIncludeDuplicates:
    """Tests for --include duplicates filter."""

    def test_include_duplicates_excludes_first(self):
        """include='duplicates' should exclude the first file."""
        group = DuplicateGroup(
            hash='abc123',
            size=100,
            count=3,
            paths=['canonical', 'dup1', 'dup2'],
        )
        entries = list(duplicate_group_to_entries(group, include='duplicates'))
        assert len(entries) == 2
        paths = [e.path for e in entries]
        assert 'canonical' not in paths

    def test_include_duplicates_returns_all_except_first(self):
        """include='duplicates' should return all files except the first."""
        group = DuplicateGroup(
            hash='abc123',
            size=100,
            count=3,
            paths=['canonical', 'dup1', 'dup2'],
        )
        entries = list(duplicate_group_to_entries(group, include='duplicates'))
        paths = [e.path for e in entries]
        assert 'dup1' in paths
        assert 'dup2' in paths

    def test_include_duplicates_with_single_file_group(self):
        """include='duplicates' with single-file group returns empty."""
        group = DuplicateGroup(
            hash='abc123',
            size=100,
            count=1,
            paths=['only_file'],
        )
        entries = list(duplicate_group_to_entries(group, include='duplicates'))
        assert len(entries) == 0


class TestIncludeFilterIntegration:
    """Integration tests for include filter with full report parsing."""

    def test_include_all_from_report(self, sample_report_file):
        """include='all' returns all files from report."""
        entries = list(generate_entries_from_report(
            sample_report_file, include='all'
        ))
        # 2 groups with 2 files each = 4 total
        assert len(entries) == 4

    def test_include_first_from_report(self, sample_report_file):
        """include='first' returns one file per group from report."""
        entries = list(generate_entries_from_report(
            sample_report_file, include='first'
        ))
        # 2 groups = 2 canonical files
        assert len(entries) == 2

    def test_include_duplicates_from_report(self, sample_report_file):
        """include='duplicates' returns all except first from report."""
        entries = list(generate_entries_from_report(
            sample_report_file, include='duplicates'
        ))
        # 2 groups with 2 files each, minus 2 canonical = 2 duplicates
        assert len(entries) == 2


# ===========================================================================
# E. Integration Tests
# ===========================================================================

class TestFullReportParsing:
    """Integration tests for full report parsing."""

    def test_full_report_metadata_and_groups(self, sample_report_file):
        """Full report parsing extracts both metadata and groups."""
        metadata, groups = parse_fclones_report(sample_report_file)
        
        # Verify metadata
        assert metadata.fclones_version == '0.35.0'
        assert metadata.timestamp == '2026-03-30 04:31:29.522 +0300'
        assert metadata.total_bytes == 1268686168746
        assert metadata.total_files == 62263
        assert metadata.total_groups == 29099
        
        # Verify groups
        assert len(groups) == 2

    def test_full_report_entry_generation(self, sample_report_file):
        """Full report generates correct FileEntry objects."""
        entries = list(generate_entries_from_report(sample_report_file))
        
        # All entries should be FileEntry objects
        assert all(isinstance(e, FileEntry) for e in entries)
        
        # All entries should have required fields
        for entry in entries:
            assert entry.path is not None
            assert entry.size is not None
            assert entry.checksum is not None
            assert entry.entry_type == 'f'


class TestOutputFormatCompatibility:
    """Tests for output format compatibility with listing.py."""

    def test_entry_to_listing_row(self, sample_report_file):
        """FileEntry from fclones can be serialized to listing row."""
        from common.attr_map import CANONICAL_MAP
        
        entries = list(generate_entries_from_report(sample_report_file))
        
        # Each entry should be serializable
        for entry in entries:
            row = entry.to_listing_row(CANONICAL_MAP)
            # Canonical map has 10 columns
            assert len(row) == 10
            # Path should be in last position
            assert row[9] == entry.path

    def test_entry_round_trip(self, sample_report_file):
        """FileEntry can round-trip through listing format."""
        from common.attr_map import CANONICAL_MAP
        
        entries = list(generate_entries_from_report(sample_report_file))
        original = entries[0]
        
        # Serialize and deserialize
        row = original.to_listing_row(CANONICAL_MAP)
        restored = FileEntry.from_listing_row(row, CANONICAL_MAP)
        
        # Core fields should match
        assert restored.path == original.path
        assert restored.size == original.size
        assert restored.checksum == original.checksum
        assert restored.entry_type == original.entry_type

    def test_write_and_read_listing(self, sample_report_file, tmp_path):
        """Entries can be written and read back via listing module."""
        from common.listing import write_listing, read_listing
        
        entries = list(generate_entries_from_report(sample_report_file))
        
        output_path = str(tmp_path / 'output.csv')
        count = write_listing(output_path, entries)
        assert count == len(entries)
        
        restored = read_listing(output_path)
        assert len(restored) == len(entries)
        
        # Verify content matches
        for orig, rest in zip(entries, restored):
            assert rest.path == orig.path
            assert rest.size == orig.size
            assert rest.checksum == orig.checksum


class TestStripPrefixIntegration:
    """Integration tests for strip_prefix with full parsing."""

    def test_strip_prefix_on_full_report(self, sample_report_file):
        """strip_prefix works across full report parsing."""
        entries = list(generate_entries_from_report(
            sample_report_file, strip_prefix='Q:\\\\'
        ))
        
        # All paths should not start with Q:/
        for entry in entries:
            assert not entry.path.startswith('Q:/')
            assert not entry.path.startswith('Q:\\')


class TestUnicodeIntegration:
    """Integration tests for Unicode handling."""

    def test_unicode_paths_preserved_through_pipeline(self, special_chars_report):
        """Unicode paths are preserved through full parsing pipeline."""
        entries = list(generate_entries_from_report(special_chars_report))
        
        paths = [e.path for e in entries]
        
        # Cyrillic
        assert any('кириллица' in p for p in paths)
        
        # Chinese
        assert any('中文' in p for p in paths)

    def test_unicode_paths_serializable(self, special_chars_report, tmp_path):
        """Unicode paths can be written to and read from listing."""
        from common.listing import write_listing, read_listing
        
        entries = list(generate_entries_from_report(special_chars_report))
        
        output_path = str(tmp_path / 'unicode_output.csv')
        write_listing(output_path, entries)
        
        restored = read_listing(output_path)
        paths = [e.path for e in restored]
        
        # Cyrillic preserved
        assert any('кириллица' in p for p in paths)
        
        # Chinese preserved
        assert any('中文' in p for p in paths)
