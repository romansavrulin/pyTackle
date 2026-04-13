# CsvToSqlite

Stream any CSV file with headers into a new SQLite table with automatic column type detection.

## Overview

**CsvToSqlite** is a high-performance tackle for importing CSV data into SQLite databases. It automatically detects column types (datetime, integer, float, text) and handles large files efficiently using a two-pass streaming approach.

### Key Features

- **Automatic type detection** — DATETIME → INTEGER → REAL → TEXT(n)
- **Memory efficient** — O(batch_size) peak memory regardless of file size
- **Smart ID handling** — Use existing column as primary key or add auto-increment
- **Unique constraints** — Create unique indexes with configurable duplicate handling
- **Column sanitization** — Automatically fixes invalid column names
- **Dry-run mode** — Preview schema without writing to database

## Quick Start

```bash
# Basic import
pyTackle CsvToSqlite sales.csv analytics.db

# Import with custom table name
pyTackle CsvToSqlite data.csv shop.db -t orders

# Preview schema without importing
pyTackle CsvToSqlite data.csv output.db --dry-run
```

## CLI Reference

### Positional Arguments

| Argument | Description |
|----------|-------------|
| `csv_file` | Input CSV file path (must have header row) |
| `db_file` | Output SQLite database path |

### Optional Arguments

