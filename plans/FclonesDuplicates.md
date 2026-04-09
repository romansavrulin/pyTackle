# FclonesDuplicates Tackle Design

## Overview

**FclonesDuplicates** is a new tackle that parses [fclones](https://github.com/pkolaczk/fclones) duplicate file reports and generates canonical FileEntry listings compatible with ValidateCopy.

### Purpose

The fclones tool identifies duplicate files across directories but outputs its own custom report format. This tackle bridges fclones output to pyTackle's ecosystem, enabling:

1. **Duplicate analysis** — Parse fclones reports to understand duplicate groups
2. **Listing generation** — Convert duplicate data to canonical CSV format for ValidateCopy
3. **Integration** — Enable validation workflows using fclones-detected duplicates

### Typical Workflow

```
1. Run fclones      →    2. Parse report    →    3. Generate listing    →    4. Use with ValidateCopy
   (external tool)        (FclonesDuplicates)     (canonical CSV)             (validate/compare)
```

---

## fclones Report Format Analysis

### Header Section

The report begins with comment lines prefixed by `#`:

```
# Report by fclones 0.35.0
# Timestamp: 2026-03-30 04:31:29.522 +0300
# Command: '.\fclones.exe' group --no-ignore --hidden 'Q:\1T-0-no-recycle-skip-err' 'Q:\20T-0-no-recycle-skip-err'
# Base dir: Q:\\
# Total: 1268686168746 B (1.3 TB) in 62263 files in 29099 groups
# Redundant: 652430768023 B (652.4 GB) in 33164 files
# Missing: 0 B (0 B) in 0 files
```

| Header Field | Description |
|--------------|-------------|
| `Report by` | fclones version |
| `Timestamp` | Report generation time with timezone |
| `Command` | Full command line used |
| `Base dir` | Base directory for relative paths |
| `Total` | Total size and file/group counts |
| `Redundant` | Size and count of redundant files |
| `Missing` | Files that were expected but not found |

### Duplicate Group Format

Each duplicate group has a header line followed by indented file paths:

```
<hash>, <size_bytes> B (<human_readable>) * <count>:
    <path_1>
    <path_2>
    ...
```

**Example:**
```
8593af76cd7c0818f0e6f8c0c3cc0e7d, 10248846420 B (10.2 GB) * 2:
    Q:\\20T-0-no-recycle-skip-err\\Дополнительно Найденные Файлы\\$$$Папка770506755\\день 10\\GX015735.MP4
    Q:\\20T-0-no-recycle-skip-err\\Дополнительно Найденные Файлы\\$$$Папка770506755\\последний день\\Go pro 11_1\\GX015735.MP4
```

### Format Details

| Element | Format | Notes |
|---------|--------|-------|
| Hash | 32-char hex string | MetroHash by default |
| Size | Integer followed by ` B` | Bytes |
| Human size | Parenthesized | e.g., `(10.2 GB)` |
| Count | Integer after `*` | Number of duplicates |
| Paths | 4-space indented | Windows escaped backslashes |
| Encoding | UTF-8 | Supports Unicode (Cyrillic, etc.) |

### Hash Algorithm Note

fclones uses **MetroHash** by default — a non-cryptographic hash optimized for speed. This is different from MD5/SHA used by most file verification tools. The hash is suitable for duplicate detection but NOT for cryptographic verification.

When generating listings:
- Store hash as `metrohash:<hexdigest>` to distinguish from MD5
- Consider providing option to recalculate with MD5/SHA for ValidateCopy compatibility

---

## Parser Design

### Parsing Strategy

```
┌─────────────────────────────────────────────────────────────┐
│                    fclones Report Parser                     │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  1. Header Parsing                                           │
│     ├─ Skip comment lines starting with #                   │
│     ├─ Extract metadata: version, timestamp, base_dir       │
│     └─ Store for logging/reference                          │
│                                                              │
│  2. Group Parsing                                            │
│     ├─ Detect group header: regex for hash,size,count       │
│     ├─ Parse subsequent indented lines as paths             │
│     └─ Create DuplicateGroup objects                        │
│                                                              │
│  3. Path Normalization                                       │
│     ├─ Handle Windows escaped backslashes                   │
│     ├─ Convert to forward slashes                           │
│     └─ Strip base directory prefix if present               │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### Data Structures

#### DuplicateGroup

Intermediate structure representing one group of duplicate files:

```python
@dataclass
class DuplicateGroup:
    hash: str           # MetroHash hex digest
    size: int           # File size in bytes
    count: int          # Number of duplicates
    paths: list[str]    # List of file paths
```

#### Conversion to FileEntry

Each path in a DuplicateGroup maps to a FileEntry:

| DuplicateGroup Field | FileEntry Field | Notes |
|---------------------|-----------------|-------|
| `hash` | `checksum` | As `metrohash:<hash>` |
| `size` | `size` | Direct mapping |
| `paths[i]` | `path` | Normalized path |
| — | `entry_type` | Always `f` (files only) |
| — | `creation` | `None` (not in report) |
| — | `access` | `None` (not in report) |
| — | `modify` | `None` (not in report) |
| — | `permissions` | `None` (not in report) |
| — | `uid` | `None` (not in report) |
| — | `gid` | `None` (not in report) |

### Regex Patterns

```python
# Group header: hash, size, count
RE_GROUP_HEADER = re.compile(
    r'^([0-9a-fA-F]+),\s*'           # hash
    r'(\d+)\s*B\s*'                   # size in bytes
    r'\([^)]+\)\s*\*\s*'              # human-readable (ignored)
    r'(\d+):$'                        # count
)

# Indented path line (4 spaces)
RE_PATH_LINE = re.compile(r'^    (.+)$')

# Header comment
RE_HEADER = re.compile(r'^#\s*(.+)$')

# Base dir extraction
RE_BASE_DIR = re.compile(r'^Base dir:\s*(.+)$')
```

---

## CLI Interface Design

### Mode Selection

Following ValidateCopy's pattern with mutually exclusive modes:

| Mode | Argument | Description |
|------|----------|-------------|
| **Parse** | `--parse REPORT` | Parse fclones report and output summary |
| **Generate** | `--generate LISTING` | Generate canonical CSV listing from report |

### Positional Arguments

| Argument | Description |
|----------|-------------|
| `report_file` | Path to fclones report file |

### Common Options

| Option | Description |
|--------|-------------|
| `--base-dir PATH` | Override base directory for path resolution |
| `--strip-prefix PREFIX` | Prefix to strip from paths before output |
| `--hash-format FORMAT` | How to store hash: `metrohash` (default), `raw`, or `recalculate:ALGO` |
| `-v` | Verbose output |
| `-q, --quiet` | Minimal output |

### Generate Mode Options

| Option | Description |
|--------|-------------|
| `--output PATH` | Output listing file path (required) |
| `--include SELECTION` | Which files to include: `all`, `first`, `duplicates` |
| `--group-id` | Add group ID column for tracking duplicate groups |

### Example Commands

```bash
# Parse and show summary
pyTackle FclonesDuplicates --parse report.txt

# Generate listing with all files
pyTackle FclonesDuplicates --generate listing.csv report.txt

# Generate listing with only first file from each group (canonical copies)
pyTackle FclonesDuplicates --generate listing.csv --include first report.txt

# Generate listing with path prefix stripped
pyTackle FclonesDuplicates --generate listing.csv --strip-prefix "Q:\\" report.txt

# Recalculate checksums as MD5 for ValidateCopy compatibility
pyTackle FclonesDuplicates --generate listing.csv --hash-format recalculate:md5 report.txt
```

---

## Output Listing Format

### Canonical 10-Column CSV

Output follows the same format as ValidateCopy's canonical listing:

| Column | Index | Content for fclones data |
|--------|-------|--------------------------|
| creation | 0 | Empty (not available) |
| access | 1 | Empty (not available) |
| modify | 2 | Empty (not available) |
| checksum | 3 | `metrohash:<hash>` or recalculated |
| entry_type | 4 | `f` (always files) |
| permissions | 5 | Empty (not available) |
| uid | 6 | Empty (not available) |
| gid | 7 | Empty (not available) |
| size | 8 | File size in bytes |
| path | 9 | Normalized file path |

### Example Output

```csv
,,,metrohash:8593af76cd7c0818f0e6f8c0c3cc0e7d,f,,,10248846420,20T-0-no-recycle-skip-err/Дополнительно Найденные Файлы/$$$Папка770506755/день 10/GX015735.MP4
,,,metrohash:8593af76cd7c0818f0e6f8c0c3cc0e7d,f,,,10248846420,20T-0-no-recycle-skip-err/Дополнительно Найденные Файлы/$$$Папка770506755/последний день/Go pro 11_1/GX015735.MP4
,,,metrohash:aebab6d5c723236dee40b8fe466fab9f,f,,,4515595719,20T-0-no-recycle-skip-err/Дополнительно Найденные Файлы/$$$Папка770506755/День 6/Insta Ace/VID_20240808_175420_008.mp4
```

### Integration with ValidateCopy

The generated listing can be used with ValidateCopy for:

1. **Size validation** — Verify file sizes match
2. **Path existence** — Check all files exist at expected paths
3. **Checksum validation** — If using `--hash-format recalculate:md5`

```bash
# Generate listing with MD5 checksums
pyTackle FclonesDuplicates --generate duplicates.csv --hash-format recalculate:md5 report.txt

# Validate files against listing
pyTackle ValidateCopy --validate duplicates.csv --attrs checksum,size /destination
```

---

## Implementation Architecture

### Class Structure

```python
class FclonesDuplicates(TackleFactory):
    """Parse fclones duplicate reports and generate canonical listings."""
    
    @classmethod
    def arg_parser(cls, subparser):
        # Mode selection (mutually exclusive)
        mode_group = subparser.add_mutually_exclusive_group(required=True)
        mode_group.add_argument('--parse', ...)
        mode_group.add_argument('--generate', ...)
        
        # Common options
        subparser.add_argument('report_file', ...)
        subparser.add_argument('--base-dir', ...)
        subparser.add_argument('--strip-prefix', ...)
        subparser.add_argument('--hash-format', ...)
        subparser.add_argument('-v', ...)
        subparser.add_argument('-q', '--quiet', ...)
        
        # Generate mode options
        subparser.add_argument('--include', ...)
        subparser.add_argument('--group-id', ...)
    
    def __init__(self, parser):
        super().__init__(parser)
        # Parse arguments and initialize mode
        ...
    
    def do(self) -> int:
        if self.mode == 'parse':
            return self._do_parse()
        elif self.mode == 'generate':
            return self._do_generate()
    
    def _do_parse(self) -> int:
        """Parse report and display summary."""
        ...
    
    def _do_generate(self) -> int:
        """Parse report and generate canonical listing."""
        ...
```

### Module Functions

```python
# In tackles/FclonesDuplicates.py

def parse_fclones_report(
    report_path: str,
    strip_prefix: Optional[str] = None,
) -> tuple[dict, list[DuplicateGroup]]:
    """Parse fclones report file.
    
    Returns:
        Tuple of (header_metadata, list_of_duplicate_groups)
    """
    ...

def normalize_fclones_path(
    raw_path: str,
    strip_prefix: Optional[str] = None,
) -> str:
    """Normalize Windows-escaped paths from fclones output.
    
    - Converts \\\\ to /
    - Strips drive letter if present
    - Removes specified prefix
    """
    ...

def duplicate_group_to_entries(
    group: DuplicateGroup,
    hash_format: str = 'metrohash',
    include: str = 'all',
) -> Iterator[FileEntry]:
    """Convert a DuplicateGroup to FileEntry objects.
    
    Args:
        group: The duplicate group to convert
        hash_format: 'metrohash', 'raw', or 'recalculate:ALGO'
        include: 'all', 'first', or 'duplicates'
    """
    ...
```

### Registration

The tackle auto-registers via `__init_subclass__` in TackleFactory:

```python
# In tackles/__init__.py
from .FclonesDuplicates import FclonesDuplicates  # Auto-registers
```

---

## Future Improvements

### Phase 1: Core Functionality
- [x] Parse fclones report format
- [x] Generate canonical CSV listings
- [x] Path normalization for Windows paths
- [x] Unicode support (Cyrillic, etc.)

### Phase 2: Enhanced Features
- [ ] **Checksum recalculation** — Option to recalculate MD5/SHA for ValidateCopy compatibility
- [ ] **Group filtering** — Filter by minimum size, group count, or path patterns
- [ ] **Statistics output** — Detailed statistics in JSON format
- [ ] **Streaming parser** — Handle very large reports without loading all into memory

### Phase 3: Advanced Integration
- [ ] **Direct fclones invocation** — Run fclones and parse output in one command
- [ ] **Duplicate resolution** — Interactive or rule-based duplicate resolution
- [ ] **ValidateCopy integration** — Direct pipeline to validation without intermediate files
- [ ] **Multiple report merging** — Combine reports from different runs

### Phase 4: Additional Output Formats
- [ ] **JSON output** — Machine-readable format for scripting
- [ ] **HTML report** — Human-readable duplicate report
- [ ] **SQLite database** — For complex queries on large datasets

---

## Error Handling

### Expected Errors

| Error | Handling |
|-------|----------|
| File not found | Exit with clear error message |
| Invalid report format | Log warning, skip malformed lines |
| Path not found (for recalculate) | Log warning, skip entry |
| Unicode decode error | Use `utf-8-sig` with fallback to `latin-1` |
| Permission denied | Log warning, continue with other files |

### Validation

```python
def validate_report_format(first_lines: list[str]) -> bool:
    """Check if file appears to be a valid fclones report."""
    # Look for characteristic header lines
    has_fclones_header = any('fclones' in line for line in first_lines)
    has_group = any(RE_GROUP_HEADER.match(line) for line in first_lines)
    return has_fclones_header or has_group
```

---

## Testing Strategy

### Unit Tests

1. **Parser tests**
   - Parse valid report header
   - Parse duplicate groups
   - Handle Unicode paths
   - Handle malformed lines gracefully

2. **Path normalization tests**
   - Windows backslash conversion
   - Drive letter handling
   - Prefix stripping

3. **FileEntry conversion tests**
   - Correct field mapping
   - Hash format handling
   - Include filtering (all/first/duplicates)

### Integration Tests

1. **End-to-end workflow**
   - Parse sample report → Generate listing → Validate with ValidateCopy

2. **Large file handling**
   - Test with reports containing 10k+ groups

3. **Error recovery**
   - Continue parsing after malformed lines

---

## Dependencies

### Internal
- [`common/FileEntry.py`](../common/FileEntry.py) — FileEntry dataclass
- [`common/listing.py`](../common/listing.py) — CSV listing I/O
- [`common/checksum.py`](../common/checksum.py) — For optional recalculation
- [`tackles/TackleFactory.py`](../tackles/TackleFactory.py) — Base class

### External
- Standard library only (no new dependencies)

---

## Summary

FclonesDuplicates bridges the gap between fclones' duplicate detection capabilities and pyTackle's file validation ecosystem. The design:

1. **Follows established patterns** — CLI structure matches ValidateCopy
2. **Maintains compatibility** — Outputs canonical FileEntry listings
3. **Handles edge cases** — Unicode, Windows paths, large files
4. **Enables workflows** — Parse → Generate → Validate pipeline
5. **Plans for growth** — Extensible architecture for future features
