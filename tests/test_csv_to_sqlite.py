"""Tests for tackles/CsvToSqlite.py."""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path
from typing import Callable

import pytest

from tackles.CsvToSqlite import (
    ColumnState,
    _coerce,
    _is_datetime,
    _is_float,
    _is_int,
    _quote,
    _sanitize_column_names,
    _to_float,
    csv_to_sqlite,
)


# ===========================================================================
# 1. Type Detection Predicate Tests
# ===========================================================================


class TestIsDatetime:
    """Tests for _is_datetime() predicate."""

    def test_iso_date_only(self):
        """ISO date without time is valid."""
        assert _is_datetime("2024-06-15") is True

    def test_iso_datetime(self):
        """ISO datetime is valid."""
        assert _is_datetime("2024-06-15T12:00:00") is True

    def test_iso_datetime_with_z(self):
        """ISO datetime with Z suffix is valid."""
        assert _is_datetime("2024-06-15T12:00:00Z") is True

    def test_iso_datetime_with_offset(self):
        """ISO datetime with timezone offset is valid."""
        assert _is_datetime("2024-06-15T12:00:00+05:30") is True
        assert _is_datetime("2024-06-15T12:00:00-08:00") is True

    def test_iso_datetime_with_microseconds(self):
        """ISO datetime with microseconds is valid."""
        assert _is_datetime("2024-06-15T12:00:00.123456") is True
        assert _is_datetime("2024-06-15T12:00:00.123456Z") is True
        assert _is_datetime("2024-06-15T12:00:00.123456+00:00") is True

    def test_invalid_datetime_plain_text(self):
        """Plain text is not a datetime."""
        assert _is_datetime("hello") is False

    def test_invalid_datetime_number(self):
        """Number string is not a datetime."""
        assert _is_datetime("12345") is False

    def test_invalid_datetime_partial(self):
        """Partial date is not valid."""
        assert _is_datetime("2024-06") is False

    def test_invalid_datetime_wrong_format(self):
        """Wrong format is not valid."""
        assert _is_datetime("06/15/2024") is False


class TestIsInt:
    """Tests for _is_int() predicate."""

    def test_positive_int(self):
        """Positive integers are valid."""
        assert _is_int("42") is True
        assert _is_int("0") is True
        assert _is_int("999999") is True

    def test_negative_int(self):
        """Negative integers are valid."""
        assert _is_int("-100") is True
        assert _is_int("-1") is True

    def test_positive_sign(self):
        """Explicit positive sign is valid."""
        assert _is_int("+5") is True

    def test_invalid_int_float(self):
        """Floats are not integers."""
        assert _is_int("1.5") is False
        assert _is_int("1,5") is False

    def test_invalid_int_text(self):
        """Text is not an integer."""
        assert _is_int("hello") is False

    def test_invalid_int_mixed(self):
        """Mixed content is not an integer."""
        assert _is_int("123abc") is False


class TestIsFloat:
    """Tests for _is_float() predicate."""

    def test_point_decimal(self):
        """Point-separated decimals are valid."""
        assert _is_float("1.23") is True
        assert _is_float("0.5") is True
        assert _is_float("-3.14") is True

    def test_comma_decimal(self):
        """Comma-separated decimals (European format) are valid."""
        assert _is_float("1,23") is True
        assert _is_float("0,5") is True
        assert _is_float("-3,14") is True

    def test_integer_as_float(self):
        """Integers are also valid floats."""
        assert _is_float("42") is True
        assert _is_float("-100") is True

    def test_invalid_float_text(self):
        """Text is not a float."""
        assert _is_float("hello") is False

    def test_invalid_float_multiple_separators(self):
        """Multiple separators are invalid."""
        assert _is_float("1.2.3") is False
        assert _is_float("1,2,3") is False


