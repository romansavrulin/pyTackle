# MediaIntegrityCheck

Validate media file integrity using Linux system tools.

## Overview

**MediaIntegrityCheck** is a tackle for automated media file integrity validation. It scans directories recursively and uses specialized system tools to verify file integrity, categorizing files into five result types.

### Key Features

- **Extensible tool registry** — Maps file extensions to validation tools via a simple dataclass configuration
- **System tool detection** — Checks tool availability and generates apt install commands
- **Recursive scanning** — Uses `os.walk()` with FileEntry integration and progress reporting
- **Five-category output** — Separate CSV listings for valid, corrupt, untestable, missing tool, and error files
- **Special case handling** — Supports ogg/opus stderr checking, qpdf exit code 3, compound extensions

### Platform Restriction

**Linux or WSL only** — This tackle relies on Linux-native tools like `ffprobe`, `jpeginfo`, `mp3val`, etc. A platform check is performed at startup with a clear error message if running on an unsupported platform.

## Installation

### Required System Tools

MediaIntegrityCheck uses external validation tools. Install them via apt:

| Package | Tool | File Types |
|---------|------|------------|
| `ffmpeg` | ffprobe | Video, WAV, AAC, M4A, WMA, AIFF, APE |
| `mp3val` | mp3val | MP3 |
| `flac` | flac | FLAC |
| `vorbis-tools` | ogginfo | OGG |
| `opus-tools` | opusinfo | Opus |
| `jpeginfo` | jpeginfo | JPEG |
| `pngcheck` | pngcheck | PNG |
| `imagemagick` | identify | GIF, BMP, TIFF, WebP, HEIC |
| `libimage-exiftool-perl` | exiftool | RAW formats (CR2, NEF, ARW, DNG) |
| `unzip` | unzip | ZIP, DOCX, XLSX, PPTX |
| `tar` | tar | TAR archives |
| `gzip` | gzip | GZIP |
| `bzip2` | bzip2 | BZIP2 |
| `xz` | xz | XZ |
| `lz4` | lz4 | LZ4 |
| `zstd` | zstd | Zstandard |
| `p7zip-full` | 7z | 7-Zip |
| `unrar` | unrar | RAR |
| `qpdf` | qpdf | PDF |
| `epubcheck` | epubcheck | EPUB |

### One-liner Install

Install all supported tools at once:

```bash
sudo apt-get install ffmpeg mp3val flac vorbis-tools opus-tools jpeginfo pngcheck imagemagick libimage-exiftool-perl unzip tar gzip bzip2 xz-utils lz4 zstd p7zip-full unrar qpdf epubcheck
```

### Check Tool Availability

Use `--list-tools` to see which tools are installed and which are missing:

```bash
pyTackle MediaIntegrityCheck --list-tools /any/path
```

This displays a table showing each extension, its validation tool, installation status, and install command.

### Get Install Command

Generate an apt-get command for only the missing tools:

```bash
pyTackle MediaIntegrityCheck --install-cmd /any/path
```

## Usage

```bash
pyTackle MediaIntegrityCheck [OPTIONS] DIRECTORY
```

### CLI Reference

#### Positional Arguments

| Argument | Description |
|----------|-------------|
| `directory` | Directory to scan recursively for media files (required) |

#### Options

| Option | Description |
|--------|-------------|
| `-o, --output BASE` | Base name for output files (default: `integrity_check`). Produces `BASE_ok.csv`, `BASE_broken.csv`, etc. |
| `--list-tools` | List all supported tools and their availability, then exit |
| `--install-cmd` | Print apt-get install command for missing tools, then exit |
| `--extensions EXT[,EXT,...]` | Filter which file extensions to check. Only files matching these extensions will be scanned. Example: `--extensions mp4,mp3,jpg` |
| `--timeout SECONDS` | Per-file validation timeout in seconds (default: 300) |

## Output Files

