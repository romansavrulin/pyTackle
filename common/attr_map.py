"""Attr-map parsing, column mapping constants, and meta-selectors.

Generalises the ``--attr-map`` parsing originally found in
:pymod:`tackles.ValidateCopy` to support all ten canonical
:class:`~common.FileEntry.FileEntry` attributes.
"""

from __future__ import annotations

from typing import Tuple

# ---------------------------------------------------------------------------
# Attribute name constants
# ---------------------------------------------------------------------------

# All valid attribute names for FileEntry
VALID_ATTRS: tuple[str, ...] = (
    'path', 'size', 'creation', 'access', 'modify',
    'permissions', 'uid', 'gid', 'checksum', 'entry_type',
)

# Core attributes — define file identity, not copyable by default
CORE_ATTRS: tuple[str, ...] = ('path', 'checksum', 'size', 'entry_type')

# Metadata attributes — transferable between entries
METADATA_ATTRS: tuple[str, ...] = (
    'creation', 'access', 'modify', 'permissions', 'uid', 'gid',
)

# Datetime attributes (eligible for meta-selectors earliest/latest)
DATETIME_ATTRS: tuple[str, ...] = ('creation', 'access', 'modify')

# ---------------------------------------------------------------------------
# Meta-selectors
# ---------------------------------------------------------------------------

# Meta-selectors for datetime attributes
META_SELECTORS: tuple[str, ...] = ('earliest', 'latest')
_SELECTOR_ALIASES: dict[str, str] = {'e': 'earliest', 'l': 'latest'}

# ---------------------------------------------------------------------------
# Canonical column mapping (10 columns, path LAST — column 9)
#
# Order: timestamps first, then checksum/entry_type, then ownership/perms,
# then size, and finally path.
# ---------------------------------------------------------------------------

CANONICAL_MAP: dict[str, str] = {
    'creation': '0',
    'access': '1',
    'modify': '2',
    'checksum': '3',
    'entry_type': '4',
    'permissions': '5',
    'uid': '6',
    'gid': '7',
    'size': '8',
    'path': '9',
}

# Canonical header row (matches CANONICAL_MAP key order)
CANONICAL_HEADER: Tuple[str, ...] = (
    'creation', 'access', 'modify', 'checksum', 'entry_type',
    'permissions', 'uid', 'gid', 'size', 'path',
)


# ---------------------------------------------------------------------------
# Canonical map helpers
# ---------------------------------------------------------------------------

def get_canonical_timestamp_map() -> dict[str, str]:
    """Return canonical mapping for datetime attributes only.

    Returns:
        Dict mapping 'creation', 'access', 'modify' to their canonical column indices.
    """
    return {attr: CANONICAL_MAP[attr] for attr in DATETIME_ATTRS}


def get_canonical_all_map() -> dict[str, str]:
    """Return canonical mapping for all attributes.

    Returns:
        Dict mapping all attributes to their canonical column indices.
    """
    return CANONICAL_MAP.copy()


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_attr_map(raw: str, *, allow_empty: bool = False) -> dict[str, str]:
    """Parse an ``--attr-map`` string into an ``{attr_name: selector}`` dict.

    *raw* is a comma-separated list of ``attr:selector`` pairs, e.g.
    ``"creation:1, access:2, modify:earliest"`` or using short aliases
    ``"creation:e, modify:l"``.

    Each *selector* is either:

    * a **0-based column index** (non-negative integer, as a string) — valid
      for every attribute, or
    * one of the **meta-selectors** ``earliest`` (alias ``e``) /
      ``latest`` (alias ``l``) — valid **only** for datetime attributes
      (``creation``, ``access``, ``modify``).

    Aliases are expanded to their canonical form in the returned dict.

    Raises :exc:`ValueError` for:
    * missing ``:`` separator in a token
    * unknown attribute name
    * meta-selector used on a non-datetime attribute
    * selector that is neither a non-negative integer nor a meta-selector
    * empty result (no valid pairs parsed)
    """
    attr_map: dict[str, str] = {}

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

        # Expand short aliases (e → earliest, l → latest)
        selector = _SELECTOR_ALIASES.get(selector, selector)

        if selector in META_SELECTORS:
            # Meta-selectors are only valid for datetime attributes
            if attr not in DATETIME_ATTRS:
                raise ValueError(
                    f'Meta-selector {selector!r} is only valid for datetime '
                    f'attributes ({", ".join(DATETIME_ATTRS)}), '
                    f'not {attr!r}'
                )
        else:
            # Must be a non-negative integer (0-based column index)
            try:
                idx = int(selector)
            except ValueError:
                raise ValueError(
                    f'Invalid selector {selector!r} for attribute {attr!r}; '
                    f'expected a 0-based column index or one of: '
                    f'{", ".join(META_SELECTORS)} (aliases: '
                    f'{", ".join(f"{k}={v}" for k, v in _SELECTOR_ALIASES.items())})'
                ) from None
            if idx < 0:
                raise ValueError(
                    f'Column index must be non-negative, got {idx} '
                    f'for attribute {attr!r}'
                )

        attr_map[attr] = selector

    if not attr_map and not allow_empty:
        raise ValueError('--attr-map produced an empty mapping')

    return attr_map