class TestToFloat:
    """Tests for _to_float() conversion function."""

    def test_point_decimal(self):
        """Convert point-separated decimal."""
        assert _to_float("1.23") == 1.23

    def test_comma_decimal(self):
        """Convert comma-separated decimal."""
        assert _to_float("1,23") == 1.23

    def test_integer(self):
        """Convert integer string."""
        assert _to_float("42") == 42.0


# ===========================================================================
# 2. Column Name Sanitization Tests
# ===========================================================================


class TestSanitizeColumnNames:
    """Tests for _sanitize_column_names() function."""

    def test_simple_names(self):
        """Simple alphanumeric names are preserved."""
        result = _sanitize_column_names(["name", "age", "email"])
        assert result == ["name", "age", "email"]

    def test_spaces_replaced(self):
        """Spaces are replaced with underscores."""
        result = _sanitize_column_names(["First Name", "Last Name"])
        assert result == ["First_Name", "Last_Name"]

    def test_special_chars_replaced(self):
        """Special characters are replaced with underscores."""
        result = _sanitize_column_names(["price ($)", "email@domain"])
        assert result == ["price", "email_domain"]

    def test_consecutive_underscores_collapsed(self):
        """Consecutive underscores are collapsed."""
        result = _sanitize_column_names(["a   b", "x---y"])
        assert result == ["a_b", "x_y"]

    def test_leading_trailing_underscores_stripped(self):
        """Leading and trailing underscores are stripped."""
        result = _sanitize_column_names(["_name_", "__value__"])
        assert result == ["name", "value"]

    def test_digit_starting_name_prefixed(self):
        """Names starting with digit are prefixed."""
        result = _sanitize_column_names(["123abc", "1st_place"])
        assert result == ["_123abc", "_1st_place"]

    def test_empty_name_becomes_col_n(self):
        """Empty names become col_N."""
        result = _sanitize_column_names(["___", ""])
        assert result == ["col_0", "col_1"]

    def test_collision_fallback_to_col_n(self):
        """Name collisions fall back to col_N."""
        result = _sanitize_column_names(["name", "name", "name"])
        assert result == ["name", "col_1", "col_2"]

    def test_collision_after_sanitization(self):
        """Collisions after sanitization fall back to col_N."""
        result = _sanitize_column_names(["first_name", "first name"])
        assert result == ["first_name", "col_1"]

    def test_unicode_chars_replaced(self):
        """Unicode characters are replaced."""
        result = _sanitize_column_names(["créé", "données"])
        assert result == ["cr", "donn_es"]


# ===========================================================================
# 3. ColumnState Tests
# ===========================================================================


class TestColumnState:
    """Tests for ColumnState class."""

    def test_initial_state_all_types_possible(self):
        """Initial state has all types possible."""
        state = ColumnState("col", "col")
        assert "DATETIME" in state._possible
        assert "INTEGER" in state._possible
        assert "REAL" in state._possible
        assert "TEXT" in state._possible

    def test_feed_datetime_preserves_datetime(self):
        """Feeding datetime values preserves DATETIME type."""
        state = ColumnState("col", "col")
        state.feed("2024-06-15T12:00:00Z")
        state.feed("2024-06-16T13:00:00+00:00")
        assert state.sql_type == "DATETIME"

    def test_feed_int_preserves_integer(self):
        """Feeding integer values preserves INTEGER type."""
        state = ColumnState("col", "col")
        state.feed("42")
        state.feed("-100")
        assert state.sql_type == "INTEGER"

    def test_feed_float_eliminates_datetime_int(self):
        """Feeding float values eliminates DATETIME and INTEGER."""
        state = ColumnState("col", "col")
        state.feed("1.5")
        assert state.sql_type == "REAL"
        assert "DATETIME" not in state._possible
        assert "INTEGER" not in state._possible

    def test_feed_text_eliminates_all_but_text(self):
        """Feeding text values eliminates all but TEXT."""
        state = ColumnState("col", "col")
        state.feed("hello world")
        assert state.sql_type.startswith("TEXT")

    def test_empty_values_dont_constrain(self):
        """Empty values don't constrain type."""
        state = ColumnState("col", "col")
        state.feed("")
        state.feed("   ")
        assert state.sql_type == "DATETIME"  # Most specific still available

    def test_max_len_tracked(self):
        """Maximum length is tracked."""
        state = ColumnState("col", "col")
        state.feed("short")
        state.feed("much longer string")
        assert state.max_len == 18

    def test_text_type_includes_length(self):
        """TEXT type includes max length."""
        state = ColumnState("col", "col")
        state.feed("hello world")
        assert state.sql_type == "TEXT(11)"

    def test_mixed_int_and_float_becomes_real(self):
        """Mixing integers and floats results in REAL."""
        state = ColumnState("col", "col")
        state.feed("42")
        state.feed("3.14")
        assert state.sql_type == "REAL"


