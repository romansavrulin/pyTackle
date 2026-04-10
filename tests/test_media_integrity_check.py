"""Tests for tackles/MediaIntegrityCheck.py."""

from __future__ import annotations

import os
import subprocess
from typing import Generator
from unittest.mock import MagicMock, patch

import pytest

from tackles.MediaIntegrityCheck import (
    CheckLevel,
    COMPOUND_EXTENSIONS,
    TOOL_REGISTRY,
    ToolConfig,
    ValidationOutcome,
    ValidationResult,
    check_tool_available,
    generate_install_command,
    get_extension,
    get_missing_packages,
    get_tool_config,
    list_tools_status,
)


# ===========================================================================
# 1. Tool Registry Tests
# ===========================================================================


class TestToolRegistry:
    """Tests for TOOL_REGISTRY configuration."""

    def test_registry_contains_mp4(self):
        """Registry should contain .mp4 extension."""
        assert '.mp4' in TOOL_REGISTRY

    def test_registry_contains_jpg(self):
        """Registry should contain .jpg extension."""
        assert '.jpg' in TOOL_REGISTRY

    def test_registry_contains_pdf(self):
        """Registry should contain .pdf extension."""
        assert '.pdf' in TOOL_REGISTRY

    def test_registry_contains_mp3(self):
        """Registry should contain .mp3 extension."""
        assert '.mp3' in TOOL_REGISTRY

    def test_registry_contains_zip(self):
        """Registry should contain .zip extension."""
        assert '.zip' in TOOL_REGISTRY

    def test_registry_entry_is_tool_config(self):
        """Registry entries should be ToolConfig instances."""
        for ext, config in TOOL_REGISTRY.items():
            assert isinstance(config, ToolConfig), f'{ext} is not ToolConfig'

    def test_registry_has_binary_field(self):
        """All registry entries should have binary field."""
        for ext, config in TOOL_REGISTRY.items():
            assert config.binary, f'{ext} missing binary'
            assert isinstance(config.binary, str)

    def test_registry_has_apt_package_field(self):
        """All registry entries should have apt_package field."""
        for ext, config in TOOL_REGISTRY.items():
            assert config.apt_package, f'{ext} missing apt_package'
            assert isinstance(config.apt_package, str)

    def test_registry_mp4_uses_ffprobe(self):
        """MP4 extension should use ffprobe."""
        config = TOOL_REGISTRY['.mp4']
        assert config.binary == 'ffprobe'
        assert config.apt_package == 'ffmpeg'

    def test_registry_jpg_uses_jpeginfo(self):
        """JPEG extension should use jpeginfo."""
        config = TOOL_REGISTRY['.jpg']
        assert config.binary == 'jpeginfo'
        assert config.apt_package == 'jpeginfo'

    def test_registry_pdf_uses_qpdf(self):
        """PDF extension should use qpdf."""
        config = TOOL_REGISTRY['.pdf']
        assert config.binary == 'qpdf'
        assert config.apt_package == 'qpdf'


class TestCompoundExtensions:
    """Tests for COMPOUND_EXTENSIONS configuration."""

    def test_compound_contains_tar_gz(self):
        """Compound extensions should contain .tar.gz."""
        assert '.tar.gz' in COMPOUND_EXTENSIONS

    def test_compound_contains_tar_bz2(self):
        """Compound extensions should contain .tar.bz2."""
        assert '.tar.bz2' in COMPOUND_EXTENSIONS

    def test_compound_contains_tar_xz(self):
        """Compound extensions should contain .tar.xz."""
        assert '.tar.xz' in COMPOUND_EXTENSIONS

    def test_compound_contains_tar_zst(self):
        """Compound extensions should contain .tar.zst."""
        assert '.tar.zst' in COMPOUND_EXTENSIONS

    def test_compound_entry_is_tool_config(self):
        """Compound extension entries should be ToolConfig instances."""
        for ext, config in COMPOUND_EXTENSIONS.items():
            assert isinstance(config, ToolConfig), f'{ext} is not ToolConfig'

    def test_compound_tar_gz_uses_tar(self):
        """.tar.gz should use tar binary."""
        config = COMPOUND_EXTENSIONS['.tar.gz']
        assert config.binary == 'tar'
        assert config.apt_package == 'tar'


# ===========================================================================
# 2. Get Extension Tests
# ===========================================================================


class TestGetExtension:
    """Tests for get_extension() function."""

    def test_simple_extension_mp4(self):
        """Extract simple .mp4 extension."""
        assert get_extension('/path/to/file.mp4') == '.mp4'

    def test_simple_extension_jpg(self):
        """Extract simple .jpg extension."""
        assert get_extension('/path/to/file.jpg') == '.jpg'

    def test_simple_extension_uppercase(self):
        """Extension should be lowercase regardless of input case."""
        assert get_extension('/path/to/file.MP4') == '.mp4'
        assert get_extension('/path/to/file.JPG') == '.jpg'

    def test_compound_extension_tar_gz(self):
        """Extract compound .tar.gz extension."""
        assert get_extension('/path/to/archive.tar.gz') == '.tar.gz'

    def test_compound_extension_tar_bz2(self):
        """Extract compound .tar.bz2 extension."""
        assert get_extension('/path/to/archive.tar.bz2') == '.tar.bz2'

    def test_compound_extension_tar_xz(self):
        """Extract compound .tar.xz extension."""
        assert get_extension('/path/to/archive.tar.xz') == '.tar.xz'

    def test_compound_extension_tar_zst(self):
        """Extract compound .tar.zst extension."""
        assert get_extension('/path/to/archive.tar.zst') == '.tar.zst'

    def test_compound_extension_uppercase(self):
        """Compound extension should be lowercase regardless of input case."""
        assert get_extension('/path/to/archive.TAR.GZ') == '.tar.gz'

    def test_no_extension(self):
        """File without extension returns empty string."""
        assert get_extension('/path/to/file') == ''

    def test_hidden_file(self):
        """Hidden file (starting with dot) with no other extension returns empty."""
        # os.path.splitext returns empty extension for files like '.hidden'
        assert get_extension('/path/to/.hidden') == ''

    def test_hidden_file_with_extension(self):
        """Hidden file with extension."""
        assert get_extension('/path/to/.config.json') == '.json'

    def test_multiple_dots(self):
        """File with multiple dots returns last extension."""
        assert get_extension('/path/to/file.backup.txt') == '.txt'

    def test_spaces_in_path(self):
        """Path with spaces works correctly."""
        assert get_extension('/path/with spaces/file name.mp4') == '.mp4'


# ===========================================================================
# 3. Get Tool Config Tests
# ===========================================================================


