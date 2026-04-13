---
status: IMPLEMENTED
implemented_in: tackles/ValidateCopy.py
last_reviewed: 2026-04-13
notes: New CLI structure fully implemented with mutually exclusive mode group (--validate/--generate/--apply), unified --attrs, progress logging, and startup settings logging. Backward compatibility layer with deprecation warnings not yet implemented.
---

# ValidateCopy CLI Refactoring and Logging Improvements

## Overview

This plan addresses two areas of improvement for the ValidateCopy tackle:
1. **CLI Simplification** — Refactor the bloated argument pattern to a cleaner mode-based structure
2. **Logging Improvements** — Add verbose mode/settings logging and progress indicators during list processing

## Current State Analysis

### Current CLI Arguments

| Argument | Type | Purpose |
|----------|------|---------|
| `--listing PATH` | Optional path | Input listing file |
| `--base-dir PATH` | Required path | Base directory for path resolution |
| `--generate-listing PATH` | Optional path | Output path for generated listing |
| `--validate` | Boolean flag | Enable validation mode |
| `--validate-attrs ATTRS` | String | Attributes to validate |
| `--attr-map MAP` | String | Timestamp mapping for apply mode |
| `--types TYPES` | String | Entry type filter (f,d,l) |
| `--checksum` | Boolean flag | Enable checksum calculation |
| `--checksum-algorithm ALG` | String | Algorithm for checksums |
| `--script-base-path PATH` | String | Path prefix to strip |
| `--dry-run` | Boolean flag | Preview changes |
| `-v` | Boolean flag | Verbose output |
| `-q, --quiet` | Boolean flag | Suppress OK entries in validation |

### Current Mode Detection

The current implementation uses implicit mode detection based on flag combinations:

```python
# In ValidateCopy.__init__():
if self.validate_mode and self.generate_listing_path is not None:
    # Error: mutually exclusive
elif self.validate_mode:
    # Validate mode
elif self.generate_listing_path is not None:
    # Generate mode
else:
    # Apply mode (requires --listing)
```

### Current Logging Gaps

After format detection, there's no feedback during potentially long operations:

```
2026-04-08 14:47:19,402 - INFO - Processing entry types: d, f, l
2026-04-08 14:47:19,402 - INFO - Detected listing format: canonical
# ... silence during list loading and processing ...
```

---

## Proposed Changes

### 1. New CLI Structure

Replace the implicit mode detection with explicit, mutually-exclusive mode arguments:

#### New Mode Arguments

| New Argument | Old Equivalent | Description |
|--------------|----------------|-------------|
| `--validate LISTING` | `--validate --listing LISTING` | Validate filesystem against listing |
| `--generate LISTING` | `--generate-listing LISTING` | Generate listing from filesystem |
| `--apply LISTING` | `--listing LISTING` (no flags) | Apply metadata from listing to filesystem |

#### Unified Attribute Selection

| New Argument | Old Equivalent | Description |
|--------------|----------------|-------------|
| `--attrs ATTRS` | `--validate-attrs` / `--attr-map` | Context-aware attribute selection |

The `--attrs` argument behavior depends on the mode:
- **Validate mode**: Attributes to compare (replaces `--validate-attrs`)
- **Generate mode**: Attributes to include in listing (new capability, checksum on by default for files)
- **Apply mode**: Attributes to set on filesystem (simplified from `--attr-map`)

### 2. New CLI Examples

#### Validate Mode
```bash
# New (proposed)
pyTackle ValidateCopy --validate source.csv --base-dir /dest --attrs checksum,size

# Old (current)
pyTackle ValidateCopy --validate --listing source.csv --base-dir /dest --validate-attrs checksum,size
```

#### Generate Mode
```bash
# New (proposed)
pyTackle ValidateCopy --generate output.csv --base-dir /source --attrs checksum

# Old (current)
pyTackle ValidateCopy --generate-listing output.csv --base-dir /source --checksum
```

#### Apply Mode
```bash
# New (proposed)
pyTackle ValidateCopy --apply source.csv --base-dir /dest --attrs creation,modify

# Old (current)
pyTackle ValidateCopy --listing source.csv --base-dir /dest --attr-map creation:0,modify:2
```

### 3. Attribute Handling by Mode

#### Validate Mode (`--validate`)
- `--attrs` specifies which attributes to compare
- Default: `size,creation,permissions,uid,gid,checksum,entry_type,path`
- Example: `--attrs checksum` for quick data integrity check

#### Generate Mode (`--generate`)
- `--attrs` specifies which attributes to include
- Default: all attributes including checksum for files
- Example: `--attrs creation,modify,size` to skip checksum calculation

