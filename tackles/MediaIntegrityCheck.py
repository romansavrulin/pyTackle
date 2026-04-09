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
    check_stderr: Optional[str] = None       # Regex pattern to find in stderr (for ogg/opus)


# File extension to tool mapping
TOOL_REGISTRY: Dict[str, ToolConfig] = {
    # Video formats
    '.mp4':   ToolConfig('ffprobe', 'ffmpeg', ('-v', 'error', '-i')),
    '.mkv':   ToolConfig('ffprobe', 'ffmpeg', ('-v', 'error', '-i')),
    '.avi':   ToolConfig('ffprobe', 'ffmpeg', ('-v', 'error', '-i')),
    '.mov':   ToolConfig('ffprobe', 'ffmpeg', ('-v', 'error', '-i')),
    '.wmv':   ToolConfig('ffprobe', 'ffmpeg', ('-v', 'error', '-i')),
    '.flv':   ToolConfig('ffprobe', 'ffmpeg', ('-v', 'error', '-i')),
    '.webm':  ToolConfig('ffprobe', 'ffmpeg', ('-v', 'error', '-i')),
    '.m4v':   ToolConfig('ffprobe', 'ffmpeg', ('-v', 'error', '-i')),
    '.mpeg':  ToolConfig('ffprobe', 'ffmpeg', ('-v', 'error', '-i')),
    '.mpg':   ToolConfig('ffprobe', 'ffmpeg', ('-v', 'error', '-i')),
    '.3gp':   ToolConfig('ffprobe', 'ffmpeg', ('-v', 'error', '-i')),
    '.ts':    ToolConfig('ffprobe', 'ffmpeg', ('-v', 'error', '-i')),
    '.m2ts':  ToolConfig('ffprobe', 'ffmpeg', ('-v', 'error', '-i')),
    '.vob':   ToolConfig('ffprobe', 'ffmpeg', ('-v', 'error', '-i')),

    # Audio formats
    '.mp3':   ToolConfig('mp3val', 'mp3val', ('-si',)),
    '.flac':  ToolConfig('flac', 'flac', ('-ts',)),
    '.ogg':   ToolConfig('ogginfo', 'vorbis-tools', (), check_stderr=r'(?i)error'),
    '.opus':  ToolConfig('opusinfo', 'opus-tools', (), check_stderr=r'(?i)error'),
    '.wav':   ToolConfig('ffprobe', 'ffmpeg', ('-v', 'error', '-i')),
    '.aac':   ToolConfig('ffprobe', 'ffmpeg', ('-v', 'error', '-i')),
    '.m4a':   ToolConfig('ffprobe', 'ffmpeg', ('-v', 'error', '-i')),
    '.wma':   ToolConfig('ffprobe', 'ffmpeg', ('-v', 'error', '-i')),
    '.aiff':  ToolConfig('ffprobe', 'ffmpeg', ('-v', 'error', '-i')),
    '.ape':   ToolConfig('ffprobe', 'ffmpeg', ('-v', 'error', '-i')),

    # Image formats
    '.jpg':   ToolConfig('jpeginfo', 'jpeginfo', ('-c',)),
    '.jpeg':  ToolConfig('jpeginfo', 'jpeginfo', ('-c',)),
    '.png':   ToolConfig('pngcheck', 'pngcheck', ('-q',)),
    '.gif':   ToolConfig('identify', 'imagemagick', ('-regard-warnings',)),
    '.bmp':   ToolConfig('identify', 'imagemagick', ('-regard-warnings',)),
    '.tiff':  ToolConfig('identify', 'imagemagick', ('-regard-warnings',)),
    '.tif':   ToolConfig('identify', 'imagemagick', ('-regard-warnings',)),
    '.webp':  ToolConfig('identify', 'imagemagick', ('-regard-warnings',)),
    '.heic':  ToolConfig('identify', 'imagemagick', ('-regard-warnings',)),
    '.cr2':   ToolConfig('exiftool', 'libimage-exiftool-perl', ('-validate', '-warning')),
    '.nef':   ToolConfig('exiftool', 'libimage-exiftool-perl', ('-validate', '-warning')),
    '.arw':   ToolConfig('exiftool', 'libimage-exiftool-perl', ('-validate', '-warning')),
    '.raw':   ToolConfig('exiftool', 'libimage-exiftool-perl', ('-validate', '-warning')),
    '.dng':   ToolConfig('exiftool', 'libimage-exiftool-perl', ('-validate', '-warning')),

    # Archive formats
    '.zip':   ToolConfig('unzip', 'unzip', ('-t',)),
    '.docx':  ToolConfig('unzip', 'unzip', ('-t',)),
    '.xlsx':  ToolConfig('unzip', 'unzip', ('-t',)),
    '.pptx':  ToolConfig('unzip', 'unzip', ('-t',)),
    '.tar':   ToolConfig('tar', 'tar', ('-tf',)),
    '.gz':    ToolConfig('gzip', 'gzip', ('-t',)),
    '.bz2':   ToolConfig('bzip2', 'bzip2', ('-t',)),
    '.xz':    ToolConfig('xz', 'xz', ('-t',)),
    '.lz4':   ToolConfig('lz4', 'lz4', ('-t',)),
    '.zst':   ToolConfig('zstd', 'zstd', ('-t',)),
    '.zstd':  ToolConfig('zstd', 'zstd', ('-t',)),
    '.7z':    ToolConfig('7z', 'p7zip-full', ('t',)),
    '.rar':   ToolConfig('unrar', 'unrar', ('t',)),

    # Document formats
    '.pdf':   ToolConfig('qpdf', 'qpdf', ('--check',), success_codes=(0, 3)),
    '.epub':  ToolConfig('epubcheck', 'epubcheck', ()),
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
        logger.info('Validation complete')
        if ok_count:
            logger.info('  Valid:        %d files -> %s', ok_count, ok_path)
        if broken_count:
            logger.info('  Corrupt:      %d files -> %s', broken_count, broken_path)
        if untestable_count:
            logger.info('  Untestable:   %d files -> %s', untestable_count, untestable_path)
        if missing_tool_count:
            logger.info('  Missing tool: %d files -> %s', missing_tool_count, missing_tool_path)
        if error_count:
            logger.info('  Tool error:   %d files -> %s', error_count, error_path)
        logger.info('=' * 60)

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
        
        Shows progress every 10 seconds.
        """
        outcomes: List[ValidationOutcome] = []
        total = len(entries)
        processed = 0
        last_progress = time.monotonic()
        progress_interval = 10  # seconds

        for entry in entries:
            outcome = self._validate_single(entry)
            outcomes.append(outcome)
            processed += 1

            # Time-based progress
            now = time.monotonic()
            if now - last_progress >= progress_interval:
                pct = (processed / total) * 100
                valid_count = sum(1 for o in outcomes if o.result == ValidationResult.VALID)
                corrupt_count = sum(1 for o in outcomes if o.result == ValidationResult.CORRUPT)
                logger.info(
                    'Progress: %d/%d (%.1f%%) — %d valid, %d corrupt',
                    processed, total, pct, valid_count, corrupt_count
                )
                last_progress = now

        return outcomes

    def _validate_single(self, entry: FileEntry) -> ValidationOutcome:
        """Validate a single file entry.
        
        Returns:
            ValidationOutcome with result, tool info, and any error details.
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

        # Check if tool is available
        if not check_tool_available(config.binary):
            return ValidationOutcome(
                entry=entry,
                result=ValidationResult.TOOL_MISSING,
                tool=config.binary,
                error_message=f'Tool not installed: {config.binary} (apt-get install {config.apt_package})',
            )

        # Build command: binary + args + file path
        cmd = [config.binary] + list(config.args) + [entry.path]

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

            # Special stderr checking (for ogg/opus)
            if is_valid and config.check_stderr and result.stderr:
                if re.search(config.check_stderr, result.stderr):
                    is_valid = False

            return ValidationOutcome(
                entry=entry,
                result=ValidationResult.VALID if is_valid else ValidationResult.CORRUPT,
                tool=config.binary,
                exit_code=exit_code,
                stderr_snippet=stderr,
            )

        except subprocess.TimeoutExpired:
            return ValidationOutcome(
                entry=entry,
                result=ValidationResult.TOOL_ERROR,
                tool=config.binary,
                error_message=f'Validation timed out after {self.timeout}s',
            )
        except OSError as exc:
            return ValidationOutcome(
                entry=entry,
                result=ValidationResult.TOOL_ERROR,
                tool=config.binary,
                error_message=str(exc),
            )
        except Exception as exc:
            return ValidationOutcome(
                entry=entry,
                result=ValidationResult.TOOL_ERROR,
                tool=config.binary,
                error_message=f'Unexpected error: {exc}',
            )

    def list_available_tools(self) -> str:
        """Format table with columns: Extension, Tool, Package, Installed, Install Command.
        
        This is an instance method wrapper around the module-level function.
        """
        return list_tools_status()