class TestGetToolConfig:
    """Tests for get_tool_config() function."""

    def test_known_extension_mp4(self):
        """Known extension .mp4 returns ToolConfig."""
        config = get_tool_config('.mp4')
        assert config is not None
        assert config.binary == 'ffprobe'

    def test_known_extension_pdf(self):
        """Known extension .pdf returns ToolConfig."""
        config = get_tool_config('.pdf')
        assert config is not None
        assert config.binary == 'qpdf'

    def test_known_extension_jpg(self):
        """Known extension .jpg returns ToolConfig."""
        config = get_tool_config('.jpg')
        assert config is not None
        assert config.binary == 'jpeginfo'

    def test_unknown_extension(self):
        """Unknown extension returns None."""
        assert get_tool_config('.xyz') is None
        assert get_tool_config('.unknown') is None
        assert get_tool_config('.foo') is None

    def test_compound_extension(self):
        """Compound extension .tar.gz returns ToolConfig."""
        config = get_tool_config('.tar.gz')
        assert config is not None
        assert config.binary == 'tar'

    def test_compound_extension_tar_bz2(self):
        """Compound extension .tar.bz2 returns ToolConfig."""
        config = get_tool_config('.tar.bz2')
        assert config is not None
        assert config.binary == 'tar'

    def test_compound_takes_precedence(self):
        """Compound extension should take precedence over single."""
        # .gz alone is handled by gzip, but .tar.gz by tar
        config_gz = get_tool_config('.gz')
        config_tar_gz = get_tool_config('.tar.gz')
        assert config_gz.binary == 'gzip'
        assert config_tar_gz.binary == 'tar'

    def test_empty_extension(self):
        """Empty extension returns None."""
        assert get_tool_config('') is None


# ===========================================================================
# 4. Tool Availability Tests
# ===========================================================================


class TestCheckToolAvailable:
    """Tests for check_tool_available() function."""

    @patch('shutil.which')
    def test_available_tool_returns_true(self, mock_which):
        """Available tool returns True."""
        mock_which.return_value = '/usr/bin/ffprobe'
        assert check_tool_available('ffprobe') is True

    @patch('shutil.which')
    def test_unavailable_tool_returns_false(self, mock_which):
        """Unavailable tool returns False."""
        mock_which.return_value = None
        assert check_tool_available('nonexistent_tool') is False

    @patch('shutil.which')
    def test_calls_which_with_binary_name(self, mock_which):
        """Function should call shutil.which with the binary name."""
        mock_which.return_value = None
        check_tool_available('my_tool')
        mock_which.assert_called_once_with('my_tool')


class TestGenerateInstallCommand:
    """Tests for generate_install_command() function."""

    def test_empty_packages_returns_comment(self):
        """Empty package set returns comment."""
        result = generate_install_command(set())
        assert result == '# All required tools are available'

    def test_single_package(self):
        """Single package generates correct command."""
        result = generate_install_command({'ffmpeg'})
        assert result == 'sudo apt-get install ffmpeg'

    def test_multiple_packages(self):
        """Multiple packages are sorted and included."""
        result = generate_install_command({'ffmpeg', 'jpeginfo', 'mp3val'})
        assert result == 'sudo apt-get install ffmpeg jpeginfo mp3val'

    def test_packages_are_sorted(self):
        """Packages are sorted alphabetically."""
        result = generate_install_command({'zstd', 'bzip2', 'mp3val'})
        assert result == 'sudo apt-get install bzip2 mp3val zstd'


class TestListToolsStatus:
    """Tests for list_tools_status() function."""

    @patch('tackles.MediaIntegrityCheck.check_tool_available')
    def test_returns_formatted_table(self, mock_available):
        """Returns a properly formatted table string."""
        mock_available.return_value = True
        result = list_tools_status()

        assert isinstance(result, str)
        assert 'Tool Availability Status' in result
        assert '=' * 80 in result
        assert 'Extension' in result
        assert 'Tool' in result
        assert 'Package' in result
        assert 'Installed' in result

    @patch('tackles.MediaIntegrityCheck.check_tool_available')
    def test_shows_available_status_yes(self, mock_available):
        """Shows 'Yes' for available tools."""
        mock_available.return_value = True
        result = list_tools_status()
        assert 'Yes' in result

    @patch('tackles.MediaIntegrityCheck.check_tool_available')
    def test_shows_available_status_no(self, mock_available):
        """Shows 'No' for unavailable tools."""
        mock_available.return_value = False
        result = list_tools_status()
        assert 'No' in result

    @patch('tackles.MediaIntegrityCheck.check_tool_available')
    def test_all_tools_available_message(self, mock_available):
        """Shows success message when all tools available."""
        mock_available.return_value = True
        result = list_tools_status()
        assert 'All tools available!' in result

    @patch('tackles.MediaIntegrityCheck.check_tool_available')
    def test_missing_tools_shows_install_command(self, mock_available):
        """Shows install command when tools are missing."""
        mock_available.return_value = False
        result = list_tools_status()
        assert 'package(s) missing' in result
        assert 'Install with:' in result


class TestGetMissingPackages:
    """Tests for get_missing_packages() function."""

    @patch('tackles.MediaIntegrityCheck.check_tool_available')
    def test_all_available_returns_empty(self, mock_available):
        """Returns empty set when all tools available."""
        mock_available.return_value = True
        result = get_missing_packages()
        assert result == set()

    @patch('tackles.MediaIntegrityCheck.check_tool_available')
    def test_none_available_returns_all_packages(self, mock_available):
        """Returns all packages when no tools available."""
        mock_available.return_value = False
        result = get_missing_packages()
        assert len(result) > 0
        # Should include common packages
        assert 'ffmpeg' in result or 'jpeginfo' in result


# ===========================================================================
# 5. ValidationResult Tests
# ===========================================================================


class TestValidationResult:
    """Tests for ValidationResult enum."""

    def test_all_values_exist(self):
        """All 5 expected values exist."""
        assert hasattr(ValidationResult, 'VALID')
        assert hasattr(ValidationResult, 'CORRUPT')
        assert hasattr(ValidationResult, 'UNTESTABLE')
        assert hasattr(ValidationResult, 'TOOL_MISSING')
        assert hasattr(ValidationResult, 'TOOL_ERROR')

    def test_enum_values_are_distinct(self):
        """All enum values are distinct."""
        values = [
            ValidationResult.VALID,
            ValidationResult.CORRUPT,
            ValidationResult.UNTESTABLE,
            ValidationResult.TOOL_MISSING,
            ValidationResult.TOOL_ERROR,
        ]
        assert len(values) == len(set(values))

    def test_enum_count(self):
        """Exactly 5 enum values exist."""
        assert len(ValidationResult) == 5


# ===========================================================================
# 6. Special Case Handling Tests
# ===========================================================================