# ===========================================================================
# 4. SQL Quoting Tests
# ===========================================================================


class TestQuote:
    """Tests for _quote() SQL identifier quoting."""

    def test_simple_name(self):
        """Simple name is quoted."""
        assert _quote("name") == '"name"'

    def test_name_with_spaces(self):
        """Name with spaces is quoted."""
        assert _quote("first name") == '"first name"'

    def test_name_with_embedded_quotes(self):
        """Embedded quotes are escaped."""
        assert _quote('say "hello"') == '"say ""hello"""'


# ===========================================================================
# 5. Coercion Tests
# ===========================================================================


class TestCoerce:
    """Tests for _coerce() value conversion."""

    def test_coerce_empty_to_none(self):
        """Empty value becomes None."""
        assert _coerce("", "TEXT") is None
        assert _coerce("   ", "TEXT") is None

    def test_coerce_datetime(self):
        """DATETIME normalizes Z to +00:00."""
        assert _coerce("2024-06-15T12:00:00Z", "DATETIME") == "2024-06-15T12:00:00+00:00"

    def test_coerce_integer(self):
        """INTEGER converts to int."""
        assert _coerce("42", "INTEGER") == 42
        assert _coerce("-100", "INTEGER") == -100

    def test_coerce_real(self):
        """REAL converts to float."""
        assert _coerce("3.14", "REAL") == 3.14
        assert _coerce("1,23", "REAL") == 1.23

    def test_coerce_text(self):
        """TEXT returns string as-is."""
        assert _coerce("hello", "TEXT") == "hello"
        assert _coerce("hello", "TEXT(10)") == "hello"


# ===========================================================================
# 6. Integration Tests - Fixtures
# ===========================================================================


@pytest.fixture
def temp_csv(tmp_path) -> Callable:
    """Factory fixture to create temporary CSV files."""
    def _make_csv(headers: list[str], rows: list[list[str]], name: str = "test.csv") -> Path:
        path = tmp_path / name
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            writer.writerows(rows)
        return path
    return _make_csv


@pytest.fixture
def temp_db(tmp_path) -> Path:
    """Provide a temporary SQLite database path."""
    return tmp_path / "test.db"


# ===========================================================================
# 7. Integration Tests - Basic Import
# ===========================================================================


