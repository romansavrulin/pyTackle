# FclonesDuplicates

Parse [fclones](https://github.com/pkolaczk/fclones) duplicate file reports and generate canonical FileEntry listings compatible with ValidateCopy.

## Overview

**FclonesDuplicates** bridges the gap between fclones' duplicate detection capabilities and pyTackle's file validation ecosystem. It can:

- **Parse fclones reports** — Read duplicate group data from fclones output files
- **Generate listings** — Create CSV manifests compatible with ValidateCopy
- **Filter duplicates** — Extract canonical copies, duplicates only, or all files

### Typical Workflow

```
1. Run fclones      →    2. Parse report    →    3. Generate listing    →    4. Use with ValidateCopy
   (external tool)        (FclonesDuplicates)     (canonical CSV)             (validate/compare)
```

## Prerequisites

### fclones Installation

Install fclones from [https://github.com/pkolaczk/fclones](https://github.com/pkolaczk/fclones):

```bash
# macOS (Homebrew)
brew install fclones

# Windows (Scoop)
scoop install fclones

# Cargo (cross-platform)
cargo install fclones
```

### Generate fclones Report

Run fclones `group` command to identify duplicates:

```bash
# Basic duplicate scan
fclones group /path/to/scan > report.txt

# Include hidden files
fclones group --hidden /path/to/scan > report.txt

# Scan multiple directories
fclones group /path1 /path2 > report.txt
```

## Usage

```bash
pyTackle FclonesDuplicates <report_file> [options]
```

## CLI Reference

### Positional Arguments

| Argument | Description |
|----------|-------------|
| `report_file` | Path to fclones report file (required) |

### Output Options

| Option | Description |
|--------|-------------|
| `-o, --output FILE` | Output listing file path (default: stdout) |

### Path Options

| Option | Description |
|--------|-------------|
| `--strip-prefix PREFIX` | Strip prefix from all paths (e.g., `Q:\\` or `/mnt/data/`) |
| `--base-dir PATH` | Override base directory from report (reserved for future use) |

### Selection Options

| Option | Description |
|--------|-------------|
| `--include {all,first,duplicates}` | Which files to include (default: `all`) |
| `--group-id` | Add group ID tracking as comment (informational only) |

#### Include Mode Details

| Mode | Description | Use Case |
|------|-------------|----------|
| `all` | All files in all duplicate groups | Full inventory of duplicates |
| `first` | First file from each group (canonical copy) | Extract unique files |
| `duplicates` | All except first (true duplicates) | Identify files safe to delete |

### Verbosity Options

| Option | Description |
|--------|-------------|
| `-v, --verbose` | Enable debug-level logging |
| `-q, --quiet` | Suppress non-error output |

## Examples

### Basic: Generate Listing from Report

Parse a fclones report and write a CSV listing:

```bash
pyTackle FclonesDuplicates report.txt -o duplicates.csv
```

### Extract Canonical Copies Only (First per Group)

Get only the first file from each duplicate group — these are the "originals" to keep:

```bash
pyTackle FclonesDuplicates report.txt -o canonical.csv --include first
```

### Extract Duplicates Only

Get all files except the first in each group — candidates for removal:

```bash
pyTackle FclonesDuplicates report.txt -o to_delete.csv --include duplicates
```

### Strip Drive/Path Prefix

When paths in the report include a prefix not present in your destination:

```bash
# Windows drive letter
pyTackle FclonesDuplicates report.txt -o listing.csv --strip-prefix "Q:\\"

# Mount point prefix
pyTackle FclonesDuplicates report.txt -o listing.csv --strip-prefix "/mnt/backup/"
```

### Output to Stdout

Omit `-o` to write CSV directly to stdout:

```bash
pyTackle FclonesDuplicates report.txt > listing.csv
```

### Pipe to ValidateCopy

Combine with ValidateCopy to validate duplicates exist at a destination:

```bash
# Generate listing and validate in one pipeline
pyTackle FclonesDuplicates report.txt -o /tmp/listing.csv --strip-prefix "Q:\\"
pyTackle ValidateCopy --validate /tmp/listing.csv --attrs size /destination/path
```

### Verbose Mode for Debugging

See detailed parsing information:

```bash
pyTackle FclonesDuplicates report.txt -o listing.csv -v
```

## Input Format

### fclones Report Structure

The fclones `group` command generates reports with a header section and duplicate groups.

#### Header Section

Comment lines starting with `#`:

```
# Report by fclones 0.35.0
# Timestamp: 2026-03-30 04:31:29.522 +0300
# Command: '.\fclones.exe' group --no-ignore --hidden 'Q:\data'
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
| `Base dir` | Base directory for paths |
| `Total` | Total size, file count, and group count |
| `Redundant` | Size and count of redundant (duplicate) files |
| `Missing` | Files expected but not found |

#### Duplicate Groups

Each group has a header line followed by indented file paths:

```
8593af76cd7c0818f0e6f8c0c3cc0e7d, 10248846420 B (10.2 GB) * 2:
    Q:\\path\\to\\original\\file.mp4
    Q:\\path\\to\\duplicate\\file.mp4
```

**Group header format:**
```
<hash>, <size_bytes> B (<human_size>) * <count>:
```

| Element | Format | Example |
|---------|--------|---------|
| Hash | 32-char hex string | `8593af76cd7c0818f0e6f8c0c3cc0e7d` |
| Size | Integer + ` B` | `10248846420 B` |
| Human size | Parenthesized | `(10.2 GB)` |
| Count | Integer after `*` | `2` |

**File paths:**
- 4-space indented
- Windows escaped backslashes (`\\`)
- UTF-8 encoded (supports Unicode/Cyrillic)

### Hash Algorithm Note

fclones uses **MetroHash** by default — a non-cryptographic hash optimized for speed. This is different from MD5/SHA used by traditional file verification tools.

- MetroHash is suitable for **duplicate detection**
- MetroHash is **NOT** suitable for cryptographic verification
- The output stores hashes as `metrohash:<hexdigest>` to distinguish from MD5

## Output Format

### Canonical 10-Column CSV

Output follows ValidateCopy's canonical listing format. By default, a header row is included:

| Column | Index | Content for fclones data |
|--------|-------|--------------------------|
| creation | 0 | Empty (not in fclones output) |
| access | 1 | Empty (not in fclones output) |
| modify | 2 | Empty (not in fclones output) |
| checksum | 3 | `metrohash:<hash>` |
| entry_type | 4 | `f` (files only) |
| permissions | 5 | Empty (not in fclones output) |
| uid | 6 | Empty (not in fclones output) |
| gid | 7 | Empty (not in fclones output) |
| size | 8 | File size in bytes |
| path | 9 | Normalized file path |

### Example Output Row

```csv
,,,metrohash:8593af76cd7c0818f0e6f8c0c3cc0e7d,f,,,10248846420,photos/vacation/IMG_001.jpg
```

### Path Normalization

Paths are automatically normalized:
- Windows double-backslashes (`\\`) → forward slashes (`/`)
- Single backslashes (`\`) → forward slashes (`/`)
- Prefix stripped if `--strip-prefix` specified

## Workflow Integration

### Workflow 1: Validate Duplicates at Destination

Verify that duplicate files exist at a backup location:

```bash
# 1. Generate listing from fclones report
pyTackle FclonesDuplicates report.txt -o duplicates.csv --strip-prefix "Q:\\"

# 2. Validate files exist with correct sizes
pyTackle ValidateCopy --validate duplicates.csv --attrs size /backup/path
```

### Workflow 2: Identify Safe-to-Delete Files

Find duplicate files that can be safely removed:

```bash
# 1. Get duplicates only (exclude first/canonical copy)
pyTackle FclonesDuplicates report.txt -o to_delete.csv --include duplicates

# 2. Review the list before deletion
cat to_delete.csv | wc -l  # Count files

# 3. Optionally validate they exist before deletion
pyTackle ValidateCopy --validate to_delete.csv --attrs size /source/path
```

### Workflow 3: Create Inventory of Unique Files

Get one file from each duplicate set:

```bash
# Extract canonical copies
pyTackle FclonesDuplicates report.txt -o unique_files.csv --include first
```

### Workflow 4: Cross-Platform Path Translation

When the fclones report was generated on Windows but you're validating on Linux/macOS:

```bash
# Strip Windows drive letter and convert paths
pyTackle FclonesDuplicates windows_report.txt \
    -o listing.csv \
    --strip-prefix "D:\\backup\\"

# Validate against mounted share
pyTackle ValidateCopy --validate listing.csv --attrs size /mnt/backup
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Error (file not found, invalid format, etc.) |

## Platform Support

FclonesDuplicates works on all platforms:

| Platform | Status |
|----------|--------|
| **Windows** | ✅ Full support |
| **macOS** | ✅ Full support |
| **Linux** | ✅ Full support |

## Limitations

### Current Limitations

1. **No timestamp data** — fclones reports don't include file timestamps; these fields are empty in output
2. **No permission data** — File permissions are not available from fclones reports
3. **MetroHash only** — Currently outputs MetroHash checksums as-is; no recalculation to MD5/SHA

### Compatibility with ValidateCopy

When using the listing with ValidateCopy:

- ✅ **Size validation** — Works (`--attrs size`)
- ✅ **Path existence** — Works (file presence check)
- ⚠️ **Checksum validation** — Requires MetroHash support in ValidateCopy (not yet implemented)
- ❌ **Timestamp validation** — Not available (empty fields)

## Future Improvements

Planned enhancements (see [`plans/FclonesDuplicates.md`](../plans/FclonesDuplicates.md)):

- **Checksum recalculation** — Option to recalculate MD5/SHA for full ValidateCopy compatibility
- **Group filtering** — Filter by minimum size, group count, or path patterns
- **Statistics output** — Detailed statistics in JSON format
- **Streaming parser** — Handle very large reports without loading all into memory
- **Direct fclones invocation** — Run fclones and parse output in one command

## See Also

- [ValidateCopy](ValidateCopy.md) — Validate file integrity and restore metadata
- [fclones documentation](https://github.com/pkolaczk/fclones) — External duplicate finder tool
- [pyTackle README](README.md) — Overview of all available tackles