#### Apply Mode (`--apply`)
- `--attrs` specifies which attributes to set on filesystem
- Default: `creation,access,modify` (timestamp attributes)
- Note: Only applicable attributes can be set (not size, checksum, entry_type)
- The old `--attr-map` selector syntax (`:0`, `:earliest`) may still be needed for advanced cases

### 4. Backward Compatibility Strategy

#### Phase 1: Deprecation Warnings
- Keep old arguments functional but emit deprecation warnings
- Map old arguments to new internally:
  - `--listing PATH` + `--validate` → `--validate PATH`
  - `--generate-listing PATH` → `--generate PATH`
  - `--listing PATH` (alone) → `--apply PATH`
  - `--validate-attrs` → `--attrs` (in validate mode)

#### Phase 2: Documentation Update
- Update [`docs/ValidateCopy.md`](../docs/ValidateCopy.md) with new syntax
- Provide migration examples

#### Phase 3: Removal (Future Release)
- Remove deprecated arguments after sufficient notice period

### 5. Logging Improvements

#### 5.1 Mode and Settings Logging

Add comprehensive startup logging after argument parsing:

```python
# After mode detection:
logger.info("Mode: %s", mode_name)  # "validate" | "generate" | "apply"
logger.info("Listing file: %s", listing_path)
logger.info("Base directory: %s", base_dir)
logger.info("Entry types: %s", ', '.join(sorted(allowed_types)))
logger.info("Attributes: %s", ', '.join(attrs))
if dry_run:
    logger.info("Dry-run mode: enabled")
```

#### 5.2 List Loading Progress

Add progress logging during listing file parsing:

```python
def parse_listing(...) -> List[FileEntry]:
    entries: List[FileEntry] = []
    total_lines = 0
    
    # First pass: count lines for progress
    with open(listing_path, ...) as fh:
        total_lines = sum(1 for _ in fh)
    logger.info("Loading listing: %d lines", total_lines)
    
    # Second pass: parse with progress
    with open(listing_path, ...) as fh:
        reader = csv.reader(fh)
        for lineno, cols in enumerate(reader, start=1):
            # Log progress every 1000 entries or 10%
            if lineno % 1000 == 0 or lineno == total_lines:
                pct = (lineno / total_lines) * 100
                logger.info("Loading: %d/%d entries (%.1f%%)", lineno, total_lines, pct)
            # ... parse row ...
    
    logger.info("Loaded %d entries from listing", len(entries))
    return entries
```

#### 5.3 Processing Progress

Add progress logging during validation and apply operations:

```python
def _do_validate(self) -> int:
    total = len(entries)
    logger.info("Validating %d entries...", total)
    
    for idx, fe in enumerate(entries, start=1):
        if idx % 100 == 0 or idx == total:
            pct = (idx / total) * 100
            logger.info("Progress: %d/%d (%.1f%%) — %d passed, %d failed",
                       idx, total, pct, passed, failed)
        # ... validate entry ...
    
    logger.info("Validation complete: %d passed, %d failed", passed, failed)
```

#### 5.4 Verbose Level Control

Enhance the `-v` flag to support multiple verbosity levels:

| Level | Flag | Logging |
|-------|------|---------|
| Normal | (none) | Summary messages only |
| Verbose | `-v` | Progress every 100 entries + per-entry results |
| Debug | `-vv` | All details including attribute values |

---

## Implementation Plan

### Task 1: Add Progress Logging to Existing Code

**Files to modify:**
- [`tackles/ValidateCopy.py`](../tackles/ValidateCopy.py) — Add progress logging to `parse_listing()`, `_do_validate()`, and `_do_attr_map()`
- [`common/listing.py`](../common/listing.py) — Add optional progress callback to `iter_listing()`

**Changes:**
1. Add a progress callback parameter to listing parsers
2. Log entry counts at regular intervals (every 100 or 1000 entries)
3. Log percentages for long operations
4. Add startup mode/settings summary logging

### Task 2: Refactor CLI Arguments

**Files to modify:**
- [`tackles/ValidateCopy.py`](../tackles/ValidateCopy.py) — Refactor `arg_parser()` and `__init__()`

**Changes:**
1. Add new mutually-exclusive argument group: `--validate`, `--generate`, `--apply`
2. Add unified `--attrs` argument
3. Keep old arguments with deprecation warnings
4. Refactor mode detection logic to use explicit arguments

### Task 3: Implement Unified Attrs Handling

**Files to modify:**
- [`tackles/ValidateCopy.py`](../tackles/ValidateCopy.py)
- [`common/attr_map.py`](../common/attr_map.py) — May need new helper functions

**Changes:**
1. Create `parse_attrs()` function that handles the unified format
2. Implement mode-specific default attrs
3. Map `--attrs` to appropriate behavior per mode

### Task 4: Backward Compatibility Layer

**Files to modify:**
- [`tackles/ValidateCopy.py`](../tackles/ValidateCopy.py)