class TestBasicImport:
    """Tests for basic CSV to SQLite import."""

    def test_simple_csv_import(self, temp_csv, temp_db):
        """Simple CSV imports correctly."""
        csv_path = temp_csv(
            ["name", "age"],
            [["Alice", "30"], ["Bob", "25"]]
        )
        
        inserted, skipped = csv_to_sqlite(csv_path, temp_db)
        
        assert inserted == 2
        assert skipped == 0
        
        conn = sqlite3.connect(temp_db)
        rows = conn.execute("SELECT name, age FROM test ORDER BY name").fetchall()
        conn.close()
        
        assert rows == [("Alice", 30), ("Bob", 25)]

    def test_type_detection(self, temp_csv, temp_db):
        """Types are detected correctly."""
        csv_path = temp_csv(
            ["timestamp", "count", "price", "name"],
            [
                ["2024-06-15T12:00:00Z", "42", "9.99", "Widget"],
                ["2024-06-16T13:00:00Z", "10", "19.99", "Gadget"],
            ]
        )
        
        csv_to_sqlite(csv_path, temp_db)
        
        conn = sqlite3.connect(temp_db)
        cursor = conn.execute("PRAGMA table_info(test)")
        columns = {row[1]: row[2] for row in cursor.fetchall()}
        conn.close()
        
        assert columns["timestamp"] == "DATETIME"
        assert columns["count"] == "INTEGER"
        assert columns["price"] == "REAL"
        assert columns["name"].startswith("TEXT")

    def test_empty_csv_header_only(self, temp_csv, temp_db):
        """CSV with only header row creates empty table."""
        csv_path = temp_csv(["name", "value"], [])
        
        inserted, skipped = csv_to_sqlite(csv_path, temp_db)
        
        assert inserted == 0
        assert skipped == 0
        
        conn = sqlite3.connect(temp_db)
        count = conn.execute("SELECT COUNT(*) FROM test").fetchone()[0]
        conn.close()
        
        assert count == 0

    def test_unicode_content(self, temp_csv, temp_db):
        """Unicode content is preserved."""
        csv_path = temp_csv(
            ["name", "city"],
            [["Привет", "Москва"], ["你好", "北京"]]
        )
        
        csv_to_sqlite(csv_path, temp_db)
        
        conn = sqlite3.connect(temp_db)
        rows = conn.execute("SELECT name, city FROM test").fetchall()
        conn.close()
        
        assert ("Привет", "Москва") in rows
        assert ("你好", "北京") in rows

    def test_null_values(self, temp_csv, temp_db):
        """Empty values become NULL."""
        csv_path = temp_csv(
            ["name", "age"],
            [["Alice", "30"], ["Bob", ""], ["Charlie", "25"]]
        )
        
        csv_to_sqlite(csv_path, temp_db)
        
        conn = sqlite3.connect(temp_db)
        row = conn.execute("SELECT age FROM test WHERE name = 'Bob'").fetchone()
        conn.close()
        
        assert row[0] is None


# ===========================================================================
# 8. Integration Tests - ID Column
# ===========================================================================


class TestIdColumn:
    """Tests for --id column handling."""

    def test_id_from_existing_column(self, temp_csv, temp_db):
        """Existing column becomes PRIMARY KEY."""
        csv_path = temp_csv(
            ["user_id", "name"],
            [["1", "Alice"], ["2", "Bob"]]
        )
        
        csv_to_sqlite(csv_path, temp_db, id_column="user_id")
        
        conn = sqlite3.connect(temp_db)
        cursor = conn.execute("PRAGMA table_info(test)")
        columns = {row[1]: row[5] for row in cursor.fetchall()}  # pk flag
        conn.close()
        
        assert columns["user_id"] == 1  # Is primary key

    def test_id_autoincrement_new_column(self, temp_csv, temp_db):
        """New column added as AUTOINCREMENT."""
        csv_path = temp_csv(
            ["name", "age"],
            [["Alice", "30"], ["Bob", "25"]]
        )
        
        csv_to_sqlite(csv_path, temp_db, id_column="id")
        
        conn = sqlite3.connect(temp_db)
        cursor = conn.execute("PRAGMA table_info(test)")
        columns = {row[1]: (row[2], row[5]) for row in cursor.fetchall()}
        rows = conn.execute("SELECT id, name FROM test ORDER BY id").fetchall()
        conn.close()
        
        assert "id" in columns
        assert columns["id"][0] == "INTEGER"
        assert columns["id"][1] == 1  # Is primary key
        assert rows[0][0] == 1
        assert rows[1][0] == 2


# ===========================================================================
# 9. Integration Tests - Unique Constraint
# ===========================================================================


