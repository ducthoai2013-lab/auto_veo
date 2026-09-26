"""Regression cho thoai-dash THẬT (app.main + Postgres + Redis tạm), chạy trước/sau khi áp module Veo.

  python tools/regression_thoai.py <backend_dir> [--veo]

Phần D100 (luôn chạy): /health, /api/plans, tạo team+user, JWT, /api/auth/me, /api/quota, tạo đơn D100 → QR,
webhook SePay D100 → kích hoạt subscription. Phần --veo: đăng nhập thiết bị, mua gói Veo qua webhook riêng,
và khẳng định gói D100 của cùng team KHÔNG đổi. Kết thúc in JSON kết quả (dùng để so sánh trước/sau).
Biến môi trường DB/Redis do người gọi đặt (POSTGRES_*, REDIS_HOST/REDIS_PORT?).
"""
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

backend = Path(sys.argv[1]).resolve()
WITH_VEO = "--veo" in sys.argv
sys.path.insert(0, str(backend))
os.chdir(backend)  # để .env cục bộ (nếu có) không bị nạp nhầm: chạy trong thư mục tạm không có .env
os.environ.update({"PAYMENT_WEBHOOK_ENABLED": "true", "SEPAY_WEBHOOK_API_KEY": "reg-d100-key",
                   "PAYMENT_BANK_BIN": "970422", "PAYMENT_BANK_ACCOUNT_NO": "0123456789",
                   "PAYMENT_BANK_ACCOUNT_NAME": "REG TEST", "PAYMENT_BANK_SHORT_NAME": "MB"})
if WITH_VEO:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "gateway"))
    from gateway.admin import make_keypair
    priv, pub = make_keypair()
    os.environ.update({"VEO_JWT_PRIVATE_KEY": priv.replace("\n", "\\n"), "VEO_WEBHOOK_ENABLED": "true",
                       "VEO_SEPAY_WEBHOOK_API_KEY": "reg-veo-key", "VEO_RECONCILE_SECONDS": "5"})

import jwt  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

t0 = time.time()
from app.main import app  # noqa: E402  (chạy create_all + migrations trên DB tạm)
from app.config import settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models import models as m  # noqa: E402

results: dict = {"import_seconds": round(time.time() - t0, 1)}
checks: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    checks.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))


c = TestClient(app)
r = c.get("/health")
check("GET /health", r.status_code == 200 and r.json().get("status") == "ok", r.text[:80])
r = c.get("/api/plans")
plans = r.json() if r.status_code == 200 else []
check("GET /api/plans có gói D100", r.status_code == 200 and len(plans) >= 2, r.text[:80])
results["d100_plan_codes"] = sorted(p["code"] for p in plans)
r = c.get("/api/billing-cycles")
check("GET /api/billing-cycles", r.status_code == 200 and len(r.json()) == 4)
check("route /api/veo chỉ có khi áp module", bool(c.get("/api/veo/plans").status_code == 200) == WITH_VEO,
      str(c.get("/api/veo/plans").status_code))

db = SessionLocal()
suffix = str(int(time.time()))
team = m.Team(name="Reg", slug=f"reg-{suffix}")
db.add(team)
db.flush()
user = m.User(team_id=team.id, email=f"reg{suffix}@test.vn", role="owner")
db.add(user)
db.commit()
team_id, user_id = team.id, user.id
db.close()
tok = jwt.encode({"user_id": user_id, "team_id": team_id, "exp": datetime.utcnow() + timedelta(hours=2)},
                 settings.SECRET_KEY, algorithm="HS256")
H = {"Authorization": f"Bearer {tok}"}

r = c.get("/api/auth/me", headers=H)
check("GET /api/auth/me", r.status_code == 200 and r.json()["email"].startswith("reg"), r.text[:80])
r = c.get("/api/quota", params={"team_id": team_id}, headers=H)
check("GET /api/quota", r.status_code == 200, r.text[:80])

