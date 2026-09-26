"""Bộ điều phối job: hàng đợi xoay vòng giữa các tài khoản, trần luồng, thử lại, tải kết quả."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import time
import unicodedata
from pathlib import Path
from urllib.parse import unquote, urlparse

from .config import Settings
from .db import DB, iso, now, parse_iso
from .glabs import GLabsError

log = logging.getLogger("gateway.runner")


def safe_filename(raw: str, max_len: int = 90) -> str:
    """Tên file lấy từ URL G-Labs thường mã hóa phần trăm và có tiếng Việt (ch%C3%B3_ch%E1%BA%A1y). Giải mã, bỏ dấu,
    chỉ giữ [A-Za-z0-9._-] để tên trên đĩa và tên trong URL luôn là MỘT chuỗi ASCII (lỗi 404 thật gặp 2026-09-19)."""
    name = unicodedata.normalize("NFKD", unquote(raw)).encode("ascii", "ignore").decode("ascii")
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    stem = stem[: max_len - len(ext) - 1] if ext else stem[:max_len]
    return f"{stem}.{ext.lower()}" if ext else stem


RETRYABLE = ("no images generated",)
INFRA_ERRORS = ("no active accounts", "no account available")
INFRA_MESSAGE = ("Máy chủ tạo video tạm thời chưa có tài khoản Flow sẵn sàng. Bạn không bị tính lượt, "
                 "hãy bấm 'Tạo lại video lỗi' sau vài phút.")
# G-Labs báo "failed" kèm chữ "Hoàn thành" khi bước nâng 1080p bị Google từ chối 403 (giới hạn tạm thời do gửi liên tục)
THROTTLE_ERRORS = ("hoàn thành",)
THROTTLE_MESSAGE = ("Google đang tạm giới hạn tốc độ tạo video (bước nâng 1080p bị từ chối). Bạn không bị tính lượt, "
                    "hãy bấm 'Tạo lại video lỗi' sau vài phút và đừng gửi quá nhiều video cùng lúc.")
MAX_ATTEMPTS = 3


class Scheduler:
    def __init__(self, db: DB, settings: Settings, glabs):
        self.db, self.s, self.glabs = db, settings, glabs
        self.running: dict[str, tuple[str, str]] = {}   # job_id -> (account_id, kind)
        self.tasks: dict[str, asyncio.Task] = {}
        self.cancelled: set[str] = set()
        self.last_served: dict[str, float] = {}
        self._wake = asyncio.Event()
        self._loop_task: asyncio.Task | None = None
        self._stop = False
        self.infra_fail_ts = 0.0     # lần gần nhất G-Labs báo chưa có tài khoản Flow sẵn sàng
        self.last_ok_ts = 0.0        # lần gần nhất một job hoàn thành

    # ---------- vòng đời ----------
    async def start(self) -> None:
        self._recover()
        self._loop_task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._stop = True
        self._wake.set()
        if self._loop_task:
            await self._loop_task
        for t in list(self.tasks.values()):
            t.cancel()
        await asyncio.gather(*self.tasks.values(), return_exceptions=True)

    def wake(self) -> None:
        self._wake.set()

    def _recover(self) -> None:
        """Sau khi Gateway khởi động lại: job đang chạy có task_id thì hỏi tiếp, không thì xếp lại."""
        for j in self.db.all("SELECT * FROM jobs WHERE status='running'"):
            if j["glabs_task_id"]:
                self._launch(j, resume_task=j["glabs_task_id"])
            else:
                self.db.run("UPDATE jobs SET status='queued' WHERE id=?", (j["id"],))

    def cancel(self, job_id: str) -> None:
        self.cancelled.add(job_id)

    # ---------- chọn job ----------
    async def _loop(self) -> None:
        last_clean = 0.0
        while not self._stop:
            try:
                self._tick()
                if time.time() - last_clean > 3600:
                    last_clean = time.time()
                    self._cleanup()
            except Exception:  # noqa: BLE001 - vòng lặp không được chết
                log.exception("lỗi trong vòng điều phối")
            try:
                await asyncio.wait_for(self._wake.wait(), 1.0)
            except asyncio.TimeoutError:
                pass
            self._wake.clear()

    def _capacity(self, kind: str) -> int:
        limit = self.s.max_inflight_video if kind == "video" else self.s.max_inflight_image
        return limit - sum(1 for _, k in self.running.values() if k == kind)

    def _tick(self) -> None:
        while True:
            rows = self.db.all(
                "SELECT j.*, t.max_concurrent FROM jobs j JOIN teams t ON t.team_id=j.team_id "
                "WHERE j.status='queued' ORDER BY j.created_at, j.rowid")
            per_acc: dict[str, int] = {}
            for acc_id, _ in self.running.values():
                per_acc[acc_id] = per_acc.get(acc_id, 0) + 1
            first: dict[str, dict] = {}
            for j in rows:
                if j["id"] in self.cancelled:
                    continue
                acc = j["team_id"]
                if acc in first or per_acc.get(acc, 0) >= j["max_concurrent"]:
                    continue
                if self._capacity(j["kind"]) <= 0:
                    continue
                first[acc] = j
            if not first:
                return
            acc = min(first, key=lambda a: self.last_served.get(a, 0.0))  # ai được phục vụ lâu nhất
            self.last_served[acc] = time.time()
            self._launch(first[acc])

    def _launch(self, job, resume_task: str | None = None) -> None:
        jid = job["id"]
        self.running[jid] = (job["team_id"], job["kind"])
        self.db.run("UPDATE jobs SET status='running', started_at=COALESCE(started_at,?) WHERE id=?",
                    (iso(), jid))
        t = asyncio.create_task(self._run(jid, job["kind"], resume_task))
        self.tasks[jid] = t

    # ---------- chạy một job ----------
    def payload_path(self, jid: str) -> Path:
        return self.s.payloads_dir / f"{jid}.json"

    async def _run(self, jid: str, kind: str, resume_task: str | None) -> None:
        try:
            await self._execute(jid, kind, resume_task)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.exception("job %s lỗi bất ngờ", jid)
            self._finish(jid, "failed", error=f"Lỗi hệ thống: {e}")
        finally:
            self.running.pop(jid, None)
            self.tasks.pop(jid, None)
            self.cancelled.discard(jid)
            self.wake()

    async def _execute(self, jid: str, kind: str, resume_task: str | None) -> None:
        timeout = self.s.video_timeout if kind == "video" else self.s.image_timeout
        payload = None
        if not resume_task:
            payload = json.loads(self.payload_path(jid).read_text(encoding="utf-8"))
        last_error = "Không rõ lỗi"
        normal_tries = infra_tries = 0
        while True:
            if jid in self.cancelled:
                return self._finish(jid, "cancelled")
            try:
                task_id = resume_task or await self.glabs.submit(kind, payload)
                resume_task = None
                self.db.run("UPDATE jobs SET glabs_task_id=?, attempts=? WHERE id=?",
                            (task_id, normal_tries + infra_tries + 1, jid))
                deadline = time.time() + timeout
                poll_errors = 0
                while True:
                    if jid in self.cancelled:
                        return self._finish(jid, "cancelled")
                    try:
                        st = await self.glabs.status(task_id)
                        poll_errors = 0
                    except GLabsError:
                        poll_errors += 1
                        if poll_errors >= 5:
                            raise
                        await asyncio.sleep(self.s.poll_seconds)
                        continue
                    if st["status"] == "completed":
                        files = await self._download(jid, st["results"])
                        return self._finish(jid, "completed", results=files)
                    if st["status"] == "failed":
                        last_error = str(st["error"] or "G-Labs báo lỗi")
                        break
                    if time.time() > deadline:
                        last_error = "Quá thời gian chờ"
                        break
                    await asyncio.sleep(self.s.poll_seconds)
            except GLabsError as e:
                last_error = str(e)
            low = last_error.lower()
            if payload is None:                      # job khôi phục sau khi khởi động lại: không còn payload để gửi lại
                break
            if any(k in low for k in INFRA_ERRORS):
                # Hạ tầng tạm thời (vd tiện ích Chrome của G-Labs mất kết nối → 'No active accounts available'):
                # KHÔNG báo lỗi ngay; chờ và thử lại, người dùng không mất hạn mức.
                self.infra_fail_ts = time.time()
                infra_tries += 1
                log.warning("job %s: %s (lần %s/%s)", jid, last_error, infra_tries, self.s.infra_retry_attempts)
                if infra_tries < self.s.infra_retry_attempts:
                    slept = 0.0
                    while slept < self.s.infra_retry_seconds and jid not in self.cancelled:
                        await asyncio.sleep(min(1.0, self.s.infra_retry_seconds))
                        slept += 1.0
                    continue
                last_error = INFRA_MESSAGE
                break
            if any(k in low for k in THROTTLE_ERRORS):
                normal_tries += 1
                log.warning("job %s: Google giới hạn tạm thời (lần %s/%s)", jid, normal_tries, MAX_ATTEMPTS)
                if normal_tries < MAX_ATTEMPTS:
                    slept = 0.0                       # chờ rồi thử lại: gửi dồn ngay chỉ làm bị giới hạn nặng hơn
                    while slept < self.s.infra_retry_seconds and jid not in self.cancelled:
                        await asyncio.sleep(min(1.0, self.s.infra_retry_seconds))
                        slept += 1.0
                    continue
                last_error = THROTTLE_MESSAGE
                break
            if any(k in low for k in RETRYABLE) or "Không gọi được" in last_error:
                normal_tries += 1
                if normal_tries < MAX_ATTEMPTS:
                    continue
            break
        self._finish(jid, "failed", error=last_error[:300])

    async def _download(self, jid: str, urls: list[str]) -> list[dict]:
        out_dir = self.s.results_dir / jid
        out_dir.mkdir(parents=True, exist_ok=True)
        files = []
        for i, url in enumerate(urls):
            base = safe_filename(Path(urlparse(url).path).name) or f"out{i}.mp4"
            name = f"{i:02d}_{base}"
            dest = out_dir / name
            await self.glabs.download(url, dest)
            files.append({"name": name, "size": dest.stat().st_size})
        if not files:
            raise GLabsError("G-Labs báo xong nhưng không có file kết quả")
        return files

    def _finish(self, jid: str, status: str, results: list | None = None, error: str | None = None) -> None:
        self.db.run("UPDATE jobs SET status=?, error=?, results_json=?, finished_at=? WHERE id=?",
                    (status, error, json.dumps(results) if results is not None else None, iso(), jid))
        if status == "completed":
            self.last_ok_ts = time.time()
        self.payload_path(jid).unlink(missing_ok=True)  # ảnh base64 có thể rất nặng
        log.info("job %s -> %s %s", jid, status, error or "")

    # ---------- dọn dẹp ----------
    def _cleanup(self) -> None:
        cutoff = now().timestamp() - self.s.retention_days * 86400
        for d in self.s.results_dir.iterdir():
            if d.is_dir() and d.stat().st_mtime < cutoff:
                shutil.rmtree(d, ignore_errors=True)
                self.db.run("UPDATE jobs SET results_json=NULL WHERE id=? AND status='completed'", (d.name,))

    def queue_position(self, job) -> int | None:
        if job["status"] != "queued":
            return None
        row = self.db.one("SELECT COUNT(*) c FROM jobs WHERE status='queued' AND "
                          "(created_at < ? OR (created_at = ? AND rowid < (SELECT rowid FROM jobs WHERE id=?)))",
                          (job["created_at"], job["created_at"], job["id"]))
        return int(row["c"]) + 1

    def eta_progress(self, job) -> int:
        if job["status"] == "completed":
            return 100
        if job["status"] != "running":
            return 0
        start = parse_iso(job["started_at"])
        if not start:
            return 5
        expected = 120 if job["kind"] == "video" else 20
        return max(5, min(95, int((now() - start).total_seconds() / expected * 100)))