class TestUniqueConstraint:
    """Tests for --unique constraint handling."""

    def test_unique_index_created(self, temp_csv, temp_db):
        """Unique index is created."""
        csv_path = temp_csv(
            ["email", "name"],
            [["alice@example.com", "Alice"], ["bob@example.com", "Bob"]]
        )
        
        csv_to_sqlite(csv_path, temp_db, unique_columns=["email"])
        
        conn = sqlite3.connect(temp_db)
        indexes = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()
        conn.close()
        
        assert any("email" in idx[0] for idx in indexes)

    def test_unique_skip_duplicates(self, temp_csv, temp_db):
        """Duplicates are skipped with on_conflict=skip."""
        csv_path = temp_csv(
            ["email", "name"],
            [
                ["alice@example.com", "Alice"],
                ["bob@example.com", "Bob"],
                ["alice@example.com", "Alice2"],  # Duplicate
            ]
        )
        
        inserted, skipped = csv_to_sqlite(
            csv_path, temp_db,
            unique_columns=["email"],
            on_conflict="skip"
        )
        
        assert inserted == 2
        assert skipped == 1

    def test_unique_fail_on_duplicate(self, temp_csv, temp_db):
        """Import fails with on_conflict=fail."""
        csv_path = temp_csv(
            ["email", "name"],
            [
                ["alice@example.com", "Alice"],
                ["bob@example.com", "Bob"],
                ["alice@example.com", "Alice2"],  # Duplicate
            ]
        )
        
        with pytest.raises(ValueError, match="Unique constraint violation"):
            csv_to_sqlite(
                csv_path, temp_db,
                unique_columns=["email"],
                on_conflict="fail"
            )


# ===========================================================================
# 10. Integration Tests - if_exists Behavior
# ===========================================================================


class TestIfExists:
    """Tests for --if-exists behavior."""

    def test_if_exists_fail(self, temp_csv, temp_db):
        """Raises error when table exists and if_exists=fail."""
        csv_path = temp_csv(["name"], [["Alice"]])
        
        csv_to_sqlite(csv_path, temp_db)
        
        with pytest.raises(ValueError, match="already exists"):
            csv_to_sqlite(csv_path, temp_db, if_exists="fail")

    def test_if_exists_replace(self, temp_csv, temp_db):
        """Drops and recreates table when if_exists=replace."""
        csv_path1 = temp_csv(["name"], [["Alice"], ["Bob"]], name="test1.csv")
        csv_path2 = temp_csv(["name"], [["Charlie"]], name="test2.csv")
        
        csv_to_sqlite(csv_path1, temp_db, table_name="test")
        csv_to_sqlite(csv_path2, temp_db, table_name="test", if_exists="replace")
        
        conn = sqlite3.connect(temp_db)
        count = conn.execute("SELECT COUNT(*) FROM test").fetchone()[0]
        conn.close()
        
        assert count == 1

    def test_if_exists_skip(self, temp_csv, temp_db):
        """Skips import when table exists and if_exists=skip."""
        csv_path = temp_csv(["name"], [["Alice"]])
        
        inserted1, _ = csv_to_sqlite(csv_path, temp_db)
        inserted2, _ = csv_to_sqlite(csv_path, temp_db, if_exists="skip")
        
        assert inserted1 == 1
        assert inserted2 == 0


# ===========================================================================
# 11. Integration Tests - Dry Run
# ===========================================================================


class TestDryRun:
    """Tests for --dry-run mode."""

    def test_dry_run_no_database_written(self, temp_csv, temp_db):
        """Dry run doesn't write to database."""
        csv_path = temp_csv(["name", "age"], [["Alice", "30"]])
        
        csv_to_sqlite(csv_path, temp_db, dry_run=True)
        
        assert not temp_db.exists()

    def test_dry_run_returns_zero_counts(self, temp_csv, temp_db):
        """Dry run returns zero counts."""
        csv_path = temp_csv(["name", "age"], [["Alice", "30"]])
        
        inserted, skipped = csv_to_sqlite(csv_path, temp_db, dry_run=True)
        
        assert inserted == 0
        assert skipped == 0


