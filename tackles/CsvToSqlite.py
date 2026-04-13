"""
CsvToSqlite tackle — Stream any CSV file with headers into a new SQLite table.

Two-pass streaming (O(batch_size) peak memory regardless of file size):
  Pass 1 – scan every row to infer column types and max lengths
  Pass 2 – stream rows in configurable batches into SQLite

Type detection priority (most specific → least specific):
  DATETIME  →  ISO 8601 with optional timezone / 'Z'
  INTEGER   →  whole numbers (optional leading ±)
  REAL      →  decimals, point-separated (1.23) OR comma-separated (1,23)
  TEXT(n)   →  fallback; n = max observed character length

Features:
  - Smart ID handling (--id): use existing column or add auto-increment
  - Unique index support (--unique): create unique constraint with duplicate handling
  - Column name sanitization: invalid chars → underscore, collision → col_N
  - Dry-run mode: preview schema without writing to database
  - Time-based progress reporting
"""

from __future__ import annotations

import csv
import logging
import pathlib
import re
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from tackles.TackleFactory import TackleFactory

# ── Module-level logger ────────────────────────────────────────────────────────
logger = logging.getLogger(__name__)


# ── Type-detection predicates ──────────────────────────────────────────────────

def _is_datetime(value: str) -> bool:
    """Accept any ISO 8601 string, including 'Z' and ±HH:MM offset."""
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def _is_int(value: str) -> bool:
    """Accept whole numbers with optional leading ± sign."""
    try:
        int(value)
        return True
    except ValueError:
        return False


def _is_float(value: str) -> bool:
    """Accept point-separated (1.23) and comma-separated (1,23) decimals."""
    try:
        float(value)
        return True
    except ValueError:
        pass
    try:
        float(value.replace(",", ".", 1))
        return True
    except ValueError:
        return False


def _to_float(value: str) -> float:
    """Convert a point- or comma-decimal string to float."""
    try:
        return float(value)
    except ValueError:
        return float(value.replace(",", ".", 1))


# ── Column name sanitization ───────────────────────────────────────────────────

def _sanitize_column_names(headers: list[str]) -> list[str]:
    """Sanitize column names for SQLite compatibility.
    
    Rules:
    1. Replace any character NOT in [a-zA-Z0-9_] with underscore
    2. Collapse consecutive underscores to single underscore
    3. Strip leading/trailing underscores
    4. If name starts with digit, prefix with underscore
    5. If sanitized name is empty, use col_N where N is column index
    6. Collision handling: if name already exists, use col_N instead
    """
    result: list[str] = []
    used_names: set[str] = set()

    for idx, raw in enumerate(headers):
        # Replace invalid chars with underscore
        name = re.sub(r'[^a-zA-Z0-9_]', '_', raw)
        # Collapse multiple underscores
        name = re.sub(r'_+', '_', name)
        # Strip leading/trailing underscores
        name = name.strip('_')
        # Handle empty result
        if not name:
            name = f'col_{idx}'
        # Prefix if starts with digit
        elif name[0].isdigit():
            name = f'_{name}'

        # Handle collision
        if name in used_names:
            name = f'col_{idx}'

        used_names.add(name)
        result.append(name)

    return result


# ── Per-column state object ────────────────────────────────────────────────────

_PRIORITY: tuple[str, ...] = ("DATETIME", "INTEGER", "REAL", "TEXT")


