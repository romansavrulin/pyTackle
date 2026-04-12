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
# Complete installation command
apt-get install -y \
    ffmpeg mp3val flac vorbis-tools opus-tools \
    jpeginfo pngcheck imagemagick libimage-exiftool-perl \
    unzip gzip bzip2 xz-utils lz4 zstd p7zip-full unrar \
    poppler-utils qpdf epubcheck \
    unrtf antiword libxml2-utils djvulibre-bin
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
| `--check-level` | Validation level: basic, default, or pedantic (default: `default`) |
| `-v, --verbose` | Enable verbose logging for debugging (flag, default: False) |
| `--debug-log PATH` | Write detailed debug output to a CSV file (see [Debug Logging](#debug-logging)) |

## Validation Levels

MediaIntegrityCheck supports three validation thoroughness levels, controlled by `--check-level`:

| Level | Flag | Description | Speed |
|-------|------|-------------|-------|
| Basic | `--check-level basic` | Exit code only | Fastest |
| Default | `--check-level default` | Exit code + stderr pattern matching | Fast (recommended) |
| Pedantic | `--check-level pedantic` | Full content decode/verification | Slowest |

### Basic Level
Only checks the tool's exit code. Fastest but may miss some corruption that tools report via stderr warnings while returning exit code 0.

### Default Level (Recommended)
Checks both exit code and stderr patterns. Catches issues like:
- ffprobe reporting "Invalid frame dimensions" or "Header missing"
- 7z reporting warnings but exit 0
- exiftool reporting invalid metadata

### Pedantic Level
For video/audio files, uses full decode instead of container validation:
- Runs `ffmpeg -hwaccel auto -v error -i FILE -f null -` instead of `ffprobe`
- Decodes every frame/sample to detect mid-file corruption
- Uses hardware acceleration when available (2-10x faster)
- Much slower than other levels - processes entire file content

## Verbose Mode

Use `-v` or `--verbose` to enable detailed logging output for debugging and tracing validation decisions.

### What Verbose Mode Shows

For each file processed:
- **File info**: Path, size (human-readable), extension
- **Tool selection**: Which validator tool is being used and its package
- **Check level policy**: The validation level being applied
- **Command executed**: The full command line
- **Tool output**: stdout and stderr (truncated to 500 chars)
- **Return code**: The exit code from the tool
- **Decision reasoning**: Why the file was marked as valid, corrupt, etc.

### Example Output

```
DEBUG - Processing: videos/test.mp4 (size=15.2MB, ext=mp4)
DEBUG -   Tool: ffprobe (package: ffmpeg)
DEBUG -   Check level: default
DEBUG -   Command: ffprobe -v error -i /media/videos/test.mp4
DEBUG -   Return code: 0
DEBUG -   stderr: [warning] Header missing
DEBUG -   Decision: CORRUPT - stderr matched pattern '(?i)(error|invalid|corrupt|moov atom not found)'
```

### Usage Example

```bash
# Enable verbose output
pyTackle MediaIntegrityCheck /media/library -o results -v

# Combine with other options
pyTackle MediaIntegrityCheck /media/videos --check-level pedantic --verbose
```

### Notes

- Verbose mode uses DEBUG log level
- Output goes to stderr
- Useful for troubleshooting validation issues or understanding tool behavior

## Debug Logging

Use `--debug-log <path.csv>` to write detailed debug information for every file validated. This produces a structured CSV file with complete execution context for each validation.

### Debug Log Format

The debug log CSV includes 18 columns with a header row:

| Column | Description |
|--------|-------------|
| `file_path` | Absolute path to the file |
| `file_size` | File size in bytes |
| `file_extension` | File extension (e.g., `.mp4`) |
| `tool_binary` | Tool binary name (e.g., `ffprobe`) |
| `tool_package` | apt package name (e.g., `ffmpeg`) |
| `command` | Full command line executed |
| `check_level` | Validation level used (basic/default/pedantic) |
| `exit_code` | Tool exit code |
| `stdout` | Full stdout output (preserved with CSV escaping) |
| `stderr` | Full stderr output (preserved with CSV escaping) |
| `stderr_regex` | Regex pattern used for stderr checking |
| `stdout_regex` | Regex pattern used for stdout checking |
| `stderr_matched` | Whether stderr matched the error pattern (True/False) |
| `stdout_matched` | Whether stdout matched the error pattern (True/False) |
| `result` | Validation result (VALID/CORRUPT/UNTESTABLE/TOOL_MISSING/TOOL_ERROR) |
| `decision_reason` | Human-readable explanation of the decision |
| `error_message` | Error details (for TOOL_ERROR/TOOL_MISSING) |
| `duration_ms` | Validation time in milliseconds |

### Usage Example

```bash
# Run validation with debug logging
pyTackle MediaIntegrityCheck /media/library -o results --debug-log debug.csv

# Combine with verbose mode for both terminal and file output
pyTackle MediaIntegrityCheck /media/library -o results --debug-log debug.csv -v
```

### Use Cases

- **Post-mortem analysis** — Review why specific files were marked corrupt
- **Tool debugging** — Examine exact command lines and tool output
- **Pattern tuning** — Check which stderr/stdout patterns are matching
- **Performance profiling** — Analyze validation time per file
- **Batch processing** — Import into a database or spreadsheet for analysis

### Notes

- Debug log uses proper CSV escaping to preserve newlines and special characters in tool output
- File is created with a header row
- Uses eager file opening (file created immediately when `--debug-log` is specified)
- Flushed after each write for reliability
- For technical implementation details, see [StreamingCsv](StreamingCsv.md)

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

Output files use the canonical 10-column CSV format with a header row:

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

### Video Formats
| Extension | Tool | Package | Testability | Notes |
|-----------|------|---------|-------------|-------|
| .mp4 | ffprobe | ffmpeg | ✅ Full | Standard MPEG-4 container |
| .mkv | ffprobe | ffmpeg | ✅ Full | Matroska container |
| .avi | ffprobe | ffmpeg | ✅ Full | AVI container |
| .mov | ffprobe | ffmpeg | ✅ Full | QuickTime container |
| .wmv | ffprobe | ffmpeg | ✅ Full | Windows Media Video |
| .flv | ffprobe | ffmpeg | ✅ Full | Flash Video |
| .webm | ffprobe | ffmpeg | ✅ Full | WebM container |
| .m4v | ffprobe | ffmpeg | ✅ Full | MPEG-4 Video |
| .mpeg/.mpg | ffprobe | ffmpeg | ✅ Full | MPEG video |
| .3gp | ffprobe | ffmpeg | ✅ Full | 3GPP multimedia |
| .ts/.m2ts | ffprobe | ffmpeg | ✅ Full | MPEG transport stream |
| .vob | ffprobe | ffmpeg | ✅ Full | DVD Video Object |
| .lrv | ffprobe | ffmpeg | ✅ Full | GoPro proxy video |
| .360 | ffprobe | ffmpeg | ✅ Full | 360-degree video |
| .insv | ffprobe | ffmpeg | ⚠️ Partial | Insta360 proprietary format |

### Audio Formats
| Extension | Tool | Package | Testability | Notes |
|-----------|------|---------|-------------|-------|
| .mp3 | mp3val | mp3val | ✅ Full | MPEG Audio Layer III |
| .flac | flac | flac | ✅ Full | Free Lossless Audio Codec |
| .ogg | ogginfo | vorbis-tools | ✅ Full | Ogg Vorbis |
| .opus | opusinfo | opus-tools | ✅ Full | Opus audio |
| .wav | ffprobe | ffmpeg | ✅ Full | Waveform Audio |
| .aac | ffprobe | ffmpeg | ✅ Full | Advanced Audio Coding |
| .m4a | ffprobe | ffmpeg | ✅ Full | MPEG-4 Audio |
| .wma | ffprobe | ffmpeg | ✅ Full | Windows Media Audio |
| .aiff | ffprobe | ffmpeg | ✅ Full | Audio Interchange Format |
| .ape | ffprobe | ffmpeg | ✅ Full | Monkey's Audio |

### Image Formats
| Extension | Tool | Package | Testability | Notes |
|-----------|------|---------|-------------|-------|
| .jpg/.jpeg | jpeginfo | jpeginfo | ✅ Full | JPEG image |
| .png | pngcheck | pngcheck | ✅ Full | PNG image |
| .gif | identify | imagemagick | ✅ Full | GIF image |
| .bmp | identify | imagemagick | ✅ Full | Bitmap image |
| .tiff/.tif | identify | imagemagick | ✅ Full | Tagged Image File Format |
| .webp | identify | imagemagick | ✅ Full | WebP image |
| .heic | identify | imagemagick | ✅ Full | HEIF container |
| .thm | jpeginfo | jpeginfo | ✅ Full | Thumbnail (JPEG) |
| .cr2 | exiftool | libimage-exiftool-perl | ⚠️ Partial | Canon RAW (metadata only) |
| .nef | exiftool | libimage-exiftool-perl | ⚠️ Partial | Nikon RAW (metadata only) |
| .arw | exiftool | libimage-exiftool-perl | ⚠️ Partial | Sony RAW (metadata only) |
| .raw | exiftool | libimage-exiftool-perl | ⚠️ Partial | Generic RAW (metadata only) |
| .dng | exiftool | libimage-exiftool-perl | ⚠️ Partial | Digital Negative (metadata only) |

### Archive Formats
| Extension | Tool | Package | Testability | Notes |
|-----------|------|---------|-------------|-------|
| .zip | unzip | unzip | ✅ Full | ZIP archive |
| .tar | tar | tar | ✅ Full | TAR archive |
| .tar.gz/.tgz | tar | tar | ✅ Full | Gzipped TAR |
| .tar.bz2 | tar | tar | ✅ Full | Bzip2 TAR |
| .tar.xz | tar | tar | ✅ Full | XZ TAR |
| .gz | gzip | gzip | ✅ Full | Gzip compressed |
| .bz2 | bzip2 | bzip2 | ✅ Full | Bzip2 compressed |
| .xz | xz | xz-utils | ✅ Full | XZ compressed |
| .lz4 | lz4 | lz4 | ✅ Full | LZ4 compressed |
| .zst/.zstd | zstd | zstd | ✅ Full | Zstandard compressed |
| .7z | 7z | p7zip-full | ✅ Full | 7-Zip archive |
| .rar | unrar | unrar | ✅ Full | RAR archive |

### Document Formats
| Extension | Tool | Package | Testability | Notes |
|-----------|------|---------|-------------|-------|
| .pdf | qpdf | qpdf | ✅ Full | PDF document |
| .epub | epubcheck | epubcheck | ✅ Full | EPUB ebook |
| .docx | unzip | unzip | ✅ Full | Office Open XML document |
| .xlsx | unzip | unzip | ✅ Full | Office Open XML spreadsheet |
| .pptx | unzip | unzip | ✅ Full | Office Open XML presentation |
| .doc | antiword | antiword | ✅ Full | Legacy Word document |
| .rtf | unrtf | unrtf | ⚠️ Partial | Rich Text Format |
| .fb2 | xmllint | libxml2-utils | ✅ Full | FictionBook ebook (XML) |
| .djvu | ddjvu | djvulibre-bin | ✅ Full | DjVu document |

### Legend
- ✅ **Full**: Reliable validation with proper exit codes
- ⚠️ **Partial**: Limited validation (may not catch all corruption)
- ❌ **Untestable**: No Linux tool available

### Known Untestable Formats
| Extension | Description |
|-----------|-------------|
| .sfk | Sony Sound Forge peak file (proprietary cache) |
| .ifo/.bup | DVD navigation files (require full DVD structure) |

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

### Thorough Video Validation (Pedantic Mode)

```bash
# Full decode validation with hardware acceleration
pyTackle MediaIntegrityCheck /media/videos --check-level pedantic -o video_check
```

This decodes every frame to detect corruption that container-level checks would miss.

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
