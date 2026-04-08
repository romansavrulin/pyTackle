"""
Filesystem attribute reading and applying.

Consolidates all filesystem attribute operations: reading stat metadata,
applying timestamps (including platform-specific creation-time setters),
permissions, and ownership.

Platform-specific creation-time implementations are copied from
``tackles/SetCreationTime.py`` to avoid coupling this shared module to
the tackle layer.
"""

from __future__ import annotations

import logging
import os
import platform
import stat
import subprocess
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_EPOCH_1601 = datetime(1601, 1, 1, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# Error classes
# ---------------------------------------------------------------------------

class FSNotPersistedError(RuntimeError):
    """Raised when an attempted metadata change is not observable via stat()."""


# ---------------------------------------------------------------------------
# Reading attributes
# ---------------------------------------------------------------------------

def _stat_creation_time(st: os.stat_result) -> datetime:
    """Extract creation time from a stat result as a TZ-aware UTC datetime.

    On macOS/Windows ``st_birthtime`` is available.  On Linux falls back to
    ``st_ctime`` (metadata-change time — the closest available proxy).
    """
    try:
        ts = st.st_birthtime
    except AttributeError:
        ts = st.st_birthtime_ns
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def _detect_entry_type(path: str, st: os.stat_result) -> str:
    """Detect entry type from filesystem: 'f', 'd', or 'l'."""
    if stat.S_ISLNK(st.st_mode):
        return 'l'
    if stat.S_ISDIR(st.st_mode):
        return 'd'
    return 'f'


def read_all(path: str) -> dict:
    """Read all available filesystem attributes from *path*.

    Returns a dict with keys matching :class:`FileEntry` field names.
    ``checksum`` is **not** included — it is expensive and must be
    explicitly requested.
    """
    st = os.lstat(path)
    return {
        'size': st.st_size,
        'creation': _stat_creation_time(st),
        'access': datetime.fromtimestamp(st.st_atime, tz=timezone.utc),
        'modify': datetime.fromtimestamp(st.st_mtime, tz=timezone.utc),
        'permissions': oct(stat.S_IMODE(st.st_mode)),
        'uid': st.st_uid,
        'gid': st.st_gid,
        'entry_type': _detect_entry_type(path, st),
    }


# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------

def _datetime_to_filetime_int(dt: datetime) -> int:
    """Convert a datetime to a Windows FILETIME 64-bit integer.

    FILETIME counts 100-nanosecond intervals since 1601-01-01 UTC.
    """
    delta = dt - _EPOCH_1601
    return int(delta.total_seconds() * 10_000_000)

def timestamps_are_close(ts1: datetime, ts2: datetime, delta_us: int = 3) -> bool:
    """Check if two timestamps are within `delta_ns` microseconds of each other."""
    diff = abs(ts1 - ts2)
    return diff <= timedelta(microseconds=delta_us)


# ---------------------------------------------------------------------------
# Platform-specific creation-time setters
# ---------------------------------------------------------------------------

def _set_creation_time_windows(path: str, dt: datetime) -> None:
    """Set creation time on Windows using the Win32 API via ctypes."""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

    GENERIC_WRITE = 0x40000000
    FILE_SHARE_READ = 0x00000001
    FILE_SHARE_WRITE = 0x00000002
    OPEN_EXISTING = 3
    FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
    INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value

    class FILETIME(ctypes.Structure):
        _fields_ = [
            ('dwLowDateTime', wintypes.DWORD),
            ('dwHighDateTime', wintypes.DWORD),
        ]

    CreateFileW = kernel32.CreateFileW
    CreateFileW.argtypes = [
        wintypes.LPCWSTR,  # lpFileName
        wintypes.DWORD,    # dwDesiredAccess
        wintypes.DWORD,    # dwShareMode
        ctypes.c_void_p,   # lpSecurityAttributes
        wintypes.DWORD,    # dwCreationDisposition
        wintypes.DWORD,    # dwFlagsAndAttributes
        wintypes.HANDLE,   # hTemplateFile
    ]
    CreateFileW.restype = wintypes.HANDLE

    SetFileTime = kernel32.SetFileTime
    SetFileTime.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(FILETIME),  # lpCreationTime
        ctypes.POINTER(FILETIME),  # lpLastAccessTime
        ctypes.POINTER(FILETIME),  # lpLastWriteTime
    ]
    SetFileTime.restype = wintypes.BOOL

    CloseHandle = kernel32.CloseHandle
    CloseHandle.argtypes = [wintypes.HANDLE]
    CloseHandle.restype = wintypes.BOOL

    # Open the file/directory (FILE_FLAG_BACKUP_SEMANTICS required for dirs)
    handle = CreateFileW(
        path,
        GENERIC_WRITE,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        None,
        OPEN_EXISTING,
        FILE_FLAG_BACKUP_SEMANTICS,
        None,
    )

    if handle == INVALID_HANDLE_VALUE or handle == -1:
        err = ctypes.get_last_error()
        raise OSError(f'CreateFileW failed for {path!r} (error {err})')

    try:
        ft_int = _datetime_to_filetime_int(dt)
        ft = FILETIME(
            dwLowDateTime=ft_int & 0xFFFFFFFF,
            dwHighDateTime=(ft_int >> 32) & 0xFFFFFFFF,
        )
        # Pass creation time only; NULL for access and write times
        ok = SetFileTime(handle, ctypes.byref(ft), None, None)
        if not ok:
            err = ctypes.get_last_error()
            raise OSError(f'SetFileTime failed for {path!r} (error {err})')
    finally:
        CloseHandle(handle)


