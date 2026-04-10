# pyTackle Coding Guide

This guide captures key patterns, conventions, and best practices discovered during pyTackle development. Follow these patterns to maintain consistency across the codebase.

## 1. Tackle Class Pattern

Every tackle extends [`TackleFactory`](../tackles/TackleFactory.py) and implements two required methods.

### Extending TackleFactory

```python
from tackles.TackleFactory import TackleFactory

class MyTackle(TackleFactory):
    """Brief description of what the tackle does."""
    
    @classmethod
    def arg_parser(cls, subparser):
        # Define CLI arguments
        pass
    
    def __init__(self, parser):
        super().__init__(parser)
        options, _ = parser.parse_known_args()
        # Initialize instance attributes from options
        
    def do(self) -> int:
        # Main execution logic
        return 0  # Exit code
```

### Auto-Registration Mechanism

Tackles are automatically registered when imported via [`__init_subclass__`](../tackles/TackleFactory.py:7):

```python
class TackleFactory(object):
    tackles = {}

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        TackleFactory.tackles[cls.__name__] = cls
```

The tackle name becomes the CLI subcommand. No manual registration needed.

### Reference Files

- [`tackles/MediaIntegrityCheck.py`](../tackles/MediaIntegrityCheck.py) — Full example
- [`tackles/ValidateCopy.py`](../tackles/ValidateCopy.py) — Multi-mode example
- [`tackles/TackleFactory.py`](../tackles/TackleFactory.py) — Base class

---

## 2. CLI Argument Patterns

Use argparse subparser pattern. Arguments are defined in the [`arg_parser()`](../tackles/MediaIntegrityCheck.py:418) classmethod.

### Positional Arguments

```python
subparser.add_argument(
    'directory',
    help='Directory to scan recursively for media files',
)
```

### Optional Arguments with Defaults

```python
subparser.add_argument(
    '-o', '--output',
    type=str,
    default='integrity_check',
    metavar='BASE',
    help='Base name for output files (default: integrity_check)',
)
```

### Boolean Flags

```python
subparser.add_argument(
    '--list-tools',
    action='store_true',
    help='List all supported tools and their availability, then exit',
)

subparser.add_argument(
    '-v', '--verbose',
    action='store_true',
    default=False,
    help='Enable verbose logging',
)
```

### Choice Arguments

```python
subparser.add_argument(
    '--check-level',
    type=str,
    choices=['basic', 'default', 'pedantic'],
    default='default',
    help='Validation thoroughness level',
)
```

### Integer Arguments with Defaults

```python
subparser.add_argument(
    '--timeout',
    type=int,
    default=300,
    help='Per-file validation timeout in seconds (default: 300)',
)
```

### Mutually Exclusive Groups

```python
mode_group = subparser.add_mutually_exclusive_group(required=True)
mode_group.add_argument('--validate', type=pathlib.Path, metavar='LISTING')
mode_group.add_argument('--generate', type=pathlib.Path, metavar='LISTING')
mode_group.add_argument('--apply', type=pathlib.Path, metavar='LISTING')
```

### Help Text Style

- Use sentence fragments starting with a capital letter
- Include default values in parentheses: `(default: X)`
- Provide examples for complex options: `Example: --extensions mp4,mp3,jpg`

---

## 3. FileEntry Usage

[`FileEntry`](../common/FileEntry.py) is the canonical representation of a filesystem entry.

### Creating from Filesystem

```python
from common.FileEntry import FileEntry

# Read all stat-derived attributes (checksum NOT calculated)
fe = FileEntry.from_fs_path('/path/to/file.txt')
```

### Available Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `path` | `str` | Absolute or relative file path |
| `size` | `Optional[int]` | File size in bytes |
| `creation` | `Optional[datetime]` | Creation timestamp |
| `access` | `Optional[datetime]` | Last access timestamp |
| `modify` | `Optional[datetime]` | Last modification timestamp |
| `permissions` | `Optional[str]` | Octal string, e.g. `"0o755"` |
| `uid` | `Optional[int]` | Owner user ID |
| `gid` | `Optional[int]` | Owner group ID |
| `checksum` | `Optional[str]` | Format: `"algorithm:hexdigest"` |
| `entry_type` | `Optional[str]` | Single char: `'f'`, `'d'`, `'l'` |

### Entry Type Constants

```python
from common.FileEntry import ENTRY_TYPE_FILE, ENTRY_TYPE_DIR, ENTRY_TYPE_SYMLINK

ENTRY_TYPE_FILE = 'f'      # Regular file
ENTRY_TYPE_DIR = 'd'       # Directory
ENTRY_TYPE_SYMLINK = 'l'   # Symbolic link
```

### Checksum Calculation

