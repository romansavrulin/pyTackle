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
import sys
from datetime import datetime
from typing import Dict, List, Optional

from common.attr_map import parse_attr_map          # noqa: F401 — re-exported
from common.FileEntry import FileEntry
from common.fs_attrs import (
    set_creation_time,                               # noqa: F401 — re-exported
    set_access_modify_time,                          # noqa: F401 — re-exported
)
from common.listing import write_listing
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

# Format-specific attribute maps for FileEntry.from_listing_row()
_ATTR_MAP_LINUX = {'creation': '0', 'access': '1', 'modify': '2', 'entry_type': '4', 'path': '5'}
_ATTR_MAP_PS_HEADER = {'creation': '0', 'access': '1', 'modify': '2', 'path': '3'}
_ATTR_MAP_PS_TYPE = {'creation': '0', 'access': '1', 'modify': '2', 'entry_type': '3', 'path': '4'}


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


def _extract_dates(fe: FileEntry) -> List[datetime]:
    """Extract non-None datetime attributes from a FileEntry in canonical order.
    
    Used for date selection logic (earliest/latest/index).
    """
    dates: List[datetime] = []
    for attr in ('creation', 'access', 'modify'):
        dt = getattr(fe, attr)
        if dt is not None:
            dates.append(dt)
    return dates


def _parse_row_linux(cols: List[str]) -> FileEntry:
    """Format 1: 6 columns — 4 dates, type, path."""
    return FileEntry.from_listing_row(cols, _ATTR_MAP_LINUX)


def _parse_row_ps_header(cols: List[str]) -> FileEntry:
    """Format 2: 4 columns — 3 dates, path (no type)."""
    return FileEntry.from_listing_row(cols, _ATTR_MAP_PS_HEADER)


def _parse_row_ps_type(cols: List[str]) -> FileEntry:
    """Format 3: 5 columns — 3 dates, type, path."""
    return FileEntry.from_listing_row(cols, _ATTR_MAP_PS_TYPE)


def parse_listing(
    listing_path: str,
    base_dir: str,
    script_base_path: Optional[str] = None,
) -> List[FileEntry]:
    """Read and parse a listing file, resolving paths against *base_dir*.

    Each FileEntry's ``path`` attribute is set to the fully-resolved filesystem
    path.  Entries with non-existent paths are logged and skipped.
    """
    entries: List[FileEntry] = []

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
                fe = row_parser(cols)
                
                # Resolve path to full filesystem path
                rel_path = normalize_path(fe.path, script_base_path)
                full_path = os.path.normpath(os.path.join(base_dir, rel_path))
                fe.path = full_path
                
                entries.append(fe)
            except Exception as exc:
                logger.warning('Line %d: skipping — %s', lineno, exc)

    return entries


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
    dates: List[datetime],
    selector: str,
) -> Optional[datetime]:
    """Resolve a single attr-map *selector* against a date list.

    *selector* is ``"earliest"``, ``"latest"``, or a 0-based column index
    string.
    """
    if not dates:
        return None
    if selector == 'earliest':
        return min(dates)
    if selector == 'latest':
        return max(dates)
    idx = int(selector)
    if 0 <= idx < len(dates):
        return dates[idx]
    logger.warning(
        'Column index %d out of range (entry has %d date columns)',
        idx, len(dates),
    )
    return None


# ---------------------------------------------------------------------------
# Entry-type classification
# ---------------------------------------------------------------------------

def normalize_entry_type(raw: Optional[str]) -> Optional[str]:
    """Normalize entry type to single-char code: 'f', 'd', or 'l'.

    Accepts various formats from listing files:
    - 'f', 'F', 'file' → 'f'
    - 'd', 'D', 'directory' → 'd'
    - 'l', 'L', 'symlink', 'link' → 'l'
    """
    if raw is None:
        return None
    raw = raw.strip().lower()
    if raw in ('f', 'file'):
        return 'f'
    if raw in ('d', 'directory'):
        return 'd'
    if raw in ('l', 'symlink', 'link'):
        return 'l'
    # Unknown format — return as-is (single char) or first char
    return raw[0] if raw else None


def classify_entry(fe: FileEntry, resolved_path: str) -> str:
    """Return a single-char type code: ``'d'``, ``'f'``, or ``'l'``.

    Symlinks are detected via the filesystem.  If the FileEntry carries a type
    marker it is used for the file-vs-directory distinction; otherwise the
    filesystem is consulted.
    """
    # Symlinks must be checked first (a symlink to a dir is still a symlink)
    if os.path.islink(resolved_path):
        return 'l'
    if fe.entry_type is not None:
        normalized = normalize_entry_type(fe.entry_type)
        if normalized == 'd':
            return 'd'
        if normalized == 'l':
            return 'l'
        return 'f'
    # No type column — fall back to filesystem
    if os.path.isdir(resolved_path):
        return 'd'
    return 'f'