class ColumnState:
    """Accumulates type evidence for a single column across streamed rows.
    
    Types are eliminated (never added), so only valid candidates survive.
    """

    __slots__ = ("name", "original_name", "_possible", "max_len")

    def __init__(self, name: str, original_name: str) -> None:
        self.name = name
        self.original_name = original_name
        self._possible: set[str] = set(_PRIORITY)
        self.max_len: int = 0

    def feed(self, raw: str) -> None:
        """Narrow candidates using a single raw cell value."""
        v = raw.strip()
        if not v:
            return  # empty / NULL → does not constrain type

        self.max_len = max(self.max_len, len(v))

        if "DATETIME" in self._possible and not _is_datetime(v):
            self._possible.discard("DATETIME")
        if "INTEGER" in self._possible and not _is_int(v):
            self._possible.discard("INTEGER")
        if "REAL" in self._possible and not _is_float(v):
            self._possible.discard("REAL")
        # TEXT is the universal fallback: never discarded

    @property
    def sql_type(self) -> str:
        """Return the most specific surviving SQLite type."""
        for t in _PRIORITY:
            if t in self._possible:
                if t == "TEXT":
                    return f"TEXT({self.max_len})" if self.max_len else "TEXT"
                return t
        return "TEXT"  # unreachable, kept for safety


# ── SQL identifier quoting ─────────────────────────────────────────────────────

def _quote(name: str) -> str:
    """Double-quote an SQL identifier, escaping embedded double-quotes."""
    return '"' + name.replace('"', '""') + '"'


# ── Streaming CSV helpers ──────────────────────────────────────────────────────

def _iter_rows(
    csv_path: Path,
    encoding: str,
    delimiter: str,
    *,
    skip_header: bool = True,
) -> Iterator[list[str]]:
    """Yield raw string rows from a CSV file one at a time (streaming)."""
    with csv_path.open(newline="", encoding=encoding) as fh:
        reader = csv.reader(fh, delimiter=delimiter)
        if skip_header:
            next(reader, None)
        yield from reader


def _coerce(value: str, col_type: str) -> int | float | str | None:
    """Map a raw CSV string to the correct Python type for SQLite binding."""
    v = value.strip()
    if not v:
        return None  # empty cell → SQL NULL
    if col_type == "DATETIME":
        return v.replace("Z", "+00:00")  # normalise to ±HH:MM
    if col_type == "INTEGER":
        return int(v)
    if col_type == "REAL":
        return _to_float(v)
    # TEXT(n) or TEXT
    return v


def _iter_batches(
    csv_path: Path,
    encoding: str,
    delimiter: str,
    col_types: list[str],
    batch_size: int,
) -> Iterator[list[list[int | float | str | None]]]:
    """Yield coerced row batches of `batch_size` ready for executemany."""
    n = len(col_types)
    batch: list[list] = []

    for row in _iter_rows(csv_path, encoding, delimiter):
        batch.append(
            [_coerce(row[i] if i < len(row) else "", col_types[i]) for i in range(n)]
        )
        if len(batch) >= batch_size:
            yield batch
            batch.clear()

    if batch:
        yield batch


# ── Pass 1 – type detection ────────────────────────────────────────────────────

def _scan_types(
    csv_path: Path,
    encoding: str,
    delimiter: str,
) -> tuple[list[str], list[str], list[ColumnState], int]:
    """Stream the CSV once to build per-column type states.
    
    Returns (original_headers, sanitized_headers, states, total_row_count).
    """
    with csv_path.open(newline="", encoding=encoding) as fh:
        reader = csv.reader(fh, delimiter=delimiter)
        original_headers = [h.strip() for h in next(reader)]
        sanitized_headers = _sanitize_column_names(original_headers)
        n = len(sanitized_headers)
        states = [
            ColumnState(sanitized_headers[i], original_headers[i])
            for i in range(n)
        ]
        count = 0

        for row in reader:
            for i, raw in enumerate(row[:n]):
                states[i].feed(raw)
            count += 1

    logger.debug("Pass 1 complete – %d rows scanned", count)
    return original_headers, sanitized_headers, states, count


# ── Main routine ───────────────────────────────────────────────────────────────