MediaIntegrityCheck produces up to five output CSV files, depending on validation results. Only non-empty listings are created.

| File | Description |
|------|-------------|
| `{base}_ok.csv` | Files confirmed valid by the validation tool |
| `{base}_broken.csv` | Files confirmed corrupt by the validation tool |
| `{base}_untestable.csv` | Files with unknown extensions (no validator defined in registry) |
| `{base}_missing_tool.csv` | Files where the required validator tool is not installed |
| `{base}_error.csv` | Files where tool execution failed (timeout, crash, permission denied) |

### CSV Format

Output files use the canonical 10-column CSV format (no header row):

| Column | Index | Description |
|--------|-------|-------------|
| creation | 0 | Creation timestamp |
| access | 1 | Access timestamp |
| modify | 2 | Modification timestamp |
| checksum | 3 | Empty (not calculated) |
| entry_type | 4 | Always `f` (file) |
| permissions | 5 | File permissions (octal) |
| uid | 6 | Owner UID |
| gid | 7 | Owner GID |
| size | 8 | File size in bytes |
| path | 9 | Absolute file path |

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success (no corrupt files found) |
| 1 | Corrupt files detected (check `_broken.csv`) |

## Supported Formats

### Video

| Extension | Tool | Package |
|-----------|------|---------|
| `.mp4`, `.mkv`, `.avi`, `.mov` | ffprobe | ffmpeg |
| `.wmv`, `.flv`, `.webm`, `.m4v` | ffprobe | ffmpeg |
| `.mpeg`, `.mpg`, `.3gp` | ffprobe | ffmpeg |
| `.ts`, `.m2ts`, `.vob` | ffprobe | ffmpeg |

### Audio

| Extension | Tool | Package |
|-----------|------|---------|
| `.mp3` | mp3val | mp3val |
| `.flac` | flac | flac |
| `.ogg` | ogginfo | vorbis-tools |
| `.opus` | opusinfo | opus-tools |
| `.wav`, `.aac`, `.m4a` | ffprobe | ffmpeg |
| `.wma`, `.aiff`, `.ape` | ffprobe | ffmpeg |

### Image

| Extension | Tool | Package |
|-----------|------|---------|
| `.jpg`, `.jpeg` | jpeginfo | jpeginfo |
| `.png` | pngcheck | pngcheck |
| `.gif`, `.bmp`, `.tiff`, `.tif` | identify | imagemagick |
| `.webp`, `.heic` | identify | imagemagick |
| `.cr2`, `.nef`, `.arw`, `.raw`, `.dng` | exiftool | libimage-exiftool-perl |

### Archive

| Extension | Tool | Package |
|-----------|------|---------|
| `.zip` | unzip | unzip |
| `.tar` | tar | tar |
| `.gz` | gzip | gzip |
| `.bz2` | bzip2 | bzip2 |
| `.xz` | xz | xz-utils |
| `.lz4` | lz4 | lz4 |
| `.zst`, `.zstd` | zstd | zstd |
| `.7z` | 7z | p7zip-full |
| `.rar` | unrar | unrar |

#### Compound Archive Extensions

| Extension | Tool | Package |
|-----------|------|---------|
| `.tar.gz` | tar | tar |
| `.tar.bz2` | tar | tar |
| `.tar.xz` | tar | tar |
| `.tar.zst` | tar | tar |

### Document

| Extension | Tool | Package |
|-----------|------|---------|
| `.pdf` | qpdf | qpdf |
| `.epub` | epubcheck | epubcheck |
| `.docx`, `.xlsx`, `.pptx` | unzip | unzip |

## Adding New Validators

The tool registry is extensible. To add support for new file types, modify the `TOOL_REGISTRY` dict in [`tackles/MediaIntegrityCheck.py`](../tackles/MediaIntegrityCheck.py).

### ToolConfig Dataclass

