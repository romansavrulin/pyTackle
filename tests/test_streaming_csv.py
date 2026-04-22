"""Tests for common/streaming_csv.py — StreamingCsvWriter base class."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List

import pytest

from common.FileEntry import FileEntry
from common.attr_map import CANONICAL_MAP
from common.streaming_csv import (
    StreamingCsvWriter,
    StreamingErrorWriter,
    get_error_filename,
)


# ===========================================================================
# Test Fixtures — concrete implementations for testing
# ===========================================================================


@dataclass
class SimpleRecord:
    """Simple test record with two fields."""
    name: str
    value: int


class SimpleWriter(StreamingCsvWriter[SimpleRecord]):
    """Concrete implementation for testing."""
    
    def _to_row(self, record: SimpleRecord) -> List[str]:
        return [record.name, str(record.value)]


class EagerWriter(StreamingCsvWriter[SimpleRecord]):
    """Writer with eager open mode for testing."""
    
    def __init__(self, path: str):
        super().__init__(
            path,
            header=('name', 'value'),
            lazy_open=False,
            flush_on_write=True,
        )
    
    def _to_row(self, record: SimpleRecord) -> List[str]:
        return [record.name, str(record.value)]


# ===========================================================================
# 1. Basic Initialization Tests
# ===========================================================================


class TestStreamingCsvWriterInit:
    """Tests for StreamingCsvWriter initialization."""

    def test_default_initialization(self, tmp_path):
        """Default initialization with minimal parameters."""
        path = tmp_path / 'output.csv'
        writer = SimpleWriter(str(path))
        
        assert writer.path == str(path)
        assert writer.count == 0
        assert writer.is_open is False

    def test_with_header(self, tmp_path):
        """Initialization with header tuple."""
        path = tmp_path / 'output.csv'
        writer = SimpleWriter(str(path), header=('col1', 'col2'))
        
        assert writer._header == ('col1', 'col2')

    def test_lazy_open_default(self, tmp_path):
        """lazy_open should be True by default."""
        path = tmp_path / 'output.csv'
        writer = SimpleWriter(str(path))
        
        assert writer._lazy_open is True

    def test_eager_open_mode(self, tmp_path):
        """Test writer with lazy_open=False."""
        path = tmp_path / 'output.csv'
        writer = EagerWriter(str(path))
        
        assert writer._lazy_open is False


# ===========================================================================
# 2. Lazy Open Mode Tests
# ===========================================================================


class TestLazyOpenMode:
    """Tests for lazy_open=True behavior."""

    def test_file_not_created_until_write(self, tmp_path):
        """In lazy mode, file should not be created until first write."""
        path = tmp_path / 'output.csv'
        writer = SimpleWriter(str(path))
        
        assert not path.exists()
        writer.close()
        assert not path.exists()

    def test_file_created_on_first_write(self, tmp_path):
        """In lazy mode, file should be created on first write."""
        path = tmp_path / 'output.csv'
        writer = SimpleWriter(str(path))
        
        writer.write(SimpleRecord('test', 42))
        assert path.exists()
        writer.close()

    def test_header_written_on_first_write(self, tmp_path):
        """Header should be written when file is opened on first write."""
        path = tmp_path / 'output.csv'
        writer = SimpleWriter(str(path), header=('name', 'value'))
        
        writer.write(SimpleRecord('test', 42))
        writer.close()
        
        with open(path, 'r') as f:
            reader = csv.reader(f)
            header = next(reader)
            assert header == ['name', 'value']

    def test_explicit_open_in_lazy_mode(self, tmp_path):
        """Explicit open() should work in lazy mode."""
        path = tmp_path / 'output.csv'
        writer = SimpleWriter(str(path))
        
        writer.open()
        assert writer.is_open is True
        assert path.exists()
        writer.close()


# ===========================================================================
# 3. Eager Open Mode Tests
# ===========================================================================


class TestEagerOpenMode:
    """Tests for lazy_open=False behavior."""

    def test_file_created_on_open(self, tmp_path):
        """In eager mode, file should be created on open()."""
        path = tmp_path / 'output.csv'
        writer = EagerWriter(str(path))
        
        assert not path.exists()
        writer.open()
        assert path.exists()
        writer.close()

    def test_write_without_open_raises(self, tmp_path):
        """In eager mode, write() without open() should raise."""
        path = tmp_path / 'output.csv'
        writer = EagerWriter(str(path))
        
        with pytest.raises(RuntimeError, match='not opened'):
            writer.write(SimpleRecord('test', 42))

    def test_context_manager_opens_file(self, tmp_path):
        """Context manager should call open() in eager mode."""
        path = tmp_path / 'output.csv'
        
        with EagerWriter(str(path)) as writer:
            assert writer.is_open is True
        
        assert path.exists()


# ===========================================================================
# 4. Write Tests
# ===========================================================================


class TestWrite:
    """Tests for write() method."""

    def test_write_single_record(self, tmp_path):
        """Write a single record."""
        path = tmp_path / 'output.csv'
        writer = SimpleWriter(str(path))
        
        writer.write(SimpleRecord('hello', 123))
        writer.close()
        
        with open(path, 'r') as f:
            content = f.read()
        assert 'hello' in content
        assert '123' in content

    def test_write_multiple_records(self, tmp_path):
        """Write multiple records."""
        path = tmp_path / 'output.csv'
        writer = SimpleWriter(str(path))
        
        for i in range(5):
            writer.write(SimpleRecord(f'item{i}', i * 10))
        writer.close()
        
        assert writer.count == 5
        
        with open(path, 'r') as f:
            lines = f.readlines()
        assert len(lines) == 5

    def test_count_increments_on_write(self, tmp_path):
        """count should increment with each write."""
        path = tmp_path / 'output.csv'
        writer = SimpleWriter(str(path))
        
        assert writer.count == 0
        writer.write(SimpleRecord('a', 1))
        assert writer.count == 1
        writer.write(SimpleRecord('b', 2))
        assert writer.count == 2
        writer.close()

    def test_flush_on_write(self, tmp_path):
        """Test flush_on_write=True behavior."""
        path = tmp_path / 'output.csv'
        writer = EagerWriter(str(path))  # has flush_on_write=True
        writer.open()
        
        writer.write(SimpleRecord('test', 1))
        
        # File should be readable without closing
        with open(path, 'r') as f:
            content = f.read()
        assert 'test' in content
        
        writer.close()


# ===========================================================================
# 5. Close Tests
# ===========================================================================


class TestClose:
    """Tests for close() method."""

    def test_close_after_write(self, tmp_path):
        """Close after writing should finalize file."""
        path = tmp_path / 'output.csv'
        writer = SimpleWriter(str(path))
        
        writer.write(SimpleRecord('test', 1))
        writer.close()
        
        assert writer.is_open is False

    def test_close_without_open(self, tmp_path):
        """Close without open should be safe (no-op)."""
        path = tmp_path / 'output.csv'
        writer = SimpleWriter(str(path))
        
        writer.close()  # Should not raise
        assert writer.is_open is False

    def test_close_multiple_times(self, tmp_path):
        """Multiple close() calls should be safe."""
        path = tmp_path / 'output.csv'
        writer = SimpleWriter(str(path))
        
        writer.write(SimpleRecord('test', 1))
        writer.close()
        writer.close()  # Should not raise
        writer.close()  # Should not raise


# ===========================================================================
# 6. Context Manager Tests
# ===========================================================================


class TestContextManager:
    """Tests for __enter__ and __exit__."""

    def test_context_manager_lazy(self, tmp_path):
        """Context manager with lazy_open=True."""
        path = tmp_path / 'output.csv'
        
        with SimpleWriter(str(path)) as writer:
            writer.write(SimpleRecord('test', 1))
        
        assert path.exists()

    def test_context_manager_eager(self, tmp_path):
        """Context manager with lazy_open=False."""
        path = tmp_path / 'output.csv'
        
        with EagerWriter(str(path)) as writer:
            assert writer.is_open is True
            writer.write(SimpleRecord('test', 1))
        
        assert path.exists()

    def test_context_manager_closes_on_exit(self, tmp_path):
        """Context manager should close file on exit."""
        path = tmp_path / 'output.csv'
        writer = SimpleWriter(str(path))
        
        with writer:
            writer.write(SimpleRecord('test', 1))
        
        assert writer.is_open is False

    def test_context_manager_closes_on_exception(self, tmp_path):
        """Context manager should close file even on exception."""
        path = tmp_path / 'output.csv'
        writer = SimpleWriter(str(path))
        
        try:
            with writer:
                writer.write(SimpleRecord('test', 1))
                raise ValueError('Test error')
        except ValueError:
            pass
        
        assert writer.is_open is False


# ===========================================================================
# 7. Header Tests
# ===========================================================================


class TestHeader:
    """Tests for header handling."""

    def test_header_written_first(self, tmp_path):
        """Header should be written before data rows."""
        path = tmp_path / 'output.csv'
        writer = SimpleWriter(str(path), header=('name', 'value'))
        
        writer.write(SimpleRecord('first', 1))
        writer.write(SimpleRecord('second', 2))
        writer.close()
        
        with open(path, 'r') as f:
            reader = csv.reader(f)
            rows = list(reader)
        
        assert rows[0] == ['name', 'value']
        assert rows[1] == ['first', '1']
        assert rows[2] == ['second', '2']

    def test_no_header(self, tmp_path):
        """Writer without header should not write header row."""
        path = tmp_path / 'output.csv'
        writer = SimpleWriter(str(path), header=None)
        
        writer.write(SimpleRecord('only', 1))
        writer.close()
        
        with open(path, 'r') as f:
            reader = csv.reader(f)
            rows = list(reader)
        
        assert len(rows) == 1
        assert rows[0] == ['only', '1']


# ===========================================================================
# 8. CSV Escaping Tests
# ===========================================================================


class TestCsvEscaping:
    """Tests for proper CSV escaping."""

    def test_preserves_newlines(self, tmp_path):
        """Newlines in values should be preserved."""
        path = tmp_path / 'output.csv'
        writer = SimpleWriter(str(path))
        
        writer.write(SimpleRecord('line1\nline2\nline3', 1))
        writer.close()
        
        with open(path, 'r', newline='') as f:
            reader = csv.reader(f)
            row = next(reader)
        
        assert '\n' in row[0]
        assert 'line1' in row[0]
        assert 'line3' in row[0]

    def test_preserves_commas(self, tmp_path):
        """Commas in values should be escaped."""
        path = tmp_path / 'output.csv'
        writer = SimpleWriter(str(path))
        
        writer.write(SimpleRecord('a, b, c', 1))
        writer.close()
        
        with open(path, 'r', newline='') as f:
            reader = csv.reader(f)
            row = next(reader)
        
        assert row[0] == 'a, b, c'

    def test_preserves_quotes(self, tmp_path):
        """Quotes in values should be escaped."""
        path = tmp_path / 'output.csv'
        writer = SimpleWriter(str(path))
        
        writer.write(SimpleRecord('say "hello"', 1))
        writer.close()
        
        with open(path, 'r', newline='') as f:
            reader = csv.reader(f)
            row = next(reader)
        
        assert row[0] == 'say "hello"'


# ===========================================================================
# 9. is_open Property Tests
# ===========================================================================


class TestIsOpen:
    """Tests for is_open property."""

    def test_is_open_initially_false(self, tmp_path):
        """is_open should be False initially."""
        path = tmp_path / 'output.csv'
        writer = SimpleWriter(str(path))
        
        assert writer.is_open is False

    def test_is_open_after_write(self, tmp_path):
        """is_open should be True after write (in lazy mode)."""
        path = tmp_path / 'output.csv'
        writer = SimpleWriter(str(path))
        
        writer.write(SimpleRecord('test', 1))
        assert writer.is_open is True
        
        writer.close()

    def test_is_open_after_close(self, tmp_path):
        """is_open should be False after close."""
        path = tmp_path / 'output.csv'
        writer = SimpleWriter(str(path))
        
        writer.write(SimpleRecord('test', 1))
        writer.close()
        
        assert writer.is_open is False


# ===========================================================================
# 10. get_error_filename Tests
# ===========================================================================


class TestGetErrorFilename:
    """Tests for get_error_filename() function."""

    def test_simple_csv_filename(self):
        """Simple CSV filename should get _error suffix before extension."""
        result = get_error_filename('files.csv')
        assert result == Path('files_error.csv')

    def test_path_with_directory(self):
        """Path with directory should preserve directory."""
        result = get_error_filename('path/to/files.csv')
        assert result == Path('path/to/files_error.csv')

    def test_path_object_input(self):
        """Path object input should work."""
        result = get_error_filename(Path('data/listing.csv'))
        assert result == Path('data/listing_error.csv')

    def test_different_extension(self):
        """Non-csv extension should still work."""
        result = get_error_filename('backup.txt')
        assert result == Path('backup_error.txt')

    def test_no_extension(self):
        """File without extension should get _error suffix."""
        result = get_error_filename('myfile')
        assert result == Path('myfile_error')

    def test_multiple_dots_in_filename(self):
        """Multiple dots should only affect last extension."""
        result = get_error_filename('data.backup.2024.csv')
        assert result == Path('data.backup.2024_error.csv')

    def test_hidden_file(self):
        """Hidden file (starts with dot) should work."""
        result = get_error_filename('.hidden.csv')
        assert result == Path('.hidden_error.csv')

    def test_nested_directory_path(self):
        """Deeply nested path should preserve all directories."""
        result = get_error_filename('a/b/c/d/files.csv')
        assert result == Path('a/b/c/d/files_error.csv')


# ===========================================================================
# 11. StreamingErrorWriter Tests
# ===========================================================================


class TestStreamingErrorWriter:
    """Tests for StreamingErrorWriter class."""

    @pytest.fixture
    def sample_file_entry(self):
        """Create a sample FileEntry for testing."""
        return FileEntry(
            path='/tmp/test/file.txt',
            size=1024,
            creation=datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
            access=datetime(2024, 1, 16, 12, 0, 0, tzinfo=timezone.utc),
            modify=datetime(2024, 1, 15, 11, 45, 0, tzinfo=timezone.utc),
            permissions='0o644',
            uid=1000,
            gid=1000,
            checksum='md5:d41d8cd98f00b204e9800998ecf8427e',
            entry_type='f',
        )

    def test_creates_file_with_correct_header(self, tmp_path, sample_file_entry):
        """StreamingErrorWriter should create CSV with FileEntry columns + error."""
        path = tmp_path / 'errors.csv'
        
        with StreamingErrorWriter(str(path)) as writer:
            writer.write((sample_file_entry, 'Test error message'))
        
        # Read and verify header
        with open(path, 'r', newline='') as f:
            reader = csv.reader(f)
            header = next(reader)
        
        # Header should have 10 FileEntry columns + 'error' column
        assert len(header) == 11
        assert header[-1] == 'error'
        # Verify canonical column order
        assert header[0] == 'creation'
        assert header[1] == 'access'
        assert header[2] == 'modify'
        assert header[9] == 'path'

    def test_writes_file_entry_with_error(self, tmp_path, sample_file_entry):
        """StreamingErrorWriter should write FileEntry data + error message."""
        path = tmp_path / 'errors.csv'
        error_msg = 'File not found: source missing'
        
        with StreamingErrorWriter(str(path)) as writer:
            writer.write((sample_file_entry, error_msg))
        
        # Read and verify data row
        with open(path, 'r', newline='') as f:
            reader = csv.reader(f)
            header = next(reader)  # skip header
            row = next(reader)
        
        # Verify error message in last column
        assert row[-1] == error_msg
        # Verify path in correct column (column 9)
        assert row[9] == '/tmp/test/file.txt'
        # Verify entry_type (column 4)
        assert row[4] == 'f'

    def test_writes_multiple_errors(self, tmp_path):
        """StreamingErrorWriter should handle multiple error entries."""
        path = tmp_path / 'errors.csv'
        
        entries = [
            (FileEntry(path=f'/tmp/file{i}.txt', entry_type='f'), f'Error {i}')
            for i in range(5)
        ]
        
        with StreamingErrorWriter(str(path)) as writer:
            for entry, error in entries:
                writer.write((entry, error))
        
        # Verify count
        assert writer.count == 5
        
        # Read and verify all rows
        with open(path, 'r', newline='') as f:
            reader = csv.reader(f)
            next(reader)  # skip header
            rows = list(reader)
        
        assert len(rows) == 5
        for i, row in enumerate(rows):
            assert row[-1] == f'Error {i}'
            assert row[9] == f'/tmp/file{i}.txt'

    def test_lazy_open_no_file_without_errors(self, tmp_path):
        """StreamingErrorWriter should not create file if no errors written."""
        path = tmp_path / 'errors.csv'
        
        with StreamingErrorWriter(str(path)) as writer:
            pass  # No writes
        
        # File should not exist
        assert not path.exists()

    def test_flush_on_write_default(self, tmp_path, sample_file_entry):
        """StreamingErrorWriter should flush after each write by default."""
        path = tmp_path / 'errors.csv'
        
        writer = StreamingErrorWriter(str(path))
        writer.write((sample_file_entry, 'Error 1'))
        
        # File should be readable before close due to flush
        with open(path, 'r') as f:
            content = f.read()
        
        assert 'Error 1' in content
        writer.close()

    def test_handles_error_message_with_special_chars(self, tmp_path, sample_file_entry):
        """StreamingErrorWriter should properly escape special characters."""
        path = tmp_path / 'errors.csv'
        
        # Error message with commas, quotes, and newlines
        error_msg = 'Failed: "Permission denied", check\nthe permissions'
        
        with StreamingErrorWriter(str(path)) as writer:
            writer.write((sample_file_entry, error_msg))
        
        # Read back and verify escaping worked
        with open(path, 'r', newline='') as f:
            reader = csv.reader(f)
            next(reader)  # skip header
            row = next(reader)
        
        assert row[-1] == error_msg

    def test_uses_canonical_attr_map_by_default(self, tmp_path, sample_file_entry):
        """StreamingErrorWriter should use CANONICAL_MAP by default."""
        path = tmp_path / 'errors.csv'
        
        with StreamingErrorWriter(str(path)) as writer:
            writer.write((sample_file_entry, 'Test error'))
        
        with open(path, 'r', newline='') as f:
            reader = csv.reader(f)
            header = next(reader)
            row = next(reader)
        
        # Verify column positions match CANONICAL_MAP
        assert row[int(CANONICAL_MAP['path'])] == sample_file_entry.path
        assert row[int(CANONICAL_MAP['entry_type'])] == sample_file_entry.entry_type
        assert row[int(CANONICAL_MAP['size'])] == str(sample_file_entry.size)

    def test_path_object_accepted(self, tmp_path, sample_file_entry):
        """StreamingErrorWriter should accept Path objects."""
        path = tmp_path / 'errors.csv'
        
        with StreamingErrorWriter(path) as writer:
            writer.write((sample_file_entry, 'Error'))
        
        assert path.exists()