class TestSpecialCases:
    """Tests for special case handling."""

    def test_qpdf_exit_code_3_is_valid(self):
        """qpdf exit code 3 should be treated as VALID."""
        config = get_tool_config('.pdf')
        assert config is not None
        assert 3 in config.success_codes
        assert 0 in config.success_codes

    def test_ogg_has_stderr_check(self):
        """OGG files should have stderr checking for errors."""
        config = get_tool_config('.ogg')
        assert config is not None
        assert config.check_stderr is not None
        assert 'error' in config.check_stderr.lower()

    def test_opus_has_stderr_check(self):
        """Opus files should have stderr checking for errors."""
        config = get_tool_config('.opus')
        assert config is not None
        assert config.check_stderr is not None
        assert 'error' in config.check_stderr.lower()

    def test_most_tools_only_zero_is_success(self):
        """Most tools should only have 0 as success code."""
        config = get_tool_config('.mp4')
        assert config is not None
        assert config.success_codes == (0,)

        config = get_tool_config('.jpg')
        assert config is not None
        assert config.success_codes == (0,)

    def test_some_tools_have_no_stderr_check(self):
        """Some tools should not have stderr check (rely on exit code only)."""
        # pngcheck, flac, mp3val, tar, gzip, etc. only use exit codes
        config = get_tool_config('.png')
        assert config.check_stderr is None

        config = get_tool_config('.flac')
        assert config.check_stderr is None

        config = get_tool_config('.pdf')
        assert config.check_stderr is None


# ===========================================================================
# 7. Validation Logic Tests (mocked)
# ===========================================================================


class TestValidateSingleMocked:
    """Tests for _validate_single() method with mocking."""

    @pytest.fixture
    def mock_media_check(self):
        """Create a mock MediaIntegrityCheck instance."""
        from tackles.MediaIntegrityCheck import MediaIntegrityCheck, CheckLevel

        # Create minimal mock with required attributes
        mock = MagicMock(spec=MediaIntegrityCheck)
        mock.timeout = 300
        mock.check_level = CheckLevel.DEFAULT
        mock._validate_single = MediaIntegrityCheck._validate_single
        return mock

    @pytest.fixture
    def sample_file_entry(self, tmp_path):
        """Create a sample FileEntry for testing."""
        from common.FileEntry import FileEntry

        test_file = tmp_path / 'test.mp4'
        test_file.write_bytes(b'fake content')
        return FileEntry.from_fs_path(str(test_file))

    @patch('subprocess.run')
    @patch('tackles.MediaIntegrityCheck.check_tool_available')
    def test_valid_file_returns_valid(self, mock_available, mock_run, mock_media_check, sample_file_entry):
        """Successful validation returns VALID result."""
        mock_available.return_value = True
        mock_run.return_value = MagicMock(returncode=0, stderr='')

        outcome = mock_media_check._validate_single(mock_media_check, sample_file_entry)

        assert outcome.result == ValidationResult.VALID
        assert outcome.tool == 'ffprobe'
        assert outcome.exit_code == 0

    @patch('subprocess.run')
    @patch('tackles.MediaIntegrityCheck.check_tool_available')
    def test_corrupt_file_returns_corrupt(self, mock_available, mock_run, mock_media_check, sample_file_entry):
        """Non-zero exit code returns CORRUPT result."""
        mock_available.return_value = True
        mock_run.return_value = MagicMock(returncode=1, stderr='Error in stream')

        outcome = mock_media_check._validate_single(mock_media_check, sample_file_entry)

        assert outcome.result == ValidationResult.CORRUPT
        assert outcome.exit_code == 1

    @patch('subprocess.run')
    @patch('tackles.MediaIntegrityCheck.check_tool_available')
    def test_timeout_returns_tool_error(self, mock_available, mock_run, mock_media_check, sample_file_entry):
        """Timeout exception returns TOOL_ERROR result."""
        mock_available.return_value = True
        mock_run.side_effect = subprocess.TimeoutExpired(cmd='ffprobe', timeout=300)

        outcome = mock_media_check._validate_single(mock_media_check, sample_file_entry)

        assert outcome.result == ValidationResult.TOOL_ERROR
        assert 'timed out' in outcome.error_message.lower()

    @patch('subprocess.run')
    @patch('tackles.MediaIntegrityCheck.check_tool_available')
    def test_os_error_returns_tool_error(self, mock_available, mock_run, mock_media_check, sample_file_entry):
        """OSError exception returns TOOL_ERROR result."""
        mock_available.return_value = True
        mock_run.side_effect = OSError('Permission denied')

        outcome = mock_media_check._validate_single(mock_media_check, sample_file_entry)

        assert outcome.result == ValidationResult.TOOL_ERROR
        assert 'Permission denied' in outcome.error_message

    @patch('subprocess.run')
    @patch('tackles.MediaIntegrityCheck.check_tool_available')
    def test_generic_exception_returns_tool_error(self, mock_available, mock_run, mock_media_check, sample_file_entry):
        """Generic exception returns TOOL_ERROR result."""
        mock_available.return_value = True
        mock_run.side_effect = Exception('Unexpected error')

        outcome = mock_media_check._validate_single(mock_media_check, sample_file_entry)

        assert outcome.result == ValidationResult.TOOL_ERROR
        assert 'Unexpected error' in outcome.error_message

    @patch('tackles.MediaIntegrityCheck.check_tool_available')
    def test_tool_missing_returns_tool_missing(self, mock_available, mock_media_check, sample_file_entry):
        """Missing tool returns TOOL_MISSING result."""
        mock_available.return_value = False

        outcome = mock_media_check._validate_single(mock_media_check, sample_file_entry)

        assert outcome.result == ValidationResult.TOOL_MISSING
        assert outcome.tool == 'ffprobe'
        assert 'not installed' in outcome.error_message.lower()

    def test_unknown_extension_returns_untestable(self, mock_media_check, tmp_path):
        """Unknown extension returns UNTESTABLE result."""
        from common.FileEntry import FileEntry

        test_file = tmp_path / 'test.xyz'
        test_file.write_bytes(b'content')
        entry = FileEntry.from_fs_path(str(test_file))

        outcome = mock_media_check._validate_single(mock_media_check, entry)

        assert outcome.result == ValidationResult.UNTESTABLE
        assert 'no validator' in outcome.error_message.lower()


