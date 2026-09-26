"""Production Smoke Test cho Auto_veo3 — chỉ ĐỌC (GET) trừ device/start (tạo 1 mã chờ 10 phút, vô hại).

  python tools/prod_smoke.py            # kiểm tra domain, API, giá, khóa, trang tải, file tải, webhook, Gateway
  python tools/prod_smoke.py --video    # thêm: tạo 1 video THẬT qua tunnel (tốn 1 lượt credit Veo)

Không dùng dữ liệu giả để kết luận PASS: mọi kiểm tra đi qua domain/tunnel thật.
"""
import hashlib
import json
import socket
import subprocess
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
ACC = "https://d100radar.com"
GW = "https://veo.d100radar.com"
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    results.append((name, ok, detail))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
    return ok


def get(url, **kw):
    try:
        return httpx.get(url, timeout=30, follow_redirects=True, **kw)
    except httpx.HTTPError as e:
        class R:  # noqa: N801
            status_code, text, content, headers = 0, str(e), b"", {}

            def json(self):
                raise ValueError(str(e))
        return R()


# ---- 1. domain / tunnel ----
try:
    ips = socket.gethostbyname_ex("veo.d100radar.com")[2]
    check("DNS veo.d100radar.com", bool(ips), ",".join(ips))
except OSError as e:
    check("DNS veo.d100radar.com", False, str(e))
r = get(f"{GW}/v1/health")
h = r.json() if r.status_code == 200 else {}
check("Gateway qua tunnel /v1/health", r.status_code == 200 and h.get("ok") is True, f"HTTP {r.status_code} {r.text[:80]}")
check("Gateway chế độ THẬT (mock=false)", h.get("mock") is False)
check("G-Labs up", h.get("glabs") == "up", str(h.get("glabs")))
check("Gateway đã có API Key G-Labs", h.get("glabs_key_set") is True, "chạy installer\setup_gateway.ps1 -KeyFromJson D:\GatewayData\config.json")

# ---- 2. thoai-dash / module Veo ----
r = get(f"{ACC}/health")
check("D100 /health", r.status_code == 200, f"HTTP {r.status_code}")
r = get(f"{ACC}/api/plans")
check("D100 /api/plans vẫn hoạt động", r.status_code == 200 and len(r.json()) >= 2 if r.status_code == 200 else False, f"HTTP {r.status_code}")
r = get(f"{ACC}/api/veo/plans")
try:
    plans = {p["code"]: p for p in r.json()} if r.status_code == 200 else {}
except ValueError:
    plans = {}
check("Veo /api/veo/plans có 3 gói", set(plans) == {"trial", "pro", "ultra"}, f"HTTP {r.status_code} {sorted(plans)}")
if plans:
    check("Giá Pro = 199.000đ/tháng", plans["pro"]["price_month"] == 199000, str(plans["pro"]["price_month"]))
    check("Giá Ultra = 399.000đ/tháng", plans["ultra"]["price_month"] == 399000, str(plans["ultra"]["price_month"]))
    check("Trial = 3 video, không thu phí", plans["trial"]["video_quota"] == 3 and plans["trial"]["price_month"] == 0)
    check("Ultra có 4K, Pro/Trial không", plans["ultra"]["allow_4k"] and not plans["pro"]["allow_4k"] and not plans["trial"]["allow_4k"])
r = get(f"{ACC}/api/veo/public-key")
local_pub = (ROOT / "secrets" / "veo" / "veo_public.pem").read_text().strip()
check("Khóa công khai trên VPS = khóa Gateway đang tin", r.status_code == 200 and r.json().get("pem", "").strip() == local_pub,
      f"HTTP {r.status_code}")

# ---- 3. đăng nhập thiết bị (bắt đầu) ----
try:
    r = httpx.post(f"{ACC}/api/veo/device/start", json={"machine_hash": "prod-smoke-machine-0001", "device_name": "PROD-SMOKE"}, timeout=30)
    d = r.json() if r.status_code == 200 else {}
    check("Veo device/start", r.status_code == 200 and d.get("verification_url", "").startswith(f"{ACC}/veo3/device.html?code="),
          f"HTTP {r.status_code} {d.get('verification_url', r.text[:80])}")
except httpx.HTTPError as e:
    check("Veo device/start", False, str(e))

# ---- 4. webhook thanh toán ----
try:
    r = httpx.post(f"{ACC}/api/veo/webhook/sepay", content=b"{}", timeout=30)
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    enabled = r.status_code == 401
    check("Webhook Veo đã BẬT (không key → 401)", enabled, f"HTTP {r.status_code} {str(body)[:80]}")
except httpx.HTTPError as e:
    check("Webhook Veo đã BẬT", False, str(e))

# ---- 5. trang tải + file tải ----
r = get(f"{ACC}/veo3/")
check("Trang d100radar.com/veo3", r.status_code == 200 and "Auto_veo3" in r.text, f"HTTP {r.status_code}")
r = get(f"{ACC}/veo3/device.html?code=TEST")
check("Trang duyệt thiết bị", r.status_code == 200 and "thiết bị" in r.text.lower())
r = get(f"{ACC}/veo3/latest.json")
try:
    lj = r.json() if r.status_code == 200 else {}
except ValueError:
    lj = {}       # trang trả HTML (chưa deploy) chứ không phải JSON
check("latest.json", bool(lj.get("version") and lj.get("url") and lj.get("sha256")), str(lj)[:120])
if lj.get("url"):
    h256 = hashlib.sha256()
    n = 0
    try:
        with httpx.stream("GET", lj["url"], timeout=300, follow_redirects=True) as resp:
            ok = resp.status_code == 200
            for chunk in resp.iter_bytes(1 << 20):
                h256.update(chunk)
                n += len(chunk)
        check("Tải zip từ URL trong latest.json", ok and n > 10_000_000, f"HTTP {resp.status_code}, {n/1e6:.1f} MB")
        check("SHA256 zip tải về = latest.json", h256.hexdigest() == lj["sha256"], h256.hexdigest()[:16])
    except httpx.HTTPError as e:
        check("Tải zip từ URL trong latest.json", False, str(e))
    local = ROOT / "dist" / f"Auto_veo3-{lj['version']}-win64.zip"
    if local.is_file():
        check("Zip production = bản build hiện tại", hashlib.sha256(local.read_bytes()).hexdigest() == lj["sha256"])

# ---- 6. video thật qua tunnel ----
if "--video" in sys.argv:
    p = subprocess.run([sys.executable, str(ROOT / "tools" / "smoke_gateway.py"), "--url", GW, "--mode", "text", "--n", "1",
                        "--resolution", "720p", "--timeout", "900"], capture_output=True, text=True, encoding="utf-8")
    print(p.stdout[-1500:])
    check("Tạo video THẬT qua tunnel", p.returncode == 0)

bad = [n for n, ok, _ in results if not ok]
print(f"\nTỔNG: {len(results) - len(bad)}/{len(results)} PASS" + (f" — FAIL: {bad}" if bad else " — PRODUCTION SMOKE PASS"))
sys.exit(1 if bad else 0)
