"""FastAPI: API /v1 của Gateway Auto_veo3 (tạo ảnh/video qua G-Labs)."""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote, unquote

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from .auth import Principal, api_error, authenticate
from .config import VERSION, Settings, load_settings
from .db import DB, iso, now
from .glabs import GLabs, MockGLabs
from .runner import Scheduler

log = logging.getLogger("gateway")

VIDEO_MODES = {"text_to_video", "start_image", "start_end_image", "components"}
MODES = VIDEO_MODES | {"image"}
RESOLUTIONS = {"360p", "720p", "1080p", "4K"}
VOICES = {"achernar", "achird", "algenib", "algieba", "alnilam", "aoede", "autonoe", "callirrhoe", "charon", "despina",
          "enceladus", "erinome", "fenrir", "gacrux", "iapetus", "kore", "laomedeia", "leda", "orus", "puck",
          "pulcherrima", "rasalgethi", "sadachbia", "sadaltager", "schedar", "sulafat", "umbriel", "vindemiatrix",
          "zephyr", "zubenelgenubi"}
NEED_IMAGES = {"text_to_video": (0, 0), "start_image": (1, 1), "start_end_image": (2, 2),
               "components": (1, 7), "image": (0, 10)}


class ImageIn(BaseModel):
    name: str = "image.jpg"
    data: str  # data URI base64


class JobIn(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=64)
    mode: str
    prompt: str = Field(min_length=1, max_length=4000)
    model: str | None = None
    aspect_ratio: str = "16:9"
    resolution: list[str] = ["720p"]
    video_length: int | None = None
    voice: str = ""          # giọng đọc (chữ thường); chỉ dùng ở mode components
    reference_images: list[ImageIn] = []
    batch_id: str | None = None
    line_no: int | None = None


class BatchIn(BaseModel):
    jobs: list[JobIn] = Field(min_length=1, max_length=200)


class StatusIn(BaseModel):
    ids: list[str] = Field(default_factory=list, max_length=500)


