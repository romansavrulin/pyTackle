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

Available subcommands:

| Subcommand | Description |
|---|---|
| `ValidateCopy` | Verify file copy integrity and restore metadata |
| `CopyValidateMD5` | Copy files listed in an MD5 manifest, verifying checksums at source and destination |
| `ZfsIotop` | ZFS I/O monitoring |
| `GetCoursera` | Coursera content downloader |
| `TestTackle` | Minimal placeholder tackle |

📚 **[Full Documentation](docs/README.md)** — Detailed guides for each tackle

### CopyValidateMD5

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
