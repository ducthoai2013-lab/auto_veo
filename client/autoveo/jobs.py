"""Quản lý job: tạo từ các tab, gửi lên Gateway, theo dõi, tải kết quả, tiếp tục sau khi mở lại app."""
from __future__ import annotations

import json
import re
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from . import config, ffmpeg_tools, imaging
from .api import ApiError, GatewayApi
from .store import Store, files_of, now_iso

VIDEO_MODES = ("text_to_video", "start_image", "start_end_image", "components")
MODE_LABEL = {"text_to_video": "Text to Video", "start_image": "Image to Video",
              "start_end_image": "Start-End", "components": "Đồng bộ nhân vật", "image": "Ảnh"}
SEND_CHUNK = 10
POLL_SECONDS = 3.0
FATAL_CODES = {"expired", "quota_exceeded", "no_4k", "bad_images", "bad_mode", "bad_ratio", "bad_resolution",
               "bad_request", "bad_voice", "device_revoked", "not_signed_in"}


@dataclass
class JobSpec:
    mode: str
    prompt: str
    line_no: int
    ratio: str = "16:9"
    resolution: list[str] = field(default_factory=lambda: ["1080p"])
    images: list[dict] = field(default_factory=list)   # [{"name": tên gắn @tag, "path": đường dẫn}]
    voice: str = ""                                     # giọng đọc (mã chữ thường), chỉ chế độ components

    def dumps(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @staticmethod
    def loads(s: str) -> "JobSpec":
        return JobSpec(**json.loads(s))


def _slug(text: str, n: int = 28) -> str:
    s = re.sub(r"[^\w]+", "-", text.strip(), flags=re.UNICODE).strip("-").lower()
    return s[:n] or "video"


class JobManager(QObject):
    changed = Signal(str)           # id job đã đổi
    online = Signal(bool)           # kết nối tới Gateway
    notice = Signal(str, str)       # (code, thông báo) lỗi cần người dùng chú ý: hết hạn, hết hạn mức...
    usage_dirty = Signal()          # có job xong/lỗi: khung tài khoản nên làm mới

    def __init__(self, gateway: GatewayApi, store: Store, parent=None):
        super().__init__(parent)
        self.gw, self.store = gateway, store
        self._stop = threading.Event()
        self._poll_thread: threading.Thread | None = None
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="dl")
        self._sending: set[str] = set()
        self._downloading: set[str] = set()
        self._lock = threading.Lock()
        self._online: bool | None = None
        self.thumbs_dir = config.data_dir() / "thumbs"
        self.thumbs_dir.mkdir(exist_ok=True)

    # ---------------------------------------------------------------- vòng đời
    def start(self) -> None:
        pending = [r["id"] for r in self.store.all("WHERE status='sending'")]
        if pending:
            self._spawn_send(pending)
        self._poll_thread = threading.Thread(target=self._poll_loop, name="poll", daemon=True)
        self._poll_thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._pool.shutdown(wait=False, cancel_futures=True)

    # ---------------------------------------------------------------- tạo job
    def submit(self, specs: list[JobSpec], out_root: str) -> list[str]:
        batch_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        folder = str(Path(out_root) / batch_id)
        ids = []
        for sp in specs:
            jid = uuid.uuid4().hex[:12]
            self.store.add(dict(id=jid, idem_key=uuid.uuid4().hex, batch_id=batch_id, line_no=sp.line_no,
                                mode=sp.mode, prompt=sp.prompt, status="sending", spec_json=sp.dumps(),
                                out_dir=folder, created_at=now_iso()))
            ids.append(jid)
            self.changed.emit(jid)
        self._spawn_send(ids)
        return ids

    def retry(self, job_ids: list[str]) -> list[str]:
        """Tạo lại các job đã chọn NGAY TRÊN CHÍNH DÒNG ĐÓ (không thêm dòng mới). Job đã HOÀN THÀNH trên máy chủ mà
        chỉ lỗi lúc tải về thì TẢI LẠI kết quả cũ (không tốn hạn mức); các dòng còn lại được đặt về 'đang gửi' với khóa
        chống trùng mới rồi gửi lại. Dòng đang chạy/chờ/tải thì bỏ qua (tránh tạo trùng)."""
        self._pool.submit(self._retry_worker, list(job_ids))
        return []

    def edit_and_retry(self, jid: str, prompt: str) -> None:
        """Sửa lệnh (prompt) của một dòng rồi tạo lại NGAY TRÊN DÒNG ĐÓ. Lệnh đã đổi thì luôn tạo video mới
        (không dùng lại kết quả cũ)."""
        self._pool.submit(self._retry_worker, [jid], prompt.strip())

    def _reset_row(self, jid: str) -> None:
        self.store.update(jid, idem_key=uuid.uuid4().hex, gw_id=None, status="sending", progress=0,
                          queue_pos=None, error=None, finished_at=None, thumb=None)
        self.changed.emit(jid)

    def _retry_worker(self, job_ids: list[str], new_prompt: str | None = None) -> None:
        resend: list[str] = []
        for jid in job_ids:
            row = self.store.get(jid)
            if not row or row["status"] not in ("completed", "failed", "cancelled"):
                continue
            if new_prompt:
                spec = JobSpec.loads(row["spec_json"])
                spec.prompt = new_prompt
                self.store.update(jid, prompt=new_prompt, spec_json=spec.dumps())
            if row["gw_id"] and row["status"] == "failed" and not new_prompt:
                try:
                    gj = self.gw.status([row["gw_id"]])
                except ApiError:
                    gj = []
                if gj and gj[0]["status"] == "completed" and gj[0].get("results"):
                    with self._lock:
                        if jid in self._downloading:
                            continue
                        self._downloading.add(jid)
                    self.store.update(jid, status="downloading", error=None, progress=100)
                    self.changed.emit(jid)
                    self._pool.submit(self._download, jid, gj[0]["results"])
                    continue
            with self._lock:
                if jid in self._sending or jid in self._downloading:
                    continue
            self._reset_row(jid)
            resend.append(jid)
        if resend:
            self._spawn_send(resend)

    def cancel(self, job_ids: list[str]) -> None:
        for jid in job_ids:
            row = self.store.get(jid)
            if not row or row["status"] in ("completed", "failed", "cancelled"):
                continue
            if row["gw_id"]:
                try:
                    self.gw.cancel(row["gw_id"])
                except ApiError:
                    pass
            self.store.update(jid, status="cancelled", finished_at=now_iso())
            self.changed.emit(jid)

    def remove(self, job_ids: list[str], delete_files: bool = False) -> None:
        if delete_files:
            for jid in job_ids:
                row = self.store.get(jid)
                for f in files_of(row) if row else []:
                    Path(f).unlink(missing_ok=True)
        self.store.delete(job_ids)

    # ---------------------------------------------------------------- gửi
    def _spawn_send(self, ids: list[str]) -> None:
        with self._lock:
            ids = [i for i in ids if i not in self._sending]
            self._sending.update(ids)
        for i in range(0, len(ids), SEND_CHUNK):
            self._pool.submit(self._send_chunk, ids[i:i + SEND_CHUNK])

    def _payload(self, row) -> dict:
        sp = JobSpec.loads(row["spec_json"])
        refs = []
        for im in sp.images:
            crop = None if sp.mode == "components" else sp.ratio
            data = imaging.prepare(im["path"], crop)
            name = im["name"] if im["name"].lower().endswith((".jpg", ".jpeg")) else im["name"] + ".jpg"
            refs.append({"name": name, "data": data})
        return {"idempotency_key": row["idem_key"], "mode": sp.mode, "prompt": sp.prompt,
                "aspect_ratio": sp.ratio, "resolution": sp.resolution, "reference_images": refs,
                "batch_id": row["batch_id"], "line_no": row["line_no"], "voice": sp.voice if sp.mode == "components" else ""}

    def _send_chunk(self, ids: list[str]) -> None:
        try:
            rows = [self.store.get(i) for i in ids]
            try:
                payloads = [self._payload(r) for r in rows if r]
            except Exception as e:  # noqa: BLE001 - ảnh hỏng/không đọc được
                for i in ids:
                    self._fail(i, f"Không đọc được ảnh: {e}")
                return
            delay = 3
            for attempt in range(8):
                if self._stop.is_set():
                    return
                try:
                    out = self.gw.submit_batch(payloads)
                except ApiError as e:
                    if e.is_network or e.status >= 500:
                        self._set_online(False)
                        time.sleep(delay)
                        delay = min(delay * 2, 30)
                        continue
                    for i in ids:
                        self._fail(i, e.message)
                    if e.code in FATAL_CODES:
                        self.notice.emit(e.code, e.message)
                    return
                self._set_online(True)
                by_key = {j["idempotency_key"]: j for j in out}
                for r in rows:
                    j = by_key.get(r["idem_key"])
                    if j:
                        self.store.update(r["id"], gw_id=j["id"], status=self._map(j["status"]),
                                          queue_pos=j.get("queue_position"))
                        self.changed.emit(r["id"])
                return
            for i in ids:
                self._fail(i, "Mất kết nối tới máy chủ, hãy bấm 'Tạo lại video lỗi'")
        finally:
            with self._lock:
                self._sending.difference_update(ids)

    # ---------------------------------------------------------------- theo dõi
    @staticmethod
    def _map(gw_status: str) -> str:
        return {"queued": "queued", "running": "running", "completed": "downloading",
                "failed": "failed", "cancelled": "cancelled"}.get(gw_status, "queued")

    def _set_online(self, ok: bool) -> None:
        if ok != self._online:
            self._online = ok
            self.online.emit(ok)

    def _fail(self, jid: str, msg: str) -> None:
        self.store.update(jid, status="failed", error=msg, finished_at=now_iso())
        self.changed.emit(jid)
        self.usage_dirty.emit()

    def _poll_loop(self) -> None:
        while not self._stop.wait(POLL_SECONDS):
            try:
                self._poll_once()
            except Exception:  # noqa: BLE001 - vòng theo dõi không được chết
                pass

    def _poll_once(self) -> None:
        rows = [r for r in self.store.all("WHERE status IN ('queued','running','downloading')") if r["gw_id"]]
        if not rows:
            return
        by_gw = {r["gw_id"]: r for r in rows}
        try:
            for i in range(0, len(rows), 200):
                for j in self.gw.status([r["gw_id"] for r in rows[i:i + 200]]):
                    self._apply(by_gw[j["id"]], j)
            self._set_online(True)
        except ApiError as e:
            if e.is_network or e.status >= 500:
                self._set_online(False)
            elif e.code in ("device_revoked", "not_signed_in"):
                self.notice.emit(e.code, e.message)

    def _apply(self, row, j: dict) -> None:
        jid, st = row["id"], j["status"]
        if st == "completed":
            with self._lock:
                if jid in self._downloading:
                    return
                self._downloading.add(jid)
            self.store.update(jid, status="downloading", progress=100)
            self.changed.emit(jid)
            self._pool.submit(self._download, jid, j["results"])
        elif st == "failed":
            self.store.update(jid, status="failed", error=j.get("error") or "Lỗi không rõ", finished_at=now_iso())
            self.changed.emit(jid)
            self.usage_dirty.emit()
        elif st == "cancelled":
            self.store.update(jid, status="cancelled", finished_at=now_iso())
            self.changed.emit(jid)
        elif st in ("queued", "running"):
            if row["status"] != st or row["progress"] != j.get("progress") or row["queue_pos"] != j.get("queue_position"):
                self.store.update(jid, status=st, progress=j.get("progress") or 0, queue_pos=j.get("queue_position"))
                self.changed.emit(jid)

    # ---------------------------------------------------------------- tải kết quả
    def _download(self, jid: str, results: list[dict]) -> None:
        try:
            row = self.store.get(jid)
            if not row:
                return
            out_dir = Path(row["out_dir"])
            out_dir.mkdir(parents=True, exist_ok=True)
            base = f"{(row['line_no'] or 0):03d}_{_slug(row['prompt'] or '')}"
            files = []
            for k, res in enumerate(results):
                ext = Path(res["name"]).suffix or ".mp4"
                suffix = f"_{k + 1}" if len(results) > 1 else ""
                dest = out_dir / f"{base}{suffix}{ext}"
                n = 2
                while dest.exists():            # không đè file cùng tên
                    dest = out_dir / f"{base}{suffix}_{n}{ext}"
                    n += 1
                self.gw.download(res["url"], dest)
                files.append(str(dest))
            for old in files_of(row):                # dòng được tạo lại: kết quả mới thay kết quả cũ
                if old not in files:
                    try:
                        Path(old).unlink(missing_ok=True)
                    except OSError:                  # file cũ đang mở trong trình phát: bỏ qua, không làm hỏng kết quả mới
                        pass
            thumb = self._make_thumb(jid, files[0]) if files else None
            self.store.update(jid, status="completed", files_json=json.dumps(files), thumb=thumb,
                              progress=100, finished_at=now_iso())
            self.changed.emit(jid)
            self.usage_dirty.emit()
        except ApiError as e:
            if e.is_network:
                self._set_online(False)
            # giữ 'downloading': vòng theo dõi sẽ thử tải lại
            elif e.status in (404, 410):
                self._fail(jid, "File kết quả đã bị dọn khỏi máy chủ (quá hạn lưu)")
        except OSError as e:
            self._fail(jid, f"Không ghi được file: {e}")
        finally:
            with self._lock:
                self._downloading.discard(jid)

    def _make_thumb(self, jid: str, file: str) -> str | None:
        out = self.thumbs_dir / f"{jid}.jpg"
        try:
            if file.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                shutil.copyfile(file, out)
            else:
                ffmpeg_tools.first_frame(Path(file), out)
            return str(out)
        except (ffmpeg_tools.FFmpegError, OSError):
            return None
