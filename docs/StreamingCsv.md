# StreamingCsv Infrastructure

Memory-efficient streaming CSV writers for pyTackle.

## Overview

The `common.streaming_csv` module provides a generic abstract base class for streaming CSV writers. These writers are designed for memory efficiency — writing data line-by-line rather than accumulating all entries in memory.

### Key Features

- **Generic type support** — `StreamingCsvWriter[T]` can write any data type
- **Lazy vs eager opening** — File created on first write or explicitly opened
- **Optional header row** — Configurable column headers
- **Flush-on-write** — Optional immediate flushing for debug/reliability
- **Context manager** — Proper resource cleanup via `with` statement
- **Write counting** — Track number of entries written

## Architecture

```
StreamingCsvWriter[T]  (ABC)
├── StreamingListingWriter   (FileEntry → canonical CSV)
└── DebugLogWriter           (DebugRecord → debug CSV)
```

The base class handles:
- File opening/closing and context management
- Header row writing
- Write counting
- Flush-on-write option

Subclasses only implement `_to_row()` to convert their specific data type to a list of string values.

## Base Class: StreamingCsvWriter

### Constructor Parameters

```python
StreamingCsvWriter(
    path: str,
    header: Optional[Tuple[str, ...]] = None,
    lazy_open: bool = True,
    flush_on_write: bool = False,
)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `path` | str | required | Path to the output CSV file |
| `header` | Tuple[str, ...] | None | Column names for header row |
| `lazy_open` | bool | True | If True, file opens on first write |
| `flush_on_write` | bool | False | If True, flush after each write |

### Methods

| Method | Description |
|--------|-------------|
| `open()` | Explicitly open the file (required if `lazy_open=False`) |
| `write(item: T)` | Write a single item to the CSV |
| `close()` | Close the file (safe to call multiple times) |

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `count` | int | Number of items written so far |
| `is_open` | bool | Whether the file is currently open |
| `path` | str | Path to the output file |

### Abstract Method

Subclasses must implement:

```python
def _to_row(self, item: T) -> List[str]:
    """Convert an item to a list of string values for CSV output."""
    ...
```

## StreamingListingWriter

Streaming CSV writer for [`FileEntry`](../common/FileEntry.py) listings.

### Constructor

```python
StreamingListingWriter(
    path: str,
    attr_map: Optional[Dict[str, str]] = None,
    include_header: bool = True,
)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `path` | str | required | Path to the output CSV file |
| `attr_map` | Dict[str, str] | `CANONICAL_MAP` | Column mapping for serialization |
| `include_header` | bool | True | Write header row when file opens |

### Behavior

- Uses lazy opening (file created on first write)
- Flushes after each write for reliability
- Default mapping produces 10-column canonical format
- Header row uses attribute names from `attr_map` keys

### Example Usage

```python
from common.streaming_csv import StreamingListingWriter
from common.FileEntry import FileEntry

# Basic usage with context manager
with StreamingListingWriter('output.csv') as writer:
    for entry in entries:
        writer.write(entry)
    
print(f'Wrote {writer.count} entries')

# Without header
with StreamingListingWriter('output.csv', include_header=False) as writer:
    for entry in entries:
        writer.write(entry)
```

### Output Format

The default canonical format with header:

```csv
creation,access,modify,checksum,entry_type,permissions,uid,gid,size,path
2024-01-15T10:30:00,2024-01-15T10:30:00,2024-01-15T10:30:00,d41d8cd9...,f,0644,501,20,1234,photos/img.jpg
```

## DebugLogWriter

Streaming CSV writer for debug records in [`MediaIntegrityCheck`](MediaIntegrityCheck.md).

### Constructor

```python
DebugLogWriter(path: str)
```

### Behavior

- Uses **eager** opening (`lazy_open=False`) — file must be opened explicitly
- Always includes header row
- Flushes after each write for debug reliability
- Writes 18-column debug records

### Example Usage

