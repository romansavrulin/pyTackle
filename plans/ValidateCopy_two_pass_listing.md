# Two-Pass Listing Generation Enhancement

## Overview

Enhance `generate_listing()` to support accurate percentage-based progress reporting by implementing a two-pass approach as the default behavior, while preserving the current streaming approach as an optional memory-efficient mode.

## Current Behavior (Before Enhancement)

The original implementation used streaming:
- Walk → stat → checksum → write immediately
- Progress: "1500 entries | 50 checksums | 12.3 entries/sec"
- No total count available for percentage

## Implementation Summary

### 1. CLI Option

Added `--streaming` flag to [`arg_parser()`](tackles/ValidateCopy.py:792):

```python
subparser.add_argument(
    '--streaming',
    action='store_true',
    default=False,
    help=(
        'Generate mode: Use streaming (memory-efficient) approach instead '
        'of two-pass. Processes each file inline (stat + checksum + write). '
        'Recommended for extremely large datasets.'
    ),
)
```

### 2. Refactored `generate_listing()`

**Mode Selection:**

```python
def generate_listing(..., streaming: bool = False) -> int:
    if streaming:
        return _generate_listing_streaming(...)  # Memory-efficient mode
    return _generate_listing_two_pass(...)       # Default with percentage
```

### 3. Shared Helper Functions

Extracted common code into reusable helpers:

**[`_collect_paths_for_walk_level()`](tackles/ValidateCopy.py:324):**
```python
def _collect_paths_for_walk_level(
    dirpath: str,
    dirnames: List[str],
    filenames: List[str],
    allowed_types: set,
    base: str,
) -> List[str]:
    """Collect filesystem paths for a single os.walk() level based on allowed types."""
```

**[`_calculate_entry_checksum()`](tackles/ValidateCopy.py:372):**
```python
def _calculate_entry_checksum(
    fe: FileEntry,
    checksum_algorithm: str,
) -> Optional[str]:
    """Calculate checksum for a FileEntry if it's a file.
    
    Returns error message if checksum calculation failed, None on success.
    """
```

### 4. Two-Pass Implementation

**Pass 1 - Collection ([`_generate_listing_two_pass()`](tackles/ValidateCopy.py:455)):**
- Walk directory and stat all entries
- Store full `FileEntry` objects (enables future attribute-based filtering)
- Track stat errors separately for later error reporting
- Progress: "Pass 1: Scanned 5000 entries..."

**Pass 2 - Processing:**
- Calculate checksums for files (if requested)
- Write entries to CSV with relative paths
- Progress: "Processing: 1500/10000 (15.0%) - calculating checksums"

### 5. Progress Reporting

**Two-pass mode (default):**
```
INFO: Pass 1: Scanning directory structure from: /data
INFO: Pass 1: Scanned 5000 entries...
INFO: Pass 1 complete: Found 10000 entries in 2.5s (3 stat errors)
INFO: Pass 2: Calculating checksums and writing listing...
INFO: Processing: 1500/10000 (15.0%) - calculating checksums
INFO: Processing: 3000/10000 (30.0%) - calculating checksums
INFO: Listing complete: 9997 entries, 8500 checksums, 3 errors (45.2s)
```

**Streaming mode (`--streaming`):**
```
INFO: Starting streaming listing generation from: /data
INFO: Listing progress: 1500 entries written | 50 checksums calculated | 12.3 entries/sec
INFO: Listing complete: 10000 entries, 0 errors (85.3s)
```

### 6. Code Changes Summary

| File | Change |
|------|--------|
| [`tackles/ValidateCopy.py`](tackles/ValidateCopy.py) | Add `--streaming` arg, refactor into `_generate_listing_two_pass()` and `_generate_listing_streaming()`, extract shared helpers |
| [`docs/ValidateCopy.md`](docs/ValidateCopy.md) | Document `--streaming` option and processing modes |

### 7. Memory Considerations

- **Two-pass mode:** Stores full `FileEntry` objects (~500 bytes each including metadata)
  - For 1 million files: ~500MB memory overhead
  - Acceptable for most use cases; provides percentage progress
  
- **Streaming mode:** Constant memory usage
  - Suitable for extremely large datasets (10M+ files)
  - No percentage progress available

### 8. Testing

- All existing tests pass with default two-pass mode
- Verified memory usage difference with large directories
- Both modes produce identical CSV output

## Design Decisions

1. **`--streaming` flag name:** Chosen over alternatives (`--memory-efficient`, `--no-count`) as it's technically accurate and commonly understood.

2. **Full FileEntry in Pass 1:** Chose to store complete `FileEntry` objects rather than lightweight tuples to:
   - Simplify code (no separate data structure)
   - Enable future attribute-based filtering between passes
   - Minimal memory overhead for typical use cases