class TestOggOpusStderrDetection:
    """Tests for ogg/opus stderr error pattern detection."""

    @pytest.fixture
    def mock_media_check(self):
        """Create a mock MediaIntegrityCheck instance."""
        from tackles.MediaIntegrityCheck import MediaIntegrityCheck, CheckLevel

        mock = MagicMock(spec=MediaIntegrityCheck)
        mock.timeout = 300
        mock.check_level = CheckLevel.DEFAULT
        mock._validate_single = MediaIntegrityCheck._validate_single
        return mock

    @patch('subprocess.run')
    @patch('tackles.MediaIntegrityCheck.check_tool_available')
    def test_ogg_stderr_with_error_is_corrupt(self, mock_available, mock_run, mock_media_check, tmp_path):
        """OGG file with 'error' in stderr should be CORRUPT even with exit 0."""
        from common.FileEntry import FileEntry

        test_file = tmp_path / 'test.ogg'
        test_file.write_bytes(b'OggS')
        entry = FileEntry.from_fs_path(str(test_file))

        mock_available.return_value = True
        mock_run.return_value = MagicMock(returncode=0, stderr='Warning: error in stream data')

        outcome = mock_media_check._validate_single(mock_media_check, entry)

        assert outcome.result == ValidationResult.CORRUPT

    @patch('subprocess.run')
    @patch('tackles.MediaIntegrityCheck.check_tool_available')
    def test_ogg_stderr_without_error_is_valid(self, mock_available, mock_run, mock_media_check, tmp_path):
        """OGG file without 'error' in stderr should be VALID."""
        from common.FileEntry import FileEntry

        test_file = tmp_path / 'test.ogg'
        test_file.write_bytes(b'OggS')
        entry = FileEntry.from_fs_path(str(test_file))

        mock_available.return_value = True
        mock_run.return_value = MagicMock(returncode=0, stderr='Processing complete')

        outcome = mock_media_check._validate_single(mock_media_check, entry)

        assert outcome.result == ValidationResult.VALID

    @patch('subprocess.run')
    @patch('tackles.MediaIntegrityCheck.check_tool_available')
    def test_opus_stderr_with_error_is_corrupt(self, mock_available, mock_run, mock_media_check, tmp_path):
        """Opus file with 'error' in stderr should be CORRUPT even with exit 0."""
        from common.FileEntry import FileEntry

        test_file = tmp_path / 'test.opus'
        test_file.write_bytes(b'OggS')
        entry = FileEntry.from_fs_path(str(test_file))

        mock_available.return_value = True
        mock_run.return_value = MagicMock(returncode=0, stderr='ERROR: could not parse')

        outcome = mock_media_check._validate_single(mock_media_check, entry)

        assert outcome.result == ValidationResult.CORRUPT


class TestQpdfSpecialExitCode:
    """Tests for qpdf special exit code handling."""

    @pytest.fixture
    def mock_media_check(self):
        """Create a mock MediaIntegrityCheck instance."""
        from tackles.MediaIntegrityCheck import MediaIntegrityCheck, CheckLevel

        mock = MagicMock(spec=MediaIntegrityCheck)
        mock.timeout = 300
        mock.check_level = CheckLevel.DEFAULT
        mock._validate_single = MediaIntegrityCheck._validate_single
        return mock

    @patch('subprocess.run')
    @patch('tackles.MediaIntegrityCheck.check_tool_available')
    def test_qpdf_exit_0_is_valid(self, mock_available, mock_run, mock_media_check, tmp_path):
        """qpdf exit code 0 should be VALID."""
        from common.FileEntry import FileEntry

        test_file = tmp_path / 'test.pdf'
        test_file.write_bytes(b'%PDF-1.4')
        entry = FileEntry.from_fs_path(str(test_file))

        mock_available.return_value = True
        mock_run.return_value = MagicMock(returncode=0, stderr='')

        outcome = mock_media_check._validate_single(mock_media_check, entry)

        assert outcome.result == ValidationResult.VALID

    @patch('subprocess.run')
    @patch('tackles.MediaIntegrityCheck.check_tool_available')
    def test_qpdf_exit_3_is_valid(self, mock_available, mock_run, mock_media_check, tmp_path):
        """qpdf exit code 3 (warnings) should be VALID."""
        from common.FileEntry import FileEntry

        test_file = tmp_path / 'test.pdf'
        test_file.write_bytes(b'%PDF-1.4')
        entry = FileEntry.from_fs_path(str(test_file))

        mock_available.return_value = True
        mock_run.return_value = MagicMock(returncode=3, stderr='WARNING: repaired')

        outcome = mock_media_check._validate_single(mock_media_check, entry)

        assert outcome.result == ValidationResult.VALID

    @patch('subprocess.run')
    @patch('tackles.MediaIntegrityCheck.check_tool_available')
    def test_qpdf_exit_2_is_corrupt(self, mock_available, mock_run, mock_media_check, tmp_path):
        """qpdf exit code 2 (error) should be CORRUPT."""
        from common.FileEntry import FileEntry

        test_file = tmp_path / 'test.pdf'
        test_file.write_bytes(b'%PDF-1.4')
        entry = FileEntry.from_fs_path(str(test_file))

        mock_available.return_value = True
        mock_run.return_value = MagicMock(returncode=2, stderr='ERROR: invalid PDF')

        outcome = mock_media_check._validate_single(mock_media_check, entry)

        assert outcome.result == ValidationResult.CORRUPT


# ===========================================================================
# 8. Integration-style Tests (using tmp_path)
# ===========================================================================


class TestScanDirectory:
    """Tests for _scan_directory() method."""

    @pytest.fixture
    def mock_media_check_for_scan(self, tmp_path):
        """Create a mock MediaIntegrityCheck instance for scanning."""
        from tackles.MediaIntegrityCheck import MediaIntegrityCheck

        mock = MagicMock(spec=MediaIntegrityCheck)
        mock.directory = str(tmp_path)
        mock.allowed_extensions = None
        mock._scan_directory = MediaIntegrityCheck._scan_directory
        return mock

    def test_scan_finds_all_files(self, mock_media_check_for_scan, tmp_path):
        """Scan should find all files in directory."""
        # Create test files
        (tmp_path / 'file1.mp4').write_bytes(b'content1')
        (tmp_path / 'file2.jpg').write_bytes(b'content2')
        (tmp_path / 'file3.txt').write_bytes(b'content3')

        entries = mock_media_check_for_scan._scan_directory(mock_media_check_for_scan)

        assert len(entries) == 3
        paths = [e.path for e in entries]
        assert any('file1.mp4' in p for p in paths)
        assert any('file2.jpg' in p for p in paths)
        assert any('file3.txt' in p for p in paths)

    def test_scan_recursive(self, mock_media_check_for_scan, tmp_path):
        """Scan should find files recursively."""
        # Create nested structure
        subdir = tmp_path / 'subdir'
        subdir.mkdir()
        (tmp_path / 'root.mp4').write_bytes(b'content')
        (subdir / 'nested.mp4').write_bytes(b'content')

        entries = mock_media_check_for_scan._scan_directory(mock_media_check_for_scan)

        assert len(entries) == 2
        paths = [e.path for e in entries]
        assert any('root.mp4' in p for p in paths)
        assert any('nested.mp4' in p for p in paths)

    def test_scan_skips_symlinks(self, mock_media_check_for_scan, tmp_path):
        """Scan should skip symlinks."""
        real_file = tmp_path / 'real.mp4'
        real_file.write_bytes(b'content')

        link = tmp_path / 'link.mp4'
        try:
            link.symlink_to(real_file)
        except OSError:
            pytest.skip('Symlinks not supported on this system')

        entries = mock_media_check_for_scan._scan_directory(mock_media_check_for_scan)

        # Should only find the real file, not the symlink
        assert len(entries) == 1
        assert 'real.mp4' in entries[0].path

    def test_scan_with_extension_filter(self, mock_media_check_for_scan, tmp_path):
        """Scan should filter by allowed extensions."""
        mock_media_check_for_scan.allowed_extensions = {'.mp4', '.jpg'}

        (tmp_path / 'file1.mp4').write_bytes(b'content1')
        (tmp_path / 'file2.jpg').write_bytes(b'content2')
        (tmp_path / 'file3.txt').write_bytes(b'content3')
        (tmp_path / 'file4.png').write_bytes(b'content4')

        entries = mock_media_check_for_scan._scan_directory(mock_media_check_for_scan)

        assert len(entries) == 2
        paths = [e.path for e in entries]
        assert any('file1.mp4' in p for p in paths)
        assert any('file2.jpg' in p for p in paths)
        assert not any('file3.txt' in p for p in paths)
        assert not any('file4.png' in p for p in paths)

    def test_scan_empty_directory(self, mock_media_check_for_scan, tmp_path):
        """Scan of empty directory returns empty list."""
        entries = mock_media_check_for_scan._scan_directory(mock_media_check_for_scan)
        assert entries == []


