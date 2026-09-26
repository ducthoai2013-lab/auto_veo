"""Đường dẫn, cài đặt, mã máy. Dữ liệu người dùng ở %APPDATA%\\Auto_veo3, không ghi vào thư mục cài."""
from __future__ import annotations

import hashlib
import json
import os
import socket
import sys
import uuid
from pathlib import Path

APP_NAME = "Auto_veo3"
VERSION = "1.0.8"

# Địa chỉ mặc định; đổi bằng biến môi trường (dùng khi thử nghiệm) hoặc trong settings.json.
DEFAULT_ACCOUNT_URL = "https://d100radar.com"
DEFAULT_GATEWAY_URL = "https://veo.d100radar.com"
UPDATE_INFO_URL = "https://d100radar.com/veo3/latest.json"
DOWNLOAD_PAGE_URL = "https://d100radar.com/veo3"
ZALO_GROUP_URL = "https://zalo.me/g/tw23yenusdo9iezutcww"      # nhóm Zalo hỗ trợ khách hàng


def data_dir() -> Path:
    override = os.getenv("AUTOVEO_DATA")
    base = Path(override) if override else Path(os.getenv("APPDATA") or Path.home()) / APP_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def app_root() -> Path:
    """Thư mục chứa file chạy (khi đóng gói) hoặc thư mục client/ (khi chạy từ mã nguồn)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def resource_path(rel: str) -> Path:
    if getattr(sys, "frozen", False):
        meipass = Path(getattr(sys, "_MEIPASS", app_root()))
        for base in (meipass, app_root(), app_root() / "_internal"):
            if (base / "resources" / rel).exists():
                return base / "resources" / rel
        return meipass / "resources" / rel
    return app_root() / "resources" / rel


def machine_hash() -> str:
    """Mã máy ổn định, không chứa thông tin cá nhân: băm(MachineGuid + tên máy)."""
    guid = ""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as k:
            guid = str(winreg.QueryValueEx(k, "MachineGuid")[0])
    except Exception:  # noqa: BLE001 - máy không phải Windows / không đọc được registry
        guid = str(uuid.getnode())
    return hashlib.sha256(f"{guid}|{socket.gethostname()}".encode()).hexdigest()[:40]


def device_name() -> str:
    return socket.gethostname()[:60]


DEFAULTS = {
    "lang": "vi",
    "ratio": "16:9",
    "resolution": "1080p",
    "out_dir": str(Path.home() / "Videos" / "Auto_veo3"),
    "account_url": os.getenv("AUTOVEO_ACCOUNT_URL", DEFAULT_ACCOUNT_URL),
    "gateway_url": os.getenv("AUTOVEO_GATEWAY_URL", DEFAULT_GATEWAY_URL),
}


class Settings:
    def __init__(self, path: Path | None = None):
        self.path = path or data_dir() / "settings.json"
        self.values = dict(DEFAULTS)
        try:
            self.values.update(json.loads(self.path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
        # biến môi trường luôn thắng file (tiện cho test và cho quản trị)
        for k, env in (("account_url", "AUTOVEO_ACCOUNT_URL"), ("gateway_url", "AUTOVEO_GATEWAY_URL")):
            if os.getenv(env):
                self.values[k] = os.getenv(env)

    def __getitem__(self, k: str):
        return self.values[k]

    def get(self, k: str, default=None):
        return self.values.get(k, default)

    def set(self, k: str, v) -> None:
        self.values[k] = v
        self.save()

    def save(self) -> None:
        try:
            self.path.write_text(json.dumps(self.values, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass
