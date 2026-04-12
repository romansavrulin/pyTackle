"""CSV and md5sum listing I/O for :class:`~common.FileEntry.FileEntry`.

Provides both **bulk** (load all into memory) and **streaming** (yield one
at a time) interfaces for reading and writing FileEntry listings.

The ``iter_*`` functions are the primary implementations; the ``read_*``
functions are thin convenience wrappers that materialise the iterator into
a list.
"""

from __future__ import annotations

import csv
import logging
from typing import Iterator

from common.attr_map import CANONICAL_MAP, CANONICAL_HEADER
from common.FileEntry import FileEntry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# CSV listing — reading
# ---------------------------------------------------------------------------

def _is_header_row(cols: list[str], attr_map: dict[str, str]) -> bool:
    """Check if a row looks like a header row.
    
    A row is considered a header if all column values match expected
    attribute names from the attr_map keys.
    
    Parameters
    ----------
    cols:
        The CSV row values.
    attr_map:
        Column mapping to check against.
    
    Returns
    -------
    bool
        True if the row appears to be a header row.
    """
    # Build expected header from attr_map (sorted by column index)
    sorted_attrs = sorted(attr_map.items(), key=lambda x: int(x[1]))
    expected_header = tuple(attr for attr, _ in sorted_attrs)
    
    # Check if the row values match the expected header names
    if len(cols) < len(expected_header):
        return False
    
    for i, attr in enumerate(expected_header):
        col_idx = int(attr_map[attr])
        if col_idx >= len(cols):
            return False
        if cols[col_idx].strip().lower() != attr.lower():
            return False
    
    return True


def iter_listing(
    listing_path: str,
    attr_map: dict[str, str] | None = None,
    encoding: str = 'utf-8-sig',
    progress_interval: int = 1000,
    has_header: bool | None = None,
) -> Iterator[FileEntry]:
    """Yield :class:`FileEntry` objects one row at a time from a CSV listing.

    Memory-efficient for extremely large listings — only one row is held in
    memory at a time.

    Parameters
    ----------
    listing_path:
        Path to the CSV file.
    attr_map:
        Column mapping (attribute name → selector).  If *None*,
        :data:`~common.attr_map.CANONICAL_MAP` is used.
    encoding:
        File encoding.  Defaults to ``'utf-8-sig'`` to transparently strip
        a UTF-8 BOM if present.
    progress_interval:
        Log progress every this many entries. Set to 0 to disable.
    has_header:
        Whether the CSV has a header row. If *None* (default), auto-detect
        by checking if the first row matches expected attribute names.
        If *True*, always skip the first row. If *False*, never skip.
    """
    if attr_map is None:
        attr_map = CANONICAL_MAP

    # First pass: count total lines for progress reporting
    with open(listing_path, encoding=encoding) as fh:
        total_lines = sum(1 for line in fh if line.strip())
    logger.info('Loading listing: %s (%d lines)', listing_path, total_lines)

    with open(listing_path, newline='', encoding=encoding) as fh:
        reader = csv.reader(fh)
        processed = 0
        first_row = True
        for lineno, cols in enumerate(reader, start=1):
            # Skip empty lines (all columns empty or blank)
            if not cols or all(c.strip() == '' for c in cols):
                continue
            
            # Handle header row
            if first_row:
                first_row = False
                skip_row = False
                if has_header is True:
                    skip_row = True
                elif has_header is None:
                    # Auto-detect: check if row looks like a header
                    skip_row = _is_header_row(cols, attr_map)
                # has_header=False means never skip
                
                if skip_row:
                    logger.debug('Skipping header row: %s', cols)
                    continue
            
            try:
                fe = FileEntry.from_listing_row(cols, attr_map)
                processed += 1
                
                # Progress logging
                if progress_interval > 0 and processed % progress_interval == 0:
                    pct = (processed / total_lines) * 100
                    logger.info(
                        'Loading entries: %d/%d (%.1f%%)',
                        processed, total_lines, pct
                    )
                
                yield fe
            except Exception as exc:
                logger.warning(
                    "Skipping row %d in %s: %s", lineno, listing_path, exc,
                )
        
        logger.info('Loaded %d entries from listing', processed)


