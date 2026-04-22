"""Streaming CSV writer base class for memory-efficient file output.

Provides a generic abstract base class for streaming CSV writers that:
- Handle file opening/closing and context management
- Support lazy (on-first-write) or eager (explicit open) modes
- Track write counts
- Use proper CSV escaping to preserve newlines and special characters

Subclasses only need to implement `_to_row()` to convert items to CSV rows.
"""

from __future__ import annotations

import csv
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Generic, List, Optional, Tuple, TypeVar, TextIO

from common.FileEntry import FileEntry
from common.attr_map import CANONICAL_MAP


def get_error_filename(source_path: Path | str) -> Path:
    """Generate error CSV filename from source filename.
    
    Inserts '_error' before the file extension.
    
    Args:
        source_path: Path to the source file.
    
    Returns:
        Path object with '_error' suffix.
    
    Examples:
        >>> get_error_filename('files.csv')
        PosixPath('files_error.csv')
        >>> get_error_filename(Path('data/listing.csv'))
        PosixPath('data/listing_error.csv')
        >>> get_error_filename('backup.txt')
        PosixPath('backup_error.txt')
    """
    path = Path(source_path) if isinstance(source_path, str) else source_path
    stem = path.stem
    suffix = path.suffix
    return path.parent / f"{stem}_error{suffix}"

# Generic type for items written to the CSV
T = TypeVar('T')


