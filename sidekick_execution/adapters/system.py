"""Real local operating-system capabilities for Sidekick execution.

These adapters use **real** Windows APIs through :mod:`ctypes` (standard
library only -- no third-party packages):

* **volume** -- the master system volume via ``waveOutGetVolume`` /
  ``waveOutSetVolume`` in ``winmm.dll``.
* **media keys** -- real multimedia key presses (``play_pause``, ``next``,
  ``previous``, ``stop``, ``mute``, ``volume_up``, ``volume_down``) via
  ``user32.keybd_event``. These drive whatever player the user actually has
  running, which is the honest way to do "music control" without a music
  provider account.
* **clipboard** -- the real Windows clipboard via ``user32`` / ``kernel32``.
* **open** -- open a file or URL with the operating system's default handler.

Every capability reports honestly whether it is available on the current
platform. On a non-Windows host the adapters raise ``not_implemented``
instead of pretending to work.
"""

from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes
from typing import Any, Dict, Optional

from .. import errors
from ..errors import SidekickError

IS_WINDOWS = os.name == "nt"

# Windows virtual-key codes for the multimedia keys.
VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_STOP = 0xB2
VK_MEDIA_PLAY_PAUSE = 0xB3
VK_VOLUME_MUTE = 0xAD
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_UP = 0xAF

KEYEVENTF_KEYUP = 0x0002

MEDIA_KEYS: Dict[str, int] = {
    "play_pause": VK_MEDIA_PLAY_PAUSE,
    "play": VK_MEDIA_PLAY_PAUSE,
    "pause": VK_MEDIA_PLAY_PAUSE,
    "next": VK_MEDIA_NEXT_TRACK,
    "next_track": VK_MEDIA_NEXT_TRACK,
    "previous": VK_MEDIA_PREV_TRACK,
    "prev": VK_MEDIA_PREV_TRACK,
    "previous_track": VK_MEDIA_PREV_TRACK,
    "stop": VK_MEDIA_STOP,
    "mute": VK_VOLUME_MUTE,
    "volume_up": VK_VOLUME_UP,
    "volume_down": VK_VOLUME_DOWN,
}

#: Windows clipboard format for Unicode text.
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002


class _WinDLL:
    """Lazily loaded Windows libraries with correct prototypes."""

    def __init__(self) -> None:
        self._user32 = None
        self._kernel32 = None
        self._winmm = None

    # -- libraries ---------------------------------------------------------
    @property
    def user32(self):
        if self._user32 is None:
            dll = ctypes.WinDLL("user32", use_last_error=True)
            dll.keybd_event.argtypes = [
                wintypes.BYTE,
                wintypes.BYTE,
                wintypes.DWORD,
                ctypes.c_size_t,
            ]
            dll.keybd_event.restype = None
            dll.OpenClipboard.argtypes = [wintypes.HWND]
            dll.OpenClipboard.restype = wintypes.BOOL
            dll.CloseClipboard.argtypes = []
            dll.CloseClipboard.restype = wintypes.BOOL
            dll.EmptyClipboard.argtypes = []
            dll.EmptyClipboard.restype = wintypes.BOOL
            dll.GetClipboardData.argtypes = [wintypes.UINT]
            dll.GetClipboardData.restype = wintypes.HANDLE
            dll.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
            dll.SetClipboardData.restype = wintypes.HANDLE
            self._user32 = dll
        return self._user32

    @property
    def kernel32(self):
        if self._kernel32 is None:
            dll = ctypes.WinDLL("kernel32", use_last_error=True)
            dll.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
            dll.GlobalAlloc.restype = wintypes.HGLOBAL
            dll.GlobalLock.argtypes = [wintypes.HGLOBAL]
            dll.GlobalLock.restype = ctypes.c_void_p
            dll.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
            dll.GlobalUnlock.restype = wintypes.BOOL
            dll.GlobalFree.argtypes = [wintypes.HGLOBAL]
            dll.GlobalFree.restype = wintypes.HGLOBAL
            self._kernel32 = dll
        return self._kernel32

    @property
    def winmm(self):
        if self._winmm is None:
            dll = ctypes.WinDLL("winmm")
            dll.waveOutGetVolume.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
            dll.waveOutGetVolume.restype = wintypes.DWORD
            dll.waveOutSetVolume.argtypes = [wintypes.HWND, wintypes.DWORD]
            dll.waveOutSetVolume.restype = wintypes.DWORD
            self._winmm = dll
        return self._winmm


