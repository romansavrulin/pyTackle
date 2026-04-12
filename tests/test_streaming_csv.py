"""Tests for common/streaming_csv.py — StreamingCsvWriter base class."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from typing import List

import pytest

from common.streaming_csv import StreamingCsvWriter


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
