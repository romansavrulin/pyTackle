"""Core FileEntry dataclass — canonical representation of a filesystem entry.

Provides factory methods for construction from CSV listing rows, md5sum lines,
and filesystem paths, plus instance methods for attribute access, copying,
filesystem application, and checksum calculation.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
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

# Attributes that are plain strings
_STR_ATTRS: frozenset[str] = frozenset(('path', 'permissions', 'checksum'))

# Attributes that are not applicable to filesystem writes — silently skipped
_NON_FS_ATTRS: frozenset[str] = frozenset(('path', 'size', 'checksum'))

# Timestamp attribute names (for grouping in apply_to_fs)
_TIMESTAMP_ATTRS: frozenset[str] = frozenset(('creation', 'access', 'modify'))


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
        names to selectors — either a 0-based column index (as a string) or
        a meta-selector (``'earliest'`` / ``'latest'``) for datetime attrs.
        """
        kwargs: dict[str, Any] = {}

        # First pass: resolve all column-index selectors so we can collect
        # datetime values for meta-selectors.
        resolved_datetimes: dict[str, datetime] = {}

        for attr, selector in attr_map.items():
            if selector.isdigit():
                idx = int(selector)
                raw = cols[idx] if idx < len(cols) else ''
                raw = raw.strip()
                if not raw:
                    kwargs[attr] = None
                    continue
                kwargs[attr] = _parse_value(attr, raw)
                # Track resolved datetimes for meta-selectors
                if attr in _DATETIME_ATTRS and kwargs[attr] is not None:
                    resolved_datetimes[attr] = kwargs[attr]

        # Second pass: resolve meta-selectors (earliest / latest)
        for attr, selector in attr_map.items():
            if selector in ('earliest', 'latest'):
                if not resolved_datetimes:
                    kwargs[attr] = None
                    continue
                if selector == 'earliest':
                    kwargs[attr] = min(resolved_datetimes.values())
                else:
                    kwargs[attr] = max(resolved_datetimes.values())

        # 'path' is required — fall back to empty string if missing
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

def _parse_value(attr: str, raw: str) -> Any:
    """Parse a raw string *raw* into the appropriate Python type for *attr*."""
    if attr in _INT_ATTRS:
        return int(raw)
    if attr in _DATETIME_ATTRS:
        return datetime.fromisoformat(raw)
    # str attrs: path, permissions, checksum
    return raw


def _format_value(value: Any) -> str:
    """Format a Python value for CSV serialisation."""
    if value is None:
        return ''
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, int):
        return str(value)
    return str(value)
