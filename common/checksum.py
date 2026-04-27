"""External checksum utility wrapper with hashlib fallback.

Used by FileEntry.calculate_checksum() and FileEntry.recalculate_checksum()
to compute file checksums. Returns raw hexdigest strings — the caller is
responsible for storing the result as "algorithm:hexdigest".
"""

from __future__ import annotations

import hashlib
import logging
import subprocess
import time
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)


# Progress callback signature: (bytes_read, total_bytes, file_path) -> None
ProgressCallback = Callable[[int, int, str], None]


def calculate(
    path: str,
    algorithm: str = 'md5',
    utility: str | None = None,
    progress_callback: ProgressCallback | None = None,
) -> str:
    """Calculate checksum of file at *path*.

    If *utility* is provided (e.g. ``'md5sum'``, ``'sha256sum'``, ``'shasum'``),
    runs it as a subprocess via :func:`_run_external`.
    Otherwise falls back to :func:`_run_hashlib`.

    Args:
        path: Path to the file to checksum.
        algorithm: Hash algorithm name (e.g. 'md5', 'sha256'). Default 'md5'.
        utility: Optional external utility name (e.g. 'md5sum'). If provided,
            the external utility is used and progress_callback is ignored.
        progress_callback: Optional callback for progress reporting during
            hashlib-based calculation. Signature: (bytes_read, total_bytes, file_path).
            Called at time-based intervals (~5 seconds). Ignored when using
            external utilities.

    Returns the hexdigest string (no algorithm prefix).
    """
    if utility:
        logger.debug("Calculating checksum for %s using external utility %s",
                      path, utility)
        return _run_external(path, utility)
    logger.debug("Calculating checksum for %s using hashlib algorithm '%s'",
                  path, algorithm)
    return _run_hashlib(path, algorithm, progress_callback)


def _run_external(path: str, utility: str) -> str:
    """Run an external checksum utility and parse its output.

    Executes ``<utility> <path>`` and expects the standard output format::

        <hexdigest>  <filename>

    (two-space separator, as produced by ``md5sum``, ``sha256sum``, etc.)

    Returns just the hexdigest string.

    Raises:
        FileNotFoundError: If the utility is not found on the system.
        RuntimeError: If the utility exits with a non-zero code or its
            output cannot be parsed.
    """
    try:
        result = subprocess.run(
            [utility, path],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        raise FileNotFoundError(
            f"Checksum utility '{utility}' not found on this system"
        )

    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise RuntimeError(
            f"Checksum utility '{utility}' failed with exit code "
            f"{result.returncode}: {stderr}"
        )

    output = result.stdout.strip()
    # Standard format: "<hexdigest>  <filename>" (two spaces)
    parts = output.split("  ", 1)
    if len(parts) != 2 or not parts[0]:
        raise RuntimeError(
            f"Cannot parse output from '{utility}': {output!r}"
        )

    hexdigest = parts[0]
    logger.debug("External utility %s returned hexdigest: %s", utility, hexdigest)
    return hexdigest


def _run_hashlib(
    path: str,
    algorithm: str,
    progress_callback: ProgressCallback | None = None,
) -> str:
    """Calculate checksum using Python's :mod:`hashlib`.

    Reads the file in 64KB chunks to handle large files efficiently.
    Uses ``hashlib.new(algorithm)`` to support any algorithm hashlib knows about.

    Args:
        path: Path to the file to checksum.
        algorithm: Hash algorithm name supported by hashlib.
        progress_callback: Optional callback for progress reporting.
            Signature: (bytes_read, total_bytes, file_path).
            Called at time-based intervals (~5 seconds during hashing).

    Returns the hexdigest string.

    Raises:
        ValueError: If *algorithm* is not supported by hashlib.
    """
    try:
        file_hash = hashlib.new(algorithm)
    except ValueError:
        raise ValueError(
            f"Unsupported hash algorithm: '{algorithm}'. "
            f"Available: {', '.join(sorted(hashlib.algorithms_available))}"
        )

    # Get file size for progress reporting
    file_path = Path(path)
    file_size = file_path.stat().st_size
    bytes_read = 0
    
    # Time-based progress tracking
    last_progress = time.monotonic()
    progress_interval = 5.0  # seconds

    with open(path, "rb") as f:
        while chunk := f.read(65536):  # 64KB chunks for better performance
            file_hash.update(chunk)
            bytes_read += len(chunk)
            
            # Call progress callback at time-based intervals
            if progress_callback:
                now = time.monotonic()
                if now - last_progress >= progress_interval:
                    progress_callback(bytes_read, file_size, str(path))
                    last_progress = now

    hexdigest = file_hash.hexdigest()
    logger.debug("hashlib %s returned hexdigest: %s", algorithm, hexdigest)
    return hexdigest
