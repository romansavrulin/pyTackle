"""Attr-map parsing, column mapping constants, and meta-selectors.

Generalises the ``--attr-map`` parsing originally found in
:pymod:`tackles.SetCreationTime` to support all nine canonical
:class:`~common.FileEntry.FileEntry` attributes.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Attribute name constants
# ---------------------------------------------------------------------------

# All valid attribute names for FileEntry
VALID_ATTRS: tuple[str, ...] = (
    'path', 'size', 'creation', 'access', 'modify',
    'permissions', 'uid', 'gid', 'checksum',
)

# Core attributes — define file identity, not copyable by default
CORE_ATTRS: tuple[str, ...] = ('path', 'checksum', 'size')

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
# Canonical column mapping (path LAST — column 8)
# ---------------------------------------------------------------------------

CANONICAL_MAP: dict[str, str] = {
    'size': '0',
    'creation': '1',
    'access': '2',
    'modify': '3',
    'permissions': '4',
    'uid': '5',
    'gid': '6',
    'checksum': '7',
    'path': '8',
}


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_attr_map(raw: str) -> dict[str, str]:
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

    if not attr_map:
        raise ValueError('--attr-map produced an empty mapping')

    return attr_map
