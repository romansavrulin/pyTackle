# ValidateCopy

Verify file copy integrity and restore metadata not preserved during copy operations.

## Overview

**ValidateCopy** is a versatile tackle for ensuring file copies are exact replicas of their sources. It can:

- **Generate listings** — Create a CSV manifest of files with timestamps, checksums, permissions, and ownership
- **Validate copies** — Compare files against a listing to verify integrity (checksums, sizes, timestamps)
- **Apply/fix metadata** — Restore timestamps and permissions that weren't preserved during copy

### Typical Workflow

```
1. Generate listing    →    2. Copy files    →    3. Validate    →    4. Apply metadata
   (source)                 (any method)          (destination)        (if needed)
```

## Operating Modes

ValidateCopy has three mutually exclusive modes of operation. Each mode takes a listing file path as its argument.

### Validate Mode (`--validate <listing>`)

Validates files against a pre-existing listing. No changes are made to the filesystem.

```bash
pyTackle ValidateCopy --validate listing.csv --attrs checksum,size /path/to/validate
```

- `--attrs` specifies which attributes to compare (default: all available)
- Use `-q` / `--quiet` to show only failures
- Exit code: 0 = all entries match, 1 = validation failures

### Generate Mode (`--generate <listing>`)

Generates a listing file from the filesystem.

```bash
pyTackle ValidateCopy --generate output.csv --attrs checksum /path/to/scan
```

- `--attrs checksum` enables checksum calculation (off by default)
- Use `--types fd` to include both files and directories

### Apply Mode (`--apply <listing>`)

Applies attributes from a listing to the filesystem (timestamps, etc.).

```bash
pyTackle ValidateCopy --apply listing.csv --attrs creation,modify /path/to/update
```

- `--attrs` specifies which attributes to set (creation, access, modify)
- Use `--dry-run` to preview changes without modifying anything
- Default: applies creation, access, and modify timestamps

## CLI Reference

### Mode Selection (mutually exclusive, one required)

| Option | Description |
|--------|-------------|
| `--validate PATH` | Validate filesystem against the specified listing file. |
| `--generate PATH` | Generate a listing from the filesystem and write to the specified path. |
| `--apply PATH` | Apply metadata from the specified listing to the filesystem. |

### Positional Arguments

| Argument | Description |
|----------|-------------|
| `base_dir` | Local base directory to resolve relative paths against (required). |

### Common Options

| Option | Description |
|--------|-------------|
| `--attrs ATTRS` | Comma-separated list of attributes. Meaning depends on mode (see below). |
| `--types TYPES` | Comma-separated entry types to process: `f` (file), `d` (directory), `l` (symlink). Default: `d`. |
| `-v` | Verbose output (debug level logging). |

### Attribute Options by Mode

The `--attrs` option behaves differently depending on the active mode:

| Mode | `--attrs` Meaning | Default |
|------|-------------------|---------|
| **Validate** | Attributes to compare | `size,creation,permissions,uid,gid,checksum,entry_type,path` |
| **Generate** | Include checksum in listing (use `--attrs checksum` to enable) | (no checksum) |
| **Apply** | Attributes to set on filesystem | `creation,access,modify` |

### Validation Options

| Option | Description |
|--------|-------------|
| `-q, --quiet` | In validation mode, omit OK entries from output (show only failures). |

### Generation Options

| Option | Description |
|--------|-------------|
| `--checksum-algorithm ALG` | Algorithm for checksum calculation. Default: `md5`. Supports any algorithm from Python's hashlib. |

### Apply/Path Options

