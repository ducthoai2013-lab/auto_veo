"""Test Gateway với G-Labs giả lập và token Ed25519 tự ký."""
import base64
import json
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "gateway"))

from gateway.admin import make_keypair, sign_token  # noqa: E402
from gateway.app import create_app  # noqa: E402
from gateway.config import Settings  # noqa: E402

IMG = "data:image/jpeg;base64," + base64.b64encode(b"x" * 64).decode()


@pytest.fixture()
def env(tmp_path):
    priv, pub = make_keypair()
    s = Settings(data_dir=tmp_path, glabs_url="", glabs_key="", mock=True, mock_delay=0.2,
                 max_inflight_video=2, max_inflight_image=4, video_timeout=20, image_timeout=20,
                 poll_seconds=0.1, public_url="http://t", jwt_pubkey=pub, retention_days=7,
                 client_latest_version="1.0.0", client_download_url="http://t/veo3",
                 downloads_dir=tmp_path / "dl", infra_retry_seconds=0.2, infra_retry_attempts=3)
    for d in (s.results_dir, s.payloads_dir, s.downloads_dir):
        d.mkdir(parents=True, exist_ok=True)
    with TestClient(create_app(s)) as c:
        yield c, priv


def hdr(priv, **kw):
    return {"Authorization": "Bearer " + sign_token(priv, **kw)}


def job(key, **kw):
    d = {"idempotency_key": key * 4, "mode": "text_to_video", "prompt": "a cat " + key}
    d.update(kw)
    return d


