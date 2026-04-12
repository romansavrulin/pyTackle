# pyTackle Documentation

Collection of command-line tools ("tackles") for various automation tasks.

## Available Tackles

| Tackle | Description |
|--------|-------------|
| [ValidateCopy](ValidateCopy.md) | Verify file copy integrity and restore metadata |
| [MediaIntegrityCheck](MediaIntegrityCheck.md) | Validate media file integrity using Linux system tools |
| [FclonesDuplicates](FclonesDuplicates.md) | Parse fclones duplicate file reports |
| [CopyValidateMD5](CopyValidateMD5.md) | Simple MD5-based copy validation |
| ZfsIotop | ZFS I/O monitoring |
| GetCoursera | Coursera content downloader |

## Developer Documentation

| Document | Description |
|----------|-------------|
| [StreamingCsv](StreamingCsv.md) | Memory-efficient streaming CSV writer infrastructure |

## Installation

```bash
pip install -e .
```

## Usage

```bash
pyTackle <TackleName> [options]
```

## Quick Start

### Generate a listing from source directory

```bash
pyTackle ValidateCopy --generate-listing source_listing.csv --base-dir /source/path --checksum --types fd
```

### Validate a copy against the listing

```bash
pyTackle ValidateCopy --listing source_listing.csv --base-dir /destination/path --validate
```

### Restore metadata that wasn't preserved during copy

```bash
pyTackle ValidateCopy --listing source_listing.csv --base-dir /destination/path
```

## Documentation Structure

- [`ValidateCopy.md`](ValidateCopy.md) — Full documentation for file copy validation and metadata restoration
- [`CopyValidateMD5.md`](CopyValidateMD5.md) — Simple MD5-based copy with checksum verification
