# pyTackle

A small Python CLI utility that dispatches sub-commands ("tackles") from a single entry point.

## Install

```bash
pip install -e .
```

## Usage

```bash
pytackle <subcommand> [options]
```

## Available Tackles

| Tackle | Description | Docs |
|--------|-------------|------|
| `CopyValidateMD5` | Copy files with MD5 validation | [docs](docs/CopyValidateMD5.md) |
| `CsvToSqlite` | Convert CSV files to SQLite database | [docs](docs/CsvToSqlite.md) |
| `FclonesDuplicates` | Find and manage duplicate files using fclones | [docs](docs/FclonesDuplicates.md) |
| `GetCoursera` | Scrape GetCourse.ru educational platform content | [docs](docs/GetCoursera.md) |
| `MediaIntegrityCheck` | Validate media file integrity (video/audio/images) | [docs](docs/MediaIntegrityCheck.md) |
| `ValidateCopy` | Validate file copies with checksums and attributes | [docs](docs/ValidateCopy.md) |
| `ZfsIotop` | ZFS I/O statistics visualization | [docs](docs/ZfsIotop.md) |

📚 **[Full Documentation](docs/README.md)** — Detailed guides for each tackle

## Common Modules

The `common/` package provides shared utilities used across tackles:

| Module | Description |
|--------|-------------|
| `FileEntry` | File metadata handling and representation |
| `StreamingCsv` | Memory-efficient CSV processing for large files |
| `checksum` | File hashing utilities (MD5, SHA256, etc.) |
| `attr_map` | Attribute mapping utilities for metadata transformation |

### Example: CopyValidateMD5

```bash
pytackle CopyValidateMD5 --from-dir <src> --to-dir <dst> --from-file <md5-manifest>
```

## Adding a new tackle

1. Create `tackles/MyTackle.py` with a class named `MyTackle` that extends `TackleFactory`.
2. Implement `arg_parser(cls, parser)` and `do(self)`.
3. Register it in `tackles/_cli.py`:

```python
MyTackle.register()
```

The `tackles/__init__.py` auto-discovers any `*.py` file in the package, so no further imports are needed.

## Development

```bash
# run without installing
python pyTackle <subcommand>
```