```python
# Calculate and cache checksum
hexdigest = fe.calculate_checksum(algorithm='md5')

# Force recalculation
hexdigest = fe.recalculate_checksum(algorithm='md5')
```

### Reference

- [`common/FileEntry.py`](../common/FileEntry.py)

---

## 4. Listing Functions

[`common/listing.py`](../common/listing.py) provides CSV I/O for FileEntry collections.

### Writing Entries to CSV

```python
from common.listing import write_listing

# Write entries to CSV, returns count
count = write_listing('output.csv', entries)
```

### Reading Entries from CSV

```python
from common.listing import read_listing

# Load all entries into memory
entries = read_listing('listing.csv')
```

### Streaming Entries from CSV

```python
from common.listing import iter_listing

# Memory-efficient iteration
for entry in iter_listing('large_listing.csv'):
    process(entry)
```

### Canonical Attribute Mapping

The [`CANONICAL_MAP`](../common/attr_map.py:46) defines the 10-column CSV format:

```python
CANONICAL_MAP = {
    'creation': '0',
    'access': '1',
    'modify': '2',
    'checksum': '3',
    'entry_type': '4',
    'permissions': '5',
    'uid': '6',
    'gid': '7',
    'size': '8',
    'path': '9',
}
```

### Reference

- [`common/listing.py`](../common/listing.py)
- [`common/attr_map.py`](../common/attr_map.py)

---

## 5. Directory Scanning Pattern

Use [`os.walk()`](../tackles/MediaIntegrityCheck.py:662) for recursive directory scanning.

### Basic Pattern

```python
import os
from common.FileEntry import FileEntry

def scan_directory(directory: str) -> List[FileEntry]:
    entries: List[FileEntry] = []
    
    for dirpath, dirnames, filenames in os.walk(directory):
        for filename in filenames:
            full_path = os.path.join(dirpath, filename)
            
            # Skip symlinks if needed
            if os.path.islink(full_path):
                continue
            
            try:
                fe = FileEntry.from_fs_path(full_path)
                entries.append(fe)
            except OSError as exc:
                logger.warning('Cannot stat %s: %s', full_path, exc)
    
    return entries
```

### Filtering by Entry Type

```python
# Filter files, directories, or symlinks
for dirpath, dirnames, filenames in os.walk(base_dir):
    paths: List[str] = []
    
    if 'f' in allowed_types:
        paths.extend(
            os.path.join(dirpath, f) for f in filenames
            if not os.path.islink(os.path.join(dirpath, f))
        )
    if 'd' in allowed_types:
        paths.extend(os.path.join(dirpath, d) for d in dirnames)
    if 'l' in allowed_types:
        paths.extend(
            os.path.join(dirpath, f) for f in filenames
            if os.path.islink(os.path.join(dirpath, f))
        )
```

### Reference

- [`tackles/MediaIntegrityCheck.py:652`](../tackles/MediaIntegrityCheck.py:652) — `_scan_directory()`
- [`tackles/ValidateCopy.py:287`](../tackles/ValidateCopy.py:287) — `generate_listing()`

---

## 6. Progress Indication

Two patterns for progress reporting: time-based and count-based.

### Time-Based Progress (Preferred for Slow Operations)

```python
import time

last_progress = time.monotonic()
progress_interval = 10  # seconds

for item in items:
    process(item)
    
    now = time.monotonic()
    if now - last_progress >= progress_interval:
        logger.info('Progress: %d/%d (%.1f%%)', processed, total, pct)
        last_progress = now
```

### Count-Based Progress (For Fast Operations)

```python
progress_interval = 1000

for idx, item in enumerate(items, start=1):
    process(item)
    
    if idx % progress_interval == 0:
        pct = (idx / total) * 100
        logger.info('Progress: %d/%d (%.1f%%)', idx, total, pct)
```

### Logging Format

```python
# Standard progress format
logger.info('Progress: %d/%d (%.1f%%)', processed, total, pct)

# With category statistics
logger.info(
    'Progress: %d/%d (%.1f%%) | OK: %d | Broken: %d | Errors: %d',
    processed, total, pct, ok_count, broken_count, error_count
)
```

### Reference

- [`tackles/MediaIntegrityCheck.py:659`](../tackles/MediaIntegrityCheck.py:659) — Time-based during scan
- [`tackles/MediaIntegrityCheck.py:719`](../tackles/MediaIntegrityCheck.py:719) — Time-based during validation

---

## 7. Logging Patterns

### Module-Level Logger Setup

```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
```

### Startup Settings Log

```python
def _log_startup_settings(self) -> None:
    """Log startup configuration."""
    logger.info('=' * 60)
    logger.info('MyTackle')
    logger.info('=' * 60)
    logger.info('Directory: %s', self.directory)
    logger.info('Output base: %s', self.output_base)
    logger.info('Timeout: %d seconds', self.timeout)
    logger.info('-' * 60)
```