**Changes:**
1. Add deprecation warning emission for old argument patterns
2. Map old arguments to new internal representation
3. Add migration helper messages pointing to new syntax

### Task 5: Update Documentation

**Files to modify:**
- [`docs/ValidateCopy.md`](../docs/ValidateCopy.md)

**Changes:**
1. Document new CLI syntax
2. Add migration guide section
3. Update all examples to use new syntax
4. Note deprecated arguments

### Task 6: Add Tests

**Files to modify:**
- [`tests/test_tackles_integration.py`](../tests/test_tackles_integration.py) — Add CLI argument tests

**Changes:**
1. Test new argument parsing
2. Test deprecation warnings
3. Test backward compatibility
4. Test progress logging output

---

## Detailed Code Changes

### CLI Argument Parser Refactoring

```python
# In ValidateCopy.arg_parser():

@classmethod
def arg_parser(cls, subparser):
    # Mode group (mutually exclusive)
    mode_group = subparser.add_mutually_exclusive_group()
    mode_group.add_argument(
        '--validate',
        type=pathlib.Path,
        metavar='LISTING',
        default=None,
        help='Validate filesystem against listing file',
    )
    mode_group.add_argument(
        '--generate',
        type=pathlib.Path,
        metavar='LISTING',
        default=None,
        help='Generate listing from filesystem',
    )
    mode_group.add_argument(
        '--apply',
        type=pathlib.Path,
        metavar='LISTING',
        default=None,
        help='Apply metadata from listing to filesystem',
    )
    
    # Common options
    subparser.add_argument(
        '--base-dir',
        type=pathlib.Path,
        required=True,
        help='Local base directory for path resolution',
    )
    subparser.add_argument(
        '--attrs',
        type=str,
        default=None,
        help=(
            'Comma-separated attributes. Behavior depends on mode:\n'
            '  validate: attributes to compare (default: all)\n'
            '  generate: attributes to include (default: all + checksum)\n'
            '  apply: attributes to set (default: creation,access,modify)'
        ),
    )
    subparser.add_argument(
        '--types',
        type=str,
        default='d,f,l',
        help='Entry types to process: f,d,l (default: d,f,l)',
    )
    
    # Execution options
    subparser.add_argument('--dry-run', action='store_true')
    subparser.add_argument('-v', '--verbose', action='count', default=0)
    subparser.add_argument('-q', '--quiet', action='store_true')
    
    # === DEPRECATED ARGUMENTS (backward compatibility) ===
    subparser.add_argument(
        '--listing',
        type=pathlib.Path,
        default=None,
        help=argparse.SUPPRESS,  # Hidden from help
    )
    subparser.add_argument(
        '--generate-listing',
        type=pathlib.Path,
        default=None,
        help=argparse.SUPPRESS,
    )
    subparser.add_argument(
        '--validate-attrs',
        type=str,
        default=None,
        help=argparse.SUPPRESS,
    )
    subparser.add_argument(
        '--attr-map',
        type=str,
        default=None,
        help=argparse.SUPPRESS,
    )
    subparser.add_argument(
        '--checksum',
        action='store_true',
        default=False,
        help=argparse.SUPPRESS,
    )
    subparser.add_argument(
        '--checksum-algorithm',
        type=str,
        default='md5',
        help=argparse.SUPPRESS,
    )
```

### Mode Detection with Deprecation Warnings

```python
def __init__(self, parser):
    super().__init__(parser)
    options, _ = parser.parse_known_args()
    
    # Detect mode from new or deprecated arguments
    self._handle_deprecated_args(options)
    
    # Determine mode
    if options.validate:
        self.mode = 'validate'
        self.listing_path = str(options.validate)
    elif options.generate:
        self.mode = 'generate'
        self.output_path = str(options.generate)
    elif options.apply:
        self.mode = 'apply'
        self.listing_path = str(options.apply)
    else:
        # No mode specified — error
        logger.error(
            'One of --validate, --generate, or --apply is required'
        )
        sys.exit(1)
    
    # Log mode and settings
    self._log_settings()

def _handle_deprecated_args(self, options):
    """Map deprecated arguments to new ones with warnings."""
    import warnings
    
    # --generate-listing → --generate
    if options.generate_listing is not None:
        warnings.warn(
            '--generate-listing is deprecated, use --generate instead',
            DeprecationWarning,
        )
        logger.warning(
            'DEPRECATED: --generate-listing PATH → --generate PATH'
        )
        if options.generate is None:
            options.generate = options.generate_listing
    
    # --validate (flag) + --listing → --validate LISTING
    if hasattr(options, 'validate') and isinstance(options.validate, bool):
        if options.validate and options.listing:
            warnings.warn(
                '--validate --listing PATH is deprecated, '
                'use --validate PATH instead',
                DeprecationWarning,
            )
            logger.warning(
                'DEPRECATED: --validate --listing PATH → --validate PATH'
            )
            options.validate = options.listing
    
    # --listing alone → --apply
    if options.listing and not options.validate and not options.generate:
        warnings.warn(
            '--listing PATH is deprecated, use --apply PATH instead',
            DeprecationWarning,
        )
        logger.warning(
            'DEPRECATED: --listing PATH → --apply PATH'
        )
        options.apply = options.listing
    
    # --validate-attrs → --attrs (in validate mode)
    if options.validate_attrs and options.attrs is None:
        warnings.warn(
            '--validate-attrs is deprecated, use --attrs instead',
            DeprecationWarning,
        )
        logger.warning(
            'DEPRECATED: --validate-attrs → --attrs'
        )
        options.attrs = options.validate_attrs
```