def _set_creation_time_macos(path: str, dt: datetime) -> None:
    """Set creation time on macOS using the ``SetFile`` command."""
    # SetFile -d expects: "MM/DD/YYYY HH:MM:SS" in local time
    # Convert UTC datetime to local time for SetFile
    local_dt = dt.astimezone()
    formatted = local_dt.strftime('%m/%d/%Y %H:%M:%S')
    result = subprocess.run(
        ['SetFile', '-d', formatted, path],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise OSError(
            f'SetFile failed for {path!r}: {result.stderr.strip()}'
        )


def set_creation_time(path: str, dt: datetime) -> None:
    """Dispatch to the platform-specific creation-time setter.

    Raises :exc:`NotImplementedError` on Linux (no reliable mechanism).
    """
    system = platform.system()
    if system == 'Windows':
        _set_creation_time_windows(path, dt)
    elif system == 'Darwin':
        _set_creation_time_macos(path, dt)
    else:
        raise NotImplementedError(
            f'Setting creation time is not supported on {system}'
        )


# ---------------------------------------------------------------------------
# Access / modify time setter
# ---------------------------------------------------------------------------

def set_access_modify_time(
    path: str,
    access_dt: datetime | None = None,
    modify_dt: datetime | None = None,
) -> None:
    """Set access and/or modification time using :func:`os.utime`.

    Works on all platforms.  Pass ``None`` for either argument to leave
    that timestamp unchanged.
    """
    # os.utime expects (atime, mtime) as floats (epoch seconds).
    # Passing None for the whole tuple means "set both to now", so we
    # need to read the current values for whichever side we're not changing.
    st = os.stat(path)
    atime = access_dt.timestamp() if access_dt is not None else st.st_atime
    mtime = modify_dt.timestamp() if modify_dt is not None else st.st_mtime
    os.utime(path, (atime, mtime))


# ---------------------------------------------------------------------------
# Applying attributes
# ---------------------------------------------------------------------------

def apply_timestamps(path: str, attrs: dict) -> None:
    """Apply creation/access/modify timestamps from *attrs* to *path*.

    Only keys that are present **and** not ``None`` are applied.
    """
    if 'creation' in attrs and attrs['creation'] is not None:
        set_creation_time(path, attrs['creation'])

    access_dt = attrs.get('access')
    modify_dt = attrs.get('modify')
    if access_dt is not None or modify_dt is not None:
        set_access_modify_time(path, access_dt, modify_dt)


def apply_permissions(path: str, perms: str) -> None:
    """Apply an octal permission string (e.g. '0o755') to *path* and verify."""
    desired = int(perms, 8) & 0o7777
    os.chmod(path, desired)

    st = os.stat(path)
    actual = st.st_mode & 0o7777
    if actual != desired:
        raise FSNotPersistedError(
            f"permissions not persisted for {path!r}: expected {oct(desired)}, got {oct(actual)}"
        )


def apply_ownership(
    path: str,
    uid: int | None = None,
    gid: int | None = None,
) -> None:
    """Apply *uid* and/or *gid* to *path* and verify.

    Requires appropriate privileges (typically root). If either value is None,
    the current value from the filesystem is preserved.

    Raises FSNotPersistedError if a requested change doesn't stick.
    """
    st_before = os.stat(path)
    effective_uid = uid if uid is not None else st_before.st_uid
    effective_gid = gid if gid is not None else st_before.st_gid

    os.chown(path, effective_uid, effective_gid)

    st_after = os.stat(path)

    if uid is not None and st_after.st_uid != effective_uid:
        raise FSNotPersistedError(
            f"uid not persisted for {path!r}: expected {effective_uid}, got {st_after.st_uid}"
        )
    if gid is not None and st_after.st_gid != effective_gid:
        raise FSNotPersistedError(
            f"gid not persisted for {path!r}: expected {effective_gid}, got {st_after.st_gid}"
        )