_WIN = _WinDLL()


def _require_windows(feature: str) -> None:
    if not IS_WINDOWS:
        raise SidekickError(
            errors.NOT_IMPLEMENTED,
            f"{feature} is not implemented on this platform ({sys.platform}).",
            details={"feature": feature, "platform": sys.platform},
        )


#: The volume word is 16 bits per channel; the high bits carry the master
#: "all devices" marker (``0xFFFFFFFF``) when the volume is at 100%.
VOLUME_MASK = 0xFFFF
VOLUME_SCALE = 65535.0

# --- volume ----------------------------------------------------------------
def get_volume() -> int:
    """Return the master system volume as a percentage (0-100).

    Raises:
        SidekickError: ``not_implemented`` off Windows, ``provider_unavailable``
            when the Windows audio API cannot be reached.
    """
    _require_windows("System volume control")
    value = wintypes.DWORD(0)
    try:
        code = _WIN.winmm.waveOutGetVolume(None, ctypes.byref(value))
    except OSError as exc:  # pragma: no cover - API missing
        raise SidekickError(
            errors.PROVIDER_UNAVAILABLE,
            f"The Windows audio API is unavailable: {exc}",
            details={"api": "waveOutGetVolume"},
        ) from exc
    if code != 0:
        raise SidekickError(
            errors.PROVIDER_UNAVAILABLE,
            "The Windows audio API refused to report the volume.",
            details={"api": "waveOutGetVolume", "code": code},
            retryable=True,
        )
    # ``0xFFFFFFFF`` is the "master volume for all devices" marker; masking to
    # the 16-bit volume word turns it into the correct 100%.
    raw = value.value & VOLUME_MASK
    return int(round(raw / VOLUME_SCALE * 100))


def set_volume(level: int) -> int:
    """Set the master system volume to ``level`` percent (0-100).

    Returns the volume that was actually applied.
    """
    _require_windows("System volume control")
    if not isinstance(level, int) or isinstance(level, bool):
        raise SidekickError(errors.INVALID_REQUEST, "'level' must be an integer percentage.")
    if not 0 <= level <= 100:
        raise SidekickError(
            errors.INVALID_REQUEST, "'level' must be between 0 and 100.", details={"level": level}
        )
    raw = int(round(level / 100.0 * VOLUME_SCALE)) & VOLUME_MASK
    try:
        code = _WIN.winmm.waveOutSetVolume(None, raw)
    except OSError as exc:  # pragma: no cover - API missing
        raise SidekickError(
            errors.PROVIDER_UNAVAILABLE,
            f"The Windows audio API is unavailable: {exc}",
            details={"api": "waveOutSetVolume"},
        ) from exc
    if code != 0:
        raise SidekickError(
            errors.PROVIDER_UNAVAILABLE,
            "The Windows audio API refused to set the volume.",
            details={"api": "waveOutSetVolume", "code": code},
            retryable=True,
        )
    return get_volume()


# --- media keys ------------------------------------------------------------
def send_media_key(action: str) -> str:
    """Send a real multimedia key press.

    The key is delivered to the operating system, so it drives whichever
    player the user actually has running.
    """
    _require_windows("Media key control")
    key = str(action or "").strip().lower()
    if key not in MEDIA_KEYS:
        raise SidekickError(
            errors.INVALID_REQUEST,
            f"Unknown media action {action!r}.",
            details={"action": action, "supported": sorted(set(MEDIA_KEYS))},
        )
    code = MEDIA_KEYS[key]
    try:
        _WIN.user32.keybd_event(code, 0, 0, 0)
        _WIN.user32.keybd_event(code, 0, KEYEVENTF_KEYUP, 0)
    except OSError as exc:  # pragma: no cover - API missing
        raise SidekickError(
            errors.PROVIDER_UNAVAILABLE,
            f"Could not send the media key: {exc}",
            details={"action": action},
        ) from exc
    return key


