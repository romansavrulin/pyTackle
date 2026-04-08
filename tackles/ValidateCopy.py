"""
ValidateCopy tackle — reads a CSV file listing and sets file/directory
timestamps on the local filesystem, or validates copies against a listing.

Supports two listing formats (auto-detected):
  Format 1: Canonical, 10 columns — full pyTackle format
  Format 2: Linux-style, 6 columns — stat output

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

from common.attr_map import (
    CANONICAL_MAP,
    VALID_ATTRS,
    get_canonical_timestamp_map,
    parse_attr_map,
)  # noqa: F401 — re-exported
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

FORMAT_CANONICAL = 'canonical'  # 10 columns — full pyTackle format
FORMAT_LINUX = 'linux'          # 6 columns — Linux stat output

# Format-specific attribute maps for FileEntry.from_listing_row()
# Linux stat output: creation, access, modify, ctime (ignored), entry_type, path
_ATTR_MAP_LINUX = {'creation': '0', 'access': '1', 'modify': '2', 'entry_type': '4', 'path': '5'}


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
    """Return format identifier based on column count.
    
    Supported formats:
    - canonical: 10 columns (full pyTackle format)
    - linux: 6 columns (Linux stat output)
    """
    # Parse the first line as CSV to count columns
    reader = csv.reader(io.StringIO(first_line.strip()))
    cols = next(reader, [])
    n = len(cols)

    if n == 10:
        return FORMAT_CANONICAL
    if n == 6:
        return FORMAT_LINUX

    raise ValueError(
        f'Unsupported listing format: {n} columns. '
        f'Expected 10 (canonical) or 6 (linux).'
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


def _parse_row_canonical(cols: List[str]) -> FileEntry:
    """Canonical format: 10 columns — full pyTackle format."""
    return FileEntry.from_listing_row(cols, CANONICAL_MAP)


def _parse_row_linux(cols: List[str]) -> FileEntry:
    """Linux format: 6 columns — 4 dates, type, path."""
    return FileEntry.from_listing_row(cols, _ATTR_MAP_LINUX)


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

        # First line is data — rewind
        fh.seek(0)

        row_parser = {
            FORMAT_CANONICAL: _parse_row_canonical,
            FORMAT_LINUX: _parse_row_linux,
        }[fmt]

        reader = csv.reader(fh)
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
# Listing generation
# ---------------------------------------------------------------------------

def generate_listing(
    base_dir: str,
    output_path: str,
    allowed_types: set,
    calculate_checksum: bool = False,
    checksum_algorithm: str = 'md5',
) -> int:
    """Walk *base_dir* and write a canonical 10-column CSV listing to *output_path*.

    Uses :meth:`FileEntry.from_fs_path` to read filesystem attributes and
    :func:`common.listing.write_listing` to serialise the canonical format.

    If *calculate_checksum* is True, checksums are computed for files
    (entry_type='f') using the specified *checksum_algorithm*.

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
                # Calculate checksum for files if requested (before changing path!)
                if calculate_checksum and fe.entry_type == 'f':
                    try:
                        fe.calculate_checksum(algorithm=checksum_algorithm)
                    except OSError as exc:
                        logger.warning(
                            'Cannot calculate checksum for %s: %s',
                            full_path, exc,
                        )
                # Store relative path from base_dir (after checksum calculation)
                fe.path = os.path.relpath(full_path, base)
                yield fe

    return write_listing(output_path, _collect_entries())


# ---------------------------------------------------------------------------
# Tackle class
# ---------------------------------------------------------------------------

