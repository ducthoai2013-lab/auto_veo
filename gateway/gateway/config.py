"""Cấu hình Gateway: đọc từ biến môi trường GW_* (và file .env nếu có)."""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

VERSION = "1.0.0"


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _read_pubkey() -> str:
    """Khóa công khai Ed25519 của thoai-dash: GW_JWT_PUBKEY (PEM) hoặc GW_JWT_PUBKEY_FILE."""
    f = os.getenv("GW_JWT_PUBKEY_FILE")
    if f and Path(f).is_file():
        return Path(f).read_text(encoding="utf-8")
    return os.getenv("GW_JWT_PUBKEY", "").replace("\\n", "\n")


def find_ffmpeg() -> str | None:
    env = os.getenv("GW_FFMPEG")
    if env and Path(env).is_file():
        return env
    found = shutil.which("ffmpeg")
    if found:
        return found
    fallback = Path(r"C:\ffmpeg\bin\ffmpeg.exe")
    return str(fallback) if fallback.is_file() else None


@dataclass
class Settings:
    data_dir: Path
    glabs_url: str
    glabs_key: str
    mock: bool
    mock_delay: float
    max_inflight_video: int
    max_inflight_image: int
    video_timeout: int
    image_timeout: int
    poll_seconds: float
    public_url: str
    jwt_pubkey: str
    retention_days: int
    client_latest_version: str
    client_download_url: str
    downloads_dir: Path
    infra_retry_seconds: float = 20.0
    infra_retry_attempts: int = 6

    @property
    def db_path(self) -> Path:
        return self.data_dir / "gateway.db"

    @property
    def results_dir(self) -> Path:
        return self.data_dir / "results"

    @property
    def payloads_dir(self) -> Path:
        return self.data_dir / "payloads"


def load_settings() -> Settings:
    _load_dotenv(Path.cwd() / ".env")
    g = os.getenv
    data_dir = Path(g("GW_DATA_DIR", "data")).resolve()
    s = Settings(
        data_dir=data_dir,
        glabs_url=g("GW_GLABS_URL", "http://127.0.0.1:8765").rstrip("/"),
        glabs_key="".join(g("GW_GLABS_KEY", "").split()),   # khóa copy hay dính dấu cách/xuống dòng
        mock=g("GW_MOCK", "0") == "1",
        mock_delay=float(g("GW_MOCK_DELAY", "2")),
        max_inflight_video=int(g("GW_MAX_INFLIGHT_VIDEO", "5")),
        max_inflight_image=int(g("GW_MAX_INFLIGHT_IMAGE", "8")),
        video_timeout=int(g("GW_VIDEO_TIMEOUT", "480")),
        image_timeout=int(g("GW_IMAGE_TIMEOUT", "180")),
        poll_seconds=float(g("GW_POLL_SECONDS", "5")),
        public_url=g("GW_PUBLIC_URL", "http://127.0.0.1:8080").rstrip("/"),
        jwt_pubkey=_read_pubkey(),
        retention_days=int(g("GW_RETENTION_DAYS", "7")),
        client_latest_version=g("GW_CLIENT_LATEST", VERSION),
        client_download_url=g("GW_CLIENT_URL", "https://d100radar.com/veo3"),
        downloads_dir=Path(g("GW_DOWNLOADS_DIR", str(data_dir / "downloads"))),
        infra_retry_seconds=float(g("GW_INFRA_RETRY_SECONDS", "20")),
        infra_retry_attempts=int(g("GW_INFRA_RETRY_ATTEMPTS", "6")),
    )
    for d in (s.data_dir, s.results_dir, s.payloads_dir, s.downloads_dir):
        d.mkdir(parents=True, exist_ok=True)
    return s