class TestOutputFileNaming:
    """Tests for output file naming with suffixes."""

    def test_output_suffixes(self):
        """Output files should use correct suffixes."""
        output_base = '/tmp/integrity_check'

        ok_path = f'{output_base}_ok.csv'
        broken_path = f'{output_base}_broken.csv'
        untestable_path = f'{output_base}_untestable.csv'
        missing_tool_path = f'{output_base}_missing_tool.csv'
        error_path = f'{output_base}_error.csv'

        assert ok_path == '/tmp/integrity_check_ok.csv'
        assert broken_path == '/tmp/integrity_check_broken.csv'
        assert untestable_path == '/tmp/integrity_check_untestable.csv'
        assert missing_tool_path == '/tmp/integrity_check_missing_tool.csv'
        assert error_path == '/tmp/integrity_check_error.csv'

    def test_custom_output_base(self):
        """Custom output base generates correct paths."""
        output_base = '/data/media/scan_2024'

        ok_path = f'{output_base}_ok.csv'
        broken_path = f'{output_base}_broken.csv'

        assert ok_path == '/data/media/scan_2024_ok.csv'
        assert broken_path == '/data/media/scan_2024_broken.csv'


# ===========================================================================
# 9. ValidationOutcome Tests
# ===========================================================================


class TestValidationOutcome:
    """Tests for ValidationOutcome dataclass."""

    def test_create_valid_outcome(self, tmp_path):
        """Create outcome for valid file."""
        from common.FileEntry import FileEntry

        test_file = tmp_path / 'test.mp4'
        test_file.write_bytes(b'content')
        entry = FileEntry.from_fs_path(str(test_file))

        outcome = ValidationOutcome(
            entry=entry,
            result=ValidationResult.VALID,
            tool='ffprobe',
            exit_code=0,
        )

        assert outcome.result == ValidationResult.VALID
        assert outcome.tool == 'ffprobe'
        assert outcome.exit_code == 0
        assert outcome.error_message is None

    def test_create_corrupt_outcome(self, tmp_path):
        """Create outcome for corrupt file."""
        from common.FileEntry import FileEntry

        test_file = tmp_path / 'test.mp4'
        test_file.write_bytes(b'content')
        entry = FileEntry.from_fs_path(str(test_file))

        outcome = ValidationOutcome(
            entry=entry,
            result=ValidationResult.CORRUPT,
            tool='ffprobe',
            exit_code=1,
            stderr_snippet='Invalid data found',
        )

        assert outcome.result == ValidationResult.CORRUPT
        assert outcome.stderr_snippet == 'Invalid data found'

    def test_create_tool_error_outcome(self, tmp_path):
        """Create outcome for tool error."""
        from common.FileEntry import FileEntry

        test_file = tmp_path / 'test.mp4'
        test_file.write_bytes(b'content')
        entry = FileEntry.from_fs_path(str(test_file))

        outcome = ValidationOutcome(
            entry=entry,
            result=ValidationResult.TOOL_ERROR,
            tool='ffprobe',
            error_message='Timeout after 300s',
        )

        assert outcome.result == ValidationResult.TOOL_ERROR
        assert outcome.error_message == 'Timeout after 300s'

    def test_create_untestable_outcome(self, tmp_path):
        """Create outcome for untestable file."""
        from common.FileEntry import FileEntry

        test_file = tmp_path / 'test.xyz'
        test_file.write_bytes(b'content')
        entry = FileEntry.from_fs_path(str(test_file))

        outcome = ValidationOutcome(
            entry=entry,
            result=ValidationResult.UNTESTABLE,
            error_message='No validator defined',
        )

        assert outcome.result == ValidationResult.UNTESTABLE
        assert outcome.tool is None

    def test_create_tool_missing_outcome(self, tmp_path):
        """Create outcome for missing tool."""
        from common.FileEntry import FileEntry

        test_file = tmp_path / 'test.mp4'
        test_file.write_bytes(b'content')
        entry = FileEntry.from_fs_path(str(test_file))

        outcome = ValidationOutcome(
            entry=entry,
            result=ValidationResult.TOOL_MISSING,
            tool='ffprobe',
            error_message='Tool not installed',
        )

        assert outcome.result == ValidationResult.TOOL_MISSING
        assert outcome.tool == 'ffprobe'


# ===========================================================================
# 10. ToolConfig Tests
# ===========================================================================


class TestToolConfig:
    """Tests for ToolConfig dataclass."""

    def test_create_basic_config(self):
        """Create basic ToolConfig."""
        config = ToolConfig(
            binary='ffprobe',
            apt_package='ffmpeg',
            args=('-v', 'error', '-i'),
        )

        assert config.binary == 'ffprobe'
        assert config.apt_package == 'ffmpeg'
        assert config.args == ('-v', 'error', '-i')
        assert config.success_codes == (0,)  # default
        assert config.check_stderr is None  # default

    def test_create_config_with_success_codes(self):
        """Create ToolConfig with custom success codes."""
        config = ToolConfig(
            binary='qpdf',
            apt_package='qpdf',
            args=('--check',),
            success_codes=(0, 3),
        )

        assert config.success_codes == (0, 3)

    def test_create_config_with_stderr_check(self):
        """Create ToolConfig with stderr pattern check."""
        config = ToolConfig(
            binary='ogginfo',
            apt_package='vorbis-tools',
            args=(),
            check_stderr=r'(?i)error',
        )

        assert config.check_stderr == r'(?i)error'


# ===========================================================================
# 11. Edge Cases Tests
# ===========================================================================