# --- clipboard -------------------------------------------------------------
def set_clipboard(text: str) -> int:
    """Put ``text`` on the real Windows clipboard. Returns the character count."""
    _require_windows("Clipboard access")
    if not isinstance(text, str):
        raise SidekickError(errors.INVALID_REQUEST, "'text' must be a string.")
    payload = text + "\0"
    size = len(payload) * 2
    handle = _WIN.kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
    if not handle:
        raise SidekickError(
            errors.PROVIDER_UNAVAILABLE,
            "Could not allocate clipboard memory.",
            retryable=True,
        )
    pointer = _WIN.kernel32.GlobalLock(handle)
    if not pointer:
        raise SidekickError(
            errors.PROVIDER_UNAVAILABLE,
            "Could not lock clipboard memory.",
            retryable=True,
        )
    try:
        buffer = ctypes.create_unicode_buffer(payload)
        ctypes.memmove(pointer, ctypes.byref(buffer), size)
    finally:
        _WIN.kernel32.GlobalUnlock(handle)

    if not _WIN.user32.OpenClipboard(None):
        raise SidekickError(
            errors.PROVIDER_UNAVAILABLE,
            "Another application is holding the clipboard open.",
            retryable=True,
        )
    try:
        _WIN.user32.EmptyClipboard()
        if not _WIN.user32.SetClipboardData(CF_UNICODETEXT, handle):
            raise SidekickError(
                errors.PROVIDER_UNAVAILABLE,
                "The clipboard refused the data.",
                retryable=True,
            )
        # Ownership transferred to the clipboard; do not free it.
        handle = None
    finally:
        _WIN.user32.CloseClipboard()
    return len(text)


def get_clipboard() -> str:
    """Return the current text content of the real Windows clipboard."""
    _require_windows("Clipboard access")
    if not _WIN.user32.OpenClipboard(None):
        raise SidekickError(
            errors.PROVIDER_UNAVAILABLE,
            "Another application is holding the clipboard open.",
            retryable=True,
        )
    try:
        handle = _WIN.user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return ""
        pointer = _WIN.kernel32.GlobalLock(handle)
        if not pointer:
            return ""
        try:
            return ctypes.wstring_at(pointer)
        finally:
            _WIN.kernel32.GlobalUnlock(handle)
    finally:
        _WIN.user32.CloseClipboard()


# --- opening files ---------------------------------------------------------
def open_path(path: str) -> str:
    """Open ``path`` (a file or a URL) with the operating system's default handler."""
    if not isinstance(path, str) or not path.strip():
        raise SidekickError(errors.INVALID_REQUEST, "A non-empty 'path' is required.")
    target = path.strip()
    try:
        if IS_WINDOWS:
            os.startfile(target)  # noqa: S606 - the user asked for this file
        elif sys.platform == "darwin":
            os.system(f'open "{target}"')  # noqa: S605 - POSIX only
        else:
            raise SidekickError(
                errors.NOT_IMPLEMENTED,
                f"Opening a path is not implemented on {sys.platform}.",
                details={"platform": sys.platform},
            )
    except OSError as exc:
        raise SidekickError(
            errors.PROVIDER_UNAVAILABLE,
            f"Could not open {target!r}: {exc.strerror or exc}",
            details={"path": target},
            retryable=True,
        ) from exc
    return target


def capabilities() -> Dict[str, Any]:
    """Report which of these real capabilities are usable right now."""
    report: Dict[str, Any] = {
        "platform": sys.platform,
        "windows": IS_WINDOWS,
        "volume": False,
        "media_keys": False,
        "clipboard": False,
        "open_path": IS_WINDOWS,
    }
    if not IS_WINDOWS:
        report["reason"] = "These adapters use Windows APIs and are not implemented on this platform."
        return report
    try:
        get_volume()
        report["volume"] = True
    except SidekickError:
        report["volume"] = False
    report["media_keys"] = True
    report["clipboard"] = True
    return report
