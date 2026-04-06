"""
SetCreationTime tackle — reads a CSV file listing and sets file/directory
timestamps on the local filesystem.

Supports three listing formats (auto-detected):
  Format 1: Linux-style, 6 columns, no header
  Format 2: PowerShell-style, 4 columns, with header
  Format 3: PowerShell-style with type marker, 5 columns, no header

Cross-platform: Windows (ctypes/Win32), macOS (SetFile), Linux (warning only
for creation time; access/modify work everywhere via os.utime).

Attribute mapping (--attr-map) lets you choose which listing columns drive
which filesystem timestamps.  Entry-type filtering (--types) lets you
restrict processing to files, directories, and/or symlinks.
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
from typing import Dict, List, Optional

from tackles.TackleFactory import TackleFactory

logging.basicConfig(
    level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Valid attribute names and meta-selectors for --attr-map
# ---------------------------------------------------------------------------

VALID_ATTRS = ('creation', 'access', 'modify')
META_SELECTORS = ('earliest', 'latest')
# Short aliases accepted in --attr-map selectors
_SELECTOR_ALIASES = {'e': 'earliest', 'l': 'latest'}

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

def normalize_path(raw_path: str, script_base_path: Optional[str] = None) -> str:
    """Strip UNC prefix, normalise separators, and optionally remove a leading
    base-path prefix.

    ``\\\\server\\share\\rest\\of\\path`` → ``rest/of/path``

    When *script_base_path* is given the corresponding leading directory
    components are stripped from the result so that only the relative tail
    remains.  For example, with ``script_base_path="photos/vacation"`` the
    path ``photos/vacation/2020/img.jpg`` becomes ``2020/img.jpg``.
    """
    path = raw_path.strip().strip('"')
    if path.startswith('\\\\') or path.startswith('//'):
        parts = path.replace('\\', '/').lstrip('/').split('/')
        # parts[0] = server, parts[1] = share, parts[2:] = relative
        if len(parts) > 2:
            path = os.path.join(*parts[2:])
        else:
            path = '.'
    else:
        path = path.replace('\\', '/')

    if script_base_path is not None:
        # Normalise both sides so comparison is separator-agnostic
        norm = os.path.normpath(path)
        base = os.path.normpath(script_base_path)
        # Use os.path.relpath to strip the prefix; if the path doesn't
        # start with the base the result will contain '..' components —
        # in that case fall back to the original normalised path.
        rel = os.path.relpath(norm, base)
        if not rel.startswith('..'):
            path = rel

    return path


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
# Attr-map parsing
# ---------------------------------------------------------------------------

def parse_attr_map(raw: str) -> Dict[str, str]:
    """Parse an ``--attr-map`` string into ``{attr_name: selector}`` dict.

    *raw* is a comma-separated list of ``attr:selector`` pairs, e.g.
    ``"creation:1, access:2, modify:earliest"`` or using short aliases
    ``"creation:e, modify:l"``.

    Each *selector* is either a 0-based column index (as a string digit) or
    one of the meta-selectors ``earliest`` (alias ``e``) / ``latest``
    (alias ``l``).

    Returns a dict like ``{'creation': '1', 'access': '2', 'modify': 'earliest'}``.
    Aliases are expanded to their canonical form in the returned dict.
    """
    attr_map: Dict[str, str] = {}
    for token in raw.split(','):
        token = token.strip()
        if not token:
            continue
        if ':' not in token:
            raise ValueError(
                f'Invalid attr-map token {token!r} — expected "attr:selector"'
            )
        attr, selector = token.split(':', 1)
        attr = attr.strip().lower()
        selector = selector.strip().lower()
        if attr not in VALID_ATTRS:
            raise ValueError(
                f'Unknown attribute {attr!r} in --attr-map; '
                f'valid attributes: {", ".join(VALID_ATTRS)}'
            )
        # Expand short aliases
        selector = _SELECTOR_ALIASES.get(selector, selector)
        if selector not in META_SELECTORS:
            # Must be a non-negative integer
            try:
                int(selector)
            except ValueError:
                raise ValueError(
                    f'Invalid selector {selector!r} for attribute {attr!r}; '
                    f'expected a 0-based column index or one of: '
                    f'{", ".join(META_SELECTORS)} (aliases: e, l)'
                )
        attr_map[attr] = selector
    if not attr_map:
        raise ValueError('--attr-map produced an empty mapping')
    return attr_map


def parse_types(raw: str) -> set:
    """Parse a ``--types`` string into a set of single-char type codes.

    *raw* is a comma-separated list of type codes: ``f`` (file), ``d``
    (directory), ``l`` (symlink).  Returns e.g. ``{'f', 'd'}``.
    """
    valid = {'f', 'd', 'l'}
    result = set()
    for token in raw.split(','):
        token = token.strip().lower()
        if not token:
            continue
        if token not in valid:
            raise ValueError(
                f'Unknown type code {token!r} in --types; '
                f'valid codes: f (file), d (directory), l (symlink)'
            )
        result.add(token)
    if not result:
        raise ValueError('--types produced an empty set')
    return result


# ---------------------------------------------------------------------------
# Date selection
# ---------------------------------------------------------------------------

def resolve_selector(
    entry: ListingEntry,
    selector: str,
) -> Optional[datetime]:
    """Resolve a single attr-map *selector* against an entry's date list.

    *selector* is ``"earliest"``, ``"latest"``, or a 0-based column index
    string.
    """
    if not entry.dates:
        return None
    if selector == 'earliest':
        return min(entry.dates)
    if selector == 'latest':
        return max(entry.dates)
    idx = int(selector)
    if 0 <= idx < len(entry.dates):
        return entry.dates[idx]
    logger.warning(
        'Column index %d out of range (entry has %d date columns) for %s',
        idx, len(entry.dates), entry.raw_path,
    )
    return None


# ---------------------------------------------------------------------------
# Entry-type classification
# ---------------------------------------------------------------------------

def classify_entry(entry: ListingEntry, resolved_path: str) -> str:
    """Return a single-char type code for *entry*: ``'d'``, ``'f'``, or ``'l'``.

    Symlinks are detected via the filesystem.  If the listing carries a type
    marker it is used for the file-vs-directory distinction; otherwise the
    filesystem is consulted.
    """
    # Symlinks must be checked first (a symlink to a dir is still a symlink)
    if os.path.islink(resolved_path):
        return 'l'
    if entry.entry_type is not None:
        if entry.entry_type.lower() in ('directory', 'd'):
            return 'd'
        return 'f'
    # No type column — fall back to filesystem
    if os.path.isdir(resolved_path):
        return 'd'
    return 'f'


def is_directory_entry(entry: ListingEntry, resolved_path: str) -> bool:
    """Decide whether *entry* represents a directory.

    Kept for backward compatibility with ``--date-column`` legacy mode.
    """
    return classify_entry(entry, resolved_path) == 'd'


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


def set_access_modify_time(
    path: str,
    access_dt: Optional[datetime] = None,
    modify_dt: Optional[datetime] = None,
) -> None:
    """Set access and/or modification time using :func:`os.utime`.

    Works on all platforms.  Pass ``None`` for either argument to leave that
    timestamp unchanged.
    """
    # os.utime expects (atime, mtime) as floats (epoch seconds).
    # Passing None for the whole tuple means "set both to now", so we need
    # to read the current values for whichever side we're not changing.
    stat = os.stat(path)
    atime = access_dt.timestamp() if access_dt is not None else stat.st_atime
    mtime = modify_dt.timestamp() if modify_dt is not None else stat.st_mtime
    os.utime(path, (atime, mtime))


# ---------------------------------------------------------------------------
# Listing generation helpers
# ---------------------------------------------------------------------------

def _get_creation_time(stat_result) -> float:
    """Return the creation (birth) time from a stat result.

    On macOS/Windows ``st_birthtime`` is available.  On Linux fall back to
    ``st_ctime`` (metadata-change time — the closest available proxy).
    """
    try:
        return stat_result.st_birthtime
    except AttributeError:
        return stat_result.st_ctime


def _format_ts_utc(epoch: float) -> str:
    """Format an epoch timestamp as ``MM/DD/YYYY HH:MM:SS`` in UTC."""
    dt = datetime.fromtimestamp(epoch, tz=timezone.utc)
    return dt.strftime('%m/%d/%Y %H:%M:%S')


def _entry_type_code(path: str) -> str:
    """Return ``'D'`` for directory, ``'F'`` for file, ``'L'`` for symlink."""
    if os.path.islink(path):
        return 'L'
    if os.path.isdir(path):
        return 'D'
    return 'F'


def _type_code_to_filter(code: str) -> str:
    """Map a listing type code (``D``/``F``/``L``) to a ``--types`` filter
    char (``d``/``f``/``l``)."""
    return code.lower()


def generate_listing(
    base_dir: str,
    output_path: str,
    allowed_types: set,
) -> int:
    """Walk *base_dir* and write a Format-3 CSV listing to *output_path*.

    Returns the number of entries written.
    """
    count = 0
    base = os.path.normpath(base_dir)

    with open(output_path, 'w', encoding='utf-8', newline='') as fh:
        writer = csv.writer(fh)
        for dirpath, dirnames, filenames in os.walk(base):
            # Collect all entries in this directory level
            entries: List[str] = []
            if 'd' in allowed_types:
                entries.extend(
                    os.path.join(dirpath, d) for d in dirnames
                )
            if 'f' in allowed_types:
                entries.extend(
                    os.path.join(dirpath, f) for f in filenames
                    if not os.path.islink(os.path.join(dirpath, f))
                )
            if 'l' in allowed_types:
                # Symlinks among files
                entries.extend(
                    os.path.join(dirpath, f) for f in filenames
                    if os.path.islink(os.path.join(dirpath, f))
                )
                # Symlinks among dirs
                entries.extend(
                    os.path.join(dirpath, d) for d in dirnames
                    if os.path.islink(os.path.join(dirpath, d))
                )

            # Also include the directory itself if it's the base
            if dirpath == base and 'd' in allowed_types:
                entries.insert(0, dirpath)

            for full_path in entries:
                try:
                    st = os.lstat(full_path)
                except OSError as exc:
                    logger.warning('Cannot stat %s: %s', full_path, exc)
                    continue

                creation = _format_ts_utc(_get_creation_time(st))
                access = _format_ts_utc(st.st_atime)
                modify = _format_ts_utc(st.st_mtime)
                type_code = _entry_type_code(full_path)

                # Relative path from base_dir
                rel = os.path.relpath(full_path, base)

                writer.writerow([creation, access, modify, type_code, rel])
                count += 1

    return count


# ---------------------------------------------------------------------------
# Tackle class
# ---------------------------------------------------------------------------

class SetCreationTime(TackleFactory):
    """Read a directory listing CSV and set timestamps on local entries."""

    @classmethod
    def arg_parser(cls, subparser):
        subparser.add_argument(
            '--listing',
            type=pathlib.Path,
            default=None,
            help=(
                'Path to the CSV listing file.  Required unless '
                '--generate-listing is used.'
            ),
        )
        subparser.add_argument(
            '--base-dir',
            type=pathlib.Path,
            required=True,
            help='Local base directory to resolve relative paths against',
        )
        subparser.add_argument(
            '--generate-listing',
            type=pathlib.Path,
            default=None,
            help=(
                'Generate a Format-3 CSV listing of --base-dir and write it '
                'to the given path.  The listing contains creation, access, '
                'and modification timestamps with relative paths.  '
                'Respects --types for filtering.  '
                'When this option is used, --listing is not required and '
                'no timestamps are applied.'
            ),
        )
        subparser.add_argument(
            '--attr-map',
            type=str,
            default='creation:e',
            help=(
                'Comma-separated mapping of filesystem attributes to listing '
                'column selectors.  Format: "attr:selector[,attr:selector,…]". '
                'Attributes: creation, access, modify.  '
                'Selectors: a 0-based column index, or "earliest" / "latest" '
                '(short: "e" / "l") to pick the min/max date from the row.  '
                'Default: "creation:e" (set creation time to earliest date).  '
                'Example: --attr-map="creation:1,access:2,modify:e"'
            ),
        )
        subparser.add_argument(
            '--types',
            type=str,
            default='d',
            help=(
                'Comma-separated list of entry types to process: '
                'f (file), d (directory), l (symlink).  '
                'Default: "d" (directories only).  '
                'Example: --types="f,d,l"'
            ),
        )
        subparser.add_argument(
            '--script-base-path',
            type=str,
            default=None,
            help=(
                'Leading directory prefix to strip from paths in the listing '
                'before resolving against --base-dir.  For example, if the '
                'listing contains "server/share/photos/2020" and you pass '
                '--script-base-path "server/share", the resolved relative '
                'path becomes "photos/2020".'
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

        self.base_dir = str(options.base_dir)
        self.script_base_path = options.script_base_path
        self.dry_run = options.dry_run
        self.generate_listing_path: Optional[str] = (
            str(options.generate_listing) if options.generate_listing else None
        )

        if options.v:
            logger.setLevel(logging.DEBUG)

        # ------------------------------------------------------------------
        # Parse --types
        # ------------------------------------------------------------------
        try:
            self.allowed_types: set = parse_types(options.types)
        except ValueError as exc:
            logger.error('Invalid --types: %s', exc)
            sys.exit(1)
        logger.info('Processing entry types: %s', ', '.join(sorted(self.allowed_types)))

        # ------------------------------------------------------------------
        # Validate base-dir
        # ------------------------------------------------------------------
        if not os.path.isdir(self.base_dir):
            logger.error('Base directory not found: %s', self.base_dir)
            sys.exit(1)

        # ------------------------------------------------------------------
        # Generate-listing mode — no listing file needed
        # ------------------------------------------------------------------
        if self.generate_listing_path is not None:
            self.listing_path: Optional[str] = None
            self.attr_map: Dict[str, str] = {}
            return

        # ------------------------------------------------------------------
        # Apply mode — listing file required
        # ------------------------------------------------------------------
        if options.listing is None:
            logger.error(
                '--listing is required when --generate-listing is not used'
            )
            sys.exit(1)

        self.listing_path = str(options.listing)

        if not os.path.isfile(self.listing_path):
            logger.error('Listing file not found: %s', self.listing_path)
            sys.exit(1)

        # ------------------------------------------------------------------
        # Parse --attr-map
        # ------------------------------------------------------------------
        try:
            self.attr_map = parse_attr_map(options.attr_map)
        except ValueError as exc:
            logger.error('Invalid --attr-map: %s', exc)
            sys.exit(1)
        logger.info('Attribute map: %s', self.attr_map)

    # ------------------------------------------------------------------
    # Main processing
    # ------------------------------------------------------------------

    def do(self):
        # Generate-listing mode
        if self.generate_listing_path is not None:
            count = generate_listing(
                self.base_dir,
                self.generate_listing_path,
                self.allowed_types,
            )
            logger.info(
                'Generated listing with %d entries: %s',
                count, self.generate_listing_path,
            )
            return

        # Apply mode
        entries = parse_listing(self.listing_path)
        logger.info('Parsed %d entries from listing', len(entries))
        self._do_attr_map(entries)

    def _do_attr_map(self, entries: List[ListingEntry]) -> None:
        """Apply timestamps according to ``--attr-map``."""
        success = 0
        skipped = 0
        failed = 0

        for entry in entries:
            rel_path = normalize_path(entry.raw_path, self.script_base_path)
            resolved = os.path.normpath(os.path.join(self.base_dir, rel_path))

            if not os.path.exists(resolved):
                logger.error('Path not found locally, skipping: %s', resolved)
                failed += 1
                continue

            # Type filter
            entry_type = classify_entry(entry, resolved)
            if entry_type not in self.allowed_types:
                logger.debug(
                    'Skipping %s (type=%s, allowed=%s)',
                    rel_path, entry_type, self.allowed_types,
                )
                skipped += 1
                continue

            # Resolve dates for each requested attribute
            resolved_attrs: Dict[str, datetime] = {}
            skip_entry = False
            for attr, selector in self.attr_map.items():
                dt = resolve_selector(entry, selector)
                if dt is None:
                    logger.warning(
                        'No valid date for attr=%s selector=%s on %s, skipping entry',
                        attr, selector, rel_path,
                    )
                    skip_entry = True
                    break
                resolved_attrs[attr] = dt

            if skip_entry:
                skipped += 1
                continue

            if self.dry_run:
                parts = ', '.join(
                    f'{a}={d.isoformat()}' for a, d in resolved_attrs.items()
                )
                logger.info('[DRY-RUN] Would set %s on %s', parts, resolved)
                success += 1
                continue

            # Apply timestamps
            try:
                self._apply_attrs(resolved, resolved_attrs)
                parts = ', '.join(
                    f'{a}={d.isoformat()}' for a, d in resolved_attrs.items()
                )
                logger.info('Set %s on %s', parts, resolved)
                success += 1
            except NotImplementedError as exc:
                logger.warning('%s — skipping %s', exc, resolved)
                skipped += 1
            except OSError as exc:
                logger.error('Failed for %s: %s', resolved, exc)
                failed += 1
            except Exception as exc:
                logger.error('Unexpected error for %s: %s', resolved, exc)
                failed += 1

        logger.info(
            'Done. success=%d  skipped=%d  failed=%d',
            success, skipped, failed,
        )

    @staticmethod
    def _apply_attrs(
        path: str, attrs: Dict[str, datetime],
    ) -> None:
        """Apply resolved attribute datetimes to *path*."""
        if 'creation' in attrs:
            set_creation_time(path, attrs['creation'])

        access_dt = attrs.get('access')
        modify_dt = attrs.get('modify')
        if access_dt is not None or modify_dt is not None:
            set_access_modify_time(path, access_dt, modify_dt)
