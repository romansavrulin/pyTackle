"""External checksum utility wrapper with hashlib fallback.

Used by FileEntry.calculate_checksum() and FileEntry.recalculate_checksum()
to compute file checksums. Returns raw hexdigest strings — the caller is
responsible for storing the result as "algorithm:hexdigest".
"""

from __future__ import annotations

import hashlib
import logging
import subprocess

logger = logging.getLogger(__name__)


def calculate(path: str, algorithm: str = 'md5',
              utility: str | None = None) -> str:
    """Calculate checksum of file at *path*.

    If *utility* is provided (e.g. ``'md5sum'``, ``'sha256sum'``, ``'shasum'``),
    runs it as a subprocess via :func:`_run_external`.
    Otherwise falls back to :func:`_run_hashlib`.

    Returns the hexdigest string (no algorithm prefix).
    """
    if utility:
        logger.debug("Calculating checksum for %s using external utility %s",
                      path, utility)
        return _run_external(path, utility)
    logger.debug("Calculating checksum for %s using hashlib algorithm '%s'",
                  path, algorithm)
    return _run_hashlib(path, algorithm)


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


def _run_hashlib(path: str, algorithm: str) -> str:
    """Calculate checksum using Python's :mod:`hashlib`.

    Reads the file in 8192-byte chunks to handle large files efficiently.
    Uses ``hashlib.new(algorithm)`` to support any algorithm hashlib knows about.

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

    with open(path, "rb") as f:
        while chunk := f.read(8192):
            file_hash.update(chunk)

    hexdigest = file_hash.hexdigest()
    logger.debug("hashlib %s returned hexdigest: %s", algorithm, hexdigest)
    return hexdigest