| Option | Description |
|--------|-------------|
| `--attr-map MAP` | Advanced: Comma-separated mapping of filesystem attributes to listing column selectors. Format: `attr:selector[,attr:selector,…]`. See [Attribute Mapping](#attribute-mapping). |
| `--script-base-path PATH` | Leading directory prefix to strip from paths in the listing before resolving. |
| `--dry-run` | Preview changes without modifying timestamps. |

## Typical Workflows with Examples

### Workflow 1: Generate listing from source

Create a comprehensive listing with checksums for files and directories:

```bash
pyTackle ValidateCopy \
    --generate source_listing.csv \
    --attrs checksum \
    --types fd \
    /source/path
```

This generates a 10-column CSV with all metadata (timestamps, permissions, ownership, checksums).

### Workflow 2: Validate copy against listing

After copying files to a destination, validate that all files match:

```bash
pyTackle ValidateCopy \
    --validate source_listing.csv \
    /destination/path
```

Output shows `OK:` or `FAIL:` for each entry, with a summary at the end.

### Workflow 3: Validate only checksums (fast data integrity check)

When you only care about data integrity (not metadata):

```bash
pyTackle ValidateCopy \
    --validate source_listing.csv \
    --attrs checksum \
    /destination/path
```

### Workflow 4: Validate and show only failures (quiet mode)

For large directories, show only problems:

```bash
pyTackle ValidateCopy \
    --validate source_listing.csv \
    -q \
    /destination/path
```

### Workflow 5: Apply/fix metadata that wasn't preserved

Many copy tools don't preserve creation timestamps or ownership. Fix them:

```bash
pyTackle ValidateCopy \
    --apply source_listing.csv \
    /destination/path
```

By default, this applies `creation`, `access`, and `modify` timestamps from the listing.

### Workflow 6: Apply only creation timestamps

When you only need to fix creation times:

```bash
pyTackle ValidateCopy \
    --apply source_listing.csv \
    --attrs creation \
    /destination/path
```

### Workflow 7: Preview changes (dry run)

See what would be changed without modifying anything:

```bash
pyTackle ValidateCopy \
    --apply source_listing.csv \
    --dry-run \
    /destination/path
```

### Workflow 8: Process both files and directories

By default, only directories are processed. To include files:

```bash
pyTackle ValidateCopy \
    --apply source_listing.csv \
    --types fd \
    /destination/path
```

## Listing Format

ValidateCopy uses a canonical 10-column CSV format. By default, generated listings include a header row:

| Column | Index | Description |
|--------|-------|-------------|
| creation | 0 | Creation timestamp (ISO 8601) |
| access | 1 | Last access timestamp (ISO 8601) |
| modify | 2 | Last modification timestamp (ISO 8601) |
| checksum | 3 | File checksum (empty for directories) |
| entry_type | 4 | `f` (file), `d` (directory), or `l` (symlink) |
| permissions | 5 | Octal permissions (e.g., `0755`) |
| uid | 6 | Owner user ID |
| gid | 7 | Owner group ID |
| size | 8 | File size in bytes |
| path | 9 | Relative path from base directory |

### Example Row

```csv
2024-01-15T10:30:00,2024-03-20T14:22:33,2024-01-15T10:30:00,d41d8cd98f00b204e9800998ecf8427e,f,0644,501,20,1234,photos/vacation/IMG_001.jpg
```

### Header Auto-Detection

When reading listings (in validate or apply mode), ValidateCopy automatically detects whether the first row is a header. The detection works by checking if the column values match the expected attribute names (e.g., `creation`, `access`, `modify`, etc.). Header rows are automatically skipped.

### Legacy Format Support

ValidateCopy also auto-detects a 6-column Linux stat format for backward compatibility:

| Column | Index | Description |
|--------|-------|-------------|
| creation | 0 | Creation timestamp |
| access | 1 | Access timestamp |
| modify | 2 | Modification timestamp |
| ctime | 3 | (ignored) |
| entry_type | 4 | Entry type |
| path | 5 | Path |

## Attribute Mapping

The `--attr-map` option controls which listing columns drive which filesystem timestamps.

### Format

```
--attr-map="attr:selector[,attr:selector,…]"
```

### Valid Attributes

- `creation` — Creation timestamp (birthtime)
- `access` — Last access timestamp
- `modify` — Last modification timestamp

### Valid Selectors

| Selector | Description |
|----------|-------------|
| `0`, `1`, `2`, ... | 0-based column index |
| `earliest` or `e` | Pick the minimum (oldest) date from the row |
| `latest` or `l` | Pick the maximum (newest) date from the row |

### Examples

```bash
# Set creation from column 1, modify from earliest available date
--attr-map="creation:1,modify:earliest"

# Use short aliases
--attr-map="creation:e,modify:l"

# Only set creation timestamp from column 0
--attr-map="creation:0"
```

### Default Behavior

When `--attr-map` is empty (the default in apply mode), the canonical mapping is used:

- `creation` ← column 0
- `access` ← column 1  
- `modify` ← column 2

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success (or validation passed with all entries matching) |
| 1 | Validation failed (one or more entries don't match) |

## Platform Support

| Platform | Creation Time | Access/Modify Time |
|----------|--------------|-------------------|
| **Windows** | ✅ Full support (Win32 API) | ✅ Full support |
| **macOS** | ✅ Full support (SetFile) | ✅ Full support |
| **Linux** | ⚠️ Warning only (not supported by filesystem) | ✅ Full support |

## Backward Compatibility

### SetCreationTime Alias

`SetCreationTime` is a deprecated alias for `ValidateCopy`. Both commands are functionally identical:

```bash
# These are equivalent:
pyTackle SetCreationTime --apply file.csv /path
pyTackle ValidateCopy --apply file.csv /path
```

Using `SetCreationTime` will emit a deprecation warning. Migrate to `ValidateCopy` for new scripts.

## Advanced Usage

### Handling UNC Paths

ValidateCopy automatically normalizes UNC paths:

```
\\server\share\rest\of\path → rest/of/path
```

### Stripping Path Prefixes

When the listing contains paths with a common prefix that doesn't exist in the destination:

```bash
# Listing contains: server/share/photos/2020/img.jpg
# Destination has:  /backup/photos/2020/img.jpg

pyTackle ValidateCopy \
    --apply source.csv \
    --script-base-path "server/share" \
    /backup
```

The `--script-base-path` strips `server/share`, so the resolved path becomes `/backup/photos/2020/img.jpg`.

## See Also

- [CopyValidateMD5](CopyValidateMD5.md) — Simpler MD5-based copy validation
- [pyTackle README](README.md) — Overview of all available tackles