class TestEdgeCases:
    """Tests for edge cases and corner scenarios."""

    def test_empty_file(self, tmp_path):
        """Empty file can be processed."""
        from common.FileEntry import FileEntry

        test_file = tmp_path / 'empty.mp4'
        test_file.write_bytes(b'')
        entry = FileEntry.from_fs_path(str(test_file))

        assert entry.size == 0
        assert entry.path.endswith('empty.mp4')

    def test_unicode_filename(self, tmp_path):
        """Unicode filename is handled correctly."""
        from common.FileEntry import FileEntry

        test_file = tmp_path / 'файл_видео.mp4'
        test_file.write_bytes(b'content')
        entry = FileEntry.from_fs_path(str(test_file))

        assert 'файл_видео.mp4' in entry.path

    def test_unicode_filename_chinese(self, tmp_path):
        """Chinese filename is handled correctly."""
        from common.FileEntry import FileEntry

        test_file = tmp_path / '视频文件.mp4'
        test_file.write_bytes(b'content')
        entry = FileEntry.from_fs_path(str(test_file))

        assert '视频文件.mp4' in entry.path

    def test_space_in_filename(self, tmp_path):
        """Filename with spaces is handled correctly."""
        from common.FileEntry import FileEntry

        test_file = tmp_path / 'my video file.mp4'
        test_file.write_bytes(b'content')
        entry = FileEntry.from_fs_path(str(test_file))

        assert 'my video file.mp4' in entry.path

    def test_special_chars_in_filename(self, tmp_path):
        """Filename with special characters is handled."""
        from common.FileEntry import FileEntry

        test_file = tmp_path / 'file-with_special.chars.mp4'
        test_file.write_bytes(b'content')
        entry = FileEntry.from_fs_path(str(test_file))

        assert 'file-with_special.chars.mp4' in entry.path

    def test_very_long_filename(self, tmp_path):
        """Very long filename is handled."""
        from common.FileEntry import FileEntry

        long_name = 'a' * 200 + '.mp4'
        try:
            test_file = tmp_path / long_name
            test_file.write_bytes(b'content')
            entry = FileEntry.from_fs_path(str(test_file))
            assert entry.path.endswith('.mp4')
        except OSError:
            pytest.skip('Filesystem does not support long filenames')

    def test_deeply_nested_path(self, tmp_path):
        """Deeply nested path is handled."""
        from common.FileEntry import FileEntry

        deep_path = tmp_path / 'a' / 'b' / 'c' / 'd' / 'e'
        deep_path.mkdir(parents=True)
        test_file = deep_path / 'deep.mp4'
        test_file.write_bytes(b'content')
        entry = FileEntry.from_fs_path(str(test_file))

        assert entry.path.endswith('deep.mp4')
        assert 'a' in entry.path


# ===========================================================================
# 12. Coverage for All Supported Extensions
# ===========================================================================


class TestAllSupportedExtensions:
    """Tests that verify all supported extensions are properly configured."""

    @pytest.mark.parametrize('ext', [
        '.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm', '.m4v',
        '.mpeg', '.mpg', '.3gp', '.ts', '.m2ts', '.vob',
    ])
    def test_video_extensions_use_ffprobe(self, ext):
        """All video extensions should use ffprobe."""
        config = get_tool_config(ext)
        assert config is not None, f'{ext} not in registry'
        assert config.binary == 'ffprobe'
        assert config.apt_package == 'ffmpeg'

    @pytest.mark.parametrize('ext', ['.jpg', '.jpeg'])
    def test_jpeg_extensions_use_jpeginfo(self, ext):
        """JPEG extensions should use jpeginfo."""
        config = get_tool_config(ext)
        assert config is not None
        assert config.binary == 'jpeginfo'

    @pytest.mark.parametrize('ext', ['.gif', '.bmp', '.tiff', '.tif', '.webp', '.heic'])
    def test_image_extensions_use_identify(self, ext):
        """Various image extensions should use ImageMagick identify."""
        config = get_tool_config(ext)
        assert config is not None
        assert config.binary == 'identify'
        assert config.apt_package == 'imagemagick'

    @pytest.mark.parametrize('ext', ['.zip', '.docx', '.xlsx', '.pptx'])
    def test_zip_based_extensions_use_unzip(self, ext):
        """ZIP-based extensions should use unzip."""
        config = get_tool_config(ext)
        assert config is not None
        assert config.binary == 'unzip'

    def test_mp3_uses_mp3val(self):
        """MP3 should use mp3val."""
        config = get_tool_config('.mp3')
        assert config is not None
        assert config.binary == 'mp3val'
        assert config.apt_package == 'mp3val'

    def test_flac_uses_flac(self):
        """FLAC should use flac binary."""
        config = get_tool_config('.flac')
        assert config is not None
        assert config.binary == 'flac'

    def test_png_uses_pngcheck(self):
        """PNG should use pngcheck."""
        config = get_tool_config('.png')
        assert config is not None
        assert config.binary == 'pngcheck'

    def test_7z_uses_7z(self):
        """.7z should use 7z binary."""
        config = get_tool_config('.7z')
        assert config is not None
        assert config.binary == '7z'
        assert config.apt_package == 'p7zip-full'

    def test_rar_uses_unrar(self):
        """.rar should use unrar binary."""
        config = get_tool_config('.rar')
        assert config is not None
        assert config.binary == 'unrar'


# ===========================================================================
# 13. CheckLevel Enum Tests
# ===========================================================================


class TestCheckLevel:
    """Tests for CheckLevel enum."""

    def test_all_levels_exist(self):
        """All three check levels should exist."""
        assert hasattr(CheckLevel, 'BASIC')
        assert hasattr(CheckLevel, 'DEFAULT')
        assert hasattr(CheckLevel, 'PEDANTIC')

    def test_level_values(self):
        """Check level enum values should match expected strings."""
        assert CheckLevel.BASIC.value == 'basic'
        assert CheckLevel.DEFAULT.value == 'default'
        assert CheckLevel.PEDANTIC.value == 'pedantic'

    def test_level_count(self):
        """Exactly 3 check levels should exist."""
        assert len(CheckLevel) == 3

    def test_levels_are_distinct(self):
        """All check levels should be distinct."""
        levels = [CheckLevel.BASIC, CheckLevel.DEFAULT, CheckLevel.PEDANTIC]
        assert len(levels) == len(set(levels))


# ===========================================================================
# 14. Stderr Pattern Tests
# ===========================================================================


class TestStderrPatterns:
    """Tests for check_stderr patterns in tool configurations."""

    def test_ffprobe_has_check_stderr(self):
        """All ffprobe-based tools should have check_stderr pattern."""
        for ext in ['.mp4', '.mkv', '.avi', '.mov', '.wav', '.aac']:
            config = get_tool_config(ext)
            assert config is not None, f'{ext} not in registry'
            assert config.check_stderr is not None, f'{ext} missing check_stderr'

    def test_exiftool_has_check_stderr(self):
        """All exiftool-based RAW image tools should have check_stderr pattern."""
        for ext in ['.cr2', '.nef', '.arw', '.raw', '.dng']:
            config = get_tool_config(ext)
            assert config is not None, f'{ext} not in registry'
            assert config.check_stderr is not None, f'{ext} missing check_stderr'

    def test_archive_tools_have_check_stderr(self):
        """Archive tools (7z, rar, zip) should have check_stderr pattern."""
        assert get_tool_config('.7z').check_stderr is not None
        assert get_tool_config('.rar').check_stderr is not None
        assert get_tool_config('.zip').check_stderr is not None

    def test_reliable_tools_no_check_stderr(self):
        """Tools with reliable exit codes should not need check_stderr."""
        # These tools return reliable exit codes, so no stderr pattern needed
        assert get_tool_config('.flac').check_stderr is None
        assert get_tool_config('.png').check_stderr is None
        assert get_tool_config('.pdf').check_stderr is None
        assert get_tool_config('.tar').check_stderr is None

    def test_ogg_opus_have_check_stderr(self):
        """OGG and Opus tools should have check_stderr for error detection."""
        assert get_tool_config('.ogg').check_stderr is not None
        assert get_tool_config('.opus').check_stderr is not None