### Log Levels

| Level | Use Case |
|-------|----------|
| `DEBUG` | Verbose/debug output, per-file details |
| `INFO` | Progress updates, results summary |
| `WARNING` | Non-fatal issues, skipped items |
| `ERROR` | Fatal errors, validation failures |

### Verbose Mode Pattern

```python
if self.verbose:
    logger.debug('Processing: %s (size=%s)', entry.path, size)
    logger.debug('  Tool: %s', config.binary)
    logger.debug('  Decision: %s', result)
```

### Reference

- [`tackles/MediaIntegrityCheck.py:534`](../tackles/MediaIntegrityCheck.py:534) — `_log_startup_settings()`

---

## 8. Testing Patterns

### Test File Organization

```
tests/
├── __init__.py
├── conftest.py           # Shared fixtures
├── test_file_entry.py    # Unit tests for FileEntry
├── test_listing.py       # Unit tests for listing.py
├── test_media_integrity_check.py  # Tests for tackle
└── test_tackles_integration.py    # Integration tests
```

### pytest with Fixtures

```python
import pytest
from common.FileEntry import FileEntry

@pytest.fixture
def sample_file_entry(tmp_path):
    """Create a sample FileEntry for testing."""
    test_file = tmp_path / 'test.mp4'
    test_file.write_bytes(b'fake content')
    return FileEntry.from_fs_path(str(test_file))
```

### Mocking with unittest.mock

```python
from unittest.mock import MagicMock, patch

@patch('subprocess.run')
@patch('tackles.MediaIntegrityCheck.check_tool_available')
def test_valid_file_returns_valid(self, mock_available, mock_run):
    mock_available.return_value = True
    mock_run.return_value = MagicMock(returncode=0, stderr='')
    
    outcome = self._validate_single(entry)
    assert outcome.result == ValidationResult.VALID
```

### Using tmp_path for Temp Directories

```python
def test_scan_finds_all_files(self, tmp_path):
    # Create test files
    (tmp_path / 'file1.mp4').write_bytes(b'content1')
    (tmp_path / 'file2.jpg').write_bytes(b'content2')
    
    entries = scan_directory(str(tmp_path))
    assert len(entries) == 2
```

### Test Class Organization by Feature

```python
class TestToolRegistry:
    """Tests for TOOL_REGISTRY configuration."""
    
    def test_registry_contains_mp4(self):
        assert '.mp4' in TOOL_REGISTRY

class TestGetExtension:
    """Tests for get_extension() function."""
    
    def test_simple_extension_mp4(self):
        assert get_extension('/path/to/file.mp4') == '.mp4'
```

### Parametrized Tests for Multiple Cases

```python
@pytest.mark.parametrize('ext', [
    '.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm',
])
def test_video_extensions_use_ffprobe(self, ext):
    config = get_tool_config(ext)
    assert config is not None
    assert config.binary == 'ffprobe'
```

### Reference

- [`tests/test_media_integrity_check.py`](../tests/test_media_integrity_check.py)
- [`tests/conftest.py`](../tests/conftest.py)

---

## 9. Documentation Structure

### Document Layout

```markdown
# TackleName

Brief description.

## Overview

Key features as bullet list.

### Platform Restrictions (if any)

Note platform requirements.

## Installation

Required dependencies.

## Usage

```bash
pyTackle TackleName [OPTIONS] ARGUMENTS
```

### CLI Reference

#### Positional Arguments

| Argument | Description |
|----------|-------------|

#### Options

| Option | Description |
|--------|-------------|

## Output

Output format description.

### CSV Format

| Column | Index | Description |
|--------|-------|-------------|

## Examples

```bash
# Example with description
pyTackle TackleName /path --option value
```

## See Also

Links to related documentation.
```

### Reference

- [`docs/MediaIntegrityCheck.md`](../docs/MediaIntegrityCheck.md)
- [`docs/ValidateCopy.md`](../docs/ValidateCopy.md)

---

## 10. Subprocess Execution

### Basic Pattern

```python
import subprocess

result = subprocess.run(
    cmd,
    capture_output=True,
    text=True,
    timeout=self.timeout,
)

exit_code = result.returncode
stdout = result.stdout
stderr = result.stderr
```

### Timeout Handling

```python
try:
    result = subprocess.run(
        cmd,
        capture_output=True,
        timeout=self.timeout,
        text=True,
    )
except subprocess.TimeoutExpired:
    return ValidationOutcome(
        entry=entry,
        result=ValidationResult.TOOL_ERROR,
        error_message=f'Validation timed out after {self.timeout}s',
    )
```

### Exit Code Checking

