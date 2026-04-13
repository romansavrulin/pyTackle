# pyTackle Development Plans

This folder contains design documents and implementation plans for pyTackle features and refactoring efforts.

## Status Conventions

Each plan document includes a YAML front-matter header with status information:

```yaml
---
status: IMPLEMENTED | IN PROGRESS | OUTDATED | SUPERSEDED
implemented_in: [file paths where the plan was implemented]
last_reviewed: YYYY-MM-DD
notes: [brief description of current state]
---
```

### Status Definitions

| Status | Description |
|--------|-------------|
| **IMPLEMENTED** | The plan has been fully or substantially implemented. The `implemented_in` field lists the relevant source files. |
| **IN PROGRESS** | Implementation is actively underway. Some features may be complete while others are pending. |
| **OUTDATED** | The plan describes an approach that is no longer relevant due to architectural changes or evolving requirements. |
| **SUPERSEDED** | The plan's functionality has been absorbed into another implementation. The `notes` field indicates what replaced it. |

## Plan Index

### Active Tackles

| Plan | Status | Implemented In |
|------|--------|----------------|
| [CsvToSqlite.md](CsvToSqlite.md) | ✅ IMPLEMENTED | [`tackles/CsvToSqlite.py`](../tackles/CsvToSqlite.py) |
| [FclonesDuplicates.md](FclonesDuplicates.md) | ✅ IMPLEMENTED | [`tackles/FclonesDuplicates.py`](../tackles/FclonesDuplicates.py) |
| [MediaIntegrityCheck.md](MediaIntegrityCheck.md) | ✅ IMPLEMENTED | [`tackles/MediaIntegrityCheck.py`](../tackles/MediaIntegrityCheck.py) |

### Core Infrastructure

| Plan | Status | Implemented In |
|------|--------|----------------|
| [FileEntry.md](FileEntry.md) | ✅ IMPLEMENTED | [`common/FileEntry.py`](../common/FileEntry.py), [`common/attr_map.py`](../common/attr_map.py), [`common/checksum.py`](../common/checksum.py), [`common/fs_attrs.py`](../common/fs_attrs.py), [`common/listing.py`](../common/listing.py) |

### ValidateCopy Evolution

The ValidateCopy tackle absorbed functionality originally planned for SetCreationTime:

| Plan | Status | Notes |
|------|--------|-------|
| [ValidateCopy_cli_refactor.md](ValidateCopy_cli_refactor.md) | ✅ IMPLEMENTED | New CLI structure with `--validate`/`--generate`/`--apply` modes |
| [SetCreationTime.md](SetCreationTime.md) | ⚠️ SUPERSEDED | Original design; functionality consolidated into ValidateCopy |
| [SetCreationTime_refactor.md](SetCreationTime_refactor.md) | ⚠️ SUPERSEDED | Migration plan; executed as part of ValidateCopy development |
| [SetCreationTime_validation_checksum.md](SetCreationTime_validation_checksum.md) | ✅ IMPLEMENTED | Checksum features implemented in ValidateCopy |
| [SetCreationTime_FileEntry_consolidation.md](SetCreationTime_FileEntry_consolidation.md) | ✅ IMPLEMENTED | `FileEntry.validate()` method implemented |
| [SetCreationTime_entry_type_refactor.md](SetCreationTime_entry_type_refactor.md) | ✅ IMPLEMENTED | Entry type normalization in FileEntry and attr_map |

## Historical Context

The SetCreationTime tackle was the original timestamp management tool. During development, its functionality was consolidated into the more general-purpose ValidateCopy tackle, which now handles:

- **Generate mode** (`--generate`): Create canonical CSV listings from directory scans
- **Validate mode** (`--validate`): Compare filesystem state against listings
- **Apply mode** (`--apply`): Restore timestamps and attributes from listings

The SetCreationTime plans remain in this folder as historical documentation of the design evolution and to preserve the rationale behind architectural decisions.

## Adding New Plans

When creating a new plan document:

1. Add the status header at the top of the document (after any title)
2. Use `status: IN PROGRESS` for new plans
3. Update this README with an entry in the appropriate section
4. As implementation progresses, update the status header to reflect current state

## Related Documentation

- [`docs/`](../docs/) — User-facing documentation for implemented features
- [`tackles/`](../tackles/) — Implementation source code
- [`common/`](../common/) — Shared infrastructure modules
