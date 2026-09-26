"""Bộ nối tới G-Labs Automation (thật) và bản giả lập để test không cần G-Labs."""
from __future__ import annotations

import asyncio
import hashlib
import subprocess
import time
import uuid
from pathlib import Path
from urllib.parse import quote

import httpx

from .config import Settings, find_ffmpeg


class GLabsError(Exception):
    pass


class GLabs:
    """Gọi webhook G-Labs (127.0.0.1:8765). Mọi endpoint generate đều bất đồng bộ."""

    def __init__(self, base_url: str, api_key: str):
        self.base = base_url
        self.headers = {"X-API-Key": api_key}
        self.http = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0))

    async def health(self) -> bool:
        try:
            r = await self.http.get(f"{self.base}/api/health", timeout=5)
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    async def submit(self, kind: str, payload: dict) -> str:
        path = "/api/video/generate" if kind == "video" else "/api/image/generate"
        try:
            r = await self.http.post(self.base + path, json=payload, headers=self.headers)
        except httpx.HTTPError as e:
            raise GLabsError(f"Không gọi được G-Labs: {e}") from e
        if r.status_code not in (200, 201, 202):
            raise GLabsError(f"G-Labs từ chối ({r.status_code}): {r.text[:200]}")
        task_id = r.json().get("task_id")
        if not task_id:
            raise GLabsError("G-Labs không trả task_id")
        return str(task_id)

    async def status(self, task_id: str) -> dict:
        try:
            r = await self.http.get(f"{self.base}/api/status/{task_id}", headers=self.headers)
        except httpx.HTTPError as e:
            raise GLabsError(f"Không hỏi được trạng thái: {e}") from e
        if r.status_code != 200:
            raise GLabsError(f"Trạng thái lỗi ({r.status_code})")
        j = r.json()
        return {"status": j.get("status"), "results": j.get("results") or [], "error": j.get("error")}

    async def download(self, url: str, dest: Path) -> None:
        if url.startswith("/"):
            url = self.base + url
        try:
            async with self.http.stream("GET", url, headers=self.headers) as r:
                if r.status_code != 200:
                    raise GLabsError(f"Tải kết quả lỗi ({r.status_code})")
                with dest.open("wb") as f:
                    async for chunk in r.aiter_bytes(1 << 16):
                        f.write(chunk)
        except httpx.HTTPError as e:
            raise GLabsError(f"Tải kết quả lỗi: {e}") from e

    async def aclose(self) -> None:
        await self.http.aclose()


class MockGLabs:
    """Giả lập G-Labs: tạo video/ảnh thật bằng ffmpeg/Pillow để test toàn tuyến.
    Prompt chứa FAIL → lỗi; chứa FLAKY → lần đầu 'No images generated' rồi thành công."""

    def __init__(self, settings: Settings):
        self.delay = settings.mock_delay
        self.ffmpeg = find_ffmpeg()
        self.tasks: dict[str, dict] = {}
        self.flaky_seen: set[str] = set()
        self.noacc: dict[str, int] = {}

    async def health(self) -> bool:
        return True

    async def submit(self, kind: str, payload: dict) -> str:
        tid = uuid.uuid4().hex[:12]
        prompt = str(payload.get("prompt", ""))
        state = {"kind": kind, "payload": payload, "ready": time.time() + self.delay, "error": None}
        if "NOACCOUNTALWAYS" in prompt:
            state["error"] = "No active accounts available"
        elif "THROTTLEALWAYS" in prompt:
            state["error"] = "Hoàn thành"
        elif "THROTTLE" in prompt:
            key = hashlib.md5(prompt.encode()).hexdigest()
            self.noacc[key] = self.noacc.get(key, 0) + 1
            if self.noacc[key] <= 1:
                state["error"] = "Hoàn thành"
        elif "NOACCOUNT" in prompt:
            key = hashlib.md5(prompt.encode()).hexdigest()
            self.noacc[key] = self.noacc.get(key, 0) + 1
            if self.noacc[key] <= 2:
                state["error"] = "No active accounts available"
        elif "FAIL" in prompt:
            state["error"] = "Mock: lỗi cố ý"
        elif "FLAKY" in prompt:
            key = hashlib.md5(prompt.encode()).hexdigest()
            if key not in self.flaky_seen:
                self.flaky_seen.add(key)
                state["error"] = "No images generated"
        self.tasks[tid] = state
        return tid

    async def status(self, task_id: str) -> dict:
        t = self.tasks.get(task_id)
        if not t:
            raise GLabsError("Không có task")
        if time.time() < t["ready"]:
            return {"status": "running", "results": [], "error": None}
        if t["error"]:
            return {"status": "failed", "results": [], "error": t["error"]}
        ext = "mp4" if t["kind"] == "video" else "jpg"
        n = len(t["payload"].get("resolution") or [1]) if t["kind"] == "video" else 1
        prompt = str(t["payload"].get("prompt", ""))
        stem = quote(prompt[:14].replace(" ", "_") + "_") if not prompt.isascii() else ""   # giống G-Labs: tên có tiếng Việt mã hóa %C3%B3
        return {"status": "completed", "error": None,
                "results": [f"mock://{task_id}/{stem}{i}.{ext}" for i in range(n)]}

    async def download(self, url: str, dest: Path) -> None:
        task_id = url.split("//", 1)[1].split("/", 1)[0]
        t = self.tasks[task_id]
        await asyncio.to_thread(self._make, t, dest)

    def _make(self, t: dict, dest: Path) -> None:
        p = t["payload"]
        portrait = p.get("aspect_ratio") == "9:16"
        res = (p.get("resolution") or ["720p"])[0]
        h = {"360p": 360, "720p": 720, "1080p": 1080, "4K": 2160}.get(res, 720)
        w = h * 16 // 9
        if portrait:
            w, h = h, w
        w, h = w // 2 * 2, h // 2 * 2
        color = hashlib.md5(str(p.get("prompt", "")).encode()).hexdigest()[:6]
        if t["kind"] == "image":
            from PIL import Image
            Image.new("RGB", (w // 2, h // 2), "#" + color).save(dest, "JPEG")
            return
        if not self.ffmpeg:
            dest.write_bytes(b"mock-video")
            return
        dur = min(float(p.get("video_length") or 8), 3)
        cmd = [self.ffmpeg, "-y", "-loglevel", "error",
               "-f", "lavfi", "-i", f"testsrc2=s={min(w, 640)}x{min(h, 640)}:d={dur}:r=24",
               "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(dest)]
        subprocess.run(cmd, check=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    async def aclose(self) -> None:
        return None