# ===========================================================================
# 15. Pedantic Mode Tests
# ===========================================================================


class TestPedanticMode:
    """Tests for pedantic mode configuration."""

    def test_ffprobe_has_pedantic_binary(self):
        """ffprobe-based tools should have pedantic_binary=ffmpeg."""
        for ext in ['.mp4', '.mkv', '.avi', '.mov']:
            config = get_tool_config(ext)
            assert config is not None, f'{ext} not in registry'
            assert config.pedantic_binary == 'ffmpeg', f'{ext} missing pedantic_binary'

    def test_pedantic_args_includes_hwaccel(self):
        """Pedantic args for video should include -hwaccel auto."""
        config = get_tool_config('.mp4')
        assert config is not None
        assert config.pedantic_args is not None
        assert '-hwaccel' in config.pedantic_args
        assert 'auto' in config.pedantic_args

    def test_pedantic_args_includes_error_verbosity(self):
        """Pedantic args should include -v error for quiet output."""
        config = get_tool_config('.mp4')
        assert config is not None
        assert config.pedantic_args is not None
        assert '-v' in config.pedantic_args
        assert 'error' in config.pedantic_args

    def test_non_video_no_pedantic_binary(self):
        """Non-video tools should not have pedantic_binary."""
        for ext in ['.zip', '.pdf', '.png', '.flac', '.mp3']:
            config = get_tool_config(ext)
            assert config is not None, f'{ext} not in registry'
            assert config.pedantic_binary is None, f'{ext} should not have pedantic_binary'

    def test_audio_ffprobe_has_pedantic_binary(self):
        """Audio formats using ffprobe should also have pedantic_binary."""
        for ext in ['.wav', '.aac', '.m4a', '.wma']:
            config = get_tool_config(ext)
            assert config is not None, f'{ext} not in registry'
            assert config.pedantic_binary == 'ffmpeg', f'{ext} missing pedantic_binary'


# ===========================================================================
# 16. Validation Logic with Levels (mocked)
# ===========================================================================


class TestValidationWithLevels:
    """Tests for validation logic with different check levels."""

    @pytest.fixture
    def mock_media_check_basic(self):
        """Create a mock MediaIntegrityCheck instance with BASIC level."""
        from tackles.MediaIntegrityCheck import MediaIntegrityCheck

        mock = MagicMock(spec=MediaIntegrityCheck)
        mock.timeout = 300
        mock.check_level = CheckLevel.BASIC
        mock._validate_single = MediaIntegrityCheck._validate_single
        return mock

    @pytest.fixture
    def mock_media_check_default(self):
        """Create a mock MediaIntegrityCheck instance with DEFAULT level."""
        from tackles.MediaIntegrityCheck import MediaIntegrityCheck

        mock = MagicMock(spec=MediaIntegrityCheck)
        mock.timeout = 300
        mock.check_level = CheckLevel.DEFAULT
        mock._validate_single = MediaIntegrityCheck._validate_single
        return mock

    @pytest.fixture
    def mock_media_check_pedantic(self):
        """Create a mock MediaIntegrityCheck instance with PEDANTIC level."""
        from tackles.MediaIntegrityCheck import MediaIntegrityCheck

        mock = MagicMock(spec=MediaIntegrityCheck)
        mock.timeout = 300
        mock.check_level = CheckLevel.PEDANTIC
        mock._validate_single = MediaIntegrityCheck._validate_single
        return mock

    @patch('subprocess.run')
    @patch('tackles.MediaIntegrityCheck.check_tool_available')
    def test_basic_level_ignores_stderr(self, mock_available, mock_run, mock_media_check_basic, tmp_path):
        """BASIC level should only check exit code, not stderr."""
        from common.FileEntry import FileEntry

        test_file = tmp_path / 'test.mp4'
        test_file.write_bytes(b'fake mp4')
        entry = FileEntry.from_fs_path(str(test_file))

        mock_available.return_value = True
        mock_run.return_value = MagicMock(
            returncode=0,
            stderr='[error] some warning message'
        )

        # With BASIC level, should return VALID despite stderr errors
        outcome = mock_media_check_basic._validate_single(mock_media_check_basic, entry)
        assert outcome.result == ValidationResult.VALID

    @patch('subprocess.run')
    @patch('tackles.MediaIntegrityCheck.check_tool_available')
    def test_default_level_checks_stderr(self, mock_available, mock_run, mock_media_check_default, tmp_path):
        """DEFAULT level should check stderr patterns."""
        from common.FileEntry import FileEntry

        test_file = tmp_path / 'test.mp4'
        test_file.write_bytes(b'fake mp4')
        entry = FileEntry.from_fs_path(str(test_file))

        mock_available.return_value = True
        mock_run.return_value = MagicMock(
            returncode=0,
            stderr='[error] invalid header'
        )

        # With DEFAULT level, should return CORRUPT due to stderr pattern match
        outcome = mock_media_check_default._validate_single(mock_media_check_default, entry)
        assert outcome.result == ValidationResult.CORRUPT

    @patch('subprocess.run')
    @patch('tackles.MediaIntegrityCheck.check_tool_available')
    def test_pedantic_level_uses_ffmpeg(self, mock_available, mock_run, mock_media_check_pedantic, tmp_path):
        """PEDANTIC level should use ffmpeg instead of ffprobe for video."""
        from common.FileEntry import FileEntry

        test_file = tmp_path / 'test.mp4'
        test_file.write_bytes(b'fake mp4')
        entry = FileEntry.from_fs_path(str(test_file))

        mock_available.return_value = True
        mock_run.return_value = MagicMock(returncode=0, stderr='')

        outcome = mock_media_check_pedantic._validate_single(mock_media_check_pedantic, entry)

        # Verify ffmpeg was called, not ffprobe
        assert outcome.tool == 'ffmpeg'
        assert outcome.result == ValidationResult.VALID

    @patch('subprocess.run')
    @patch('tackles.MediaIntegrityCheck.check_tool_available')
    def test_pedantic_level_falls_back_to_normal_for_non_video(self, mock_available, mock_run, mock_media_check_pedantic, tmp_path):
        """PEDANTIC level should use normal binary for tools without pedantic_binary."""
        from common.FileEntry import FileEntry

        test_file = tmp_path / 'test.pdf'
        test_file.write_bytes(b'%PDF-1.4')
        entry = FileEntry.from_fs_path(str(test_file))

        mock_available.return_value = True
        mock_run.return_value = MagicMock(returncode=0, stderr='')

        outcome = mock_media_check_pedantic._validate_single(mock_media_check_pedantic, entry)

        # Should still use qpdf since PDF has no pedantic_binary
        assert outcome.tool == 'qpdf'
        assert outcome.result == ValidationResult.VALID


# ===========================================================================
# 17. Stderr Pattern Matching Tests
# ===========================================================================