def read_listing(
    listing_path: str,
    attr_map: dict[str, str] | None = None,
    encoding: str = 'utf-8-sig',
    progress_interval: int = 1000,
    has_header: bool | None = None,
) -> list[FileEntry]:
    """Load an entire CSV listing into a list of :class:`FileEntry` objects.

    Convenience wrapper around :func:`iter_listing`.
    
    Parameters
    ----------
    listing_path:
        Path to the CSV file.
    attr_map:
        Column mapping (attribute name → selector).  If *None*,
        :data:`~common.attr_map.CANONICAL_MAP` is used.
    encoding:
        File encoding.  Defaults to ``'utf-8-sig'``.
    progress_interval:
        Log progress every this many entries. Set to 0 to disable.
    has_header:
        Whether the CSV has a header row. If *None* (default), auto-detect.
        If *True*, always skip the first row. If *False*, never skip.
    """
    return list(iter_listing(listing_path, attr_map, encoding, progress_interval, has_header))


# ---------------------------------------------------------------------------
# md5sum listing — reading
# ---------------------------------------------------------------------------

def iter_md5sum_listing(
    listing_path: str,
    encoding: str = 'utf-8-sig',
) -> Iterator[FileEntry]:
    """Yield :class:`FileEntry` objects from a native ``md5sum`` bulk file.

    Expected line format::

        <hexdigest>  <path>

    (two spaces between hexdigest and path).

    Parameters
    ----------
    listing_path:
        Path to the md5sum output file.
    encoding:
        File encoding.  Defaults to ``'utf-8-sig'``.
    """
    with open(listing_path, encoding=encoding) as fh:
        for lineno, line in enumerate(fh, start=1):
            if not line.strip():
                continue
            try:
                yield FileEntry.from_md5sum_line(line)
            except Exception as exc:
                logger.warning(
                    "Skipping line %d in %s: %s", lineno, listing_path, exc,
                )


def read_md5sum_listing(
    listing_path: str,
    encoding: str = 'utf-8-sig',
) -> list[FileEntry]:
    """Load an entire md5sum file into a list of :class:`FileEntry` objects.

    Convenience wrapper around :func:`iter_md5sum_listing`.
    """
    return list(iter_md5sum_listing(listing_path, encoding))


# ---------------------------------------------------------------------------
# CSV listing — writing
# ---------------------------------------------------------------------------

def _generate_header_row(attr_map: dict[str, str]) -> list[str]:
    """Generate a header row from attr_map keys in column order.
    
    Parameters
    ----------
    attr_map:
        Column mapping (attribute name → column index).
    
    Returns
    -------
    list[str]
        Header row with attribute names in column order.
    """
    # Find max column index to determine row width
    max_col = max(int(idx) for idx in attr_map.values())
    header = [''] * (max_col + 1)
    
    for attr, col_idx in attr_map.items():
        header[int(col_idx)] = attr
    
    return header


def write_listing(
    output_path: str,
    entries: list[FileEntry] | Iterator[FileEntry],
    attr_map: dict[str, str] | None = None,
    encoding: str = 'utf-8',
    include_header: bool = False,
) -> int:
    """Write :class:`FileEntry` objects to a CSV listing file.

    Parameters
    ----------
    output_path:
        Destination file path.
    entries:
        An iterable (list or iterator) of :class:`FileEntry` objects.
    attr_map:
        Column mapping.  If *None*, :data:`~common.attr_map.CANONICAL_MAP`
        is used.
    encoding:
        Output file encoding.  Defaults to ``'utf-8'``.
    include_header:
        If *True*, write a header row with attribute names before data.
        Defaults to *False*.

    Returns
    -------
    int
        The number of entries written.
    """
    if attr_map is None:
        attr_map = CANONICAL_MAP

    count = 0
    with open(output_path, 'w', newline='', encoding=encoding) as fh:
        writer = csv.writer(fh)
        
        if include_header:
            header = _generate_header_row(attr_map)
            writer.writerow(header)
        
        for entry in entries:
            row = entry.to_listing_row(attr_map)
            writer.writerow(row)
            count += 1

    return count