# ===========================================================================
# 12. Integration Tests - Column Name Sanitization
# ===========================================================================


class TestColumnNameSanitization:
    """Tests for column name sanitization in import."""

    def test_special_chars_sanitized(self, temp_csv, temp_db):
        """Special characters in headers are sanitized."""
        csv_path = temp_csv(
            ["First Name", "price ($)", "email@domain"],
            [["Alice", "9.99", "alice@example.com"]]
        )
        
        csv_to_sqlite(csv_path, temp_db)
        
        conn = sqlite3.connect(temp_db)
        cursor = conn.execute("PRAGMA table_info(test)")
        columns = [row[1] for row in cursor.fetchall()]
        conn.close()
        
        assert "First_Name" in columns
        assert "price" in columns
        assert "email_domain" in columns


# ===========================================================================
# 13. FileEntry Format Compatibility Test
# ===========================================================================


class TestFileEntryCompatibility:
    """Tests that FileEntry format CSVs load correctly."""

    def test_fileentry_format_loads(self, tmp_path, temp_db):
        """FileEntry 10-column format loads correctly."""
        csv_path = tmp_path / "fileentry.csv"
        
        # Create a CSV matching FileEntry canonical format
        headers = [
            "creation", "access", "modify", "checksum", "entry_type",
            "permissions", "uid", "gid", "size", "path"
        ]
        rows = [
            [
                "2024-06-15T10:00:00+00:00",
                "2024-06-20T14:30:00+00:00",
                "2024-06-15T10:00:00+00:00",
                "d41d8cd98f00b204e9800998ecf8427e",
                "f",
                "0644",
                "501",
                "20",
                "1234",
                "photos/vacation/IMG_001.jpg"
            ],
            [
                "2024-06-16T11:00:00+00:00",
                "2024-06-21T15:30:00+00:00",
                "2024-06-16T11:00:00+00:00",
                "e2d0fe1585a63ec6009c8016ff8dda8a",
                "f",
                "0644",
                "501",
                "20",
                "5678",
                "photos/vacation/IMG_002.jpg"
            ],
        ]
        
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            writer.writerows(rows)
        
        inserted, skipped = csv_to_sqlite(csv_path, temp_db)
        
        assert inserted == 2
        assert skipped == 0
        
        conn = sqlite3.connect(temp_db)
        cursor = conn.execute("PRAGMA table_info(fileentry)")
        columns = {row[1]: row[2] for row in cursor.fetchall()}
        conn.close()
        
        # Verify type detection
        assert columns["creation"] == "DATETIME"
        assert columns["access"] == "DATETIME"
        assert columns["modify"] == "DATETIME"
        assert columns["uid"] == "INTEGER"
        assert columns["gid"] == "INTEGER"
        assert columns["size"] == "INTEGER"
        assert columns["checksum"].startswith("TEXT")
        assert columns["entry_type"].startswith("TEXT")
        assert columns["path"].startswith("TEXT")


# ===========================================================================
# 14. DebugLog Format Compatibility Test
# ===========================================================================