def create_app(settings: Settings | None = None) -> FastAPI:
    s = settings or load_settings()
    db = DB(s.db_path)
    glabs = MockGLabs(s) if s.mock else GLabs(s.glabs_url, s.glabs_key)
    sched = Scheduler(db, s, glabs)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await sched.start()
        yield
        await sched.stop()
        await glabs.aclose()
        db.close()

    app = FastAPI(title="Auto_veo3 Gateway", version=VERSION, lifespan=lifespan)
    app.state.db, app.state.settings, app.state.sched = db, s, sched

    @app.exception_handler(HTTPException)
    async def http_exc(_: Request, exc: HTTPException):
        d = exc.detail if isinstance(exc.detail, dict) else {"code": "error", "message": str(exc.detail)}
        return JSONResponse({"detail": d}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_exc(_: Request, exc: RequestValidationError):
        msg = "; ".join(f"{'.'.join(map(str, e['loc'][1:]))}: {e['msg']}" for e in exc.errors()[:3])
        return JSONResponse({"detail": {"code": "bad_request", "message": msg}}, status_code=422)

    def who(request: Request) -> Principal:
        return authenticate(request, db, s.jwt_pubkey)

    # ---------- công khai ----------
    @app.get("/v1/health")
    async def health():
        ok = await glabs.health()
        q = db.one("SELECT SUM(status='queued') q, SUM(status='running') r FROM jobs")
        return {"ok": True, "version": VERSION, "glabs": "up" if ok else "down", "mock": s.mock,
                "glabs_key_set": bool(s.glabs_key) or s.mock,
                "glabs_accounts": ("unavailable" if sched.infra_fail_ts > sched.last_ok_ts and time.time() - sched.infra_fail_ts < 900 else "ok"),
                "queued": q["q"] or 0, "running": q["r"] or 0}

    @app.get("/v1/client/latest")
    def client_latest():
        return {"version": s.client_latest_version, "download_url": s.client_download_url}

    # ---------- tải app (công khai, chỉ đúng mẫu tên file bản phát hành) ----------
    _DL_RE = re.compile(r"^Auto_veo3-\d+\.\d+\.\d+-win64\.zip$")

    @app.get("/downloads/{name}")
    def download_release(name: str):
        f = s.downloads_dir / name
        if not _DL_RE.match(name) or not f.is_file():
            raise api_error(404, "no_file", "Không có file này")
        return FileResponse(f, media_type="application/zip", filename=name)

    # ---------- hạn mức ----------
    def period_start(p: Principal) -> str | None:
        n = now()
        if p.quota_period == "day":
            return iso(n.replace(hour=0, minute=0, second=0))
        if p.quota_period == "month":
            return iso(n.replace(day=1, hour=0, minute=0, second=0))
        return None

    def used_in_period(p: Principal) -> int:
        start = period_start(p)
        if start:
            return db.one("SELECT COUNT(*) c FROM jobs WHERE team_id=? AND kind='video' AND status='completed' "
                          "AND finished_at >= ?", (p.team_id, start))["c"]
        return db.one("SELECT COUNT(*) c FROM jobs WHERE team_id=? AND kind='video' AND status='completed'",
                      (p.team_id,))["c"]

    @app.get("/v1/me")
    def me(p: Principal = Depends(who)):
        used_total = db.one("SELECT COUNT(*) c FROM jobs WHERE team_id=? AND status='completed'",
                            (p.team_id,))["c"]
        used = used_in_period(p)
        return {"email": p.email, "plan_code": p.plan, "plan_name": p.plan_name,
                "max_concurrent": p.max_concurrent, "allow_4k": p.allow_4k, "expires_at": p.sub_expires,
                "expired": p.expired, "used_total": used_total, "used_in_period": used, "quota": p.quota,
                "quota_period": p.quota_period,
                "remaining": None if p.quota is None else max(0, p.quota - used), "server_version": VERSION}

    def check_quota(p: Principal, pending_new: int) -> None:
        if p.quota is None or pending_new <= 0:
            return
        active = db.one("SELECT COUNT(*) c FROM jobs WHERE team_id=? AND kind='video' "
                        "AND status IN ('queued','running')", (p.team_id,))["c"]
        if used_in_period(p) + active + pending_new > p.quota:
            raise api_error(402, "quota_exceeded", "Đã hết hạn mức video của gói. Bấm MUA GÓI CƯỚC để nâng cấp.")

    # ---------- job ----------
    def validate_job(j: JobIn, p: Principal) -> str:
        if p.expired:
            raise api_error(402, "expired", "Gói đã hết hạn. Bấm MUA GÓI CƯỚC để gia hạn.")
        if j.mode not in MODES:
            raise api_error(422, "bad_mode", f"mode không hợp lệ: {j.mode}")
        lo, hi = NEED_IMAGES[j.mode]
        if not lo <= len(j.reference_images) <= hi:
            raise api_error(422, "bad_images", f"mode {j.mode} cần {lo}–{hi} ảnh, nhận {len(j.reference_images)}")
        if j.voice and j.voice not in VOICES:
            raise api_error(422, "bad_voice", f"Giọng đọc không hợp lệ: {j.voice}")
        if j.mode in VIDEO_MODES:
            if j.aspect_ratio not in ("16:9", "9:16"):
                raise api_error(422, "bad_ratio", "Video chỉ nhận 16:9 hoặc 9:16")
            if not j.resolution or any(r not in RESOLUTIONS for r in j.resolution):
                raise api_error(422, "bad_resolution", "Độ phân giải không hợp lệ")
            if "4K" in j.resolution and not p.allow_4k:
                raise api_error(403, "no_4k", "Gói của bạn không có 4K")
        elif j.aspect_ratio not in ("1:1", "3:4", "4:3", "9:16", "16:9"):
            raise api_error(422, "bad_ratio", "Tỷ lệ ảnh không hợp lệ")
        return "video" if j.mode in VIDEO_MODES else "image"

    def glabs_payload(j: JobIn, kind: str) -> dict:
        p: dict = {"prompt": j.prompt, "aspect_ratio": j.aspect_ratio}
        if j.model:
            p["model"] = j.model
        if kind == "video":
            if "no text overlay" not in j.prompt.lower():
                p["prompt"] = j.prompt.rstrip(" .,") + ", no text overlay"
            p["mode"] = j.mode
            p["resolution"] = j.resolution
            if j.video_length:
                p["video_length"] = j.video_length
            if j.mode == "components":
                p["reference_images"] = [{"data": i.data, "name": i.name} for i in j.reference_images]
                if j.voice:
                    p["voice"] = j.voice
            else:
                p["reference_images"] = [i.data for i in j.reference_images]
        elif j.reference_images:
            p["reference_images"] = [{"data": i.data, "name": i.name} for i in j.reference_images]
        return p

    def job_view(j) -> dict:
        d = {"id": j["id"], "status": j["status"], "mode": j["mode"], "line_no": j["line_no"],
             "batch_id": j["batch_id"], "error": j["error"], "created_at": j["created_at"],
             "finished_at": j["finished_at"], "queue_position": sched.queue_position(j),
             "progress": sched.eta_progress(j), "idempotency_key": j["idem_key"], "results": []}
        if j["results_json"]:
            d["results"] = [{"name": f["name"], "size": f["size"],
                             "url": f"/v1/files/{j['id']}/{quote(f['name'], safe='')}"} for f in json.loads(j["results_json"])]
        return d

    def find_existing(p: Principal, key: str):
        return db.one("SELECT * FROM jobs WHERE team_id=? AND idem_key=?", (p.team_id, key))

    def submit_one(j: JobIn, p: Principal, device_id: str) -> dict:
        existing = find_existing(p, j.idempotency_key)
        if existing:
            return job_view(existing)
        kind = validate_job(j, p)
        jid = uuid.uuid4().hex[:16]
        sched.payload_path(jid).write_text(json.dumps(glabs_payload(j, kind)), encoding="utf-8")
        db.run("INSERT INTO jobs(id,team_id,device_id,idem_key,status,mode,kind,batch_id,line_no,prompt,created_at) "
               "VALUES (?,?,?,?, 'queued',?,?,?,?,?,?)",
               (jid, p.team_id, device_id, j.idempotency_key, j.mode, kind, j.batch_id, j.line_no,
                j.prompt[:500], iso()))
        return job_view(db.one("SELECT * FROM jobs WHERE id=?", (jid,)))

    @app.post("/v1/jobs", status_code=202)
    def job_create(body: JobIn, p: Principal = Depends(who)):
        if not find_existing(p, body.idempotency_key):
            validate_job(body, p)
            check_quota(p, 1 if body.mode in VIDEO_MODES else 0)
        out = submit_one(body, p, p.device_id)
        sched.wake()
        return out

    @app.post("/v1/batches", status_code=202)
    def batch_create(body: BatchIn, p: Principal = Depends(who)):
        new = [j for j in body.jobs if not find_existing(p, j.idempotency_key)]
        for j in new:
            validate_job(j, p)
        check_quota(p, sum(1 for j in new if j.mode in VIDEO_MODES))
        out = [submit_one(j, p, p.device_id) for j in body.jobs]
        sched.wake()
        return {"jobs": out}

    @app.get("/v1/jobs/{job_id}")
    def job_get(job_id: str, p: Principal = Depends(who)):
        j = db.one("SELECT * FROM jobs WHERE id=? AND team_id=?", (job_id, p.team_id))
        if not j:
            raise api_error(404, "no_job", "Không có job này")
        return job_view(j)

    @app.get("/v1/jobs")
    def job_list(since: str | None = None, limit: int = 500, p: Principal = Depends(who)):
        rows = db.all("SELECT * FROM jobs WHERE team_id=? AND created_at >= ? ORDER BY created_at DESC LIMIT ?",
                      (p.team_id, since or "1970-01-01T00:00:00Z", min(limit, 1000)))
        return {"jobs": [job_view(j) for j in rows]}

    @app.post("/v1/jobs/status")
    def job_status_many(body: StatusIn, p: Principal = Depends(who)):
        """Hỏi nhiều job một lần (app dùng để poll gọn)."""
        if not body.ids:
            return {"jobs": []}
        marks = ",".join("?" * len(body.ids))
        rows = db.all(f"SELECT * FROM jobs WHERE team_id=? AND id IN ({marks})", (p.team_id, *body.ids))
        return {"jobs": [job_view(j) for j in rows]}

    @app.post("/v1/jobs/{job_id}/cancel")
    def job_cancel(job_id: str, p: Principal = Depends(who)):
        j = db.one("SELECT * FROM jobs WHERE id=? AND team_id=?", (job_id, p.team_id))
        if not j:
            raise api_error(404, "no_job", "Không có job này")
        if j["status"] == "queued":
            db.run("UPDATE jobs SET status='cancelled', finished_at=? WHERE id=?", (iso(), job_id))
            sched.payload_path(job_id).unlink(missing_ok=True)
        elif j["status"] == "running":
            sched.cancel(job_id)
        return job_view(db.one("SELECT * FROM jobs WHERE id=?", (job_id,)))

    @app.get("/v1/files/{job_id}/{name}")
    def file_get(job_id: str, name: str, p: Principal = Depends(who)):
        j = db.one("SELECT 1 FROM jobs WHERE id=? AND team_id=?", (job_id, p.team_id))
        if not j or name != Path(name).name:
            raise api_error(404, "no_file", "Không có file")
        d = s.results_dir / job_id
        f = d / name
        if not f.is_file() and d.is_dir():      # file cũ lưu với tên còn mã hóa phần trăm (%C3%B3...) trước bản sửa
            f = next((x for x in d.iterdir() if x.is_file() and unquote(x.name) == unquote(name)), f)
        if not f.is_file():
            raise api_error(404, "gone", "File đã bị dọn (quá hạn lưu)")
        return FileResponse(f)

    return app
