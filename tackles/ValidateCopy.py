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
    progress_interval: int = 1000,
) -> List[FileEntry]:
    """Read and parse a listing file, resolving paths against *base_dir*.

    Each FileEntry's ``path`` attribute is set to the fully-resolved filesystem
    path.  Entries with non-existent paths are logged and skipped.
    
    Progress is logged every *progress_interval* entries.
    """
    entries: List[FileEntry] = []

    # First pass: count total lines for progress reporting
    with open(listing_path, encoding='utf-8-sig') as fh:
        total_lines = sum(1 for line in fh if line.strip())
    logger.info('Loading listing: %s (%d lines)', listing_path, total_lines)

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
        processed = 0
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
                processed += 1
                
                # Progress logging
                if processed % progress_interval == 0:
                    pct = (processed / total_lines) * 100
                    logger.info(
                        'Loading entries: %d/%d (%.1f%%)',
                        processed, total_lines, pct
                    )
            except Exception as exc:
                logger.warning('Line %d: skipping — %s', lineno, exc)

    logger.info('Loaded %d entries from listing', len(entries))
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
        # =====================================================================
        # MODE SELECTION (mutually exclusive)
        # =====================================================================
        mode_group = subparser.add_mutually_exclusive_group(required=True)

        mode_group.add_argument(
            '--validate',
            type=pathlib.Path,
            default=None,
            metavar='LISTING',
            help='Validate filesystem against listing file',
        )
        mode_group.add_argument(
            '--generate',
            type=pathlib.Path,
            default=None,
            metavar='LISTING',
            help='Generate listing from filesystem to output file',
        )
        mode_group.add_argument(
            '--apply',
            type=pathlib.Path,
            default=None,
            metavar='LISTING',
            help='Apply metadata from listing to filesystem',
        )

        # Unified attribute specification
        subparser.add_argument(
            '--attrs',
            type=str,
            default=None,
            help=(
                'Comma-separated attributes. Behavior depends on mode:\n'
                '  validate: attributes to compare (default: all)\n'
                '  generate: attributes to include (default: all + checksum)\n'
                '  apply: attributes to set (default: creation,access,modify)'
            ),
        )

        # =====================================================================
        # COMMON OPTIONS
        # =====================================================================
        # Positional argument for base directory
        subparser.add_argument(
            'base_dir',
            type=pathlib.Path,
            help='Local base directory to resolve relative paths against',
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
                'before resolving against base_dir.  For example, if the '
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
            '-q', '--quiet',
            action='store_true',
            default=False,
            help='In validation mode, omit OK entries from output',
        )
        subparser.add_argument(
            '--checksum-algorithm',
            type=str,
            default='md5',
            help='Algorithm for checksum calculation (default: md5)',
        )

        # Advanced option for apply mode (still useful for selector logic)
        subparser.add_argument(
            '--attr-map',
            type=str,
            default='',
            help=(
                'Advanced: Comma-separated mapping of filesystem attributes '
                'to listing column selectors. Format: attr:selector[,…]. '
                'Selectors: 0-based column index, "earliest"/"e", "latest"/"l".'
            ),
        )

    def __init__(self, parser):
        super().__init__(parser)
        options, _ = parser.parse_known_args()

        # ------------------------------------------------------------------
        # Common options
        # ------------------------------------------------------------------
        self.base_dir = str(options.base_dir)
        self.script_base_path = options.script_base_path
        self.dry_run = options.dry_run
        self.quiet: bool = options.quiet
        self.checksum_algorithm: str = options.checksum_algorithm

        if options.v:
            logger.setLevel(logging.DEBUG)

        # ------------------------------------------------------------------
        # Determine mode from arguments
        # ------------------------------------------------------------------
        self.mode: str = self._determine_mode(options)

        # ------------------------------------------------------------------
        # Parse --types
        # ------------------------------------------------------------------
        try:
            self.allowed_types: set = parse_types(options.types)
        except ValueError as exc:
            logger.error('Invalid --types: %s', exc)
            sys.exit(1)

        # ------------------------------------------------------------------
        # Validate base-dir
        # ------------------------------------------------------------------
        if not os.path.isdir(self.base_dir):
            logger.error('Base directory not found: %s', self.base_dir)
            sys.exit(1)

        # ------------------------------------------------------------------
        # Mode-specific initialization
        # ------------------------------------------------------------------
        if self.mode == 'generate':
            self._init_generate_mode(options)
        elif self.mode == 'validate':
            self._init_validate_mode(options)
        elif self.mode == 'apply':
            self._init_apply_mode(options)

        self._log_startup_settings()

    def _determine_mode(self, options) -> str:
        """Determine the operation mode from CLI arguments.
        
        Returns one of: 'validate', 'generate', 'apply'
        
        Mode is determined by the mutually exclusive group, so exactly one
        of --validate, --generate, or --apply will be set.
        """
        if options.validate is not None:
            return 'validate'
        if options.generate is not None:
            return 'generate'
        if options.apply is not None:
            return 'apply'
        
        # This should never happen due to argparse's required=True
        logger.error('One of --validate, --generate, or --apply is required')
        sys.exit(1)

    def _init_generate_mode(self, options) -> None:
        """Initialize generate mode settings."""
        self.generate_listing_path: Optional[str] = str(options.generate)
        self.listing_path: Optional[str] = None
        self.attr_map: Dict[str, str] = {}
        self.validate_attrs: List[str] = []

        # Handle --attrs for generate mode
        # Default: include checksum for files (checksum ON by default)
        self.calculate_checksum: bool = True

        if options.attrs is not None:
            # Parse attrs to see if checksum is included
            attrs_list = [a.strip().lower() for a in options.attrs.split(',') if a.strip()]
            self.calculate_checksum = 'checksum' in attrs_list

    def _init_validate_mode(self, options) -> None:
        """Initialize validate mode settings."""
        self.generate_listing_path: Optional[str] = None
        self.calculate_checksum: bool = False

        # Get listing path from --validate argument (always a pathlib.Path)
        self.listing_path = str(options.validate)

        if not os.path.isfile(self.listing_path):
            logger.error('Listing file not found: %s', self.listing_path)
            sys.exit(1)

        # Handle --attrs for validate mode
        # Default: all available attributes
        default_validate_attrs = 'size,creation,permissions,uid,gid,checksum,entry_type,path'

        if options.attrs is not None:
            attrs_raw = options.attrs
        else:
            attrs_raw = default_validate_attrs

        self.validate_attrs = [
            a.strip() for a in attrs_raw.split(',') if a.strip()
        ]
        invalid_attrs = [a for a in self.validate_attrs if a not in VALID_ATTRS]
        if invalid_attrs:
            logger.error(
                'Invalid attribute(s) in --attrs: %s. '
                'Valid attributes: %s',
                ', '.join(invalid_attrs),
                ', '.join(VALID_ATTRS),
            )
            sys.exit(1)

        self.attr_map: Dict[str, str] = {}

    def _init_apply_mode(self, options) -> None:
        """Initialize apply mode settings."""
        self.generate_listing_path: Optional[str] = None
        self.validate_attrs: List[str] = []
        self.calculate_checksum: bool = False

        # Get listing path from --apply argument
        self.listing_path = str(options.apply)

        if not os.path.isfile(self.listing_path):
            logger.error('Listing file not found: %s', self.listing_path)
            sys.exit(1)

        # Handle --attrs for apply mode
        # Default: creation, access, modify (timestamp attributes)
        if options.attrs is not None:
            # User specified attrs - convert to attr_map format
            # For apply mode, --attrs is a simpler way to specify which attrs to set
            # Each attr maps to its canonical column
            attrs_list = [a.strip().lower() for a in options.attrs.split(',') if a.strip()]
            timestamp_attrs = {'creation', 'access', 'modify'}
            valid_apply_attrs = timestamp_attrs

            invalid_attrs = [a for a in attrs_list if a not in valid_apply_attrs]
            if invalid_attrs:
                logger.error(
                    'Invalid attribute(s) in --attrs for apply mode: %s. '
                    'Valid attributes: %s',
                    ', '.join(invalid_attrs),
                    ', '.join(sorted(valid_apply_attrs)),
                )
                sys.exit(1)

            # Build attr_map from attrs list using canonical column indices
            canonical_indices = {'creation': '0', 'access': '1', 'modify': '2'}
            self.attr_map = {attr: canonical_indices[attr] for attr in attrs_list}
        elif options.attr_map:
            # Old --attr-map style (still supported for advanced selector use)
            try:
                self.attr_map = parse_attr_map(options.attr_map, allow_empty=True)
            except ValueError as exc:
                logger.error('Invalid --attr-map: %s', exc)
                sys.exit(1)
        else:
            # Default: use canonical timestamp mapping
            self.attr_map = get_canonical_timestamp_map()

        # If attr-map is empty, use canonical timestamp mapping
        if not self.attr_map:
            self.attr_map = get_canonical_timestamp_map()

    # Backward compatibility properties
    @property
    def validate_mode(self) -> bool:
        """Backward compatibility: returns True if in validate mode."""
        return self.mode == 'validate'

    # ------------------------------------------------------------------
    # Startup logging
    # ------------------------------------------------------------------

    def _log_startup_settings(self) -> None:
        """Log mode and configuration at startup."""
        # Use the mode attribute directly (set during __init__)
        mode_name = self.mode

        logger.info('=' * 60)
        logger.info('ValidateCopy — Mode: %s', mode_name.upper())
        logger.info('=' * 60)
        logger.info('Base directory: %s', self.base_dir)

        if mode_name in ('validate', 'apply'):
            logger.info('Listing file: %s', self.listing_path)
        else:
            logger.info('Output file: %s', self.generate_listing_path)

        logger.info('Entry types: %s', ', '.join(sorted(self.allowed_types)))

        if mode_name == 'validate':
            logger.info('Validate attributes: %s', ', '.join(self.validate_attrs))
            logger.info('Quiet mode: %s', 'enabled' if self.quiet else 'disabled')
        elif mode_name == 'apply':
            logger.info('Attribute map: %s', self.attr_map)

        if mode_name == 'generate':
            logger.info('Calculate checksum: %s', 'enabled' if self.calculate_checksum else 'disabled')
            if self.calculate_checksum:
                logger.info('Checksum algorithm: %s', self.checksum_algorithm)

        if self.dry_run:
            logger.info('Dry-run: ENABLED (no changes will be made)')

        if self.script_base_path:
            logger.info('Script base path: %s', self.script_base_path)

        logger.info('-' * 60)

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
        progress_interval = 1000
        
        # First pass: count total lines for progress reporting
        with open(self.listing_path, encoding='utf-8-sig') as fh:
            total_lines = sum(1 for line in fh if line.strip())
        logger.info('Loading listing: %s (%d lines)', self.listing_path, total_lines)
        
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
            processed = 0
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
                    processed += 1
                    
                    # Progress logging during loading
                    if processed % progress_interval == 0:
                        pct = (processed / total_lines) * 100
                        logger.info(
                            'Loading entries: %d/%d (%.1f%%)',
                            processed, total_lines, pct
                        )
                except Exception as exc:
                    logger.warning('Line %d: skipping — %s', lineno, exc)

        logger.info('Loaded %d entries from listing', len(entries))
        
        passed = 0
        failed = 0
        skipped = 0
        total = len(entries)
        
        logger.info('Validating %d entries...', total)

        for idx, fe in enumerate(entries, start=1):
            rel_path = getattr(fe, '_rel_path', fe.path)
            
            # Type filter
            if fe.entry_type and fe.entry_type not in self.allowed_types:
                logger.debug(
                    'Skipping %s (type=%s, allowed=%s)',
                    rel_path, fe.entry_type, self.allowed_types,
                )
                skipped += 1
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
            
            # Progress logging during validation
            processed_count = passed + failed + skipped
            if processed_count % progress_interval == 0:
                pct = (processed_count / total) * 100
                logger.info(
                    'Validation progress: %d/%d (%.1f%%) — %d passed, %d failed, %d skipped',
                    processed_count, total, pct, passed, failed, skipped
                )

        validated_total = passed + failed
        print('---')
        print(f'Validated {validated_total} files: {passed} passed, {failed} failed')
        
        logger.info(
            'Validation complete: %d passed, %d failed, %d skipped',
            passed, failed, skipped
        )

        return 0 if failed == 0 else 1

    def _do_attr_map(self, entries: List[FileEntry]) -> None:
        """Apply timestamps according to ``--attr-map``."""
        progress_interval = 1000
        success = 0
        skipped = 0
        failed = 0
        total = len(entries)

        # Source attributes needed for date selection
        source_attrs = ['creation', 'access', 'modify']
        
        logger.info('Applying attributes to %d entries...', total)

        for idx, fe in enumerate(entries, start=1):
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
                if getattr(fe, attr) != dt:
                    setattr(fe, attr, dt)
                    attrs_to_apply.append(attr)

            if skip_entry or len(attrs_to_apply) == 0:
                skipped += 1
                continue

            # Apply timestamps using FileEntry.apply_to_fs()
            try:
                inent = "Set"
                if self.dry_run:
                    intent = "[DRY-RUN] Would set"
                else:
                    fe.apply_to_fs(attrs=attrs_to_apply)

                parts = ', '.join(
                    f'{a}={getattr(fe, a).isoformat()}' for a in attrs_to_apply
                )
                logger.info('%s %s on %s', intent, parts, fe.path)
                success += 1

            except NotImplementedError as exc:
                logger.warning('%s — skipping %s', exc, fe.path)
                skipped += 1
            except OSError as exc:
                logger.error('Failed for %s: %s', fe.path, exc)
                failed += 1
            except fs_attrs.FSNotPersistedError as exc:
                logger.error('Failed for %s: %s', fe.path, exc)
                failed += 1
            except Exception as exc:
                logger.error('Unexpected error for %s: %s', fe.path, exc)
                failed += 1
            
            # Progress logging
            processed_count = success + skipped + failed
            if processed_count % progress_interval == 0:
                pct = (processed_count / total) * 100
                logger.info(
                    'Apply progress: %d/%d (%.1f%%) — %d success, %d skipped, %d failed',
                    processed_count, total, pct, success, skipped, failed
                )

        logger.info(
            'Apply complete: %d success, %d skipped, %d failed',
            success, skipped, failed,
        )