| Option | Default | Description |
|--------|---------|-------------|
| `-t, --table NAME` | CSV filename stem | Target table name |
| `-d, --delimiter CHAR` | `,` | CSV field delimiter |
| `-e, --encoding ENC` | `utf-8-sig` | CSV file encoding (utf-8-sig strips Excel BOM) |
| `-b, --batch-size N` | 500 | Number of rows per INSERT batch |
| `--if-exists ACTION` | `fail` | Action when table exists: `fail`, `replace`, `skip` |
| `--id COLUMN` | none | Primary key column (see [ID Column](#id-column)) |
| `--unique COLUMNS` | none | Column(s) to create unique index on (comma-separated) |
| `--on-conflict ACTION` | `skip` | Action on uniqueness violation: `skip`, `fail` |
| `--dry-run` | off | Preview detected types and schema without writing |
| `--log-level LEVEL` | `INFO` | Logging verbosity: DEBUG, INFO, WARNING, ERROR |
| `-v` | - | Verbose output (same as --log-level DEBUG) |

## Type Detection

CsvToSqlite automatically detects the most appropriate SQLite type for each column by scanning all values in Pass 1.

### Detection Priority

Types are tested from most specific to least specific:

| Priority | Type | Pattern | Examples |
|----------|------|---------|----------|
| 1 | `DATETIME` | ISO 8601 with optional timezone | `2024-06-15T12:00:00Z`, `2024-06-15T12:00:00+05:30` |
| 2 | `INTEGER` | Whole numbers with optional ± | `42`, `-100`, `+5` |
| 3 | `REAL` | Decimals (point or comma separator) | `1.23`, `1,23` (European format) |
| 4 | `TEXT(n)` | Fallback; n = max observed length | Any string |

### Rules

- Empty cells are treated as NULL and don't constrain type detection
- Once a type is eliminated for a column, it cannot be added back
- European decimal format (comma separator) is automatically detected

## ID Column

The `--id` option provides smart primary key handling:

### Use Existing Column

If the column name exists in the CSV, it becomes the PRIMARY KEY using data from the file:

```bash
# CSV has order_id column → use it as primary key
pyTackle CsvToSqlite orders.csv shop.db --id order_id
```

```sql
CREATE TABLE "orders" (
    "order_id" INTEGER PRIMARY KEY,  -- from CSV data
    "customer" TEXT(50),
    "total" REAL
);
```

### Add Auto-Increment

If the column name does NOT exist in the CSV, a new auto-increment column is added:

```bash
# CSV doesn't have id column → add auto-increment
pyTackle CsvToSqlite products.csv shop.db --id id
```

```sql
CREATE TABLE "products" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT,  -- auto-generated
    "name" TEXT(100),
    "price" REAL
);
```

## Unique Constraints

Create unique indexes to enforce data integrity:

```bash
# Single column unique constraint
pyTackle CsvToSqlite users.csv app.db --unique email

# Multi-column unique constraint
pyTackle CsvToSqlite contacts.csv crm.db --unique "first_name,last_name"
```

### Duplicate Handling

| Option | Behavior |
|--------|----------|
| `--on-conflict skip` | Log warning and skip duplicate rows (default) |
| `--on-conflict fail` | Abort import on first duplicate |

```bash
# Skip duplicates and continue
pyTackle CsvToSqlite contacts.csv crm.db --unique email --on-conflict skip

# Fail immediately on duplicate
pyTackle CsvToSqlite orders.csv shop.db --unique order_id --on-conflict fail
```

## Column Name Sanitization

Invalid characters in CSV headers are automatically fixed:

| Transformation | Before | After |
|----------------|--------|-------|
| Spaces → underscore | `First Name` | `First_Name` |
| Special chars removed | `price ($)` | `price` |
| Leading digits prefixed | `123abc` | `_123abc` |
| Empty → col_N | `___` | `col_0` |
| Collisions → col_N | `name`, `name` | `name`, `col_1` |

## Table Exists Behavior

| Option | Behavior |
|--------|----------|
| `--if-exists fail` | Raise error if table exists (default) |
| `--if-exists replace` | Drop and recreate table |
| `--if-exists skip` | Return without importing |

## Dry-Run Mode

Preview the schema without writing to the database:

```bash
pyTackle CsvToSqlite large_file.csv analysis.db --dry-run
```

Output:
```
12:30:45  INFO      Source   : large_file.csv
12:30:45  INFO      Target   : analysis.db  →  table 'large_file' (DRY RUN)
12:30:46  INFO      Pass 1/2 – scanning column types …
12:30:46  INFO      Detected 5 column(s) across 10000 row(s):
12:30:46  INFO        'timestamp'      →  DATETIME
12:30:46  INFO        'product_id'     →  INTEGER
12:30:46  INFO        'quantity'       →  INTEGER
12:30:46  INFO        'price'          →  REAL
12:30:46  INFO        'description'    →  TEXT(256)
12:30:46  INFO      
12:30:46  INFO      [DRY RUN] Would create table with schema:
12:30:46  INFO      CREATE TABLE "large_file" (
12:30:46  INFO          "timestamp" DATETIME,
12:30:46  INFO          "product_id" INTEGER,
12:30:46  INFO          "quantity" INTEGER,
12:30:46  INFO          "price" REAL,
12:30:46  INFO          "description" TEXT(256)
12:30:46  INFO      );
12:30:46  INFO      
12:30:46  INFO      [DRY RUN] Would insert 10000 rows. No database written.
```

## Example Workflows

### Basic Import

```bash
pyTackle CsvToSqlite sales.csv analytics.db
```

### European CSV (Semicolon Delimiter, Comma Decimals)

```bash
pyTackle CsvToSqlite export.csv warehouse.db -d ";"
```

### Large File with Bigger Batches

```bash
pyTackle CsvToSqlite bigfile.csv results.db -b 5000
```

### Full-Featured Import

```bash
pyTackle CsvToSqlite contacts.csv crm.db \
    --id user_id \
    --unique email \
    --on-conflict skip \
    --if-exists replace \
    -v
```

## Performance Tips

1. **Increase batch size** for large files: `-b 5000` or higher
2. **Use SSDs** for best performance with large databases
3. **WAL mode** is automatically enabled for better write performance

## Canonical Format Compatibility

CsvToSqlite correctly handles pyTackle's canonical CSV formats:

### FileEntry Format (10 columns)

```
creation,access,modify,checksum,entry_type,permissions,uid,gid,size,path
2024-06-15T10:00:00+00:00,2024-06-20T14:30:00+00:00,...
```

### DebugLog Format (18 columns)

```
file_path,file_size,file_extension,tool_binary,tool_package,...
/path/to/file.mp4,1024000,.mp4,ffprobe,ffmpeg,...
```

Both formats load with correct type detection (datetimes, integers, floats, text).

## See Also

- [ValidateCopy](ValidateCopy.md) — Generate and validate file listings
- [MediaIntegrityCheck](MediaIntegrityCheck.md) — Validate media file integrity
- [pyTackle README](README.md) — Overview of all available tackles