class StreamingCsvWriter(ABC, Generic[T]):
    """Abstract base class for streaming CSV writers.
    
    Provides common file handling, context manager, and counting logic.
    Subclasses override `_to_row()` to convert items to CSV rows.
    
    Attributes:
        path: Path to the output CSV file.
        count: Number of items written so far.
    
    Example usage (subclass):
    
        class MyWriter(StreamingCsvWriter[MyRecord]):
            def __init__(self, path: str):
                super().__init__(path, header=('col1', 'col2'), lazy_open=False)
            
            def _to_row(self, record: MyRecord) -> List[str]:
                return [record.field1, str(record.field2)]
        
        with MyWriter('output.csv') as writer:
            writer.write(record1)
            writer.write(record2)
    """
    
    def __init__(
        self,
        path: str,
        header: Optional[Tuple[str, ...]] = None,
        lazy_open: bool = True,
        flush_on_write: bool = False,
    ):
        """Initialize the streaming CSV writer.
        
        Args:
            path: Path to the output CSV file.
            header: Optional tuple of column names. If provided, written as first row.
            lazy_open: If True, file is opened on first write. If False, must call open().
            flush_on_write: If True, flush after each write (useful for debug logs).
        """
        self.path = path
        self._header = header
        self._lazy_open = lazy_open
        self._flush_on_write = flush_on_write
        self._fh: Optional[TextIO] = None
        self._writer: Optional[csv.writer] = None
        self._count: int = 0
    
    @abstractmethod
    def _to_row(self, item: T) -> List[str]:
        """Convert an item to a list of string values for CSV output.
        
        Subclasses must implement this method to serialize their specific
        data type to CSV columns.
        
        Args:
            item: The item to convert.
        
        Returns:
            A list of string values, one per column.
        """
        ...
    
    def _ensure_open(self) -> None:
        """Open the file on demand (for lazy_open mode)."""
        if self._fh is None:
            self._fh = open(self.path, 'w', newline='', encoding='utf-8')
            self._writer = csv.writer(self._fh, quoting=csv.QUOTE_MINIMAL)
            if self._header:
                self._writer.writerow(self._header)
                self._fh.flush()
    
    def open(self) -> None:
        """Explicitly open the file.
        
        In lazy_open mode, this is optional — the file will be opened
        automatically on first write. In eager mode (lazy_open=False),
        this must be called before write() or via context manager.
        """
        self._ensure_open()
    
    def write(self, item: T) -> None:
        """Write a single item to the CSV file.
        
        Args:
            item: The item to write. Will be converted using `_to_row()`.
        
        Raises:
            RuntimeError: If lazy_open=False and open() was not called.
        """
        if self._lazy_open:
            self._ensure_open()
        elif self._writer is None:
            raise RuntimeError(
                f'{self.__class__.__name__} not opened. '
                f'Call open() or use as context manager.'
            )
        
        row = self._to_row(item)
        self._writer.writerow(row)
        self._count += 1
        
        if self._flush_on_write and self._fh is not None:
            self._fh.flush()
    
    @property
    def count(self) -> int:
        """Return the number of items written so far."""
        return self._count
    
    @property
    def is_open(self) -> bool:
        """Return True if the file is currently open."""
        return self._fh is not None
    
    def close(self) -> None:
        """Close the CSV file if it was opened.
        
        Safe to call multiple times or if file was never opened.
        """
        if self._fh is not None:
            self._fh.close()
            self._fh = None
            self._writer = None
    
    def __enter__(self) -> 'StreamingCsvWriter[T]':
        """Context manager entry. Opens file in eager mode."""
        if not self._lazy_open:
            self.open()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit. Closes the file."""
        self.close()


class StreamingListingWriter(StreamingCsvWriter[FileEntry]):
    """Streaming CSV writer for FileEntry listings.
    
    Writes entries line-by-line to avoid memory accumulation.
    Uses lazy open mode — file is created only on first write.
    """
    
    def __init__(
        self,
        path: str,
        attr_map: Optional[Dict[str, str]] = None,
        include_header: bool = True,
        flush_on_write: bool = True,
        lazy_open: bool = False
    ):
        """Initialize the streaming listing writer.
        
        Args:
            path: Path to the output CSV file.
            attr_map: Column mapping for FileEntry serialization.
            include_header: If True, write a header row with attribute names
                when the file is opened. Defaults to True.
        """
        self.attr_map = attr_map or CANONICAL_MAP
        
        # Generate header from attr_map keys in column order
        header: Optional[Tuple[str, ...]] = None
        if include_header:
            header = self._generate_header(self.attr_map)
        
        super().__init__(
            path,
            header=header,
            lazy_open=lazy_open,
            flush_on_write=flush_on_write,
        )
    
    @staticmethod
    def _generate_header(attr_map: Dict[str, str]) -> Tuple[str, ...]:
        """Generate a header tuple from attr_map keys in column order.
        
        Args:
            attr_map: Column mapping (attribute name → column index).
        
        Returns:
            Tuple of attribute names in column order.
        """
        # Find max column index to determine row width
        max_col = max(int(idx) for idx in attr_map.values())
        header_list = [''] * (max_col + 1)
        
        for attr, col_idx in attr_map.items():
            header_list[int(col_idx)] = attr
        
        return tuple(header_list)
    
    def _to_row(self, entry: FileEntry) -> List[str]:
        """Convert a FileEntry to a list of CSV column values."""
        return entry.to_listing_row(self.attr_map)


class StreamingErrorWriter(StreamingCsvWriter[Tuple[FileEntry, str]]):
    """Streaming CSV writer for error logging with FileEntry + error message.
    
    Writes FileEntry data plus an error message column for tracking failed
    operations during copy/delete modes. Uses lazy open mode — file is only
    created if errors actually occur.
    
    The output format matches the canonical listing format with an additional
    'error' column at the end.
    """
    
    def __init__(
        self,
        path: str | Path,
        attr_map: Optional[Dict[str, str]] = None,
        flush_on_write: bool = True,
    ):
        """Initialize the streaming error writer.
        
        Args:
            path: Path to the output error CSV file.
            attr_map: Column mapping for FileEntry serialization.
                Defaults to CANONICAL_MAP.
            flush_on_write: If True, flush after each write. Defaults to True
                for durability in error logging.
        """
        self.attr_map = attr_map or CANONICAL_MAP
        
        # Generate header with error column
        header = self._generate_header_with_error(self.attr_map)
        
        super().__init__(
            str(path),
            header=header,
            lazy_open=True,  # Only create file if errors occur
            flush_on_write=flush_on_write,
        )
    
    @staticmethod
    def _generate_header_with_error(attr_map: Dict[str, str]) -> Tuple[str, ...]:
        """Generate a header tuple from attr_map keys plus 'error' column.
        
        Args:
            attr_map: Column mapping (attribute name → column index).
        
        Returns:
            Tuple of attribute names in column order, with 'error' at the end.
        """
        # Find max column index to determine row width
        max_col = max(int(idx) for idx in attr_map.values())
        header_list = [''] * (max_col + 1)
        
        for attr, col_idx in attr_map.items():
            header_list[int(col_idx)] = attr
        
        # Add error column at the end
        header_list.append('error')
        
        return tuple(header_list)
    
    def _to_row(self, item: Tuple[FileEntry, str]) -> List[str]:
        """Convert a (FileEntry, error_message) tuple to CSV columns.
        
        Args:
            item: A tuple of (FileEntry, error_message).
        
        Returns:
            List of string values for CSV output.
        """
        entry, error_msg = item
        row = entry.to_listing_row(self.attr_map)
        row.append(error_msg)
        return row
