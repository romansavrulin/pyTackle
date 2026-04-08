"""Core FileEntry dataclass — canonical representation of a filesystem entry.

Provides factory methods for construction from CSV listing rows, md5sum lines,
and filesystem paths, plus instance methods for attribute access, copying,
filesystem application, checksum calculation, and validation.

Entry Type Handling
-------------------
The ``entry_type`` attribute stores a normalized single-character type code:

- ``'f'`` — regular file
- ``'d'`` — directory
- ``'l'`` — symbolic link

Entry types are automatically normalized during CSV parsing via
:func:`normalize_entry_type`, which accepts various input formats (e.g.,
``'file'``, ``'F'``, ``'directory'``, ``'D'``, ``'symlink'``).

Module Constants
----------------
- :const:`ENTRY_TYPE_FILE` — ``'f'``
- :const:`ENTRY_TYPE_DIR` — ``'d'``
- :const:`ENTRY_TYPE_SYMLINK` — ``'l'``
- :const:`VALID_ENTRY_TYPES` — frozenset of valid type codes
- :const:`ALL_ATTRS` — tuple of all attribute names (core + metadata)

Public Functions
----------------
- :func:`parse_datetime` — Parse datetime strings in ISO, Linux stat, or PowerShell formats
- :func:`normalize_entry_type` — Normalize entry type to single-char code
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from common.attr_map import (
    CANONICAL_MAP,
    CORE_ATTRS,
    DATETIME_ATTRS,
    METADATA_ATTRS,
    VALID_ATTRS,
)
from common import checksum
from common import fs_attrs

logger = logging.getLogger(__name__)

# Re-export grouped tuples for convenience
ALL_ATTRS: tuple[str, ...] = CORE_ATTRS + METADATA_ATTRS

# Attributes that are integers
_INT_ATTRS: frozenset[str] = frozenset(('size', 'uid', 'gid'))

# Attributes that are datetimes
_DATETIME_ATTRS: frozenset[str] = frozenset(DATETIME_ATTRS)

# Attributes that are plain strings (entry_type is handled specially)
_STR_ATTRS: frozenset[str] = frozenset(('path', 'permissions', 'checksum'))

# Attributes that are not applicable to filesystem writes — silently skipped
_NON_FS_ATTRS: frozenset[str] = frozenset(('path', 'size', 'checksum', 'entry_type'))

# Timestamp attribute names (for grouping in apply_to_fs)
_TIMESTAMP_ATTRS: frozenset[str] = frozenset(('creation', 'access', 'modify'))


# Valid entry type codes
ENTRY_TYPE_FILE = 'f'
ENTRY_TYPE_DIR = 'd'
ENTRY_TYPE_SYMLINK = 'l'
VALID_ENTRY_TYPES: frozenset[str] = frozenset((ENTRY_TYPE_FILE, ENTRY_TYPE_DIR, ENTRY_TYPE_SYMLINK))


@dataclass
class FileEntry:
    """A filesystem entry with rich metadata.

    All fields except *path* default to ``None`` (unknown / not applicable).
    """

    path: str
    size: Optional[int] = None
    creation: Optional[datetime] = None
    access: Optional[datetime] = None
    modify: Optional[datetime] = None
    permissions: Optional[str] = None   # octal string e.g. "0o755"
    uid: Optional[int] = None
    gid: Optional[int] = None
    checksum: Optional[str] = None      # "algorithm:hexdigest"
    entry_type: Optional[str] = None    # 'f' (file), 'd' (directory), 'l' (symlink)

    # ------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------

    @classmethod
    def from_listing_row(
        cls,
        cols: list[str],
        attr_map: dict[str, str],
    ) -> FileEntry:
        """Create a :class:`FileEntry` from a CSV row and an attr-map.

        *cols* is a list of string column values.  *attr_map* maps attribute
        names to column indices (as strings, e.g. ``'0'``, ``'1'``).

        Meta-selectors like ``'earliest'`` or ``'latest'`` are **not**
        supported here — use tackle-specific logic for date selection.

        Raises :exc:`ValueError` if a selector is not a valid column index
        or if ``'path'`` is not in *attr_map*.
        """
        kwargs: dict[str, Any] = {}

        for attr, selector in attr_map.items():
            if not selector.isdigit():
                raise ValueError(
                    f"Selector for {attr!r} must be a column index (digit), "
                    f"got {selector!r}. Meta-selectors like 'earliest'/'latest' "
                    f"are not supported in from_listing_row()."
                )
            idx = int(selector)
            raw = cols[idx] if idx < len(cols) else ''
            raw = raw.strip()
            if not raw:
                kwargs[attr] = None
                continue
            kwargs[attr] = _parse_value(attr, raw)

        # 'path' is required
        if 'path' not in kwargs:
            raise ValueError(
                "attr_map must include 'path' to construct a FileEntry"
            )

        return cls(**kwargs)

    @classmethod
    def from_md5sum_line(cls, line: str) -> FileEntry:
        """Create a :class:`FileEntry` from a native ``md5sum`` output line.

        Expected format::

            <hexdigest>  <path>

        (two spaces between hexdigest and path).

        Raises :exc:`ValueError` if *line* does not match.
        """
        match = re.match(r'^([0-9a-fA-F]+)\s{2}(.+)$', line.strip())
        if not match:
            raise ValueError(
                f"Line does not match md5sum format "
                f"'<hexdigest>  <path>': {line!r}"
            )
        hexdigest = match.group(1)
        path = match.group(2).strip()
        return cls(path=path, checksum=f'md5:{hexdigest}')

    @classmethod
    def from_fs_path(cls, path: str) -> FileEntry:
        """Create a :class:`FileEntry` by reading filesystem attributes.

        Calls :func:`common.fs_attrs.read_all` to populate all stat-derived
        fields.  Checksum is **not** calculated (expensive).
        """
        attrs = fs_attrs.read_all(path)
        return cls(path=path, **attrs)

    # ------------------------------------------------------------------
    # Attribute access
    # ------------------------------------------------------------------

    def get_attr(self, name: str) -> Any:
        """Return the value of attribute *name*.

        Raises :exc:`ValueError` if *name* is not a valid attribute.
        """
        if name not in VALID_ATTRS:
            raise ValueError(
                f"Unknown attribute {name!r}; "
                f"valid attributes: {', '.join(VALID_ATTRS)}"
            )
        return getattr(self, name)

    def set_attr(self, name: str, value: Any) -> None:
        """Set attribute *name* to *value*.

        Raises :exc:`ValueError` for unknown names or if *name* is
        ``'checksum'`` (use :meth:`calculate_checksum` instead).
        Accepts ``None`` to clear any attribute.
        """
        if name not in VALID_ATTRS:
            raise ValueError(
                f"Unknown attribute {name!r}; "
                f"valid attributes: {', '.join(VALID_ATTRS)}"
            )
        if name == 'checksum':
            raise ValueError(
                "Cannot set 'checksum' directly — "
                "use calculate_checksum() or recalculate_checksum() instead"
            )
        setattr(self, name, value)

    # ------------------------------------------------------------------
    # Copying attributes
    # ------------------------------------------------------------------

    def copy_attrs_from(
        self,
        other: FileEntry,
        attrs: list[str] | str = 'metadata',
    ) -> None:
        """Copy attribute values from *other* into this entry.

        *attrs* controls which attributes are copied:

        - ``'metadata'`` (default) — all :data:`METADATA_ATTRS`
        - ``'all'`` — every attribute in :data:`ALL_ATTRS`
        - a list of attribute names — only those listed

        Only non-``None`` values from *other* are copied; if the source
        attribute is ``None``, the target is left unchanged.
        """
        if attrs == 'metadata':
            attr_names = METADATA_ATTRS
        elif attrs == 'all':
            attr_names = ALL_ATTRS
        elif isinstance(attrs, list):
            for name in attrs:
                if name not in VALID_ATTRS:
                    raise ValueError(
                        f"Unknown attribute {name!r}; "
                        f"valid attributes: {', '.join(VALID_ATTRS)}"
                    )
            attr_names = tuple(attrs)
        else:
            raise TypeError(
                f"attrs must be 'metadata', 'all', or a list of names, "
                f"got {attrs!r}"
            )

        for name in attr_names:
            value = getattr(other, name)
            if value is not None:
                setattr(self, name, value)

    # ------------------------------------------------------------------
    # Filesystem application
    # ------------------------------------------------------------------

    def apply_to_fs(self, attrs: list[str] | str = 'all') -> None:
        """Apply selected attributes to the filesystem at :attr:`path`.

        *attrs* controls which attributes are applied:

        - ``'all'`` (default) — all non-``None`` attributes
        - a list of attribute names — only those listed

        Attributes that are ``None`` are silently skipped.  ``path``,
        ``size``, and ``checksum`` are not applicable to the filesystem
        and are silently skipped.
        """
        if attrs == 'all':
            attr_names = [
                name for name in ALL_ATTRS
                if name not in _NON_FS_ATTRS and getattr(self, name) is not None
            ]
        elif isinstance(attrs, list):
            attr_names = [
                name for name in attrs
                if name not in _NON_FS_ATTRS and getattr(self, name) is not None
            ]
        else:
            raise TypeError(
                f"attrs must be 'all' or a list of names, got {attrs!r}"
            )

        # Group timestamp attributes
        ts_attrs: dict[str, datetime] = {}
        for name in attr_names:
            if name in _TIMESTAMP_ATTRS:
                ts_attrs[name] = getattr(self, name)

        if ts_attrs:
            logger.debug("Applying timestamps to %s: %s", self.path, ts_attrs)
            fs_attrs.apply_timestamps(self.path, ts_attrs)

        # Permissions
        if 'permissions' in attr_names and self.permissions is not None:
            logger.debug(
                "Applying permissions %s to %s", self.permissions, self.path
            )
            fs_attrs.apply_permissions(self.path, self.permissions)

        # Ownership
        has_uid = 'uid' in attr_names
        has_gid = 'gid' in attr_names
        if has_uid or has_gid:
            uid = self.uid if has_uid else None
            gid = self.gid if has_gid else None
            logger.debug(
                "Applying ownership uid=%s gid=%s to %s", uid, gid, self.path
            )
            fs_attrs.apply_ownership(self.path, uid, gid)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(
        self,
        attrs: list[str] | None = None,
        check_fs: bool = False,
    ) -> list[str]:
        """Validate this entry against the filesystem.

        Args:
            attrs: Attributes to validate. If ``None``, only checks path
                existence.
            check_fs: If ``True``, compare attribute values against the actual
                filesystem. If ``False``, only check that *attrs* are not
                ``None`` in this entry.

        Returns:
            A list of validation error strings. An empty list means the entry
            is valid.

        Examples::

            # Check path exists
            errors = fe.validate()

            # Check path exists and timestamps are set
            errors = fe.validate(['creation', 'modify'])

            # Verify timestamps match filesystem
            errors = fe.validate(['creation', 'modify'], check_fs=True)

            # Verify checksum matches file content
            errors = fe.validate(['checksum'], check_fs=True)
        """
        errors: list[str] = []

        # Check path existence
        if not os.path.exists(self.path):
            errors.append(f"path does not exist: {self.path}")
            return errors  # Cannot check further without the file

        if not attrs:
            return errors

        if check_fs:
            # Compare against actual filesystem values
            try:
                fs_entry = FileEntry.from_fs_path(self.path)
            except OSError as exc:
                errors.append(f"cannot read filesystem attributes: {exc}")
                return errors

            for attr in attrs:
                my_val = getattr(self, attr, None)

                if my_val is None:
                    errors.append(f"{attr}: not set in entry")
                    continue

                if attr == 'checksum':
                    # Checksum needs special handling — calculate on demand
                    if ':' in my_val:
                        algo, expected = my_val.split(':', 1)
                    else:
                        algo, expected = 'md5', my_val
                    try:
                        fs_digest = fs_entry.calculate_checksum(algorithm=algo)
                        if fs_digest != expected:
                            errors.append(
                                f"checksum mismatch: expected {expected}, "
                                f"got {fs_digest}"
                            )
                    except OSError as exc:
                        errors.append(f"checksum calculation failed: {exc}")
                else:
                    fs_val = getattr(fs_entry, attr, None)
                    if my_val != fs_val:
                        errors.append(
                            f"{attr} mismatch: entry={my_val!r}, fs={fs_val!r}"
                        )
        else:
            # Just check that attrs are not None
            for attr in attrs:
                if getattr(self, attr, None) is None:
                    errors.append(f"{attr}: not set in entry")

        return errors

    # ------------------------------------------------------------------
    # Checksum
    # ------------------------------------------------------------------

    def calculate_checksum(
        self,
        algorithm: str = 'md5',
        utility: str | None = None,
    ) -> str:
        """Return the hexdigest, using a cached value if available.

        If :attr:`checksum` is already set and its algorithm prefix matches
        *algorithm*, the cached hexdigest is returned without recalculation.
        Otherwise the checksum is computed, stored as
        ``"<algorithm>:<hexdigest>"``, and the hexdigest returned.
        """
        prefix = algorithm + ':'
        if self.checksum is not None and self.checksum.startswith(prefix):
            hexdigest = self.checksum[len(prefix):]
            logger.debug(
                "Returning cached %s checksum for %s: %s",
                algorithm, self.path, hexdigest,
            )
            return hexdigest

        return self._compute_and_store(algorithm, utility)

    def recalculate_checksum(
        self,
        algorithm: str = 'md5',
        utility: str | None = None,
    ) -> str:
        """Always recalculate the checksum, ignoring any cached value.

        Stores the result and returns the hexdigest.
        """
        return self._compute_and_store(algorithm, utility)

    def _compute_and_store(
        self,
        algorithm: str,
        utility: str | None,
    ) -> str:
        """Compute checksum, store it, and return the hexdigest."""
        hexdigest = checksum.calculate(self.path, algorithm, utility)
        self.checksum = f'{algorithm}:{hexdigest}'
        logger.debug(
            "Computed %s checksum for %s: %s",
            algorithm, self.path, hexdigest,
        )
        return hexdigest

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_listing_row(
        self,
        attr_map: dict[str, str] | None = None,
    ) -> list[str]:
        """Serialise this entry to a list of column strings.

        If *attr_map* is ``None``, :data:`~common.attr_map.CANONICAL_MAP`
        is used.  Each attribute value is formatted and placed at the
        column index specified by the map.
        """
        if attr_map is None:
            attr_map = CANONICAL_MAP

        # Determine the number of columns needed
        max_col = max(
            (int(v) for v in attr_map.values() if v.isdigit()),
            default=-1,
        )
        row = [''] * (max_col + 1)

        for attr, selector in attr_map.items():
            if not selector.isdigit():
                continue
            idx = int(selector)
            value = getattr(self, attr, None)
            row[idx] = _format_value(value)

        return row


# ----------------------------------------------------------------------
# Module-level helpers
# ----------------------------------------------------------------------

# Regex for Linux-style timestamps: 2020-08-20 06:15:03.491092220 +0000
_RE_LINUX_TS = re.compile(
    r'(\d{4}-\d{2}-\d{2})\s+'
    r'(\d{2}:\d{2}:\d{2})'
    r'\.(\d+)\s+'
    r'([+-]\d{4})'
)

# Regex for PowerShell-style timestamps: 02/24/2023 14:04:32
_RE_POWERSHELL_TS = re.compile(
    r'\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}:\d{2}'
)


def parse_datetime(raw: str) -> datetime:
    """Parse a datetime string using a fallback chain of formats.

    Supported formats (tried in order):

    1. **ISO 8601** — ``2024-06-15T12:00:00+00:00`` or any string accepted
       by :meth:`datetime.fromisoformat`.
    2. **Linux stat-style** — ``2020-08-20 06:15:03.491092220 +0000``.
       Nanosecond fractional seconds are truncated to microseconds (6 digits).
       The ``+HHMM`` timezone offset produces a tz-aware datetime.
    3. **PowerShell-style** — ``02/24/2023 14:04:32`` (``MM/DD/YYYY HH:MM:SS``).
       Parsed as **UTC** (tz-aware).

    Returns a :class:`datetime` object.  Raises :exc:`ValueError` if none of
    the formats match.
    """
    raw = raw.strip()

    # --- Attempt 1: ISO 8601 ---
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        pass

    # --- Attempt 2: Linux stat-style with nanoseconds + tz offset ---
    m = _RE_LINUX_TS.match(raw)
    if m:
        date_part, time_part, frac, tz_offset = m.groups()
        # Truncate nanoseconds to microseconds (max 6 digits)
        micro = frac[:6].ljust(6, '0')
        iso = f'{date_part} {time_part}.{micro} {tz_offset}'
        return datetime.strptime(iso, '%Y-%m-%d %H:%M:%S.%f %z')

    # --- Attempt 3: PowerShell-style MM/DD/YYYY HH:MM:SS (assumed UTC) ---
    if _RE_POWERSHELL_TS.match(raw):
        dt = datetime.strptime(raw, '%m/%d/%Y %H:%M:%S')
        return dt.replace(tzinfo=timezone.utc)

    raise ValueError(
        f'Cannot parse datetime: {raw!r}. '
        f'Expected ISO 8601, Linux stat-style '
        f'(YYYY-MM-DD HH:MM:SS.nnnnnnnnn +HHMM), '
        f'or PowerShell-style (MM/DD/YYYY HH:MM:SS).'
    )


def normalize_entry_type(raw: str | None) -> str | None:
    """Normalize entry type to single-char code: f, d, or l.

    Accepts various formats from listing files:
    - f, F, file → f
    - d, D, directory → d
    - l, L, symlink, link → l

    Returns None if input is None or empty.
    """
    if raw is None:
        return None
    raw = raw.strip().lower()
    if not raw:
        return None
    if raw in ('f', 'file'):
        return 'f'
    if raw in ('d', 'directory'):
        return 'd'
    if raw in ('l', 'symlink', 'link'):
        return 'l'
    # Unknown format — return first char
    return raw[0] if raw else None


def _parse_value(attr: str, raw: str) -> Any:
    """Parse a raw string *raw* into the appropriate Python type for *attr*."""
    if attr in _INT_ATTRS:
        return int(raw)
    if attr in _DATETIME_ATTRS:
        return parse_datetime(raw)
    if attr == 'entry_type':
        return normalize_entry_type(raw)
    # str attrs: path, permissions, checksum
    return raw


def _format_value(value: Any) -> str:
    """Format a Python value for CSV serialisation."""
    if value is None:
        return ''
    if isinstance(value, datetime):
        # Always include microseconds (6 digits) for consistent output
        return value.isoformat(timespec='microseconds')
    if isinstance(value, int):
        return str(value)
    return str(value)
