"""
SetCreationTime tackle — reads a CSV file listing and sets directory creation
times on the local filesystem.

Supports three listing formats (auto-detected):
  Format 1: Linux-style, 6 columns, no header
  Format 2: PowerShell-style, 4 columns, with header
  Format 3: PowerShell-style with type marker, 5 columns, no header

Cross-platform: Windows (ctypes/Win32), macOS (SetFile), Linux (warning only).
"""

import csv
import io
import logging
import os
import pathlib
import platform
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

from tackles.TackleFactory import TackleFactory

logging.basicConfig(
    level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FORMAT_LINUX = 'linux'          # Format 1: 6 cols, no header
FORMAT_PS_HEADER = 'ps_header'  # Format 2: 4 cols, header row
FORMAT_PS_TYPE = 'ps_type'      # Format 3: 5 cols, no header, type marker

_EPOCH_1601 = datetime(1601, 1, 1, tzinfo=timezone.utc)

# Regex for Linux-style timestamps: 2020-08-20 06:15:03.491092220 +0000
_RE_LINUX_TS = re.compile(
    r'(\d{4}-\d{2}-\d{2})\s+'
    r'(\d{2}:\d{2}:\d{2})'
    r'\.(\d+)\s+'
    r'([+-]\d{4})'
)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ListingEntry:
    """One row from a listing file."""
    dates: List[datetime] = field(default_factory=list)
    entry_type: Optional[str] = None   # 'directory'/'D' or 'file'/'F' or None
    raw_path: str = ''


# ---------------------------------------------------------------------------
# Timestamp parsing
# ---------------------------------------------------------------------------

def parse_timestamp_linux(raw: str) -> datetime:
    """Parse ``2020-08-20 06:15:03.491092220 +0000`` into a tz-aware datetime."""
    raw = raw.strip()
    m = _RE_LINUX_TS.match(raw)
    if not m:
        raise ValueError(f'Cannot parse Linux timestamp: {raw!r}')
    date_part, time_part, frac, tz_offset = m.groups()
    # Truncate nanoseconds to microseconds (max 6 digits)
    micro = frac[:6].ljust(6, '0')
    # Build ISO string that strptime can handle
    iso = f'{date_part} {time_part}.{micro} {tz_offset}'
    return datetime.strptime(iso, '%Y-%m-%d %H:%M:%S.%f %z')


def parse_timestamp_powershell(raw: str) -> datetime:
    """Parse ``02/24/2023 14:04:32`` as UTC datetime."""
    raw = raw.strip()
    dt = datetime.strptime(raw, '%m/%d/%Y %H:%M:%S')
    return dt.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def normalize_path(raw_path: str) -> str:
    """Strip UNC prefix and normalise separators.

    ``\\\\server\\share\\rest\\of\\path`` → ``rest/of/path``
    """
    path = raw_path.strip().strip('"')
    if path.startswith('\\\\') or path.startswith('//'):
        parts = path.replace('\\', '/').lstrip('/').split('/')
        # parts[0] = server, parts[1] = share, parts[2:] = relative
        if len(parts) > 2:
            return os.path.join(*parts[2:])
        return '.'
    return path.replace('\\', '/')


# ---------------------------------------------------------------------------
# Format detection & parsing
# ---------------------------------------------------------------------------

def detect_format(first_line: str) -> str:
    """Return format identifier based on the first line of the listing."""
    stripped = first_line.strip()
    if stripped.lower().startswith('creationtimeutc'):
        return FORMAT_PS_HEADER

    # Parse the first line as CSV to count columns
    reader = csv.reader(io.StringIO(stripped))
    cols = next(reader, [])
    n = len(cols)
    if n >= 6:
        return FORMAT_LINUX
    if n == 5:
        return FORMAT_PS_TYPE
    if n == 4:
        # Could be format 2 without a recognisable header — treat as ps_header data
        return FORMAT_PS_HEADER

    raise ValueError(
        f'Cannot detect listing format: first line has {n} columns'
    )


def _parse_row_linux(cols: List[str]) -> ListingEntry:
    """Format 1: 6 columns — 4 dates, type, path."""
    dates = []
    for i in range(4):
        try:
            dates.append(parse_timestamp_linux(cols[i]))
        except (ValueError, IndexError):
            pass
    entry_type = cols[4].strip().lower() if len(cols) > 4 else None
    raw_path = cols[5].strip().strip('"') if len(cols) > 5 else ''
    return ListingEntry(dates=dates, entry_type=entry_type, raw_path=raw_path)


def _parse_row_ps_header(cols: List[str]) -> ListingEntry:
    """Format 2: 4 columns — 3 dates, path (no type)."""
    dates = []
    for i in range(3):
        try:
            dates.append(parse_timestamp_powershell(cols[i]))
        except (ValueError, IndexError):
            pass
    raw_path = cols[3].strip().strip('"') if len(cols) > 3 else ''
    return ListingEntry(dates=dates, entry_type=None, raw_path=raw_path)


def _parse_row_ps_type(cols: List[str]) -> ListingEntry:
    """Format 3: 5 columns — 3 dates, type, path."""
    dates = []
    for i in range(3):
        try:
            dates.append(parse_timestamp_powershell(cols[i]))
        except (ValueError, IndexError):
            pass
    entry_type = cols[3].strip().upper() if len(cols) > 3 else None
    raw_path = cols[4].strip().strip('"') if len(cols) > 4 else ''
    return ListingEntry(dates=dates, entry_type=entry_type, raw_path=raw_path)


def parse_listing(listing_path: str) -> List[ListingEntry]:
    """Read and parse a listing file, auto-detecting the format."""
    entries: List[ListingEntry] = []

    with open(listing_path, encoding='utf-8-sig', newline='') as fh:
        first_line = fh.readline()
        if not first_line:
            return entries

        fmt = detect_format(first_line)
        logger.info('Detected listing format: %s', fmt)

        # For format 2 the first line is a header — skip it.
        # For other formats the first line is data — rewind.
        if fmt == FORMAT_PS_HEADER:
            # Check if first line is actually the header
            if first_line.strip().lower().startswith('creationtimeutc'):
                lines = fh  # header consumed, read rest
            else:
                # No header but detected as ps_header by column count
                fh.seek(0)
                lines = fh
        else:
            fh.seek(0)
            lines = fh

        row_parser = {
            FORMAT_LINUX: _parse_row_linux,
            FORMAT_PS_HEADER: _parse_row_ps_header,
            FORMAT_PS_TYPE: _parse_row_ps_type,
        }[fmt]

        reader = csv.reader(lines)
        for lineno, cols in enumerate(reader, start=1):
            if not cols or all(c.strip() == '' for c in cols):
                continue
            try:
                entry = row_parser(cols)
                entries.append(entry)
            except Exception as exc:
                logger.warning('Line %d: skipping — %s', lineno, exc)

    return entries


# ---------------------------------------------------------------------------
# Date selection
# ---------------------------------------------------------------------------

def select_date(
    entry: ListingEntry,
    date_column: Optional[int],
) -> Optional[datetime]:
    """Pick the target creation time from an entry's date columns.

    *date_column* ``None`` means "earliest"; an integer selects that index.
    """
    if not entry.dates:
        return None
    if date_column is not None:
        if 0 <= date_column < len(entry.dates):
            return entry.dates[date_column]
        logger.warning(
            'date-column %d out of range (entry has %d date columns) for %s',
            date_column, len(entry.dates), entry.raw_path,
        )
        return None
    return min(entry.dates)


# ---------------------------------------------------------------------------
# Directory filtering
# ---------------------------------------------------------------------------

def is_directory_entry(entry: ListingEntry, resolved_path: str) -> bool:
    """Decide whether *entry* represents a directory."""
    if entry.entry_type is not None:
        return entry.entry_type.lower() in ('directory', 'd')
    # Format 2 — no type column; check the filesystem
    return os.path.isdir(resolved_path)


# ---------------------------------------------------------------------------
# Platform-specific creation-time setters
# ---------------------------------------------------------------------------

def _datetime_to_filetime_int(dt: datetime) -> int:
    """Convert a datetime to a Windows FILETIME 64-bit integer."""
    delta = dt - _EPOCH_1601
    return int(delta.total_seconds() * 10_000_000)


def set_creation_time_windows(path: str, dt: datetime) -> None:
    """Set creation time on Windows using the Win32 API via ctypes."""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

    GENERIC_WRITE = 0x40000000
    FILE_SHARE_READ = 0x00000001
    FILE_SHARE_WRITE = 0x00000002
    OPEN_EXISTING = 3
    FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
    INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value

    class FILETIME(ctypes.Structure):
        _fields_ = [
            ('dwLowDateTime', wintypes.DWORD),
            ('dwHighDateTime', wintypes.DWORD),
        ]

    CreateFileW = kernel32.CreateFileW
    CreateFileW.argtypes = [
        wintypes.LPCWSTR,  # lpFileName
        wintypes.DWORD,    # dwDesiredAccess
        wintypes.DWORD,    # dwShareMode
        ctypes.c_void_p,   # lpSecurityAttributes
        wintypes.DWORD,    # dwCreationDisposition
        wintypes.DWORD,    # dwFlagsAndAttributes
        wintypes.HANDLE,   # hTemplateFile
    ]
    CreateFileW.restype = wintypes.HANDLE

    SetFileTime = kernel32.SetFileTime
    SetFileTime.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(FILETIME),  # lpCreationTime
        ctypes.POINTER(FILETIME),  # lpLastAccessTime
        ctypes.POINTER(FILETIME),  # lpLastWriteTime
    ]
    SetFileTime.restype = wintypes.BOOL

    CloseHandle = kernel32.CloseHandle
    CloseHandle.argtypes = [wintypes.HANDLE]
    CloseHandle.restype = wintypes.BOOL

    # Open the directory (FILE_FLAG_BACKUP_SEMANTICS required for dirs)
    handle = CreateFileW(
        path,
        GENERIC_WRITE,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        None,
        OPEN_EXISTING,
        FILE_FLAG_BACKUP_SEMANTICS,
        None,
    )

    if handle == INVALID_HANDLE_VALUE or handle == -1:
        err = ctypes.get_last_error()
        raise OSError(f'CreateFileW failed for {path!r} (error {err})')

    try:
        ft_int = _datetime_to_filetime_int(dt)
        ft = FILETIME(
            dwLowDateTime=ft_int & 0xFFFFFFFF,
            dwHighDateTime=(ft_int >> 32) & 0xFFFFFFFF,
        )
        # Pass creation time only; NULL for access and write times
        ok = SetFileTime(handle, ctypes.byref(ft), None, None)
        if not ok:
            err = ctypes.get_last_error()
            raise OSError(f'SetFileTime failed for {path!r} (error {err})')
    finally:
        CloseHandle(handle)