```python
# Simple check
if result.returncode != 0:
    return ValidationResult.CORRUPT

# Multiple success codes
if result.returncode in config.success_codes:
    return ValidationResult.VALID
```

### stderr/stdout Capture

```python
result = subprocess.run(cmd, capture_output=True, text=True)

# Truncate for logging/storage
stderr_snippet = result.stderr[:500] if result.stderr else None
```

### Reference

- [`tackles/MediaIntegrityCheck.py:820`](../tackles/MediaIntegrityCheck.py:820)

---

## 11. Tool Availability Checking

### Check if Tool Exists

```python
import shutil

def check_tool_available(binary: str) -> bool:
    """Check if tool is available using shutil.which()."""
    return shutil.which(binary) is not None
```

### Generate Install Commands

```python
def generate_install_command(packages: Set[str]) -> str:
    """Generate apt-get install command for the given packages."""
    if not packages:
        return "# All required tools are available"
    sorted_packages = sorted(packages)
    return f"sudo apt-get install {' '.join(sorted_packages)}"
```

### Reference

- [`tackles/MediaIntegrityCheck.py:308`](../tackles/MediaIntegrityCheck.py:308)

---

## 12. Extensible Registry Pattern

Use dataclasses for configuration and dictionaries for mapping.

### Dataclass for Configuration

```python
from dataclasses import dataclass
from typing import Optional, Tuple

@dataclass
class ToolConfig:
    """Configuration for a validation tool."""
    binary: str                              # Tool executable name
    apt_package: str                         # Debian/Ubuntu package name
    args: Tuple[str, ...]                    # Arguments BEFORE the file path
    success_codes: Tuple[int, ...] = (0,)    # Exit codes that mean "valid"
    check_stderr: Optional[str] = None       # Regex pattern to find in stderr
    args_after_file: Tuple[str, ...] = ()    # Arguments AFTER the file path
```

### Dictionary Mapping Keys to Configs

```python
TOOL_REGISTRY: Dict[str, ToolConfig] = {
    '.mp4': ToolConfig('ffprobe', 'ffmpeg', ('-v', 'error', '-i')),
    '.jpg': ToolConfig('jpeginfo', 'jpeginfo', ('-c',)),
    '.pdf': ToolConfig('qpdf', 'qpdf', ('--check',), success_codes=(0, 3)),
}
```

### Helper Functions

```python
def get_tool_config(extension: str) -> Optional[ToolConfig]:
    """Get tool config for extension."""
    return TOOL_REGISTRY.get(extension)

def check_tool_available(binary: str) -> bool:
    """Check if tool is available."""
    return shutil.which(binary) is not None

def list_tools_status() -> str:
    """Return formatted table showing all tools and their status."""
    # Implementation...
```

### Adding New Entries

```python
# Add to registry
TOOL_REGISTRY['.webm'] = ToolConfig(
    binary='ffprobe',
    apt_package='ffmpeg',
    args=('-v', 'error', '-i'),
)
```

### Reference

- [`tackles/MediaIntegrityCheck.py:60`](../tackles/MediaIntegrityCheck.py:60) — `ToolConfig` dataclass
- [`tackles/MediaIntegrityCheck.py:87`](../tackles/MediaIntegrityCheck.py:87) — `TOOL_REGISTRY`

---

## Quick Reference

### Common Imports

```python
import logging
import os
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

from common.FileEntry import FileEntry
from common.listing import write_listing, read_listing, iter_listing
from common.attr_map import CANONICAL_MAP
from tackles.TackleFactory import TackleFactory
```

### Standard Tackle Template

```python
"""
TackleName — brief description.

Extended description of what the tackle does.
"""

import logging
import os
from typing import List

from common.FileEntry import FileEntry
from tackles.TackleFactory import TackleFactory

logging.basicConfig(
    level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class TackleName(TackleFactory):
    """One-line description."""

    @classmethod
    def arg_parser(cls, subparser):
        subparser.add_argument('directory', help='Directory to process')
        subparser.add_argument('-o', '--output', default='output', help='Output base')
        subparser.add_argument('-v', '--verbose', action='store_true', help='Verbose')

    def __init__(self, parser):
        super().__init__(parser)
        options, _ = parser.parse_known_args()
        
        self.directory = os.path.abspath(options.directory)
        self.output_base = options.output
        self.verbose = options.verbose
        
        self._log_startup_settings()

    def _log_startup_settings(self) -> None:
        logger.info('=' * 60)
        logger.info('TackleName')
        logger.info('=' * 60)
        logger.info('Directory: %s', self.directory)
        logger.info('Output: %s', self.output_base)
        logger.info('-' * 60)

    def do(self) -> int:
        if not os.path.isdir(self.directory):
            logger.error('Directory not found: %s', self.directory)
            return 1
        
        # Main logic here
        logger.info('Processing complete')
        return 0
```
