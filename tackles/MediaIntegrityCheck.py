"""
MediaIntegrityCheck tackle — validates media file integrity using Linux system tools.

Scans directories recursively and categorizes files as valid, corrupt, untestable,
missing tool, or tool error based on external validation tools.

Platform Restriction: Linux/WSL only — relies on Linux-native tools like
ffprobe, jpeginfo, mp3val, etc.
"""

import logging
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, List, Optional, Set, Tuple

from common.FileEntry import FileEntry
from common.listing import write_listing
from tackles.TackleFactory import TackleFactory

logging.basicConfig(
    level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# CheckLevel Enum (3 validation levels)
# ---------------------------------------------------------------------------

class CheckLevel(Enum):
    """Validation thoroughness level."""
    BASIC = 'basic'        # Exit code only (fastest)
    DEFAULT = 'default'    # Exit code + stderr patterns (recommended)
    PEDANTIC = 'pedantic'  # Full decode/verify (slowest)


# ---------------------------------------------------------------------------
# ValidationResult Enum (5 values)
# ---------------------------------------------------------------------------

class ValidationResult(Enum):
    """Result of validating a single file."""
    VALID = auto()        # Tool confirmed file is valid
    CORRUPT = auto()      # Tool confirmed file is corrupt
    UNTESTABLE = auto()   # No validator defined for this extension
    TOOL_MISSING = auto() # Validator exists but not installed
    TOOL_ERROR = auto()   # Tool execution failed (timeout, exception, etc.)


# ---------------------------------------------------------------------------
# Tool Registry Data Structures
# ---------------------------------------------------------------------------

@dataclass
class ToolConfig:
    """Configuration for a validation tool."""
    binary: str                              # Tool executable name
    apt_package: str                         # Debian/Ubuntu package name
    args: Tuple[str, ...]                    # Arguments BEFORE the file path
    success_codes: Tuple[int, ...] = (0,)    # Exit codes that mean "valid"
    check_stderr: Optional[str] = None       # Regex pattern to find in stderr (for DEFAULT level)
    pedantic_binary: Optional[str] = None    # Alternative binary for PEDANTIC level
    pedantic_args: Optional[Tuple[str, ...]] = None  # Alternative args for PEDANTIC level
    args_after_file: Tuple[str, ...] = ()    # Arguments AFTER the file path (e.g., for ddjvu output)


# Common patterns for check_stderr
_FFPROBE_STDERR = r'(?i)(error|invalid|corrupt|moov atom not found)'
_EXIFTOOL_STDERR = r'(?i)(warning|error|invalid)'
_7Z_STDERR = r'(?i)(error|cannot|warnings:\s*[1-9])'
_EPUBCHECK_STDERR = r'(?i)(error|fatal)'
_JPEGINFO_STDERR = r'(?i)(warning|error|corrupt)'
_UNRAR_STDERR = r'(?i)(error|corrupt|crc failed)'
_UNZIP_STDERR = r'(?i)(error|warning|bad crc)'

# Common pedantic settings for ffprobe extensions
_FFMPEG_PEDANTIC_BINARY = 'ffmpeg'
_FFMPEG_PEDANTIC_ARGS = ('-hwaccel', 'auto', '-v', 'error', '-i')

# File extension to tool mapping
TOOL_REGISTRY: Dict[str, ToolConfig] = {
    # Video formats (ffprobe with pedantic ffmpeg decode)
    '.mp4':   ToolConfig('ffprobe', 'ffmpeg', ('-v', 'error', '-i'),
                         check_stderr=_FFPROBE_STDERR,
                         pedantic_binary=_FFMPEG_PEDANTIC_BINARY,
                         pedantic_args=_FFMPEG_PEDANTIC_ARGS),
    '.mkv':   ToolConfig('ffprobe', 'ffmpeg', ('-v', 'error', '-i'),
                         check_stderr=_FFPROBE_STDERR,
                         pedantic_binary=_FFMPEG_PEDANTIC_BINARY,
                         pedantic_args=_FFMPEG_PEDANTIC_ARGS),
    '.avi':   ToolConfig('ffprobe', 'ffmpeg', ('-v', 'error', '-i'),
                         check_stderr=_FFPROBE_STDERR,
                         pedantic_binary=_FFMPEG_PEDANTIC_BINARY,
                         pedantic_args=_FFMPEG_PEDANTIC_ARGS),
    '.mov':   ToolConfig('ffprobe', 'ffmpeg', ('-v', 'error', '-i'),
                         check_stderr=_FFPROBE_STDERR,
                         pedantic_binary=_FFMPEG_PEDANTIC_BINARY,
                         pedantic_args=_FFMPEG_PEDANTIC_ARGS),
    '.wmv':   ToolConfig('ffprobe', 'ffmpeg', ('-v', 'error', '-i'),
                         check_stderr=_FFPROBE_STDERR,
                         pedantic_binary=_FFMPEG_PEDANTIC_BINARY,
                         pedantic_args=_FFMPEG_PEDANTIC_ARGS),
    '.flv':   ToolConfig('ffprobe', 'ffmpeg', ('-v', 'error', '-i'),
                         check_stderr=_FFPROBE_STDERR,
                         pedantic_binary=_FFMPEG_PEDANTIC_BINARY,
                         pedantic_args=_FFMPEG_PEDANTIC_ARGS),
    '.webm':  ToolConfig('ffprobe', 'ffmpeg', ('-v', 'error', '-i'),
                         check_stderr=_FFPROBE_STDERR,
                         pedantic_binary=_FFMPEG_PEDANTIC_BINARY,
                         pedantic_args=_FFMPEG_PEDANTIC_ARGS),
    '.m4v':   ToolConfig('ffprobe', 'ffmpeg', ('-v', 'error', '-i'),
                         check_stderr=_FFPROBE_STDERR,
                         pedantic_binary=_FFMPEG_PEDANTIC_BINARY,
                         pedantic_args=_FFMPEG_PEDANTIC_ARGS),
    '.mpeg':  ToolConfig('ffprobe', 'ffmpeg', ('-v', 'error', '-i'),
                         check_stderr=_FFPROBE_STDERR,
                         pedantic_binary=_FFMPEG_PEDANTIC_BINARY,
                         pedantic_args=_FFMPEG_PEDANTIC_ARGS),
    '.mpg':   ToolConfig('ffprobe', 'ffmpeg', ('-v', 'error', '-i'),
                         check_stderr=_FFPROBE_STDERR,
                         pedantic_binary=_FFMPEG_PEDANTIC_BINARY,
                         pedantic_args=_FFMPEG_PEDANTIC_ARGS),
    '.3gp':   ToolConfig('ffprobe', 'ffmpeg', ('-v', 'error', '-i'),
                         check_stderr=_FFPROBE_STDERR,
                         pedantic_binary=_FFMPEG_PEDANTIC_BINARY,
                         pedantic_args=_FFMPEG_PEDANTIC_ARGS),
    '.ts':    ToolConfig('ffprobe', 'ffmpeg', ('-v', 'error', '-i'),
                         check_stderr=_FFPROBE_STDERR,
                         pedantic_binary=_FFMPEG_PEDANTIC_BINARY,
                         pedantic_args=_FFMPEG_PEDANTIC_ARGS),
    '.m2ts':  ToolConfig('ffprobe', 'ffmpeg', ('-v', 'error', '-i'),
                         check_stderr=_FFPROBE_STDERR,
                         pedantic_binary=_FFMPEG_PEDANTIC_BINARY,
                         pedantic_args=_FFMPEG_PEDANTIC_ARGS),
    '.vob':   ToolConfig('ffprobe', 'ffmpeg', ('-v', 'error', '-i'),
                         check_stderr=_FFPROBE_STDERR,
                         pedantic_binary=_FFMPEG_PEDANTIC_BINARY,
                         pedantic_args=_FFMPEG_PEDANTIC_ARGS),

    # Audio formats
    '.mp3':   ToolConfig('mp3val', 'mp3val', ('-si',)),
    '.flac':  ToolConfig('flac', 'flac', ('-ts',)),
    '.ogg':   ToolConfig('ogginfo', 'vorbis-tools', (), check_stderr=r'(?i)error'),
    '.opus':  ToolConfig('opusinfo', 'opus-tools', (), check_stderr=r'(?i)error'),
    '.wav':   ToolConfig('ffprobe', 'ffmpeg', ('-v', 'error', '-i'),
                         check_stderr=_FFPROBE_STDERR,
                         pedantic_binary=_FFMPEG_PEDANTIC_BINARY,
                         pedantic_args=_FFMPEG_PEDANTIC_ARGS),
    '.aac':   ToolConfig('ffprobe', 'ffmpeg', ('-v', 'error', '-i'),
                         check_stderr=_FFPROBE_STDERR,
                         pedantic_binary=_FFMPEG_PEDANTIC_BINARY,
                         pedantic_args=_FFMPEG_PEDANTIC_ARGS),
    '.m4a':   ToolConfig('ffprobe', 'ffmpeg', ('-v', 'error', '-i'),
                         check_stderr=_FFPROBE_STDERR,
                         pedantic_binary=_FFMPEG_PEDANTIC_BINARY,
                         pedantic_args=_FFMPEG_PEDANTIC_ARGS),
    '.wma':   ToolConfig('ffprobe', 'ffmpeg', ('-v', 'error', '-i'),
                         check_stderr=_FFPROBE_STDERR,
                         pedantic_binary=_FFMPEG_PEDANTIC_BINARY,
                         pedantic_args=_FFMPEG_PEDANTIC_ARGS),
    '.aiff':  ToolConfig('ffprobe', 'ffmpeg', ('-v', 'error', '-i'),
                         check_stderr=_FFPROBE_STDERR,
                         pedantic_binary=_FFMPEG_PEDANTIC_BINARY,
                         pedantic_args=_FFMPEG_PEDANTIC_ARGS),
    '.ape':   ToolConfig('ffprobe', 'ffmpeg', ('-v', 'error', '-i'),
                         check_stderr=_FFPROBE_STDERR,
                         pedantic_binary=_FFMPEG_PEDANTIC_BINARY,
                         pedantic_args=_FFMPEG_PEDANTIC_ARGS),

    # Image formats
    '.jpg':   ToolConfig('jpeginfo', 'jpeginfo', ('-c',),
                         check_stderr=_JPEGINFO_STDERR),
    '.jpeg':  ToolConfig('jpeginfo', 'jpeginfo', ('-c',),
                         check_stderr=_JPEGINFO_STDERR),
    '.png':   ToolConfig('pngcheck', 'pngcheck', ('-q',)),
    '.gif':   ToolConfig('identify', 'imagemagick', ('-regard-warnings',)),
    '.bmp':   ToolConfig('identify', 'imagemagick', ('-regard-warnings',)),
    '.tiff':  ToolConfig('identify', 'imagemagick', ('-regard-warnings',)),
    '.tif':   ToolConfig('identify', 'imagemagick', ('-regard-warnings',)),
    '.webp':  ToolConfig('identify', 'imagemagick', ('-regard-warnings',)),
    '.heic':  ToolConfig('identify', 'imagemagick', ('-regard-warnings',)),
    '.cr2':   ToolConfig('exiftool', 'libimage-exiftool-perl', ('-validate', '-warning'),
                         check_stderr=_EXIFTOOL_STDERR),
    '.nef':   ToolConfig('exiftool', 'libimage-exiftool-perl', ('-validate', '-warning'),
                         check_stderr=_EXIFTOOL_STDERR),
    '.arw':   ToolConfig('exiftool', 'libimage-exiftool-perl', ('-validate', '-warning'),
                         check_stderr=_EXIFTOOL_STDERR),
    '.raw':   ToolConfig('exiftool', 'libimage-exiftool-perl', ('-validate', '-warning'),
                         check_stderr=_EXIFTOOL_STDERR),
    '.dng':   ToolConfig('exiftool', 'libimage-exiftool-perl', ('-validate', '-warning'),
                         check_stderr=_EXIFTOOL_STDERR),

    # Archive formats
    '.zip':   ToolConfig('unzip', 'unzip', ('-t',),
                         check_stderr=_UNZIP_STDERR),
    '.docx':  ToolConfig('unzip', 'unzip', ('-t',),
                         check_stderr=_UNZIP_STDERR),
    '.xlsx':  ToolConfig('unzip', 'unzip', ('-t',),
                         check_stderr=_UNZIP_STDERR),
    '.pptx':  ToolConfig('unzip', 'unzip', ('-t',),
                         check_stderr=_UNZIP_STDERR),
    '.tar':   ToolConfig('tar', 'tar', ('-tf',)),
    '.gz':    ToolConfig('gzip', 'gzip', ('-t',)),
    '.bz2':   ToolConfig('bzip2', 'bzip2', ('-t',)),
    '.xz':    ToolConfig('xz', 'xz', ('-t',)),
    '.lz4':   ToolConfig('lz4', 'lz4', ('-t',)),
    '.zst':   ToolConfig('zstd', 'zstd', ('-t',)),
    '.zstd':  ToolConfig('zstd', 'zstd', ('-t',)),
    '.7z':    ToolConfig('7z', 'p7zip-full', ('t',),
                         check_stderr=_7Z_STDERR),
    '.rar':   ToolConfig('unrar', 'unrar', ('t',),
                         check_stderr=_UNRAR_STDERR),

    # Document formats
    '.pdf':   ToolConfig('qpdf', 'qpdf', ('--check',), success_codes=(0, 3)),
    '.epub':  ToolConfig('epubcheck', 'epubcheck', (),
                         check_stderr=_EPUBCHECK_STDERR),

    # GoPro proxy video - uses ffprobe like other video formats
    '.lrv':   ToolConfig('ffprobe', 'ffmpeg', ('-v', 'error', '-i'),
                         check_stderr=_FFPROBE_STDERR,
                         pedantic_binary=_FFMPEG_PEDANTIC_BINARY,
                         pedantic_args=_FFMPEG_PEDANTIC_ARGS),

    # Thumbnail - JPEG format
    '.thm':   ToolConfig('jpeginfo', 'jpeginfo', ('-c',),
                         check_stderr=_JPEGINFO_STDERR),

    # Insta360 video - partial support via ffprobe
    '.insv':  ToolConfig('ffprobe', 'ffmpeg', ('-v', 'error', '-i'),
                         check_stderr=_FFPROBE_STDERR,
                         pedantic_binary=_FFMPEG_PEDANTIC_BINARY,
                         pedantic_args=_FFMPEG_PEDANTIC_ARGS),

    # Rich Text Format
    '.rtf':   ToolConfig('unrtf', 'unrtf', ('--text',)),

    # Old Microsoft Word binary format
    '.doc':   ToolConfig('antiword', 'antiword', ()),

    # FictionBook ebook (XML-based)
    '.fb2':   ToolConfig('xmllint', 'libxml2-utils', ('--noout',)),

    # 360-degree video - typically MP4
    '.360':   ToolConfig('ffprobe', 'ffmpeg', ('-v', 'error', '-i'),
                         check_stderr=_FFPROBE_STDERR,
                         pedantic_binary=_FFMPEG_PEDANTIC_BINARY,
                         pedantic_args=_FFMPEG_PEDANTIC_ARGS),

    # DjVu document
    '.djvu':  ToolConfig('ddjvu', 'djvulibre-bin', ('-format=tiff', '-page=1'),
                         args_after_file=('/dev/null',)),
}

# Compound archive extensions (multi-part extensions)
COMPOUND_EXTENSIONS: Dict[str, ToolConfig] = {
    '.tar.gz':  ToolConfig('tar', 'tar', ('-tzf',)),
    '.tar.bz2': ToolConfig('tar', 'tar', ('-tjf',)),
    '.tar.xz':  ToolConfig('tar', 'tar', ('-tJf',)),
    '.tar.zst': ToolConfig('tar', 'tar', ('--zstd', '-tf')),
}


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------

def get_extension(path: str) -> str:
    """Get extension, handling compound extensions like .tar.gz.
    
    Returns the extension in lowercase with leading dot.
    """
    path_lower = path.lower()
    
    # Check compound extensions first (e.g., .tar.gz)
    for ext in COMPOUND_EXTENSIONS:
        if path_lower.endswith(ext):
            return ext
    
    # Check single extension
    _, ext = os.path.splitext(path_lower)
    return ext


def get_tool_config(extension: str) -> Optional[ToolConfig]:
    """Get tool config for extension.
    
    Args:
        extension: File extension with leading dot, lowercase (e.g., '.mp4', '.tar.gz')
    
    Returns:
        ToolConfig if a validator exists for this extension, None otherwise.
    """
    # Check compound extensions first
    if extension in COMPOUND_EXTENSIONS:
        return COMPOUND_EXTENSIONS[extension]
    
    # Check single extension
    return TOOL_REGISTRY.get(extension)


def check_tool_available(binary: str) -> bool:
    """Check if tool is available using shutil.which()."""
    return shutil.which(binary) is not None


def generate_install_command(packages: Set[str]) -> str:
    """Generate apt-get install command for the given packages."""
    if not packages:
        return "# All required tools are available"
    sorted_packages = sorted(packages)
    return f"sudo apt-get install {' '.join(sorted_packages)}"


def list_tools_status() -> str:
    """Return formatted table showing all tools and their status."""
    # Collect unique binaries and their info
    binary_info: Dict[str, Tuple[str, List[str]]] = {}  # binary -> (package, [extensions])
    
    for ext, config in TOOL_REGISTRY.items():
        if config.binary not in binary_info:
            binary_info[config.binary] = (config.apt_package, [])
        binary_info[config.binary][1].append(ext)
    
    for ext, config in COMPOUND_EXTENSIONS.items():
        if config.binary not in binary_info:
            binary_info[config.binary] = (config.apt_package, [])
        binary_info[config.binary][1].append(ext)
    
    # Build table
    lines = []
    lines.append("Tool Availability Status")
    lines.append("=" * 80)
    lines.append(f"{'Extension':<12} {'Tool':<15} {'Package':<25} {'Installed':<10} {'Install Command'}")
    lines.append("-" * 80)
    
    # Group by extension for cleaner output
    all_extensions = sorted(set(TOOL_REGISTRY.keys()) | set(COMPOUND_EXTENSIONS.keys()))
    
    for ext in all_extensions:
        config = get_tool_config(ext)
        if config is None:
            continue
        
        available = check_tool_available(config.binary)
        status = "Yes" if available else "No"
        install_cmd = "" if available else f"apt-get install {config.apt_package}"
        
        lines.append(f"{ext:<12} {config.binary:<15} {config.apt_package:<25} {status:<10} {install_cmd}")
    
    lines.append("-" * 80)
    
    # Summary of missing tools
    missing_packages: Set[str] = set()
    for binary, (package, _) in binary_info.items():
        if not check_tool_available(binary):
            missing_packages.add(package)
    
    if missing_packages:
        lines.append(f"\n{len(missing_packages)} package(s) missing. Install with:")
        lines.append(f"  {generate_install_command(missing_packages)}")
    else:
        lines.append("\nAll tools available!")
    
    return '\n'.join(lines)


def get_missing_packages() -> Set[str]:
    """Get set of apt packages for missing tools."""
    missing: Set[str] = set()
    
    # Check all unique binaries
    checked_binaries: Set[str] = set()
    
    for config in TOOL_REGISTRY.values():
        if config.binary not in checked_binaries:
            checked_binaries.add(config.binary)
            if not check_tool_available(config.binary):
                missing.add(config.apt_package)
    
    for config in COMPOUND_EXTENSIONS.values():
        if config.binary not in checked_binaries:
            checked_binaries.add(config.binary)
            if not check_tool_available(config.binary):
                missing.add(config.apt_package)
    
    return missing


# ---------------------------------------------------------------------------
# ValidationOutcome dataclass
# ---------------------------------------------------------------------------

@dataclass
class ValidationOutcome:
    """Detailed outcome of validating a single file."""
    entry: FileEntry
    result: ValidationResult
    tool: Optional[str] = None
    exit_code: Optional[int] = None
    stderr_snippet: Optional[str] = None
    error_message: Optional[str] = None


# ---------------------------------------------------------------------------
# Main Tackle Class
# ---------------------------------------------------------------------------

class MediaIntegrityCheck(TackleFactory):
    """Validate media file integrity using Linux system tools."""

    @classmethod
    def arg_parser(cls, subparser):
        # Positional argument: directory to scan
        subparser.add_argument(
            'directory',
            help='Directory to scan recursively for media files',
        )

        # Output options
        subparser.add_argument(
            '-o', '--output',
            type=str,
            default='integrity_check',
            metavar='BASE',
            help='Base name for output files (default: integrity_check)',
        )

        # Tool management
        subparser.add_argument(
            '--list-tools',
            action='store_true',
            help='List all supported tools and their availability, then exit',
        )
        subparser.add_argument(
            '--install-cmd',
            action='store_true',
            help='Print apt-get install command for missing tools, then exit',
        )

        # Filtering
        subparser.add_argument(
            '--extensions',
            type=str,
            default=None,
            metavar='EXT[,EXT,...]',
            help='Filter which file extensions to include in the integrity check. '
                 'Only files matching these extensions will be scanned and validated. '
                 'Example: --extensions mp4,mp3,jpg',
        )

        # Timeout
        subparser.add_argument(
            '--timeout',
            type=int,
            default=300,
            help='Per-file validation timeout in seconds (default: 300)',
        )

        # Check level
        subparser.add_argument(
            '--check-level',
            type=str,
            choices=['basic', 'default', 'pedantic'],
            default='default',
            help='Validation thoroughness level. basic: exit code only (fastest). '
                 'default: exit code + stderr pattern matching. '
                 'pedantic: full content decode/verification (slowest)',
        )

    def __init__(self, parser):
        super().__init__(parser)
        options, _ = parser.parse_known_args()

        # Platform check (Linux/WSL only)
        self._check_platform()

        # Store options
        self.directory: str = os.path.abspath(options.directory)
        self.output_base: str = options.output
        self.list_tools: bool = options.list_tools
        self.install_cmd: bool = options.install_cmd
        self.timeout: int = options.timeout
        self.check_level: CheckLevel = CheckLevel(options.check_level)

        # Parse extensions filter
        if options.extensions:
            self.allowed_extensions: Optional[Set[str]] = set(
                '.' + e.strip().lstrip('.').lower()
                for e in options.extensions.split(',')
                if e.strip()
            )
        else:
            self.allowed_extensions = None

        self._log_startup_settings()

    def _check_platform(self) -> None:
        """Check if running on Linux or WSL. Exit with error if not."""
        is_linux = sys.platform in ('linux', 'linux2')
        is_wsl = False
        
        # Check for WSL
        try:
            uname = os.uname()
            if 'microsoft' in uname.release.lower():
                is_wsl = True
        except (AttributeError, OSError):
            pass
        
        if not is_linux and not is_wsl:
            logger.error(
                'MediaIntegrityCheck requires Linux or WSL. '
                'Current platform: %s', sys.platform
            )
            sys.exit(1)

    def _log_startup_settings(self) -> None:
        """Log startup configuration."""
        logger.info('=' * 60)
        logger.info('MediaIntegrityCheck')
        logger.info('=' * 60)
        logger.info('Directory: %s', self.directory)
        logger.info('Output base: %s', self.output_base)
        logger.info('Timeout: %d seconds', self.timeout)
        logger.info('Check level: %s', self.check_level.value)
        if self.allowed_extensions:
            logger.info('Extensions filter: %s', ', '.join(sorted(self.allowed_extensions)))
        else:
            logger.info('Extensions filter: all supported')
        logger.info('-' * 60)

    def do(self) -> int:
        """Execute the tackle."""
        # Handle info commands first
        if self.list_tools:
            print(list_tools_status())
            return 0

        if self.install_cmd:
            missing = get_missing_packages()
            print(generate_install_command(missing))
            return 0

        # Validate directory
        if not os.path.isdir(self.directory):
            logger.error('Directory not found: %s', self.directory)
            return 1

        # Run validation
        return self._run_validation()

    def _run_validation(self) -> int:
        """Main validation workflow."""
        # 1. Scan directory
        logger.info('Scanning directory: %s', self.directory)
        entries = self._scan_directory()
        logger.info('Found %d files to check', len(entries))

        if not entries:
            logger.warning('No files to validate')
            return 0

        # 2. Validate files
        logger.info('Starting validation...')
        outcomes = self._validate_entries(entries)

        # 3. Categorize results into 5 categories
        valid_entries: List[FileEntry] = []
        corrupt_entries: List[FileEntry] = []
        untestable_entries: List[FileEntry] = []
        missing_tool_entries: List[FileEntry] = []
        error_entries: List[FileEntry] = []

        for outcome in outcomes:
            if outcome.result == ValidationResult.VALID:
                valid_entries.append(outcome.entry)
            elif outcome.result == ValidationResult.CORRUPT:
                corrupt_entries.append(outcome.entry)
            elif outcome.result == ValidationResult.UNTESTABLE:
                untestable_entries.append(outcome.entry)
            elif outcome.result == ValidationResult.TOOL_MISSING:
                missing_tool_entries.append(outcome.entry)
            elif outcome.result == ValidationResult.TOOL_ERROR:
                error_entries.append(outcome.entry)

        # 4. Write output files (only create non-empty listings)
        ok_path = f"{self.output_base}_ok.csv"
        broken_path = f"{self.output_base}_broken.csv"
        untestable_path = f"{self.output_base}_untestable.csv"
        missing_tool_path = f"{self.output_base}_missing_tool.csv"
        error_path = f"{self.output_base}_error.csv"

        ok_count = 0
        broken_count = 0
        untestable_count = 0
        missing_tool_count = 0
        error_count = 0

        if valid_entries:
            ok_count = write_listing(ok_path, valid_entries)
        if corrupt_entries:
            broken_count = write_listing(broken_path, corrupt_entries)
        if untestable_entries:
            untestable_count = write_listing(untestable_path, untestable_entries)
        if missing_tool_entries:
            missing_tool_count = write_listing(missing_tool_path, missing_tool_entries)
        if error_entries:
            error_count = write_listing(error_path, error_entries)

        # 5. Summary
        logger.info('=' * 60)
        logger.info('Validation complete:')
        logger.info('  Valid:        %d', len(valid_entries))
        logger.info('  Corrupt:      %d', len(corrupt_entries))
        logger.info('  Untestable:   %d', len(untestable_entries))
        logger.info('  Missing tool: %d', len(missing_tool_entries))
        logger.info('  Errors:       %d', len(error_entries))
        logger.info('=' * 60)
        # Output file paths
        if ok_count:
            logger.info('  Output: %s', ok_path)
        if broken_count:
            logger.info('  Output: %s', broken_path)
        if untestable_count:
            logger.info('  Output: %s', untestable_path)
        if missing_tool_count:
            logger.info('  Output: %s', missing_tool_path)
        if error_count:
            logger.info('  Output: %s', error_path)

        # Return 1 if any corrupt files found, 0 otherwise
        return 1 if broken_count > 0 else 0

    def _scan_directory(self) -> List[FileEntry]:
        """Recursively scan directory and collect FileEntry objects.
        
        Uses os.walk() with progress indication every 10 seconds.
        """
        entries: List[FileEntry] = []
        scan_count = 0
        last_progress = time.monotonic()
        progress_interval = 10  # seconds

        for dirpath, dirnames, filenames in os.walk(self.directory):
            for filename in filenames:
                full_path = os.path.join(dirpath, filename)

                # Skip symlinks
                if os.path.islink(full_path):
                    continue

                # Get extension and check filter
                ext = get_extension(full_path)
                
                if self.allowed_extensions:
                    if ext not in self.allowed_extensions:
                        continue

                try:
                    fe = FileEntry.from_fs_path(full_path)
                    entries.append(fe)
                    scan_count += 1

                    # Time-based progress
                    now = time.monotonic()
                    if now - last_progress >= progress_interval:
                        logger.info('Scanning: %d files found...', scan_count)
                        last_progress = now

                except OSError as exc:
                    logger.warning('Cannot stat %s: %s', full_path, exc)

        return entries

    def _validate_entries(self, entries: List[FileEntry]) -> List[ValidationOutcome]:
        """Validate all entries and return outcomes.
        
        Shows progress every 10 seconds with category statistics.
        """
        outcomes: List[ValidationOutcome] = []
        total = len(entries)
        processed = 0
        last_progress = time.monotonic()
        progress_interval = 10  # seconds

        # Category counters
        counts = {
            ValidationResult.VALID: 0,
            ValidationResult.CORRUPT: 0,
            ValidationResult.UNTESTABLE: 0,
            ValidationResult.TOOL_MISSING: 0,
            ValidationResult.TOOL_ERROR: 0,
        }

        for entry in entries:
            outcome = self._validate_single(entry)
            outcomes.append(outcome)
            counts[outcome.result] += 1
            processed += 1

            # Time-based progress with stats
            now = time.monotonic()
            if now - last_progress >= progress_interval:
                pct = (processed / total) * 100
                logger.info(
                    'Progress: %d/%d (%.1f%%) | OK: %d | Broken: %d | Untestable: %d | Missing tool: %d | Errors: %d',
                    processed, total, pct,
                    counts[ValidationResult.VALID],
                    counts[ValidationResult.CORRUPT],
                    counts[ValidationResult.UNTESTABLE],
                    counts[ValidationResult.TOOL_MISSING],
                    counts[ValidationResult.TOOL_ERROR],
                )
                last_progress = now

        return outcomes

    def _validate_single(self, entry: FileEntry) -> ValidationOutcome:
        """Validate a single file entry.
        
        Returns:
            ValidationOutcome with result, tool info, and any error details.
        
        Validation behavior depends on check_level:
        - BASIC: Exit code only (fastest)
        - DEFAULT: Exit code + stderr pattern matching (recommended)
        - PEDANTIC: Full decode/verification using alternative binary if configured
        """
        ext = get_extension(entry.path)
        config = get_tool_config(ext)

        # No validator for this extension
        if config is None:
            return ValidationOutcome(
                entry=entry,
                result=ValidationResult.UNTESTABLE,
                error_message='No validator defined for this file extension',
            )

        # Determine binary and args based on check level
        if self.check_level == CheckLevel.PEDANTIC and config.pedantic_binary:
            binary = config.pedantic_binary
            args_before = list(config.pedantic_args or ())
            # Special handling for ffmpeg: need to add -f null - after file
            is_ffmpeg_pedantic = (binary == 'ffmpeg')
        else:
            binary = config.binary
            args_before = list(config.args)
            is_ffmpeg_pedantic = False

        # Check if tool is available
        if not check_tool_available(binary):
            return ValidationOutcome(
                entry=entry,
                result=ValidationResult.TOOL_MISSING,
                tool=binary,
                error_message=f'Tool not installed: {binary} (apt-get install {config.apt_package})',
            )

        # Build command
        if is_ffmpeg_pedantic:
            # ffmpeg -hwaccel auto -v error -i FILE -f null -
            cmd = [binary] + args_before + [entry.path, '-f', 'null', '-']
        else:
            cmd = [binary] + args_before + [entry.path] + list(config.args_after_file)

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=self.timeout,
                text=True,
            )

            exit_code = result.returncode
            stderr = result.stderr[:500] if result.stderr else None

            # Check for success based on exit code
            is_valid = exit_code in config.success_codes

            # Check stderr patterns (for DEFAULT and PEDANTIC levels)
            if is_valid and self.check_level != CheckLevel.BASIC and config.check_stderr:
                if result.stderr and re.search(config.check_stderr, result.stderr):
                    is_valid = False

            return ValidationOutcome(
                entry=entry,
                result=ValidationResult.VALID if is_valid else ValidationResult.CORRUPT,
                tool=binary,
                exit_code=exit_code,
                stderr_snippet=stderr,
            )

        except subprocess.TimeoutExpired:
            return ValidationOutcome(
                entry=entry,
                result=ValidationResult.TOOL_ERROR,
                tool=binary,
                error_message=f'Validation timed out after {self.timeout}s',
            )
        except OSError as exc:
            return ValidationOutcome(
                entry=entry,
                result=ValidationResult.TOOL_ERROR,
                tool=binary,
                error_message=str(exc),
            )
        except Exception as exc:
            return ValidationOutcome(
                entry=entry,
                result=ValidationResult.TOOL_ERROR,
                tool=binary,
                error_message=f'Unexpected error: {exc}',
            )

    def list_available_tools(self) -> str:
        """Format table with columns: Extension, Tool, Package, Installed, Install Command.
        
        This is an instance method wrapper around the module-level function.
        """
        return list_tools_status()