def csv_to_sqlite(
    csv_path: Path,
    db_path: Path,
    *,
    table_name: str | None = None,
    encoding: str = "utf-8-sig",
    delimiter: str = ",",
    batch_size: int = 500,
    if_exists: str = "fail",
    id_column: str | None = None,
    unique_columns: list[str] | None = None,
    on_conflict: str = "skip",
    dry_run: bool = False,
) -> tuple[int, int]:
    """Import CSV to SQLite with auto-detected types.
    
    Returns (inserted_count, skipped_count).
    """
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    table_name = table_name or csv_path.stem
    
    dry_run_tag = " (DRY RUN)" if dry_run else ""
    logger.info("Source   : %s", csv_path)
    logger.info("Target   : %s  →  table '%s'%s", db_path, table_name, dry_run_tag)
    logger.info("Encoding : %s  |  Delimiter : %r  |  Batch : %d",
                encoding, delimiter, batch_size)
    
    id_mode = "None"
    if id_column:
        id_mode = id_column
    unique_str = str(unique_columns) if unique_columns else "None"
    logger.info("Options  : id=%s | unique=%s | on_conflict=%s",
                id_mode, unique_str, on_conflict)

    # ── Pass 1: detect column types ───────────────────────────────────────────
    logger.info("Pass 1/2 – scanning column types …")
    original_headers, headers, states, total_rows = _scan_types(
        csv_path, encoding, delimiter
    )

    logger.info("Detected %d column(s) across %d row(s):", len(headers), total_rows)
    for s in states:
        logger.info("  %-35s →  %s", repr(s.name), s.sql_type)

    col_types = [s.sql_type for s in states]
    
    # Determine if id_column exists in headers
    id_is_autoincrement = False
    id_column_index: int | None = None
    if id_column:
        if id_column in headers:
            id_column_index = headers.index(id_column)
            logger.info("Column '%s' found in CSV – using as PRIMARY KEY", id_column)
        else:
            id_is_autoincrement = True
            logger.info("Column '%s' not in CSV – adding as INTEGER PRIMARY KEY AUTOINCREMENT", id_column)

    # Build column definitions
    col_defs: list[str] = []
    
    # Add auto-increment ID column first if needed
    if id_column and id_is_autoincrement:
        col_defs.append(f"{_quote(id_column)} INTEGER PRIMARY KEY AUTOINCREMENT")
    
    # Add data columns
    for i, (h, t) in enumerate(zip(headers, col_types)):
        if id_column and not id_is_autoincrement and i == id_column_index:
            # This column is the primary key from data
            col_defs.append(f"{_quote(h)} {t} PRIMARY KEY")
        else:
            col_defs.append(f"{_quote(h)} {t}")
    
    col_defs_sql = ", ".join(col_defs)
    
    # Determine which columns to insert (exclude auto-increment ID)
    insert_columns = headers
    if id_column and id_is_autoincrement:
        insert_columns = headers  # All data columns
    
    insert_cols_sql = ", ".join(_quote(h) for h in insert_columns)
    placeholders = ", ".join("?" * len(insert_columns))
    
    create_sql = f"CREATE TABLE {_quote(table_name)} ({col_defs_sql});"
    insert_sql = f"INSERT INTO {_quote(table_name)} ({insert_cols_sql}) VALUES ({placeholders});"

    # ── Dry-run mode: print schema and exit ───────────────────────────────────
    if dry_run:
        logger.info("")
        logger.info("[DRY RUN] Would create table with schema:")
        logger.info("CREATE TABLE %s (", _quote(table_name))
        for col_def in col_defs:
            logger.info("    %s,", col_def)
        logger.info(");")
        logger.info("")
        
        # Build unique index statement if needed
        if unique_columns:
            valid_unique = [c for c in unique_columns if c in headers]
            if valid_unique:
                idx_name = f"idx_{table_name}_{'_'.join(valid_unique)}"
                cols_sql = ", ".join(_quote(c) for c in valid_unique)
                logger.info("CREATE UNIQUE INDEX %s ON %s (%s);",
                           _quote(idx_name), _quote(table_name), cols_sql)
                logger.info("")
        
        logger.info("[DRY RUN] Would insert %d rows. No database written.", total_rows)
        return 0, 0

    # ── Open DB, handle if_exists, create table ───────────────────────────────
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")

        table_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        ).fetchone()

        if table_exists:
            if if_exists == "fail":
                raise ValueError(
                    f"Table '{table_name}' already exists. "
                    "Use --if-exists replace|skip to override."
                )
            if if_exists == "replace":
                logger.warning("Dropping existing table '%s'", table_name)
                conn.execute(f"DROP TABLE {_quote(table_name)};")
            elif if_exists == "skip":
                logger.info("Table '%s' already exists – skipping.", table_name)
                return 0, 0

        logger.debug("DDL: %s", create_sql)
        conn.execute(create_sql)
        
        # Create unique index if specified
        if unique_columns:
            valid_unique = [c for c in unique_columns if c in headers]
            invalid_unique = [c for c in unique_columns if c not in headers]
            if invalid_unique:
                logger.warning(
                    "Ignoring unknown columns in --unique: %s",
                    ", ".join(invalid_unique)
                )
            if valid_unique:
                idx_name = f"idx_{table_name}_{'_'.join(valid_unique)}"
                cols_sql = ", ".join(_quote(c) for c in valid_unique)
                idx_sql = f"CREATE UNIQUE INDEX {_quote(idx_name)} ON {_quote(table_name)} ({cols_sql});"
                logger.debug("Creating unique index: %s", idx_sql)
                conn.execute(idx_sql)

        # ── Pass 2: stream rows into SQLite in batches ────────────────────────
        logger.info("Pass 2/2 – inserting rows in batches of %d …", batch_size)
        inserted = 0
        skipped = 0
        progress_interval = 10  # seconds
        last_progress = time.monotonic()

        for batch in _iter_batches(csv_path, encoding, delimiter, col_types, batch_size):
            try:
                conn.executemany(insert_sql, batch)
                inserted += len(batch)
            except sqlite3.IntegrityError as exc:
                if on_conflict == "fail":
                    raise ValueError(
                        f"Unique constraint violation: {exc}. "
                        f"Use --on-conflict skip to continue."
                    ) from exc
                
                # Rollback the failed transaction before row-by-row fallback
                conn.rollback()
                
                # Fall back to row-by-row insert for this batch
                for row in batch:
                    try:
                        conn.execute(insert_sql, row)
                        inserted += 1
                    except sqlite3.IntegrityError as row_exc:
                        # Log which row was skipped (find unique column values)
                        if unique_columns:
                            valid_unique = [c for c in unique_columns if c in headers]
                            dup_info = ", ".join(
                                f"{c}={row[headers.index(c)]!r}"
                                for c in valid_unique
                                if c in headers
                            )
                            logger.warning(
                                "Skipping duplicate row (%s)", dup_info
                            )
                        else:
                            logger.warning("Skipping duplicate row: %s", row_exc)
                        skipped += 1

            logger.debug("Batch done – %d / %d rows inserted", inserted, total_rows)

            # Time-based progress
            now = time.monotonic()
            if now - last_progress >= progress_interval:
                pct = (inserted + skipped) * 100 / total_rows if total_rows else 100
                logger.info(
                    "Progress: %d/%d (%.1f%%) | Skipped: %d",
                    inserted + skipped, total_rows, pct, skipped
                )
                last_progress = now

        conn.commit()

    # Summary
    if skipped > 0:
        logger.info(
            "Done – %d rows inserted, %d skipped due to unique constraint.",
            inserted, skipped
        )
    else:
        logger.info("Done – %d rows inserted into table '%s'.", inserted, table_name)
    
    return inserted, skipped