class TestDebugLogCompatibility:
    """Tests that DebugLog format CSVs load correctly."""

    def test_debuglog_format_loads(self, tmp_path, temp_db):
        """DebugLog 18-column format loads correctly."""
        csv_path = tmp_path / "debuglog.csv"
        
        # Create a CSV matching DebugLog canonical format
        headers = [
            "file_path", "file_size", "file_extension",
            "tool_binary", "tool_package", "command", "check_level",
            "exit_code", "stdout", "stderr",
            "stderr_regex", "stdout_regex", "stderr_matched", "stdout_matched",
            "result", "decision_reason", "error_message", "duration_ms"
        ]
        rows = [
            [
                "/path/to/file.mp4",
                "1024000",
                ".mp4",
                "ffprobe",
                "ffmpeg",
                "ffprobe -v error -i /path/to/file.mp4",
                "default",
                "0",
                "Stream info here",
                "",
                "(?i)error",
                "",
                "False",
                "",
                "VALID",
                "exit code 0 in success codes",
                "",
                "150.5"
            ],
            [
                "/path/to/corrupt.mp4",
                "512000",
                ".mp4",
                "ffprobe",
                "ffmpeg",
                "ffprobe -v error -i /path/to/corrupt.mp4",
                "default",
                "1",
                "",
                "Invalid data found",
                "(?i)error",
                "",
                "True",
                "",
                "CORRUPT",
                "exit code 1 not in success codes",
                "Invalid data found",
                "75.2"
            ],
        ]
        
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            writer.writerows(rows)
        
        inserted, skipped = csv_to_sqlite(csv_path, temp_db)
        
        assert inserted == 2
        assert skipped == 0
        
        conn = sqlite3.connect(temp_db)
        cursor = conn.execute("PRAGMA table_info(debuglog)")
        columns = {row[1]: row[2] for row in cursor.fetchall()}
        conn.close()
        
        # Verify type detection
        assert columns["file_size"] == "INTEGER"
        assert columns["exit_code"] == "INTEGER"
        assert columns["duration_ms"] == "REAL"
        assert columns["file_path"].startswith("TEXT")
        assert columns["result"].startswith("TEXT")


# ===========================================================================
# 15. Edge Cases
# ===========================================================================


class TestEdgeCases:
    """Tests for edge cases."""

    def test_european_decimal_format(self, temp_csv, temp_db):
        """European comma-separated decimals work."""
        csv_path = temp_csv(
            ["price"],
            [["1,99"], ["2,50"], ["10,00"]]
        )
        
        csv_to_sqlite(csv_path, temp_db)
        
        conn = sqlite3.connect(temp_db)
        cursor = conn.execute("PRAGMA table_info(test)")
        columns = {row[1]: row[2] for row in cursor.fetchall()}
        prices = conn.execute("SELECT price FROM test ORDER BY price").fetchall()
        conn.close()
        
        assert columns["price"] == "REAL"
        assert prices == [(1.99,), (2.5,), (10.0,)]

    def test_very_long_text(self, temp_csv, temp_db):
        """Very long text values are handled."""
        long_text = "x" * 10000
        csv_path = temp_csv(["description"], [[long_text]])
        
        csv_to_sqlite(csv_path, temp_db)
        
        conn = sqlite3.connect(temp_db)
        row = conn.execute("SELECT description FROM test").fetchone()
        conn.close()
        
        assert row[0] == long_text

    def test_custom_delimiter(self, tmp_path, temp_db):
        """Custom delimiter works."""
        csv_path = tmp_path / "semicolon.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            f.write("name;age\n")
            f.write("Alice;30\n")
            f.write("Bob;25\n")
        
        csv_to_sqlite(csv_path, temp_db, delimiter=";")
        
        conn = sqlite3.connect(temp_db)
        count = conn.execute("SELECT COUNT(*) FROM semicolon").fetchone()[0]
        conn.close()
        
        assert count == 2

    def test_custom_table_name(self, temp_csv, temp_db):
        """Custom table name works."""
        csv_path = temp_csv(["name"], [["Alice"]])
        
        csv_to_sqlite(csv_path, temp_db, table_name="my_custom_table")
        
        conn = sqlite3.connect(temp_db)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        conn.close()
        
        assert ("my_custom_table",) in tables

    def test_file_not_found(self, temp_db):
        """FileNotFoundError raised for missing file."""
        with pytest.raises(FileNotFoundError):
            csv_to_sqlite(Path("/nonexistent/file.csv"), temp_db)
