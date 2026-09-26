"""Lưu bí mật (refresh token) mã hóa theo tài khoản Windows bằng DPAPI. Máy khác không giải mã được."""
from __future__ import annotations

import base64
import ctypes
import sys
from ctypes import wintypes
from pathlib import Path


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _to_blob(data: bytes):
    buf = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf


def _dpapi(data: bytes, protect: bool) -> bytes:
    inp, _keep = _to_blob(data)
    out = _Blob()
    fn = ctypes.windll.crypt32.CryptProtectData if protect else ctypes.windll.crypt32.CryptUnprotectData
    if not fn(ctypes.byref(inp), None, None, None, None, 0, ctypes.byref(out)):
        raise OSError("DPAPI lỗi")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


def protect(data: bytes) -> bytes:
    if sys.platform == "win32":
        return _dpapi(data, True)
    return base64.b64encode(data)      # macOS/Linux: sẽ thay bằng Keychain/keyring


def unprotect(data: bytes) -> bytes:
    if sys.platform == "win32":
        return _dpapi(data, False)
    return base64.b64decode(data)


def save_secret(path: Path, text: str) -> None:
    path.write_bytes(protect(text.encode("utf-8")))


def load_secret(path: Path) -> str | None:
    try:
        return unprotect(path.read_bytes()).decode("utf-8")
    except (OSError, ValueError):
        return None