def is_directory_entry(fe: FileEntry, resolved_path: str) -> bool:
    """Decide whether *entry* represents a directory.

    Kept for backward compatibility with ``--date-column`` legacy mode.
    """
    return classify_entry(fe, resolved_path) == 'd'


# ---------------------------------------------------------------------------
# Listing generation
# ---------------------------------------------------------------------------

def generate_listing(
    base_dir: str,
    output_path: str,
    allowed_types: set,
) -> int:
    """Walk *base_dir* and write a canonical 9-column CSV listing to *output_path*.

    Uses :meth:`FileEntry.from_fs_path` to read filesystem attributes and
    :func:`common.listing.write_listing` to serialise the canonical format.

    Returns the number of entries written.
    """
    base = os.path.normpath(base_dir)

    def _collect_entries():
        """Yield :class:`FileEntry` objects for every matching path."""
        for dirpath, dirnames, filenames in os.walk(base):
            # Collect all full paths in this directory level
            paths: List[str] = []
            if 'd' in allowed_types:
                paths.extend(
                    os.path.join(dirpath, d) for d in dirnames
                )
            if 'f' in allowed_types:
                paths.extend(
                    os.path.join(dirpath, f) for f in filenames
                    if not os.path.islink(os.path.join(dirpath, f))
                )
            if 'l' in allowed_types:
                # Symlinks among files
                paths.extend(
                    os.path.join(dirpath, f) for f in filenames
                    if os.path.islink(os.path.join(dirpath, f))
                )
                # Symlinks among dirs
                paths.extend(
                    os.path.join(dirpath, d) for d in dirnames
                    if os.path.islink(os.path.join(dirpath, d))
                )

            # Also include the directory itself if it's the base
            if dirpath == base and 'd' in allowed_types:
                paths.insert(0, dirpath)

            for full_path in paths:
                try:
                    fe = FileEntry.from_fs_path(full_path)
                except OSError as exc:
                    logger.warning('Cannot stat %s: %s', full_path, exc)
                    continue
                # Store relative path from base_dir
                fe.path = os.path.relpath(full_path, base)
                yield fe

    return write_listing(output_path, _collect_entries())


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

        # Apply mode — parse listing with path resolution
        entries = parse_listing(
            self.listing_path,
            self.base_dir,
            self.script_base_path,
        )
        logger.info('Parsed %d entries from listing', len(entries))
        self._do_attr_map(entries)

    def _do_attr_map(self, entries: List[FileEntry]) -> None:
        """Apply timestamps according to ``--attr-map``."""
        success = 0
        skipped = 0
        failed = 0

        # Source attributes needed for date selection
        source_attrs = ['creation', 'access', 'modify']

        for fe in entries:
            # Validate: path exists and has required source data
            errors = fe.validate(source_attrs)
            if errors:
                for err in errors:
                    logger.error('%s: %s', fe.path, err)
                failed += 1
                continue

            # Type filter (path is already resolved in fe.path)
            etype = classify_entry(fe, fe.path)
            if etype not in self.allowed_types:
                logger.debug(
                    'Skipping %s (type=%s, allowed=%s)',
                    fe.path, etype, self.allowed_types,
                )
                skipped += 1
                continue

            # Extract dates for selection logic
            dates = _extract_dates(fe)

            # Apply user's selection and mutate FileEntry
            attrs_to_apply: List[str] = []
            skip_entry = False
            for attr, selector in self.attr_map.items():
                dt = resolve_selector(dates, selector)
                if dt is None:
                    logger.warning(
                        'No valid date for attr=%s selector=%s on %s, skipping entry',
                        attr, selector, fe.path,
                    )
                    skip_entry = True
                    break
                setattr(fe, attr, dt)
                attrs_to_apply.append(attr)

            if skip_entry:
                skipped += 1
                continue

            if self.dry_run:
                parts = ', '.join(
                    f'{a}={getattr(fe, a).isoformat()}' for a in attrs_to_apply
                )
                logger.info('[DRY-RUN] Would set %s on %s', parts, fe.path)
                success += 1
                continue

            # Apply timestamps using FileEntry.apply_to_fs()
            try:
                fe.apply_to_fs(attrs=attrs_to_apply)
                parts = ', '.join(
                    f'{a}={getattr(fe, a).isoformat()}' for a in attrs_to_apply
                )
                logger.info('Set %s on %s', parts, fe.path)
                success += 1
            except NotImplementedError as exc:
                logger.warning('%s — skipping %s', exc, fe.path)
                skipped += 1
            except OSError as exc:
                logger.error('Failed for %s: %s', fe.path, exc)
                failed += 1
            except Exception as exc:
                logger.error('Unexpected error for %s: %s', fe.path, exc)
                failed += 1

        logger.info(
            'Done. success=%d  skipped=%d  failed=%d',
            success, skipped, failed,
        )
