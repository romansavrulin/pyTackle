# CopyValidateMD5

Simple MD5-based copy validation — copy files from an MD5 manifest while verifying checksums.

## Overview

**CopyValidateMD5** copies files listed in an MD5 manifest file, verifying checksums at both source and destination to ensure data integrity.

## Usage

```bash
pyTackle CopyValidateMD5 --from-dir <src> --to-dir <dst> --from-file <md5-manifest>
```

## Options

| Option | Description |
|--------|-------------|
| `--from-dir PATH` | Source directory containing the files to copy (required) |
| `--to-dir PATH` | Destination directory for copied files (required) |
| `--from-file PATH` | Path to the MD5 manifest file (required) |
| `-v` | Enable verbose output (debug logging) |

## Exit Codes

| Code | Description |
|------|-------------|
| `1` | Source directory (`--from-dir`) does not exist |
| `2` | Destination directory (`--to-dir`) does not exist |
| `3` | MD5 manifest file (`--from-file`) does not exist |

## MD5 Manifest Format

The manifest file should contain one entry per line in standard MD5SUM format:

```
d41d8cd98f00b204e9800998ecf8427e  path/to/file1.txt
098f6bcd4621d373cade4e832627b4f6  path/to/file2.txt
```

## Example

```bash
# Create MD5 manifest of source files
find /source/data -type f -exec md5sum {} \; > manifest.md5

# Copy and validate
pyTackle CopyValidateMD5 \
    --from-dir /source/data \
    --to-dir /backup/data \
    --from-file manifest.md5
```

## See Also

- [ValidateCopy](ValidateCopy.md) — More comprehensive copy validation with metadata support
- [pyTackle README](README.md) — Overview of all available tackles
