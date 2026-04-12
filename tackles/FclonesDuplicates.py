"""
FclonesDuplicates tackle — parses fclones duplicate file reports and generates
canonical FileEntry listings compatible with ValidateCopy.

fclones (https://github.com/pkolaczk/fclones) identifies duplicate files but
outputs its own custom report format. This tackle bridges fclones output to
pyTackle's ecosystem.

Report Format
-------------
Header lines start with '#' and contain metadata:
    # Report by fclones 0.35.0
    # Timestamp: 2026-03-30 04:31:29.522 +0300
    # Command: '.\fclones.exe' group --no-ignore --hidden ...
    # Base dir: Q:\\
    # Total: 1268686168746 B (1.3 TB) in 62263 files in 29099 groups
    # Redundant: 652430768023 B (652.4 GB) in 33164 files
    # Missing: 0 B (0 B) in 0 files

Duplicate groups have a header followed by indented paths:
    8593af76cd7c0818f0e6f8c0c3cc0e7d, 10248846420 B (10.2 GB) * 2:
        Q:\\path\\to\\file1.mp4
        Q:\\path\\to\\file2.mp4

Usage
-----
    # Parse report and generate listing
    pyTackle FclonesDuplicates report.txt -o listing.csv

    # Include only first file from each group (canonical copy)
    pyTackle FclonesDuplicates report.txt -o listing.csv --include first

    # Include only duplicates (exclude first)
    pyTackle FclonesDuplicates report.txt -o listing.csv --include duplicates

    # Strip base directory prefix
    pyTackle FclonesDuplicates report.txt -o listing.csv --strip-prefix "Q:\\"
"""

import logging
import re
import sys
from dataclasses import dataclass, field
from typing import Iterator, Optional

from common.FileEntry import FileEntry
from common.streaming_csv import StreamingListingWriter
from tackles.TackleFactory import TackleFactory