paid_plan = next((p for p in plans if p["price"] > 0), None)
check("có gói D100 trả phí", paid_plan is not None)
sub_before = None
if paid_plan:
    r = c.post("/api/orders", headers=H, json={"team_id": team_id, "plan_code": paid_plan["code"], "billing_cycle_months": 1})
    check("POST /api/orders (D100)", r.status_code == 200 and r.json()["order_code"].startswith("D100-"), r.text[:120])
    order = r.json()
    check("QR D100 đúng nội dung", "D100RADAR%20" + order["order_code"] in order.get("qr_url", ""), order.get("qr_url", "")[:100])
    hook = {"id": f"REG{suffix}", "referenceCode": f"REG{suffix}", "transferType": "in", "transferAmount": order["amount"],
            "content": f"D100RADAR {order['order_code']}"}
    r = c.post("/api/payments/webhook/sepay", content=json.dumps(hook), headers={"Authorization": "Apikey reg-d100-key"})
    check("webhook SePay D100 xử lý", r.status_code == 200 and r.json().get("processed") is True, r.text[:120])
    r = c.get("/api/subscriptions/current", params={"team_id": team_id}, headers=H)
    sub_before = r.json()
    check("kích hoạt gói D100 (subscription active)", r.status_code == 200 and sub_before and sub_before["status"] == "active",
          r.text[:120])
    r = c.post("/api/payments/webhook/sepay", content=json.dumps(hook), headers={"Authorization": "Apikey reg-d100-key"})
    check("webhook D100 gửi trùng không kích hoạt lần 2",
          db_count := SessionLocal().query(m.Subscription).filter_by(team_id=team_id, status="active").count() == 1)

if WITH_VEO:
    r = c.post("/api/veo/device/start", json={"machine_hash": "reg-machine-hash-0001", "device_name": "REG-PC"})
    st = r.json()
    check("Veo: device/start", r.status_code == 200 and "user_code" in st, r.text[:100])
    r = c.post("/api/veo/device/approve", headers=H, json={"user_code": st["user_code"]})
    check("Veo: web duyệt thiết bị", r.status_code == 200 and r.json()["status"] == "approved", r.text[:100])
    r = c.post("/api/veo/device/poll", json={"device_code": st["device_code"]})
    tokens = r.json()
    check("Veo: app nhận token", r.status_code == 200 and tokens.get("status") == "approved", r.text[:100])
    DH = {"Authorization": "Bearer " + tokens["access_token"]}
    r = c.post("/api/veo/orders", headers=DH, json={"plan_code": "pro", "months": 1})
    check("Veo: tạo đơn AV3 + QR", r.status_code == 200 and r.json()["order_code"].startswith("AV3-")
          and "AUTOVEO3%20AV3-" in r.json()["qr_url"], r.text[:120])
    vo = r.json()
    body = json.dumps({"id": f"V{suffix}", "referenceCode": f"V{suffix}", "transferType": "in",
                       "transferAmount": vo["amount"], "content": f"AUTOVEO3 {vo['order_code']}"})
    r = c.post("/api/veo/webhook/sepay", content=body, headers={"Authorization": "Apikey reg-veo-key"})
    check("Veo: webhook riêng kích hoạt gói", r.status_code == 200 and r.json().get("status") == "matched_paid", r.text[:120])
    r = c.post("/api/payments/webhook/sepay", content=body, headers={"Authorization": "Apikey reg-d100-key"})
    check("Veo: webhook D100 bỏ qua đơn AV3 (không lỗi)", r.status_code == 200, r.text[:120])
    r = c.get("/api/subscriptions/current", params={"team_id": team_id}, headers=H)
    check("QUAN TRỌNG: gói D100 sau khi mua Veo KHÔNG đổi", r.status_code == 200 and r.json() == sub_before, r.text[:160])
    r = c.get("/api/quota", params={"team_id": team_id}, headers=H)
    check("quota D100 sau khi mua Veo vẫn trả lời", r.status_code == 200, r.text[:80])
    r = c.get("/api/veo/me", headers=DH)
    check("Veo: /me báo gói pro", r.status_code == 200 and r.json()["plan"]["code"] == "pro", r.text[:100])

