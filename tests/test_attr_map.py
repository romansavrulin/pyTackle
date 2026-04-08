"""Tests for common/attr_map.py."""

from __future__ import annotations

import pytest

from common.attr_map import (
    CANONICAL_MAP,
    CORE_ATTRS,
    DATETIME_ATTRS,
    METADATA_ATTRS,
    VALID_ATTRS,
    get_canonical_all_map,
    get_canonical_timestamp_map,
    parse_attr_map,
)


# ------------------------------------------------------------------
# Constants
# ------------------------------------------------------------------

class TestConstants:
    """Verify the module-level constant tuples and dicts."""

    def test_canonical_map_has_all_ten_attrs(self):
        # All 10 attrs are now in CANONICAL_MAP including entry_type
        assert len(CANONICAL_MAP) == 10
        for attr in VALID_ATTRS:
            assert attr in CANONICAL_MAP

    def test_path_is_column_9(self):
        # path is now the last column (column 9)
        assert CANONICAL_MAP["path"] == "9"

    def test_entry_type_is_column_4(self):
        # entry_type is now column 4 (after timestamps and checksum)
        assert CANONICAL_MAP["entry_type"] == "4"

    def test_core_attrs(self):
        assert set(CORE_ATTRS) == {"path", "checksum", "size", "entry_type"}

    def test_metadata_attrs(self):
        assert set(METADATA_ATTRS) == {
            "creation", "access", "modify", "permissions", "uid", "gid",
        }

    def test_datetime_attrs(self):
        assert set(DATETIME_ATTRS) == {"creation", "access", "modify"}

    def test_valid_attrs_has_ten(self):
        # 9 original + entry_type
        assert len(VALID_ATTRS) == 10


# ------------------------------------------------------------------
# parse_attr_map — valid inputs
# ------------------------------------------------------------------

class TestParseAttrMapValid:
    """Happy-path tests for parse_attr_map()."""

    def test_single_attr(self):
        result = parse_attr_map("path:0")
        assert result == {"path": "0"}

    def test_multiple_attrs(self):
        result = parse_attr_map("path:0, size:1, creation:2")
        assert result == {"path": "0", "size": "1", "creation": "2"}

    def test_all_ten_attrs(self):
        raw = ", ".join(f"{attr}:{idx}" for idx, attr in enumerate(VALID_ATTRS))
        result = parse_attr_map(raw)
        assert len(result) == 10
        for idx, attr in enumerate(VALID_ATTRS):
            assert result[attr] == str(idx)


# ------------------------------------------------------------------
# parse_attr_map — meta-selectors
# ------------------------------------------------------------------

class TestParseAttrMapMetaSelectors:
    """Tests for earliest/latest meta-selectors and aliases."""

    def test_earliest_selector(self):
        result = parse_attr_map("creation:earliest")
        assert result == {"creation": "earliest"}

    def test_latest_selector(self):
        result = parse_attr_map("modify:latest")
        assert result == {"modify": "latest"}

    def test_alias_e(self):
        result = parse_attr_map("access:e")
        assert result == {"access": "earliest"}

    def test_alias_l(self):
        result = parse_attr_map("creation:l")
        assert result == {"creation": "latest"}

    @pytest.mark.parametrize("attr", ["size", "path", "permissions", "uid", "gid", "checksum"])
    def test_meta_selector_rejected_for_non_datetime(self, attr):
        with pytest.raises(ValueError, match="only valid for datetime"):
            parse_attr_map(f"{attr}:earliest")

    @pytest.mark.parametrize("attr", ["size", "path", "permissions", "uid", "gid", "checksum"])
    def test_meta_selector_latest_rejected_for_non_datetime(self, attr):
        with pytest.raises(ValueError, match="only valid for datetime"):
            parse_attr_map(f"{attr}:latest")


# ------------------------------------------------------------------
# parse_attr_map — error cases
# ------------------------------------------------------------------

class TestParseAttrMapErrors:
    """Error-handling tests for parse_attr_map()."""

    def test_unknown_attr_name(self):
        with pytest.raises(ValueError, match="Unknown attribute"):
            parse_attr_map("bogus:0")

    def test_missing_colon(self):
        with pytest.raises(ValueError, match='expected "attr:selector"'):
            parse_attr_map("path0")

    def test_empty_string(self):
        with pytest.raises(ValueError, match="empty mapping"):
            parse_attr_map("")

    def test_empty_string_allowed_with_allow_empty(self):
        result = parse_attr_map("", allow_empty=True)
        assert result == {}

    def test_whitespace_only_allowed_with_allow_empty(self):
        result = parse_attr_map("   ", allow_empty=True)
        assert result == {}

    def test_negative_index(self):
        with pytest.raises(ValueError, match="non-negative"):
            parse_attr_map("path:-1")

    def test_non_integer_selector_for_non_datetime(self):
        with pytest.raises(ValueError, match="Invalid selector"):
            parse_attr_map("size:abc")


# ------------------------------------------------------------------
# get_canonical_timestamp_map
# ------------------------------------------------------------------

class TestGetCanonicalTimestampMap:
    """Tests for get_canonical_timestamp_map()."""

    def test_returns_datetime_attrs_only(self):
        result = get_canonical_timestamp_map()
        assert set(result.keys()) == {"creation", "access", "modify"}

    def test_uses_canonical_column_indices(self):
        result = get_canonical_timestamp_map()
        assert result["creation"] == "0"
        assert result["access"] == "1"
        assert result["modify"] == "2"

    def test_returns_new_dict_each_time(self):
        result1 = get_canonical_timestamp_map()
        result2 = get_canonical_timestamp_map()
        assert result1 == result2
        assert result1 is not result2


# ------------------------------------------------------------------
# get_canonical_all_map
# ------------------------------------------------------------------

class TestGetCanonicalAllMap:
    """Tests for get_canonical_all_map()."""

    def test_returns_all_attrs(self):
        result = get_canonical_all_map()
        assert len(result) == 10
        for attr in VALID_ATTRS:
            assert attr in result

    def test_matches_canonical_map(self):
        result = get_canonical_all_map()
        assert result == CANONICAL_MAP

    def test_returns_copy_not_reference(self):
        result = get_canonical_all_map()
        assert result == CANONICAL_MAP
        assert result is not CANONICAL_MAP
