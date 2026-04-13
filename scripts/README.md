# ⚠️ LEGACY / DEPRECATED

> **Warning**: This folder contains legacy utility scripts that are no longer actively maintained.
> They are preserved for historical reference only and may require updates to work with current systems.

---

## Overview

This folder contains miscellaneous shell scripts for various system administration and media processing tasks.

---

## Files

### clean-slivy.sh

**Purpose**: Cleans up downloaded course content by removing spam files and audio watermarks.

**Description**: A comprehensive cleanup script that:
- Deletes known spam/advertisement files by size and name patterns (e.g., promo videos, URL files, watermark images)
- Recursively renames files to remove `[SuperSliv.biz]` prefixes
- Detects and removes audio watermark fragments from MP3 files using `audio-offset-finder`

**Dependencies**:
- `ffmpeg`, `ffprobe`
- `jq`
- `perl rename` (with `-0ve` support)
- `audio-offset-finder` (bbc/audio-offset-finder)

**Usage**:
```bash
./clean-slivy.sh /path/to/folder /path/to/fragment.mp3
```

**Environment Variables**:
- `DEBUG=1` - Enable bash xtrace
- `AOF_LOG=1` - Print raw audio-offset-finder output
- `MAX_HITS=50` - Max watermark removals per file
- `MIN_CONF=0.60` - Minimum confidence threshold for matches
- `EPS=0.02` - Seconds padding around cuts

---

### kernel-compilation-test.sh

**Purpose**: Benchmark script for testing Linux kernel compilation performance.

**Description**: Downloads and compiles the Linux kernel 4.19.274 to test CPU compilation performance. Contains an embedded base64-encoded kernel config payload.

**What it does**:
1. Installs required build dependencies
2. Downloads kernel source tarball (if not present)
3. Extracts embedded `.config` file
4. Runs a timed full kernel compilation using all available CPU cores

**Dependencies**:
- `git`, `fakeroot`, `build-essential`, `ncurses-dev`, `xz-utils`
- `libssl-dev`, `bc`, `flex`, `libelf-dev`, `bison`

**Usage**:
```bash
./kernel-compilation-test.sh
```

---

### memory-bandwidth-test.sh

**Purpose**: Sets up tools for memory bandwidth benchmarking.

**Description**: Installs and builds memory bandwidth testing tools for performance analysis.

**What it does**:
1. Installs system dependencies (`sysbench`, `build-essential`, `nasm`, `lshw`, `jq`, `git`)
2. Clones the `bandwidth-benchmark` repository
3. Builds the benchmark tool

**Dependencies**:
- `apt` package manager (Debian/Ubuntu)
- `git`
- `make`, `nasm`

**Usage**:
```bash
./memory-bandwidth-test.sh
```

---

### reencode.sh

**Purpose**: Batch re-encode video files to HEVC/H.265 using Apple VideoToolbox hardware acceleration.

**Description**: Recursively finds video files and re-encodes them to HEVC format with optimized settings for Apple Silicon/macOS.

**What it does**:
1. Scans for video files (`.mp4`, `.m4v`, `.mov`, `.mkv`, `.avi`, `.webm`)
2. Re-encodes to HEVC using hardware acceleration (`hevc_videotoolbox`)
3. Outputs to `_reencoded/` subdirectory preserving folder structure
4. Uses 10Mbps target bitrate with AAC audio at 128kbps

**Dependencies**:
- `ffmpeg` with VideoToolbox support (macOS)

**Encoding Settings**:
- Video: HEVC (H.265), 10Mbps target, 12Mbps max
- Audio: AAC stereo, 128kbps
- Container: MP4 with `faststart` flag

**Usage**:
```bash
./reencode.sh /path/to/videos
```

---

## Notes

- These scripts were created for specific one-time tasks and personal use
- They may contain hardcoded paths or assumptions about the environment
- Review and modify scripts before running them on your system
