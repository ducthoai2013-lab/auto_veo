"""Smoke test Gateway THẬT (không mock): ký token bằng khóa riêng production ở máy này, tạo job, theo dõi, tải kết quả, kiểm tra file.

  python tools/smoke_gateway.py --url http://127.0.0.1:8080 --key secrets/veo/veo_private.pem --mode text --n 1
  python tools/smoke_gateway.py --url https://veo.d100radar.com ... (kiểm tra qua tunnel)

Khóa riêng chỉ đọc cục bộ để ký token thử; không gửi đi đâu. Mỗi job THẬT tốn credit Google Flow/Veo.
--expect-fail: mong đợi job lỗi (kiểm tra đường lỗi khi chưa có API Key G-Labs).
"""
import argparse
import base64
import io
import json
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gateway"))
from gateway.admin import sign_token  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--url", default="http://127.0.0.1:8080")
ap.add_argument("--key", default=str(ROOT / "secrets" / "veo" / "veo_private.pem"))
ap.add_argument("--team", default="smoke-team")
ap.add_argument("--mode", choices=["text", "image", "start_end", "components", "img_gen"], default="text")
ap.add_argument("--n", type=int, default=1)
ap.add_argument("--resolution", default="720p")
ap.add_argument("--ratio", default="16:9")
ap.add_argument("--quota", type=int, default=None)
ap.add_argument("--timeout", type=int, default=600)
ap.add_argument("--expect-fail", action="store_true")
ap.add_argument("--out", default=str(ROOT / "smoke_out"))
a = ap.parse_args()

fails: list[str] = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
    if not ok:
        fails.append(name)


def make_img(color, size=(1280, 720)):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "JPEG", quality=90)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


priv = Path(a.key).read_text()
tok = sign_token(priv, team=a.team, email="smoke@test.local", device="smoke-dev", plan="pro", plan_name="Smoke",
                 cc=3, k4=False, q=a.quota)
H = {"Authorization": "Bearer " + tok}
c = httpx.Client(base_url=a.url, timeout=httpx.Timeout(120, connect=15), headers=H)

r = c.get("/v1/health")
h = r.json()
check("health", r.status_code == 200 and h.get("ok"), json.dumps(h))
check("Gateway chế độ THẬT (mock=false)", h.get("mock") is False)
check("G-Labs up", h.get("glabs") == "up", str(h.get("glabs")))
check("Gateway đã có API Key G-Labs", h.get("glabs_key_set") is True, "chạy installer\setup_gateway.ps1 -KeyFromJson D:\GatewayData\config.json")
r = c.get("/v1/me")
check("token production hợp lệ (/v1/me)", r.status_code == 200, r.text[:100])

import uuid
stamp = f"{int(time.time())}-{uuid.uuid4().hex[:6]}"   # duy nhất mỗi lần chạy (tránh trùng khóa chống-trùng giữa các tiến trình)
jobs = []
for i in range(a.n):
    key = f"smoke-{stamp}-{i}"
    body = {"idempotency_key": key, "aspect_ratio": a.ratio, "resolution": [a.resolution], "line_no": i + 1,
            "prompt": ["a calm red fox walking through a snowy forest, cinematic",
                       "slow camera push in on a steaming cup of coffee on a wooden table",
                       "a paper boat floating down a small stream, soft daylight"][i % 3]}
    if a.mode == "text":
        body["mode"] = "text_to_video"
    elif a.mode == "image":
        body.update(mode="start_image", reference_images=[{"name": "a.jpg", "data": make_img((200, 120, 60))}])
    elif a.mode == "start_end":
        body.update(mode="start_end_image", reference_images=[{"name": "a.jpg", "data": make_img((200, 120, 60))},
                                                             {"name": "b.jpg", "data": make_img((60, 120, 200))}])
    elif a.mode == "components":
        body.update(mode="components", prompt="the @robotguy waves at the camera",
                    reference_images=[{"name": "robotguy.jpg", "data": make_img((90, 90, 90), (768, 768))}])
    elif a.mode == "img_gen":
        body.update(mode="image", aspect_ratio="16:9", prompt="a minimalist red house at golden hour")
    r = c.post("/v1/jobs", json=body)
    check(f"gửi job {i + 1}", r.status_code == 202, r.text[:150])
    if r.status_code == 202:
        jobs.append(r.json()["id"])

end = time.time() + a.timeout
final: dict = {}
while jobs and time.time() < end and len(final) < len(jobs):
    time.sleep(4)
    for j in c.post("/v1/jobs/status", json={"ids": jobs}).json()["jobs"]:
        if j["status"] in ("completed", "failed", "cancelled"):
            final[j["id"]] = j
    print(f"  ...{len(final)}/{len(jobs)} xong, {int(end - time.time())}s còn lại", flush=True)

out = Path(a.out)
out.mkdir(parents=True, exist_ok=True)
for jid in jobs:
    j = final.get(jid)
    if a.expect_fail:
        check("job lỗi như mong đợi (đường lỗi)", bool(j) and j["status"] == "failed", json.dumps(j)[:200] if j else "chưa xong")
        if j:
            print("     lý do:", j.get("error"))
        continue
    check(f"job {jid} hoàn thành", bool(j) and j["status"] == "completed", "" if (j and j["status"] == "completed") else ((j or {}).get("error") or "quá thời gian"))
    if not j or j["status"] != "completed":
        continue
    for f in j["results"]:
        dest = out / f"{jid}_{f['name']}"
        with c.stream("GET", f["url"]) as resp:
            check("tải file kết quả", resp.status_code == 200, str(resp.status_code))
            dest.write_bytes(b"".join(resp.iter_bytes()))
        check("file có dung lượng", dest.stat().st_size > 10_000, f"{dest.stat().st_size} bytes")
        if dest.suffix.lower() == ".mp4":
            p = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                "stream=codec_name,width,height,duration", "-of", "json", str(dest)],
                               capture_output=True, text=True)
            info = json.loads(p.stdout or "{}").get("streams", [{}])[0]
            print("     ffprobe:", info)
            check("ffprobe đọc được video", bool(info.get("codec_name")))
            want_h = {"720p": 720, "1080p": 1080}.get(a.resolution)
            if want_h:
                dims = sorted([info.get("width", 0), info.get("height", 0)])
                check(f"độ phân giải ≥ {a.resolution}", dims[0] >= want_h * 0.95, str(info))

print("\nKẾT QUẢ:", "PASS" if not fails else "FAIL: " + "; ".join(fails))
sys.exit(1 if fails else 0)