logging.basicConfig(
    level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Regex patterns for fclones report parsing
# ---------------------------------------------------------------------------

# Group header: hash, size in bytes, human-readable size, count
# Example: 8593af76cd7c0818f0e6f8c0c3cc0e7d, 10248846420 B (10.2 GB) * 2:
RE_GROUP_HEADER = re.compile(
    r'^([0-9a-fA-F]+),\s*'       # hash (capture group 1)
    r'(\d+)\s*B\s*'              # size in bytes (capture group 2)
    r'\([^)]+\)\s*\*\s*'         # human-readable size (ignored)
    r'(\d+):$'                   # count (capture group 3)
)

# Indented path line (4 spaces indent)
RE_PATH_LINE = re.compile(r'^    (.+)$')

# Header metadata patterns
RE_FCLONES_VERSION = re.compile(r'^#\s*Report by fclones\s+(.+)$')
RE_TIMESTAMP = re.compile(r'^#\s*Timestamp:\s*(.+)$')
RE_COMMAND = re.compile(r'^#\s*Command:\s*(.+)$')
RE_BASE_DIR = re.compile(r'^#\s*Base dir:\s*(.+)$')
RE_TOTAL = re.compile(r'^#\s*Total:\s*(\d+)\s*B.*in\s+(\d+)\s+files\s+in\s+(\d+)\s+groups$')
RE_REDUNDANT = re.compile(r'^#\s*Redundant:\s*(\d+)\s*B.*in\s+(\d+)\s+files$')
RE_MISSING = re.compile(r'^#\s*Missing:\s*(\d+)\s*B.*in\s+(\d+)\s+files$')


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ReportMetadata:
    """Metadata extracted from fclones report header."""
    fclones_version: Optional[str] = None
    timestamp: Optional[str] = None
    command: Optional[str] = None
    base_dir: Optional[str] = None
    total_bytes: Optional[int] = None
    total_files: Optional[int] = None
    total_groups: Optional[int] = None
    redundant_bytes: Optional[int] = None
    redundant_files: Optional[int] = None
    missing_bytes: Optional[int] = None
    missing_files: Optional[int] = None


@dataclass
class DuplicateGroup:
    """A group of duplicate files from fclones report."""
    hash: str           # MetroHash hex digest
    size: int           # File size in bytes
    count: int          # Number of duplicates
    paths: list[str] = field(default_factory=list)  # List of file paths
    group_id: int = 0   # Group index for tracking


# ---------------------------------------------------------------------------
# Path normalization
# ---------------------------------------------------------------------------

def normalize_fclones_path(
    raw_path: str,
    strip_prefix: Optional[str] = None,
) -> str:
    """Normalize Windows-escaped paths from fclones output.

    - Converts double backslashes to single forward slashes
    - Strips specified prefix if present

    Args:
        raw_path: Raw path from fclones report (e.g., Q:\\\\path\\\\to\\\\file)
        strip_prefix: Optional prefix to strip from path

    Returns:
        Normalized path with forward slashes
    """
    path = raw_path.strip()

    # Convert Windows double-backslashes to forward slashes
    # fclones escapes backslashes: Q:\\ becomes Q:\\\\
    path = path.replace('\\\\', '/')
    # Handle any remaining single backslashes
    path = path.replace('\\', '/')

    # Strip prefix if specified
    if strip_prefix:
        # Normalize prefix for comparison
        prefix = strip_prefix.replace('\\\\', '/').replace('\\', '/')
        if path.startswith(prefix):
            path = path[len(prefix):]
            # Remove leading slash if present after stripping
            path = path.lstrip('/')

    return path


# ---------------------------------------------------------------------------
# Parser functions
# ---------------------------------------------------------------------------

def parse_header_line(line: str, metadata: ReportMetadata) -> bool:
    """Parse a header line and update metadata.

    Args:
        line: Line from report (should start with #)
        metadata: ReportMetadata object to update

    Returns:
        True if line was a header line (starts with #), False otherwise
    """
    if not line.startswith('#'):
        return False

    # Try each header pattern
    m = RE_FCLONES_VERSION.match(line)
    if m:
        metadata.fclones_version = m.group(1).strip()
        return True

    m = RE_TIMESTAMP.match(line)
    if m:
        metadata.timestamp = m.group(1).strip()
        return True

    m = RE_COMMAND.match(line)
    if m:
        metadata.command = m.group(1).strip()
        return True

    m = RE_BASE_DIR.match(line)
    if m:
        # Base dir may have escaped backslashes
        metadata.base_dir = m.group(1).strip()
        return True

    m = RE_TOTAL.match(line)
    if m:
        metadata.total_bytes = int(m.group(1))
        metadata.total_files = int(m.group(2))
        metadata.total_groups = int(m.group(3))
        return True

    m = RE_REDUNDANT.match(line)
    if m:
        metadata.redundant_bytes = int(m.group(1))
        metadata.redundant_files = int(m.group(2))
        return True

    m = RE_MISSING.match(line)
    if m:
        metadata.missing_bytes = int(m.group(1))
        metadata.missing_files = int(m.group(2))
        return True

    # Unknown header line — still a header
    return True


def parse_fclones_report(
    report_path: str,
    strip_prefix: Optional[str] = None,
    encoding: str = 'utf-8-sig',
) -> tuple[ReportMetadata, list[DuplicateGroup]]:
    """Parse fclones report file.

    Args:
        report_path: Path to fclones report file
        strip_prefix: Optional prefix to strip from all paths
        encoding: File encoding (default: utf-8-sig for BOM handling)

    Returns:
        Tuple of (ReportMetadata, list of DuplicateGroup)

    Raises:
        FileNotFoundError: If report file doesn't exist
        ValueError: If report format is invalid
    """
    metadata = ReportMetadata()
    groups: list[DuplicateGroup] = []
    current_group: Optional[DuplicateGroup] = None
    group_id = 0

    with open(report_path, encoding=encoding) as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.rstrip('\n\r')

            # Skip empty lines
            if not line.strip():
                continue

            # Try header parsing
            if line.startswith('#'):
                parse_header_line(line, metadata)
                continue

            # Try group header
            m = RE_GROUP_HEADER.match(line)
            if m:
                # Save previous group if exists
                if current_group is not None:
                    groups.append(current_group)

                group_id += 1
                current_group = DuplicateGroup(
                    hash=m.group(1),
                    size=int(m.group(2)),
                    count=int(m.group(3)),
                    paths=[],
                    group_id=group_id,
                )
                continue

            # Try path line (indented)
            m = RE_PATH_LINE.match(line)
            if m and current_group is not None:
                raw_path = m.group(1)
                normalized_path = normalize_fclones_path(raw_path, strip_prefix)
                current_group.paths.append(normalized_path)
                continue

            # Unknown line format — log warning
            logger.warning('Line %d: unrecognized format: %s', lineno, line[:50])

    # Don't forget the last group
    if current_group is not None:
        groups.append(current_group)

    return metadata, groups


# ---------------------------------------------------------------------------
# FileEntry generation
# ---------------------------------------------------------------------------

def duplicate_group_to_entries(
    group: DuplicateGroup,
    include: str = 'all',
    add_group_id: bool = False,
) -> Iterator[FileEntry]:
    """Convert a DuplicateGroup to FileEntry objects.

    Args:
        group: The duplicate group to convert
        include: Which files to include:
            - 'all': all files in the group
            - 'first': only the first file (canonical copy)
            - 'duplicates': all except the first (true duplicates)
        add_group_id: If True, add group ID as comment (not implemented in FileEntry)

    Yields:
        FileEntry objects for each included path
    """
    if include == 'first':
        paths = group.paths[:1]
    elif include == 'duplicates':
        paths = group.paths[1:]
    else:  # 'all'
        paths = group.paths

    for path in paths:
        entry = FileEntry(
            path=path,
            size=group.size,
            checksum=f'metrohash:{group.hash}',
            entry_type='f',
            # These are not available in fclones output
            creation=None,
            access=None,
            modify=None,
            permissions=None,
            uid=None,
            gid=None,
        )
        yield entry


def generate_entries_from_report(
    report_path: str,
    strip_prefix: Optional[str] = None,
    include: str = 'all',
    add_group_id: bool = False,
) -> Iterator[FileEntry]:
    """Parse fclones report and yield FileEntry objects.

    Args:
        report_path: Path to fclones report file
        strip_prefix: Optional prefix to strip from all paths
        include: Which files to include ('all', 'first', 'duplicates')
        add_group_id: If True, add group ID tracking

    Yields:
        FileEntry objects for each file in the report
    """
    metadata, groups = parse_fclones_report(report_path, strip_prefix)

    logger.info(
        'Parsed %d groups from fclones report (fclones %s)',
        len(groups),
        metadata.fclones_version or 'unknown version',
    )

    for group in groups:
        yield from duplicate_group_to_entries(group, include, add_group_id)


# ---------------------------------------------------------------------------
# Tackle class
# ---------------------------------------------------------------------------

class FclonesDuplicates(TackleFactory):
    """Parse fclones duplicate reports and generate canonical listings."""

    @classmethod
    def arg_parser(cls, subparser):
        # Positional argument: report file
        subparser.add_argument(
            'report_file',
            help='Path to fclones report file',
        )

        # Output options
        subparser.add_argument(
            '-o', '--output',
            type=str,
            default=None,
            help='Output listing file (default: stdout)',
        )

        # Path manipulation
        subparser.add_argument(
            '--base-dir',
            type=str,
            default=None,
            help='Override base directory from report (unused in current implementation)',
        )
        subparser.add_argument(
            '--strip-prefix',
            type=str,
            default=None,
            help='Strip prefix from all paths (e.g., "Q:\\\\")',
        )

        # Selection options
        subparser.add_argument(
            '--include',
            choices=['all', 'first', 'duplicates'],
            default='all',
            help=(
                'Which files to include: '
                'all (every file), '
                'first (first per group - canonical copies), '
                'or duplicates (all except first)'
            ),
        )
        subparser.add_argument(
            '--group-id',
            action='store_true',
            help='Add group ID as a comment for each entry (informational only)',
        )

        # Verbosity
        subparser.add_argument(
            '-v', '--verbose',
            action='store_true',
            help='Verbose output',
        )
        subparser.add_argument(
            '-q', '--quiet',
            action='store_true',
            help='Suppress non-error output',
        )

    def __init__(self, parser):
        super().__init__(parser)
        options, _ = parser.parse_known_args()

        self.report_file: str = options.report_file
        self.output_path: Optional[str] = options.output
        self.base_dir: Optional[str] = options.base_dir
        self.strip_prefix: Optional[str] = options.strip_prefix
        self.include: str = options.include
        self.group_id: bool = options.group_id
        self.verbose: bool = options.verbose
        self.quiet: bool = options.quiet

        # Configure logging
        if self.verbose:
            logger.setLevel(logging.DEBUG)
        elif self.quiet:
            logger.setLevel(logging.WARNING)

        self._log_startup_settings()

    def _log_startup_settings(self) -> None:
        """Log configuration at startup."""
        logger.info('=' * 60)
        logger.info('FclonesDuplicates')
        logger.info('=' * 60)
        logger.info('Report file: %s', self.report_file)
        logger.info('Output: %s', self.output_path or 'stdout')
        logger.info('Include: %s', self.include)
        if self.strip_prefix:
            logger.info('Strip prefix: %s', self.strip_prefix)
        if self.group_id:
            logger.info('Group ID tracking: enabled')
        logger.info('-' * 60)

    def do(self) -> int:
        """Execute the tackle: parse report and generate listing."""
        import csv
        import os

        # Validate input file exists
        if not os.path.isfile(self.report_file):
            logger.error('Report file not found: %s', self.report_file)
            return 1

        try:
            # Parse report and generate entries
            entries = generate_entries_from_report(
                self.report_file,
                strip_prefix=self.strip_prefix,
                include=self.include,
                add_group_id=self.group_id,
            )

            # Write output
            if self.output_path:
                with StreamingListingWriter(
                    self.output_path,
                ) as writer:
                    for entry in entries:
                        writer.write(entry)
                count = writer.count
                logger.info('Wrote %d entries to %s', count, self.output_path)
            else:
                # Write to stdout
                stdout_writer = csv.writer(sys.stdout)
                count = 0
                for entry in entries:
                    stdout_writer.writerow(entry.to_listing_row())
                    count += 1
                if not self.quiet:
                    logger.info('Wrote %d entries to stdout', count)

            return 0

        except FileNotFoundError as exc:
            logger.error('File not found: %s', exc)
            return 1
        except ValueError as exc:
            logger.error('Invalid report format: %s', exc)
            return 1
        except Exception as exc:
            logger.error('Unexpected error: %s', exc)
            if self.verbose:
                import traceback
                traceback.print_exc()
            return 1