class ValidateCopy(TackleFactory):
    """Read a directory listing CSV and validate or set timestamps on local entries."""

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
            default='',
            help=(
                'Comma-separated mapping of filesystem attributes to listing '
                'column selectors.  Format: "attr:selector[,attr:selector,…]". '
                'Attributes: creation, access, modify.  '
                'Selectors: a 0-based column index, or "earliest" / "latest" '
                '(short: "e" / "l") to pick the min/max date from the row.  '
                'Default: empty — in apply mode, uses canonical mapping '
                '(creation→col0, access→col1, modify→col2); in generate-listing '
                'mode, attr-map is not used.  '
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
        subparser.add_argument(
            '--checksum',
            action='store_true',
            default=False,
            help='Calculate checksums during listing generation (only for files)',
        )
        subparser.add_argument(
            '--checksum-algorithm',
            type=str,
            default='md5',
            help='Algorithm for checksum calculation (default: md5)',
        )
        subparser.add_argument(
            '--validate',
            action='store_true',
            default=False,
            help='Validate listing entries against filesystem (no changes made)',
        )
        subparser.add_argument(
            '--validate-attrs',
            type=str,
            default='size,creation,permissions,uid,gid,checksum,entry_type,path',
            help='Comma-separated list of attributes to validate (default: size,creation,permissions,uid,gid,checksum,entry_type,path)',
        )
        subparser.add_argument(
            '-q', '--quiet',
            action='store_true',
            default=False,
            help='In validation mode, omit OK entries from output',
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
        self.validate_mode: bool = options.validate
        self.validate_attrs_raw: str = options.validate_attrs
        self.quiet: bool = options.quiet

        if options.v:
            logger.setLevel(logging.DEBUG)

        # ------------------------------------------------------------------
        # Mutual exclusivity checks
        # ------------------------------------------------------------------
        if self.validate_mode and self.generate_listing_path is not None:
            logger.error(
                '--validate and --generate-listing cannot be used together'
            )
            sys.exit(1)

        if self.validate_mode and options.listing is None:
            logger.error('--validate requires --listing to be specified')
            sys.exit(1)

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
        # Checksum options (for generate-listing mode)
        # ------------------------------------------------------------------
        self.calculate_checksum: bool = options.checksum
        self.checksum_algorithm: str = options.checksum_algorithm

        # ------------------------------------------------------------------
        # Generate-listing mode — no listing file needed
        # ------------------------------------------------------------------
        if self.generate_listing_path is not None:
            self.listing_path: Optional[str] = None
            self.attr_map: Dict[str, str] = {}
            self.validate_attrs: List[str] = []
            return

        # ------------------------------------------------------------------
        # Validate mode — listing file required (checked above)
        # ------------------------------------------------------------------
        if self.validate_mode:
            self.listing_path = str(options.listing)
            if not os.path.isfile(self.listing_path):
                logger.error('Listing file not found: %s', self.listing_path)
                sys.exit(1)
            # Parse and validate --validate-attrs
            self.validate_attrs = [
                a.strip() for a in self.validate_attrs_raw.split(',') if a.strip()
            ]
            invalid_attrs = [a for a in self.validate_attrs if a not in VALID_ATTRS]
            if invalid_attrs:
                logger.error(
                    'Invalid attribute(s) in --validate-attrs: %s. '
                    'Valid attributes: %s',
                    ', '.join(invalid_attrs),
                    ', '.join(VALID_ATTRS),
                )
                sys.exit(1)
            self.attr_map = {}
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
            self.attr_map = parse_attr_map(options.attr_map, allow_empty=True)
        except ValueError as exc:
            logger.error('Invalid --attr-map: %s', exc)
            sys.exit(1)

        # If attr-map is empty in apply mode, use canonical timestamp mapping
        if not self.attr_map:
            self.attr_map = get_canonical_timestamp_map()
            logger.info(
                'Using canonical timestamp mapping (empty --attr-map): %s',
                self.attr_map,
            )
        else:
            logger.info('Attribute map: %s', self.attr_map)

    # ------------------------------------------------------------------
    # Main processing
    # ------------------------------------------------------------------

    def do(self) -> int:
        # Validate mode
        if self.validate_mode:
            return self._do_validate()

        # Generate-listing mode
        if self.generate_listing_path is not None:
            count = generate_listing(
                self.base_dir,
                self.generate_listing_path,
                self.allowed_types,
                calculate_checksum=self.calculate_checksum,
                checksum_algorithm=self.checksum_algorithm,
            )
            logger.info(
                'Generated listing with %d entries: %s',
                count, self.generate_listing_path,
            )
            return 0

        # Apply mode — parse listing with path resolution
        entries = parse_listing(
            self.listing_path,
            self.base_dir,
            self.script_base_path,
        )
        logger.info('Parsed %d entries from listing', len(entries))
        self._do_attr_map(entries)
        return 0

    def _do_validate(self) -> int:
        """Validate listing entries against the filesystem.
        
        Returns:
            0 if all entries passed validation, 1 if any failed.
        """
        # Parse listing without path resolution (we need relative paths for output)
        entries: List[FileEntry] = []
        
        with open(self.listing_path, encoding='utf-8-sig', newline='') as fh:
            first_line = fh.readline()
            if not first_line:
                logger.info('Empty listing file')
                print('---')
                print('Validated 0 files: 0 passed, 0 failed')
                return 0

            fmt = detect_format(first_line)
            logger.info('Detected listing format: %s', fmt)

            fh.seek(0)
            row_parser = {
                FORMAT_CANONICAL: _parse_row_canonical,
                FORMAT_LINUX: _parse_row_linux,
            }[fmt]

            reader = csv.reader(fh)
            for lineno, cols in enumerate(reader, start=1):
                if not cols or all(c.strip() == '' for c in cols):
                    continue
                try:
                    fe = row_parser(cols)
                    # Store relative path before resolution for reporting
                    rel_path = normalize_path(fe.path, self.script_base_path)
                    full_path = os.path.normpath(
                        os.path.join(self.base_dir, rel_path)
                    )
                    # Store both: relative for reporting, full for validation
                    fe._rel_path = rel_path  # type: ignore[attr-defined]
                    fe.path = full_path
                    entries.append(fe)
                except Exception as exc:
                    logger.warning('Line %d: skipping — %s', lineno, exc)

        passed = 0
        failed = 0

        for fe in entries:
            rel_path = getattr(fe, '_rel_path', fe.path)
            
            # Type filter
            if fe.entry_type and fe.entry_type not in self.allowed_types:
                logger.debug(
                    'Skipping %s (type=%s, allowed=%s)',
                    rel_path, fe.entry_type, self.allowed_types,
                )
                continue

            # Validate against filesystem
            errors = fe.validate(attrs=self.validate_attrs, check_fs=True)

            if errors:
                # Format error messages nicely
                error_parts = []
                for err in errors:
                    error_parts.append(err)
                print(f'FAIL: {rel_path}: {", ".join(error_parts)}')
                failed += 1
            else:
                if not self.quiet:
                    print(f'OK: {rel_path}')
                passed += 1

        total = passed + failed
        print('---')
        print(f'Validated {total} files: {passed} passed, {failed} failed')

        return 0 if failed == 0 else 1

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

            # Type filter (entry_type is normalized during parsing)
            if fe.entry_type not in self.allowed_types:
                logger.debug(
                    'Skipping %s (type=%s, allowed=%s)',
                    fe.path, fe.entry_type, self.allowed_types,
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