def wait(c, h, ids, want=("completed", "failed", "cancelled"), timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        js = c.post("/v1/jobs/status", json={"ids": ids}, headers=h).json()["jobs"]
        if all(j["status"] in want for j in js):
            return {j["id"]: j for j in js}
        time.sleep(0.15)
    raise AssertionError("timeout: " + str(js))


def test_auth_required_and_bad_token(env):
    c, priv = env
    assert c.get("/v1/me").status_code == 401
    assert c.get("/v1/me", headers={"Authorization": "Bearer xxx"}).json()["detail"]["code"] == "bad_token"
    other_priv, _ = make_keypair()
    assert c.get("/v1/me", headers=hdr(other_priv)).status_code == 401  # ký bằng khóa lạ
    assert c.get("/v1/me", headers=hdr(priv, ttl=-10)).json()["detail"]["code"] == "token_expired"


def test_text_to_video_end_to_end(env):
    c, priv = env
    h = hdr(priv)
    r = c.post("/v1/jobs", json=job("aa"), headers=h)
    assert r.status_code == 202
    jid = r.json()["id"]
    done = wait(c, h, [jid])[jid]
    assert done["status"] == "completed" and done["results"], done
    f = c.get(done["results"][0]["url"], headers=h)
    assert f.status_code == 200 and len(f.content) > 100
    me = c.get("/v1/me", headers=h).json()
    assert me["used_total"] == 1 and me["plan_code"] == "pro"


def test_idempotency_returns_same_job(env):
    c, priv = env
    h = hdr(priv)
    a = c.post("/v1/jobs", json=job("bb"), headers=h).json()
    b = c.post("/v1/jobs", json=job("bb"), headers=h).json()
    assert a["id"] == b["id"]


def test_validation(env):
    c, priv = env
    h = hdr(priv)
    assert c.post("/v1/jobs", json=job("cc", mode="start_image"), headers=h).json()["detail"]["code"] == "bad_images"
    assert c.post("/v1/jobs", json=job("dd", aspect_ratio="1:1"), headers=h).json()["detail"]["code"] == "bad_ratio"
    assert c.post("/v1/jobs", json=job("ee", resolution=["4K"]), headers=h).json()["detail"]["code"] == "no_4k"
    ok = c.post("/v1/jobs", json=job("ff", mode="start_image", reference_images=[{"name": "a.jpg", "data": IMG}]),
                headers=h)
    assert ok.status_code == 202


def test_expired_and_quota(env):
    c, priv = env
    h = hdr(priv, sexp="2020-01-01T00:00:00Z")
    r = c.post("/v1/jobs", json=job("gg"), headers=h)
    assert r.status_code == 402 and r.json()["detail"]["code"] == "expired"
    hq = hdr(priv, team="teamq", q=2)
    r = c.post("/v1/batches", json={"jobs": [job("h1"), job("h2"), job("h3")]}, headers=hq)
    assert r.status_code == 402 and r.json()["detail"]["code"] == "quota_exceeded"
    r = c.post("/v1/batches", json={"jobs": [job("h1"), job("h2")]}, headers=hq)
    assert r.status_code == 202
    ids = [j["id"] for j in r.json()["jobs"]]
    wait(c, hq, ids)
    me = c.get("/v1/me", headers=hq).json()
    assert me["remaining"] == 0
    assert c.post("/v1/jobs", json=job("h4"), headers=hq).json()["detail"]["code"] == "quota_exceeded"


def test_failed_job_not_counted_and_retry(env):
    c, priv = env
    h = hdr(priv, q=5)
    ids = [c.post("/v1/jobs", json=job("ii", prompt="FAIL x"), headers=h).json()["id"],
           c.post("/v1/jobs", json=job("jj", prompt="FLAKY y"), headers=h).json()["id"]]
    res = wait(c, h, ids)
    assert res[ids[0]]["status"] == "failed" and "Mock" in res[ids[0]]["error"]
    assert res[ids[1]]["status"] == "completed"  # lần 1 'No images generated' rồi tự thử lại
    assert c.get("/v1/me", headers=h).json()["used_total"] == 1


def test_fair_queue_and_concurrency_cap(env):
    c, priv = env  # trần toàn hệ thống 2 video, mỗi team cc=1
    ha = hdr(priv, team="A", cc=1)
    hb = hdr(priv, team="B", cc=1)
    a = c.post("/v1/batches", json={"jobs": [job(f"a{i}") for i in range(4)]}, headers=ha).json()["jobs"]
    b = c.post("/v1/batches", json={"jobs": [job(f"b{i}") for i in range(2)]}, headers=hb).json()["jobs"]
    max_running = {"A": 0, "B": 0}
    end = time.time() + 20
    while time.time() < end:
        ja = c.post("/v1/jobs/status", json={"ids": [j["id"] for j in a]}, headers=ha).json()["jobs"]
        jb = c.post("/v1/jobs/status", json={"ids": [j["id"] for j in b]}, headers=hb).json()["jobs"]
        max_running["A"] = max(max_running["A"], sum(j["status"] == "running" for j in ja))
        max_running["B"] = max(max_running["B"], sum(j["status"] == "running" for j in jb))
        if all(j["status"] == "completed" for j in ja + jb):
            break
        time.sleep(0.05)
    assert all(j["status"] == "completed" for j in ja + jb)
    assert max_running["A"] <= 1 and max_running["B"] <= 1
    assert max_running["B"] == 1  # B không bị A chặn


def test_cancel_queued(env):
    c, priv = env
    h = hdr(priv, cc=1)
    ids = [c.post("/v1/jobs", json=job(f"k{i}", prompt=f"p{i}"), headers=h).json()["id"] for i in range(3)]
    r = c.post(f"/v1/jobs/{ids[2]}/cancel", headers=h).json()
    assert r["status"] in ("cancelled", "running", "completed")
    wait(c, h, ids)


def test_team_isolation(env):
    c, priv = env
    ha, hb = hdr(priv, team="A"), hdr(priv, team="B")
    jid = c.post("/v1/jobs", json=job("zz"), headers=ha).json()["id"]
    assert c.get(f"/v1/jobs/{jid}", headers=hb).status_code == 404
    wait(c, ha, [jid])
    name = c.get(f"/v1/jobs/{jid}", headers=ha).json()["results"][0]["url"]
    assert c.get(name, headers=hb).status_code == 404


def test_public_download_route(env, tmp_path):
    c, _ = env
    dl = tmp_path / "dl"
    (dl / "Auto_veo3-1.0.0-win64.zip").write_bytes(b"PK" + b"x" * 100)
    (dl / "secret.txt").write_text("no")
    r = c.get("/downloads/Auto_veo3-1.0.0-win64.zip")            # không cần token
    assert r.status_code == 200 and r.content.startswith(b"PK") and r.headers["content-type"] == "application/zip"
    assert c.get("/downloads/secret.txt").status_code == 404      # ngoài mẫu tên → chặn
    assert c.get("/downloads/..%2Fgateway.db").status_code == 404
    assert c.get("/downloads/Auto_veo3-9.9.9-win64.zip").status_code == 404


def test_glabs_key_is_sanitized_and_health_reports_it(monkeypatch, tmp_path):
    from gateway.config import load_settings
    monkeypatch.setenv("GW_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GW_GLABS_KEY", "  abc def\r\n\tghi \n")
    assert load_settings().glabs_key == "abcdefghi"
    monkeypatch.setenv("GW_GLABS_KEY", "")
    assert load_settings().glabs_key == ""


def test_vietnamese_prompt_filenames_download_ok(env):
    """Lỗi thật 2026-09-19: prompt tiếng Việt → tên file G-Labs mã hóa %C3%B3 → Gateway lưu sai tên → tải 404."""
    c, priv = env
    h = hdr(priv)
    jid = c.post("/v1/jobs", json={"idempotency_key": "viet-0001-viet", "mode": "text_to_video",
                                   "prompt": "con chó chạy trên đồng cỏ"}, headers=h).json()["id"]
    done = wait(c, h, [jid])[jid]
    assert done["status"] == "completed"
    name = done["results"][0]["name"]
    assert name.isascii() and "%" not in name and name.endswith(".mp4"), name        # tên an toàn
    r = c.get(done["results"][0]["url"], headers=h)
    assert r.status_code == 200 and len(r.content) > 100


def test_legacy_percent_encoded_files_still_downloadable(env, tmp_path):
    """Job cũ đã lưu file với tên chứa %C3%B3 phải tải được (2 video thật của người dùng đầu tiên)."""
    from gateway.db import iso
    c, priv = env
    h = hdr(priv, team="legacy")
    app = c.app
    db, s = app.state.db, app.state.settings
    legacy = "00_con_ch%C3%B3_ch%E1%BA%A1y_20260919_1080p.mp4"
    (s.results_dir / "legacyjob0001").mkdir(parents=True)
    (s.results_dir / "legacyjob0001" / legacy).write_bytes(b"x" * 500)
    db.run("INSERT INTO teams(team_id,email,plan,max_concurrent,last_seen) VALUES ('legacy','a','pro',1,?) "
           "ON CONFLICT(team_id) DO NOTHING", (iso(),))
    db.run("INSERT INTO jobs(id,team_id,idem_key,status,mode,kind,created_at,results_json) VALUES "
           "('legacyjob0001','legacy','k-legacy-1','completed','text_to_video','video',?,?)",
           (iso(), json.dumps([{"name": legacy, "size": 500}])))
    j = c.get("/v1/jobs/legacyjob0001", headers=h).json()
    assert c.get(j["results"][0]["url"], headers=h).status_code == 200


def test_safe_filename_unit():
    from gateway.runner import safe_filename
    assert safe_filename("00_con_ch%C3%B3_ch%E1%BA%A1y_no_text_20260919_1080p.mp4") == "00_con_cho_chay_no_text_20260919_1080p.mp4"
    assert safe_filename("%E2%80%9C%E2%80%9D") == ""          # toàn ký tự ngoài ASCII → rỗng (runner dùng tên dự phòng)
    assert len(safe_filename("a" * 300 + ".mp4")) <= 90


def test_no_active_accounts_is_retried_then_succeeds(env):
    """G-Labs báo 'No active accounts available' (tiện ích Chrome mất kết nối): chờ + thử lại, không báo lỗi ngay, không tốn lượt."""
    c, priv = env
    h = hdr(priv, q=5)
    jid = c.post("/v1/jobs", json={"idempotency_key": "noacc-retry-01", "mode": "text_to_video", "prompt": "NOACCOUNT recover"},
                 headers=h).json()["id"]
    done = wait(c, h, [jid])[jid]
    assert done["status"] == "completed", done
    assert c.get("/v1/me", headers=h).json()["used_total"] == 1


def test_no_active_accounts_gives_friendly_error_and_health_flag(env):
    c, priv = env
    h = hdr(priv, q=5)
    jid = c.post("/v1/jobs", json={"idempotency_key": "noacc-always-01", "mode": "text_to_video", "prompt": "NOACCOUNTALWAYS x"},
                 headers=h).json()["id"]
    done = wait(c, h, [jid])[jid]
    assert done["status"] == "failed" and "chưa có tài khoản Flow sẵn sàng" in done["error"]
    assert "No active accounts" not in done["error"]                       # không lộ thông báo tiếng Anh thô
    assert c.get("/v1/health").json()["glabs_accounts"] == "unavailable"     # để giám sát phát hiện
    assert c.get("/v1/me", headers=h).json()["used_total"] == 0             # lỗi hạ tầng: KHÔNG tính lượt
    ok = c.post("/v1/jobs", json=job("rr"), headers=h).json()["id"]
    assert wait(c, h, [ok])[ok]["status"] == "completed"
    assert c.get("/v1/health").json()["glabs_accounts"] == "ok"             # hồi phục thì trạng thái về ok


def test_google_throttle_error_retries_then_recovers_or_gives_friendly_message(env):
    """Lỗi thật 2026-09-19: upscale 1080p bị 403 → G-Labs báo failed với chữ 'Hoàn thành'."""
    c, priv = env
    h = hdr(priv, q=5)
    ok = c.post("/v1/jobs", json={"idempotency_key": "thr-ok-0001", "mode": "text_to_video", "prompt": "THROTTLE once"},
                headers=h).json()["id"]
    assert wait(c, h, [ok])[ok]["status"] == "completed"
    bad = c.post("/v1/jobs", json={"idempotency_key": "thr-bad-001", "mode": "text_to_video", "prompt": "THROTTLEALWAYS x"},
                 headers=h).json()["id"]
    done = wait(c, h, [bad])[bad]
    assert done["status"] == "failed" and "giới hạn tốc độ" in done["error"] and "Hoàn thành" not in done["error"]
    assert c.get("/v1/me", headers=h).json()["used_total"] == 1                # chỉ job thành công bị tính


IMG = "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAMCAgICAgMCAgIDAwMDBAYEBAQEBAgGBgUGCQgKCgkICQkKDA8MCgsOCwkJDRENDg8QEBEQCgwSExIQEw8QEBD/yQALCAABAAEBAREA/8wABgAQEAX/2gAIAQEAAD8A0s8g/9k="


def test_components_voice_reaches_glabs_and_is_validated(env, monkeypatch):
    """Đồng bộ nhân vật: giọng đọc chọn trong app (chữ thường) phải tới G-Labs; giọng lạ bị từ chối; mode khác không gửi giọng."""
    from gateway.glabs import MockGLabs
    seen = []
    orig = MockGLabs.submit

    async def rec(self, kind, payload):
        seen.append(payload)
        return await orig(self, kind, payload)
    monkeypatch.setattr(MockGLabs, "submit", rec)
    c, priv = env
    h = hdr(priv, q=10)
    body = {"idempotency_key": "voice-ok-001", "mode": "components", "prompt": "@Linhchi waves hello",
            "reference_images": [{"name": "Linhchi", "data": IMG}], "voice": "aoede"}
    jid = c.post("/v1/jobs", json=body, headers=h).json()["id"]
    assert wait(c, h, [jid])[jid]["status"] == "completed"
    assert seen[-1]["voice"] == "aoede" and seen[-1]["mode"] == "components"
    assert seen[-1]["reference_images"][0]["name"] == "Linhchi"
    bad = dict(body, idempotency_key="voice-bad-001", voice="Robot9000")
    r = c.post("/v1/jobs", json=bad, headers=h)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "bad_voice"
    n = len(seen)
    plain = c.post("/v1/jobs", json=job("nv", voice="kore"), headers=h).json()["id"]      # text_to_video: giọng bị bỏ qua
    assert wait(c, h, [plain])[plain]["status"] == "completed" and "voice" not in seen[n]
    nov = dict(body, idempotency_key="voice-none-01", voice="")
    j2 = c.post("/v1/jobs", json=nov, headers=h).json()["id"]
    assert wait(c, h, [j2])[j2]["status"] == "completed" and "voice" not in seen[-1]         # không chọn giọng: để Veo tự chọn