```python
@dataclass
class ToolConfig:
    """Configuration for a validation tool."""
    binary: str                              # Tool executable name
    apt_package: str                         # Debian/Ubuntu package name
    args: Tuple[str, ...]                    # Arguments BEFORE the file path
    success_codes: Tuple[int, ...] = (0,)    # Exit codes that mean "valid"
    check_stderr: Optional[str] = None       # Regex pattern to find in stderr
```

### Adding a New Extension

```python
TOOL_REGISTRY: Dict[str, ToolConfig] = {
    # ... existing entries ...
    
    # Add a new format
    '.webm': ToolConfig(
        binary='ffprobe',
        apt_package='ffmpeg',
        args=('-v', 'error', '-i'),
    ),
    
    # Tool with custom success codes (e.g., qpdf exit 3 = valid with warnings)
    '.pdf': ToolConfig(
        binary='qpdf',
        apt_package='qpdf',
        args=('--check',),
        success_codes=(0, 3),
    ),
    
    # Tool that needs stderr checking (e.g., ogginfo)
    '.ogg': ToolConfig(
        binary='ogginfo',
        apt_package='vorbis-tools',
        args=(),
        check_stderr=r'(?i)error',
    ),
}
```

### Compound Extensions

For multi-part extensions like `.tar.gz`, add to `COMPOUND_EXTENSIONS`:

```python
COMPOUND_EXTENSIONS: Dict[str, ToolConfig] = {
    '.tar.gz':  ToolConfig('tar', 'tar', ('-tzf',)),
    '.tar.bz2': ToolConfig('tar', 'tar', ('-tjf',)),
    # Add more compound extensions here
}
```

## Examples

### Scan a Media Library

Check all media files in a directory:

```bash
pyTackle MediaIntegrityCheck /media/library -o /tmp/media_check
```

This produces files like `/tmp/media_check_ok.csv`, `/tmp/media_check_broken.csv`, etc.

### Check Only Video Files

Filter to specific extensions:

```bash
pyTackle MediaIntegrityCheck /videos -o video_integrity --extensions mp4,mkv,avi,mov
```

### Check Only Images

```bash
pyTackle MediaIntegrityCheck /photos -o photo_check --extensions jpg,jpeg,png,gif,webp
```

### List Available Tools

See which validators are installed on your system:

```bash
pyTackle MediaIntegrityCheck --list-tools .
```

Example output:

```
Tool Availability Status
================================================================================
Extension    Tool            Package                   Installed  Install Command
--------------------------------------------------------------------------------
.mp4         ffprobe         ffmpeg                    Yes        
.mp3         mp3val          mp3val                    No         apt-get install mp3val
.jpg         jpeginfo        jpeginfo                  Yes        
...
--------------------------------------------------------------------------------

3 package(s) missing. Install with:
  sudo apt-get install mp3val vorbis-tools opus-tools
```

### Get Install Command for Missing Tools

```bash
pyTackle MediaIntegrityCheck --install-cmd .
```

Output:

```bash
sudo apt-get install mp3val vorbis-tools opus-tools
```

### Custom Timeout for Large Files

Increase timeout for very large video files:

```bash
pyTackle MediaIntegrityCheck /large_videos -o results --timeout 600
```

### Workflow: Find and Review Corrupt Files

```bash
# 1. Run integrity check
pyTackle MediaIntegrityCheck /media -o /tmp/check

# 2. Review corrupt files
cat /tmp/check_broken.csv

# 3. Check files missing validators
cat /tmp/check_untestable.csv

# 4. Install missing tools and re-run
pyTackle MediaIntegrityCheck --install-cmd . | bash
pyTackle MediaIntegrityCheck /media -o /tmp/check
```

## See Also

- [ValidateCopy](ValidateCopy.md) — Validate file copies and restore metadata
- [FclonesDuplicates](FclonesDuplicates.md) — Parse duplicate file reports
- [pyTackle README](README.md) — Overview of all available tackles