```python
from tackles.MediaIntegrityCheck import DebugLogWriter, DebugRecord

writer = DebugLogWriter('debug.csv')
writer.open()  # Required for eager mode

try:
    record = DebugRecord(
        file_path='/path/to/file.mp4',
        file_size=1234567,
        file_extension='.mp4',
        result='VALID',
        decision_reason='exit code 0 in success codes',
    )
    writer.write(record)
finally:
    writer.close()
```

See [MediaIntegrityCheck Debug Logging](MediaIntegrityCheck.md#debug-logging) for the full column specification.

## Lazy vs Eager Opening

### Lazy Opening (Default)

File is created only when the first item is written:

```python
# File doesn't exist yet
writer = StreamingListingWriter('output.csv')

# File still doesn't exist
time.sleep(10)

# File created NOW (with header if enabled)
writer.write(entry)

writer.close()
```

**Use cases:**
- Result files that may be empty (e.g., `_broken.csv` when no corrupt files)
- Avoid creating empty files
- MediaIntegrityCheck output files

### Eager Opening

File is created immediately when `open()` is called:

```python
# File doesn't exist yet
writer = DebugLogWriter('debug.csv')

# File created NOW (with header)
writer.open()

# Write data later
writer.write(record)

writer.close()
```

**Use cases:**
- Debug logs where you want immediate file creation
- When header presence matters before data
- Progress visibility (file exists from start)

## CSV Escaping

The writers use Python's `csv.writer` which handles:

- Quoting fields containing commas, quotes, or newlines
- Escaping embedded quotes (doubling them)
- Preserving newlines within fields

This is important for debug logs where tool output may contain multi-line error messages or special characters.

### Example

Input:
```python
record.stderr = 'Error: Invalid\nframe at position 1234'
```

Output CSV:
```csv
...,result,decision_reason,error_message,...
...,"Error: Invalid
frame at position 1234",decision_reason,,...
```

The quoted field preserves the newline, allowing proper parsing when read back.

## Integration with Tackles

### MediaIntegrityCheck

Uses streaming writers for all output files:

```python
# Category outputs (lazy open - only created if non-empty)
ok_writer = StreamingListingWriter(f'{base}_ok.csv')
broken_writer = StreamingListingWriter(f'{base}_broken.csv')
# ... etc

# Debug log (eager open - created immediately)
if self.debug_log_path:
    debug_writer = DebugLogWriter(self.debug_log_path)
    debug_writer.open()
```

### FclonesDuplicates

```python
with StreamingListingWriter(output_path, include_header=self.include_header) as writer:
    for entry in parsed_entries:
        writer.write(entry)
```

### ValidateCopy (Generate Mode)

```python
with StreamingListingWriter(output_path, include_header=include_header) as writer:
    for entry in entries:
        writer.write(entry)
```

## Creating Custom Writers

To create a writer for a new data type:

```python
from dataclasses import dataclass
from typing import List
from common.streaming_csv import StreamingCsvWriter

@dataclass
class MyRecord:
    name: str
    value: int
    description: str

class MyRecordWriter(StreamingCsvWriter[MyRecord]):
    def __init__(self, path: str):
        super().__init__(
            path,
            header=('name', 'value', 'description'),
            lazy_open=True,
            flush_on_write=False,
        )
    
    def _to_row(self, record: MyRecord) -> List[str]:
        return [
            record.name,
            str(record.value),
            record.description,
        ]

# Usage
with MyRecordWriter('output.csv') as writer:
    writer.write(MyRecord('test', 42, 'A test record'))
```

## See Also

- [MediaIntegrityCheck](MediaIntegrityCheck.md) — Uses `StreamingListingWriter` and `DebugLogWriter`
- [ValidateCopy](ValidateCopy.md) — Uses `StreamingListingWriter` for listing generation
- [FclonesDuplicates](FclonesDuplicates.md) — Uses `StreamingListingWriter` for output
- [`common/streaming_csv.py`](../common/streaming_csv.py) — Source implementation