# ---------------------------------------------------------------------------
# +/- modifier parsing for --attrs
# ---------------------------------------------------------------------------

def parse_attrs_with_modifiers(
    attrs_str: str | None,
    defaults: set[str],
) -> set[str]:
    """Parse an --attrs string with optional +/- modifier notation.

    Supports two modes:

    1. **Explicit mode**: Simple comma-separated list replaces defaults entirely.
       Example: ``"size,creation,checksum"`` → ``{'size', 'creation', 'checksum'}``

    2. **Modifier mode**: Tokens prefixed with ``+`` or ``-`` modify the default set.
       Example: ``"+access,-checksum"`` → defaults + access - checksum

    The mode is auto-detected:
    - If ALL tokens start with ``+`` or ``-``, modifier mode is used
    - Otherwise, explicit mode is used

    Args:
        attrs_str: Comma-separated attribute specification string, or None.
        defaults: Default attribute set to start from (used when attrs_str is None
            or in modifier mode).

    Returns:
        Set of attribute names after applying the specification.

    Raises:
        ValueError: If an attribute name is unknown or if the result is empty.

    Examples::

        >>> defaults = {'size', 'creation', 'checksum'}
        >>> parse_attrs_with_modifiers(None, defaults)
        {'size', 'creation', 'checksum'}

        >>> parse_attrs_with_modifiers('path,size', defaults)
        {'path', 'size'}

        >>> parse_attrs_with_modifiers('+access', defaults)
        {'size', 'creation', 'checksum', 'access'}

        >>> parse_attrs_with_modifiers('-checksum', defaults)
        {'size', 'creation'}

        >>> parse_attrs_with_modifiers('+access,-checksum', defaults)
        {'size', 'creation', 'access'}
    """
    # Return defaults if attrs_str is None or empty
    if attrs_str is None or not attrs_str.strip():
        result = set(defaults)
        if not result:
            raise ValueError('--attrs produced an empty attribute set')
        return result

    tokens = [t.strip() for t in attrs_str.split(',') if t.strip()]

    if not tokens:
        return set(defaults)

    # Detect mode: all tokens must have +/- prefix for modifier mode
    all_have_prefix = all(t.startswith('+') or t.startswith('-') for t in tokens)

    if all_have_prefix:
        # Modifier mode: start with defaults, apply changes
        result = set(defaults)
        for token in tokens:
            if token.startswith('+'):
                attr = token[1:]
                if attr not in VALID_ATTRS:
                    raise ValueError(
                        f"Unknown attribute {attr!r} in --attrs; "
                        f"valid attributes: {', '.join(VALID_ATTRS)}"
                    )
                result.add(attr)
            elif token.startswith('-'):
                attr = token[1:]
                if attr not in VALID_ATTRS:
                    raise ValueError(
                        f"Unknown attribute {attr!r} in --attrs; "
                        f"valid attributes: {', '.join(VALID_ATTRS)}"
                    )
                result.discard(attr)  # No error if already absent
    else:
        # Explicit mode: use tokens as-is
        result = set()
        for token in tokens:
            attr = token.lstrip('+-')  # Strip any accidental prefix
            if attr not in VALID_ATTRS:
                raise ValueError(
                    f"Unknown attribute {attr!r} in --attrs; "
                    f"valid attributes: {', '.join(VALID_ATTRS)}"
                )
            result.add(attr)

    if not result:
        raise ValueError('--attrs produced an empty attribute set')

    return result