# ── Tackle class ───────────────────────────────────────────────────────────────

class CsvToSqlite(TackleFactory):
    """Stream any CSV file with headers into a new SQLite table.
    
    Features auto type detection, smart ID handling, unique constraints,
    and column name sanitization.
    """

    @classmethod
    def arg_parser(cls, subparser):
        # Positional arguments
        subparser.add_argument(
            "csv_file",
            type=pathlib.Path,
            help="Input CSV file path (must have header row)",
        )
        subparser.add_argument(
            "db_file",
            type=pathlib.Path,
            help="Output SQLite database path",
        )

        # Optional arguments
        subparser.add_argument(
            "-t", "--table",
            dest="table_name",
            default=None,
            metavar="NAME",
            help="Target table name (default: CSV filename stem)",
        )
        subparser.add_argument(
            "-d", "--delimiter",
            default=",",
            metavar="CHAR",
            help="CSV field delimiter (default: ',')",
        )
        subparser.add_argument(
            "-e", "--encoding",
            default="utf-8-sig",
            metavar="ENC",
            help="CSV file encoding (default: utf-8-sig, strips Excel BOM)",
        )
        subparser.add_argument(
            "-b", "--batch-size",
            dest="batch_size",
            type=int,
            default=500,
            metavar="N",
            help="Number of rows per INSERT batch (default: 500)",
        )
        subparser.add_argument(
            "--if-exists",
            choices=["fail", "replace", "skip"],
            default="fail",
            help="Action when target table already exists (default: fail)",
        )
        subparser.add_argument(
            "--id",
            dest="id_column",
            default=None,
            metavar="COLUMN",
            help=(
                "Primary key column. If column exists in CSV, use it as PRIMARY KEY. "
                "If not, add as INTEGER PRIMARY KEY AUTOINCREMENT."
            ),
        )
        subparser.add_argument(
            "--unique",
            dest="unique_columns",
            default=None,
            metavar="COLUMNS",
            help="Column(s) to create unique index on (comma-separated)",
        )
        subparser.add_argument(
            "--on-conflict",
            choices=["skip", "fail"],
            default="skip",
            help="Action on uniqueness violation (default: skip)",
        )
        subparser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Preview detected types and schema without writing to database",
        )
        subparser.add_argument(
            "--log-level",
            choices=["DEBUG", "INFO", "WARNING", "ERROR"],
            default="INFO",
            help="Logging verbosity level (default: INFO)",
        )
        subparser.add_argument(
            "-v",
            action="store_true",
            help="Verbose output (same as --log-level DEBUG)",
        )

    def __init__(self, parser):
        super().__init__(parser)
        options, _ = parser.parse_known_args()

        # Configure logging
        log_level = options.log_level
        if options.v:
            log_level = "DEBUG"
        
        logging.basicConfig(
            level=log_level,
            format="%(asctime)s  %(levelname)-8s  %(message)s",
            datefmt="%H:%M:%S",
        )

        # Store options
        self.csv_path: Path = options.csv_file
        self.db_path: Path = options.db_file
        self.table_name: str | None = options.table_name
        self.encoding: str = options.encoding
        self.delimiter: str = options.delimiter
        self.batch_size: int = options.batch_size
        self.if_exists: str = options.if_exists
        self.id_column: str | None = options.id_column
        self.on_conflict: str = options.on_conflict
        self.dry_run: bool = options.dry_run
        
        # Parse unique columns
        self.unique_columns: list[str] | None = None
        if options.unique_columns:
            self.unique_columns = [
                c.strip() for c in options.unique_columns.split(",") if c.strip()
            ]

        # Validate CSV exists
        if not self.csv_path.exists():
            logger.error("CSV file not found: %s", self.csv_path)
            sys.exit(1)

    def do(self) -> int:
        """Execute the CSV to SQLite import."""
        try:
            inserted, skipped = csv_to_sqlite(
                csv_path=self.csv_path,
                db_path=self.db_path,
                table_name=self.table_name,
                encoding=self.encoding,
                delimiter=self.delimiter,
                batch_size=self.batch_size,
                if_exists=self.if_exists,
                id_column=self.id_column,
                unique_columns=self.unique_columns,
                on_conflict=self.on_conflict,
                dry_run=self.dry_run,
            )
            return 0
        except FileNotFoundError as exc:
            logger.error("%s", exc)
            return 1
        except ValueError as exc:
            logger.error("%s", exc)
            return 1
        except Exception as exc:
            logger.exception("Unexpected error: %s", exc)
            return 1