if WITH_VEO:
    # --- đồng thời trên Postgres THẬT: 6 webhook y hệt cùng lúc chỉ được kích hoạt đúng 1 lần, không lỗi 500 ---
    import threading
    from app.models.veo_models import VeoPaymentTxn, VeoSubscription
    r = c.post("/api/veo/orders", headers=DH, json={"plan_code": "ultra", "months": 1})
    o2 = r.json()
    body2 = json.dumps({"id": f"C{suffix}", "referenceCode": f"C{suffix}", "transferType": "in",
                        "transferAmount": o2["amount"], "content": f"AUTOVEO3 {o2['order_code']}"})
    outs, errs = [], []

    def hit():
        try:
            rr = TestClient(app).post("/api/veo/webhook/sepay", content=body2, headers={"Authorization": "Apikey reg-veo-key"})
            outs.append((rr.status_code, rr.json()))
        except Exception as e:  # noqa: BLE001
            errs.append(repr(e))
    ths = [threading.Thread(target=hit) for _ in range(6)]
    [t.start() for t in ths]
    [t.join() for t in ths]
    paid = [o for sc, o in outs if o.get("status") == "matched_paid"]
    check("Veo: 6 webhook đồng thời → không lỗi 500", not errs and all(sc == 200 for sc, _ in outs), str(errs or outs)[:200])
    check("Veo: 6 webhook đồng thời → đúng 1 lần kích hoạt", len(paid) == 1, str(outs)[:200])
    s2 = SessionLocal()
    check("Veo: đúng 1 dòng giao dịch cho mã đó", s2.query(VeoPaymentTxn).filter_by(gateway_txn_id=f"C{suffix}").count() == 1)
    check("Veo: đúng 1 subscription active cho team", s2.query(VeoSubscription).filter_by(team_id=team_id, status="active").count() == 1)
    s2.close()
    # --- trần đơn pending ---
    codes = [c.post("/api/veo/orders", headers=DH, json={"plan_code": "pro", "months": 1}).status_code for _ in range(6)]
    check("Veo: trần 5 đơn pending (đơn thứ 6 bị 429)", codes[:5] == [200] * 5 and codes[5] == 429, str(codes))
    r = c.get("/api/subscriptions/current", params={"team_id": team_id}, headers=H)
    check("D100 vẫn nguyên vẹn sau toàn bộ thao tác Veo", r.status_code == 200 and r.json() == sub_before)

if WITH_VEO:
    # --- SePay chỉ gọi webhook D100: giao dịch AV3- trong payment_transactions phải TỰ kích hoạt nhờ luồng nền đối soát ---
    from app.models.models import PaymentTransaction
    from app.models.veo_models import VeoOrder
    s0 = SessionLocal()      # dọn các đơn chờ của bước thử trần đơn để không vướng trần 5 đơn
    s0.query(VeoOrder).filter_by(team_id=team_id, payment_status="pending").update({"payment_status": "expired"})
    s0.commit()
    s0.close()
    o3 = c.post("/api/veo/orders", headers=DH, json={"plan_code": "pro", "months": 1}).json()
    s3 = SessionLocal()
    s3.add(PaymentTransaction(gateway="sepay", gateway_transaction_id=f"RECON{suffix}", amount=o3["amount"],
                              raw_content="AUTOVEO3 " + o3["order_code"].replace("-", "") + " CKN 999 d1B4 - MBBANK IBFT",
                              status="unmatched", raw_payload=json.dumps({"id": f"RECON{suffix}"}),
                              received_at=datetime.utcnow()))
    s3.commit()
    s3.close()
    st3 = "pending"
    for _ in range(30):                       # luồng nền chu kỳ 5 giây
        time.sleep(1)
        st3 = c.get("/api/veo/orders/" + o3["order_code"], headers=DH).json().get("status")
        if st3 != "pending":
            break
    check("Veo: luồng nền TỰ kích hoạt đơn từ giao dịch nằm trong payment_transactions (D100)", st3 == "paid", st3)
    r = c.get("/api/subscriptions/current", params={"team_id": team_id}, headers=H)
    check("D100 vẫn nguyên vẹn sau đối soát tự động", r.status_code == 200 and r.json() == sub_before)

failed = [n for n, ok, _ in checks if not ok]
results.update(total=len(checks), failed=failed)
print(json.dumps(results, ensure_ascii=False))
sys.exit(1 if failed else 0)