class TestStderrPatternMatching:
    """Tests for stderr pattern regex matching."""

    def test_ffprobe_pattern_matches_error(self):
        """ffprobe pattern should match error indicators."""
        import re

        config = get_tool_config('.mp4')
        pattern = config.check_stderr
        assert pattern is not None

        assert re.search(pattern, '[error] invalid something')
        assert re.search(pattern, 'moov atom not found')
        assert re.search(pattern, 'Invalid frame dimensions')
        assert re.search(pattern, 'Corrupt data')
        assert re.search(pattern, 'ERROR: something failed')

    def test_ffprobe_pattern_ignores_normal_output(self):
        """ffprobe pattern should not match normal output."""
        import re

        config = get_tool_config('.mp4')
        pattern = config.check_stderr
        assert pattern is not None

        assert not re.search(pattern, 'Input #0, mov,mp4,m4a')
        assert not re.search(pattern, 'Duration: 00:01:23')
        assert not re.search(pattern, 'Stream #0:0: Video: h264')
        assert not re.search(pattern, '')

    def test_7z_pattern_matches_warnings(self):
        """7z pattern should match warnings and errors."""
        import re

        config = get_tool_config('.7z')
        pattern = config.check_stderr
        assert pattern is not None

        assert re.search(pattern, 'Warnings: 1')
        assert re.search(pattern, 'Warnings: 42')
        assert re.search(pattern, 'Cannot open the file')
        assert re.search(pattern, 'Error: file is broken')

    def test_7z_pattern_ignores_warnings_zero(self):
        """7z pattern should not match 'Warnings: 0'."""
        import re

        config = get_tool_config('.7z')
        pattern = config.check_stderr
        assert pattern is not None

        # 'Warnings: 0' should not trigger the pattern
        assert not re.search(pattern, 'Warnings: 0')

    def test_unrar_pattern_matches_errors(self):
        """unrar pattern should match various error conditions."""
        import re

        config = get_tool_config('.rar')
        pattern = config.check_stderr
        assert pattern is not None

        assert re.search(pattern, 'ERROR: CRC failed')
        assert re.search(pattern, 'corrupt header')
        assert re.search(pattern, 'CRC failed in file.txt')

    def test_exiftool_pattern_matches_warnings(self):
        """exiftool pattern should match warnings and errors."""
        import re

        config = get_tool_config('.cr2')
        pattern = config.check_stderr
        assert pattern is not None

        assert re.search(pattern, 'Warning: Invalid data')
        assert re.search(pattern, 'Error: File format error')
        assert re.search(pattern, 'Invalid EXIF data')

    def test_ogg_pattern_matches_error(self):
        """ogg pattern should match error keyword."""
        import re

        config = get_tool_config('.ogg')
        pattern = config.check_stderr
        assert pattern is not None

        assert re.search(pattern, 'error in stream')
        assert re.search(pattern, 'ERROR: invalid')
        assert re.search(pattern, 'Error reading file')

    def test_ogg_pattern_case_insensitive(self):
        """ogg pattern should be case insensitive."""
        import re

        config = get_tool_config('.ogg')
        pattern = config.check_stderr
        assert pattern is not None

        assert re.search(pattern, 'error')
        assert re.search(pattern, 'Error')
        assert re.search(pattern, 'ERROR')


# ===========================================================================
# 18. New Extension Tests (8 new extensions)
# ===========================================================================


class TestNewExtensions:
    """Tests to verify new extensions are in TOOL_REGISTRY."""

    @pytest.mark.parametrize('ext', ['lrv', 'thm', 'insv', 'rtf', 'doc', 'fb2', '360', 'djvu'])
    def test_extension_in_registry(self, ext):
        """Each new extension should be in TOOL_REGISTRY."""
        assert f'.{ext}' in TOOL_REGISTRY


class TestNewExtensionConfigs:
    """Tests to verify correct tool configuration for new extensions."""

    def test_lrv_uses_ffprobe(self):
        """GoPro proxy video (.lrv) should use ffprobe with pedantic ffmpeg."""
        config = get_tool_config('.lrv')
        assert config is not None
        assert config.binary == 'ffprobe'
        assert config.pedantic_binary == 'ffmpeg'

    def test_thm_uses_jpeginfo(self):
        """Thumbnail JPEG (.thm) should use jpeginfo."""
        config = get_tool_config('.thm')
        assert config is not None
        assert config.binary == 'jpeginfo'

    def test_insv_uses_ffprobe(self):
        """Insta360 video (.insv) should use ffprobe with stderr check."""
        config = get_tool_config('.insv')
        assert config is not None
        assert config.binary == 'ffprobe'
        assert config.check_stderr is not None

    def test_rtf_uses_unrtf(self):
        """Rich Text Format (.rtf) should use unrtf."""
        config = get_tool_config('.rtf')
        assert config is not None
        assert config.binary == 'unrtf'
        assert config.apt_package == 'unrtf'

    def test_doc_uses_antiword(self):
        """Old Word binary (.doc) should use antiword."""
        config = get_tool_config('.doc')
        assert config is not None
        assert config.binary == 'antiword'
        assert config.apt_package == 'antiword'

    def test_fb2_uses_xmllint(self):
        """FictionBook ebook (.fb2) should use xmllint."""
        config = get_tool_config('.fb2')
        assert config is not None
        assert config.binary == 'xmllint'
        assert config.apt_package == 'libxml2-utils'

    def test_360_uses_ffprobe(self):
        """360-degree video (.360) should use ffprobe with pedantic ffmpeg."""
        config = get_tool_config('.360')
        assert config is not None
        assert config.binary == 'ffprobe'
        assert config.pedantic_binary == 'ffmpeg'

    def test_djvu_uses_ddjvu(self):
        """DjVu document (.djvu) should use ddjvu."""
        config = get_tool_config('.djvu')
        assert config is not None
        assert config.binary == 'ddjvu'
        assert config.apt_package == 'djvulibre-bin'


class TestArgsAfterFile:
    """Tests for args_after_file field in tool configurations."""

    def test_djvu_has_args_after_file(self):
        """ddjvu needs output file after input file."""
        config = get_tool_config('.djvu')
        assert config is not None
        assert hasattr(config, 'args_after_file')
        assert '/dev/null' in config.args_after_file

    def test_most_tools_have_empty_args_after_file(self):
        """Most tools don't need args after file."""
        for ext in ['.mp4', '.jpg', '.pdf', '.zip']:
            config = get_tool_config(ext)
            assert config is not None
            assert config.args_after_file == ()


class TestNewVideoExtensionsPedantic:
    """Tests for pedantic mode on new video extensions."""

    @pytest.mark.parametrize('ext', ['.lrv', '.insv', '.360'])
    def test_video_has_pedantic_ffmpeg(self, ext):
        """New video extensions should have pedantic_binary=ffmpeg."""
        config = get_tool_config(ext)
        assert config is not None
        assert config.pedantic_binary == 'ffmpeg'
        assert config.pedantic_args is not None
        assert '-hwaccel' in config.pedantic_args