### Progress Logging Implementation

```python
def _log_settings(self):
    """Log mode and configuration at startup."""
    logger.info("=" * 60)
    logger.info("ValidateCopy — Mode: %s", self.mode.upper())
    logger.info("=" * 60)
    logger.info("Base directory: %s", self.base_dir)
    
    if self.mode in ('validate', 'apply'):
        logger.info("Listing file: %s", self.listing_path)
    else:
        logger.info("Output file: %s", self.output_path)
    
    logger.info("Entry types: %s", ', '.join(sorted(self.allowed_types)))
    logger.info("Attributes: %s", ', '.join(self.attrs) if self.attrs else '(default)')
    
    if self.dry_run:
        logger.info("Dry-run: ENABLED (no changes will be made)")
    logger.info("-" * 60)


def parse_listing_with_progress(
    listing_path: str,
    base_dir: str,
    script_base_path: Optional[str] = None,
    progress_interval: int = 1000,
) -> List[FileEntry]:
    """Parse listing with progress logging."""
    entries: List[FileEntry] = []
    
    # Count total lines
    with open(listing_path, encoding='utf-8-sig') as fh:
        total_lines = sum(1 for line in fh if line.strip())
    
    logger.info("Loading listing: %s (%d lines)", listing_path, total_lines)
    
    with open(listing_path, encoding='utf-8-sig', newline='') as fh:
        first_line = fh.readline()
        if not first_line:
            return entries
        
        fmt = detect_format(first_line)
        logger.info("Detected format: %s", fmt)
        fh.seek(0)
        
        row_parser = {
            FORMAT_CANONICAL: _parse_row_canonical,
            FORMAT_LINUX: _parse_row_linux,
        }[fmt]
        
        reader = csv.reader(fh)
        processed = 0
        
        for lineno, cols in enumerate(reader, start=1):
            if not cols or all(c.strip() == '' for c in cols):
                continue
            
            try:
                fe = row_parser(cols)
                rel_path = normalize_path(fe.path, script_base_path)
                full_path = os.path.normpath(os.path.join(base_dir, rel_path))
                fe.path = full_path
                entries.append(fe)
                processed += 1
                
                # Progress logging
                if processed % progress_interval == 0:
                    pct = (processed / total_lines) * 100
                    logger.info(
                        "Loading: %d/%d entries (%.1f%%)",
                        processed, total_lines, pct
                    )
            except Exception as exc:
                logger.warning('Line %d: skipping — %s', lineno, exc)
    
    logger.info("Loaded %d entries", len(entries))
    return entries
```

---

## Migration Guide

### For Users

| Old Command | New Command |
|-------------|-------------|
| `--generate-listing out.csv --base-dir /path` | `--generate out.csv --base-dir /path` |
| `--validate --listing in.csv --base-dir /path` | `--validate in.csv --base-dir /path` |
| `--listing in.csv --base-dir /path` | `--apply in.csv --base-dir /path` |
| `--validate-attrs checksum,size` | `--attrs checksum,size` |
| `--checksum --checksum-algorithm sha256` | `--attrs checksum` with `--checksum-algorithm sha256` |

### Behavior Changes

1. **Default entry types**: Changed from `d` (directories only) to `d,f,l` (all types) for more intuitive defaults
2. **Checksum in generate mode**: Enabled by default for files (use `--attrs creation,modify,size` to disable)
3. **Progress logging**: Now shown by default every 1000 entries

---

## Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| Breaking existing scripts | High | Maintain backward compatibility with deprecation warnings |
| User confusion during transition | Medium | Clear migration guide and warning messages |
| Performance impact of progress logging | Low | Log only at intervals, not every entry |

---

## Success Criteria

1. New CLI syntax works as documented
2. Old CLI syntax works with deprecation warnings
3. Progress logging shows during long operations
4. Mode/settings are clearly logged at startup
5. All existing tests pass
6. Documentation is updated