def set_creation_time_macos(path: str, dt: datetime) -> None:
    """Set creation time on macOS using the ``SetFile`` command."""
    # SetFile -d expects: "MM/DD/YYYY HH:MM:SS" in local time
    # Convert UTC datetime to local time for SetFile
    local_dt = dt.astimezone()
    formatted = local_dt.strftime('%m/%d/%Y %H:%M:%S')
    result = subprocess.run(
        ['SetFile', '-d', formatted, path],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise OSError(
            f'SetFile failed for {path!r}: {result.stderr.strip()}'
        )


def set_creation_time(path: str, dt: datetime) -> None:
    """Dispatch to the platform-specific creation-time setter."""
    system = platform.system()
    if system == 'Windows':
        set_creation_time_windows(path, dt)
    elif system == 'Darwin':
        set_creation_time_macos(path, dt)
    else:
        raise NotImplementedError(
            f'Setting creation time is not supported on {system}'
        )


# ---------------------------------------------------------------------------
# Tackle class
# ---------------------------------------------------------------------------

class SetCreationTime(TackleFactory):
    """Read a directory listing CSV and set creation times on local directories."""

    @classmethod
    def arg_parser(cls, subparser):
        subparser.add_argument(
            '--listing',
            type=pathlib.Path,
            required=True,
            help='Path to the CSV listing file',
        )
        subparser.add_argument(
            '--base-dir',
            type=pathlib.Path,
            required=True,
            help='Local base directory to resolve relative paths against',
        )
        subparser.add_argument(
            '--date-column',
            type=str,
            default='earliest',
            help=(
                '0-based column index for the date to use as creation time, '
                'or "earliest" (default) to pick the minimum date'
            ),
        )
        subparser.add_argument(
            '--dry-run',
            action='store_true',
            default=False,
            help='Preview changes without modifying timestamps',
        )
        subparser.add_argument(
            '-v',
            action='store_true',
            help='Verbose output',
        )

    def __init__(self, parser):
        super().__init__(parser)
        options, _ = parser.parse_known_args()

        self.listing_path = str(options.listing)
        self.base_dir = str(options.base_dir)
        self.dry_run = options.dry_run

        if options.v:
            logger.setLevel(logging.DEBUG)

        # Parse --date-column
        if options.date_column == 'earliest':
            self.date_column: Optional[int] = None
        else:
            try:
                self.date_column = int(options.date_column)
            except ValueError:
                logger.error(
                    '--date-column must be "earliest" or a 0-based integer, '
                    'got %r', options.date_column,
                )
                sys.exit(1)

        # Validate paths
        if not os.path.isfile(self.listing_path):
            logger.error('Listing file not found: %s', self.listing_path)
            sys.exit(1)

        if not os.path.isdir(self.base_dir):
            logger.error('Base directory not found: %s', self.base_dir)
            sys.exit(1)

    def do(self):
        entries = parse_listing(self.listing_path)
        logger.info('Parsed %d entries from listing', len(entries))

        success = 0
        skipped = 0
        failed = 0

        for entry in entries:
            rel_path = normalize_path(entry.raw_path)
            resolved = os.path.normpath(os.path.join(self.base_dir, rel_path))

            # Directory-only filter
            if not is_directory_entry(entry, resolved):
                logger.debug('Skipping non-directory: %s', rel_path)
                skipped += 1
                continue

            # Check the directory exists on the local filesystem
            if not os.path.isdir(resolved):
                logger.warning(
                    'Directory not found locally, skipping: %s', resolved,
                )
                skipped += 1
                continue

            # Select the date to apply
            target_dt = select_date(entry, self.date_column)
            if target_dt is None:
                logger.warning(
                    'No valid date for %s, skipping', rel_path,
                )
                skipped += 1
                continue

            if self.dry_run:
                logger.info(
                    '[DRY-RUN] Would set creation time of %s to %s',
                    resolved, target_dt.isoformat(),
                )
                success += 1
                continue

            try:
                set_creation_time(resolved, target_dt)
                logger.info(
                    'Set creation time of %s to %s',
                    resolved, target_dt.isoformat(),
                )
                success += 1
            except NotImplementedError as exc:
                logger.warning('%s — skipping %s', exc, resolved)
                skipped += 1
            except OSError as exc:
                logger.error('Failed to set creation time for %s: %s', resolved, exc)
                failed += 1
            except Exception as exc:
                logger.error(
                    'Unexpected error for %s: %s', resolved, exc,
                )
                failed += 1

        logger.info(
            'Done. success=%d  skipped=%d  failed=%d',
            success, skipped, failed,
        )
