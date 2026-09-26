"""Kiểm thử module Veo của thoai-dash trên BẢN SAO backend (không đụng repo thật).

Chép thoai-dash/backend vào thư mục tạm → áp module bằng apply_to_thoai_dash.py → chạy API trên SQLite.
Chứng minh: đăng nhập thiết bị, token Ed25519 tương thích Gateway, mua gói QR + webhook tự kích hoạt,
chống trùng, và **gói D100 của cùng team không bị đụng** khi mua gói Veo.
"""
import json
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

import jwt
import pytest

ROOT = Path(__file__).resolve().parents[1]
THOAI_BACKEND = Path(r"D:\claude\app_b1\thoai-dash\backend")
sys.path.insert(0, str(ROOT / "gateway"))
sys.path.insert(0, str(ROOT / "thoai-dash-module"))

from gateway.admin import make_keypair  # noqa: E402
from apply_to_thoai_dash import apply  # noqa: E402

pytestmark = pytest.mark.skipif(not THOAI_BACKEND.is_dir(), reason="không có thoai-dash local")


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    import os
    tmp = tmp_path_factory.mktemp("thoai")
    backend = tmp / "backend"
    shutil.copytree(THOAI_BACKEND, backend, ignore=shutil.ignore_patterns("__pycache__", "scripts", "*.yaml"))
    assert apply(backend) is True and apply(backend, True) is True
    assert apply(backend) is True  # chạy lại vẫn ổn (idempotent)
    main_txt = (backend / "app" / "main.py").read_text(encoding="utf-8")
    assert main_txt.count("app.include_router(veo.router)") == 1

    priv, pub = make_keypair()
    os.environ.update({
        "VEO_JWT_PRIVATE_KEY": priv.replace("\n", "\\n"), "VEO_WEBHOOK_ENABLED": "true",
        "VEO_SEPAY_WEBHOOK_API_KEY": "sekret", "PAYMENT_BANK_BIN": "970422",
        "PAYMENT_BANK_ACCOUNT_NO": "0123456789", "PAYMENT_BANK_ACCOUNT_NAME": "NGUYEN VAN A",
        "PAYMENT_BANK_SHORT_NAME": "MB", "POSTGRES_HOST": "127.0.0.1", "POSTGRES_PORT": "1",
    })
    sys.path.insert(0, str(backend))
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.config import settings
    from app.database import Base, get_db
    from app.models import models as m
    from app.models import veo_models as vm
    from app.api import veo

    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng, tables=[m.Team.__table__, m.User.__table__, m.Plan.__table__,
                                          m.Subscription.__table__, m.Order.__table__, m.PaymentTransaction.__table__,
                                          *[t for n, t in Base.metadata.tables.items() if n.startswith("veo_")]])
    Session = sessionmaker(bind=eng, autoflush=False)

    def override():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app = FastAPI()
    app.include_router(veo.router)
    app.dependency_overrides[get_db] = override

    s = Session()
    team = m.Team(name="T1", slug="t1"); s.add(team); s.flush()
    owner = m.User(team_id=team.id, email="owner@x.vn", role="owner"); s.add(owner)
    admin = m.User(team_id=team.id, email="root@x.vn", role="owner", is_super_admin=True); s.add(admin)
    d100 = m.Plan(code="pro_d100", name="D100 Pro", price=1000); s.add(d100); s.flush()
    sub = m.Subscription(team_id=team.id, plan_id=d100.id, status="active",
                         expires_at=datetime.utcnow() + timedelta(days=100)); s.add(sub)
    s.commit()
    ids = dict(team=team.id, owner=owner.id, admin=admin.id, sub=sub.id)
    s.close()

    def web(user_id):
        tok = jwt.encode({"user_id": user_id, "team_id": ids["team"], "exp": datetime.utcnow() + timedelta(hours=1)},
                         settings.SECRET_KEY, algorithm="HS256")
        return {"Authorization": f"Bearer {tok}"}

    yield dict(c=TestClient(app), Session=Session, ids=ids, web=web, m=m, vm=vm, pub=pub)
    sys.path.remove(str(backend))
    for name in [n for n in sys.modules if n == "app" or n.startswith("app.")]:
        del sys.modules[name]


MACH1 = "machine-hash-aaaaaaaaaaaa"
MACH2 = "machine-hash-bbbbbbbbbbbb"


def login(w, machine, name="PC"):
    c = w["c"]
    st = c.post("/api/veo/device/start", json={"machine_hash": machine, "device_name": name}).json()
    assert c.post("/api/veo/device/poll", json={"device_code": st["device_code"]}).json()["status"] == "pending"
    return st


def approve(w, st):
    return w["c"].post("/api/veo/device/approve", json={"user_code": st["user_code"]}, headers=w["web"](w["ids"]["owner"]))


def test_plans_seeded_and_public_key(world):
    c = world["c"]
    plans = c.get("/api/veo/plans").json()
    assert [p["code"] for p in plans] == ["trial", "pro", "ultra"]
    assert plans[0]["video_quota"] == 3 and plans[2]["allow_4k"] is True
    assert plans[1]["cycles"][3]["discount_percent"] == 20
    assert c.get("/api/veo/public-key").json()["pem"].strip() == world["pub"].strip()


def test_device_login_token_compatible_with_gateway(world):
    from gateway.auth import verify_token
    c = world["c"]
    st = login(world, MACH1, "Máy kế toán")
    info = c.get("/api/veo/device/info", params={"user_code": st["user_code"]}, headers=world["web"](world["ids"]["owner"])).json()
    assert info["device_name"] == "Máy kế toán"
    assert approve(world, st).json()["status"] == "approved"
    res = c.post("/api/veo/device/poll", json={"device_code": st["device_code"]}).json()
    assert res["status"] == "approved" and res["refresh_token"].startswith("avr_")
    p = verify_token(world["pub"], res["access_token"])     # đúng thứ Gateway sẽ kiểm
    assert (p.plan, p.quota, p.quota_period, p.max_concurrent, p.email) == ("trial", 3, "total", 1, "owner@x.vn")
    assert p.sub_expires is None and not p.expired
    world["dev"] = res
    me = c.get("/api/veo/me", headers={"Authorization": "Bearer " + res["access_token"]}).json()
    assert me["plan"]["code"] == "trial" and me["email"] == "owner@x.vn"
    # đã dùng mã một lần
    assert c.post("/api/veo/device/poll", json={"device_code": st["device_code"]}).status_code == 409


def test_refresh_and_machine_binding(world):
    c = world["c"]
    dev = world["dev"]
    ok = c.post("/api/veo/token/refresh", json={"refresh_token": dev["refresh_token"], "machine_hash": MACH1})
    assert ok.status_code == 200 and ok.json()["access_token"]
    bad = c.post("/api/veo/token/refresh", json={"refresh_token": dev["refresh_token"], "machine_hash": MACH2})
    assert bad.status_code == 401 and bad.json()["detail"]["code"] == "machine_mismatch"


def test_device_limit_and_revoke(world):
    c = world["c"]
    st = login(world, MACH2, "Máy 2")
    r = approve(world, st)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "device_limit"   # trial: 1 máy
    devs = c.get("/api/veo/devices", headers=world["web"](world["ids"]["owner"])).json()
    dev_id = devs["devices"][0]["id"]
    assert c.delete(f"/api/veo/devices/{dev_id}", headers=world["web"](world["ids"]["owner"])).json()["ok"]
    dev = world["dev"]
    rf = c.post("/api/veo/token/refresh", json={"refresh_token": dev["refresh_token"], "machine_hash": MACH1})
    assert rf.status_code == 401 and rf.json()["detail"]["code"] == "device_revoked"
    assert c.get("/api/veo/me", headers={"Authorization": "Bearer " + dev["access_token"]}).status_code == 401
    # sau khi gỡ, máy 2 duyệt được
    assert approve(world, st).json()["status"] == "approved"
    world["dev"] = c.post("/api/veo/device/poll", json={"device_code": st["device_code"]}).json()


def test_purchase_qr_webhook_activates_and_d100_untouched(world):
    c, ids, m = world["c"], world["ids"], world["m"]
    H = {"Authorization": "Bearer " + world["dev"]["access_token"]}
    o = c.post("/api/veo/orders", json={"plan_code": "pro", "months": 3}, headers=H).json()
    assert o["order_code"].startswith("AV3-") and o["amount"] == round(199000 * 3 * 0.95)
    assert "img.vietqr.io/image/970422-0123456789" in o["qr_url"] and f"AUTOVEO3%20{o['order_code']}" in o["qr_url"]
    assert c.post("/api/veo/orders", json={"plan_code": "trial", "months": 1}, headers=H).json()["detail"]["code"] == "free_plan"

    def hook(content, amount, txn, key="sekret", ttype="in"):
        body = json.dumps({"id": txn, "referenceCode": txn, "transferType": ttype, "transferAmount": amount,
                           "content": content})
        return c.post("/api/veo/webhook/sepay", content=body, headers={"Authorization": f"Apikey {key}"})

    assert hook("x", 1, "T0", key="sai").status_code == 401
    assert hook(f"AUTOVEO3 {o['order_code']}", o["amount"] - 1000, "T1").json()["status"] == "matched_amount_mismatch"
    assert c.get(f"/api/veo/orders/{o['order_code']}", headers=H).json()["status"] == "pending"
    assert hook("D100RADAR D100-ABC123", 500000, "T2").json()["reason"] == "not_autoveo3"   # tiền của D100
    assert hook("khong lien quan", 5, "T3", ttype="out").json()["reason"] == "not_incoming"
    good = hook(f"chuyen tien autoveo3 {o['order_code'].lower()}", o["amount"], "T4")
    assert good.json()["status"] == "matched_paid"
    assert hook(f"AUTOVEO3 {o['order_code']}", o["amount"], "T4").json()["reason"] == "duplicate"   # cùng giao dịch
    assert hook(f"AUTOVEO3 {o['order_code']}", o["amount"], "T5").json()["status"] == "matched_duplicate"  # giao dịch khác
    assert c.get(f"/api/veo/orders/{o['order_code']}", headers=H).json()["status"] == "paid"

    # token mới mang gói Pro + hạn ~90 ngày; Gateway sẽ chấp nhận
    from gateway.auth import verify_token
    dev = world["dev"]
    rf = c.post("/api/veo/token/refresh", json={"refresh_token": dev["refresh_token"], "machine_hash": MACH2}).json()
    p = verify_token(world["pub"], rf["access_token"])
    assert p.plan == "pro" and p.quota is None and p.max_concurrent == 3 and not p.expired
    exp = datetime.strptime(p.sub_expires, "%Y-%m-%dT%H:%M:%SZ")
    assert timedelta(days=89) < exp - datetime.utcnow() < timedelta(days=91)

    # ĐIỂM CHỐT: gói D100 của cùng team vẫn active, không bị tắt
    s = world["Session"]()
    d100_sub = s.query(m.Subscription).filter_by(id=ids["sub"]).one()
    assert d100_sub.status == "active"
    assert s.query(m.Subscription).filter_by(team_id=ids["team"]).count() == 1
    s.close()


def test_renew_stacks_and_expired_order(world):
    c, vm = world["c"], world["vm"]
    H = {"Authorization": "Bearer " + world["dev"]["access_token"]}
    o = c.post("/api/veo/orders", json={"plan_code": "pro", "months": 1}, headers=H).json()
    s = world["Session"]()
    row = s.query(vm.VeoOrder).filter_by(order_code=o["order_code"]).one()
    row.expires_at = datetime.utcnow() - timedelta(minutes=1)
    s.commit(); s.close()
    body = json.dumps({"id": "T9", "referenceCode": "T9", "transferType": "in", "transferAmount": o["amount"],
                       "content": f"AUTOVEO3 {o['order_code']}"})
    r = c.post("/api/veo/webhook/sepay", content=body, headers={"Authorization": "Apikey sekret"}).json()
    assert r["status"] == "matched_expired"           # tiền về sau hạn: không tự kích hoạt
    admin_h = world["web"](world["ids"]["admin"])
    assert c.post(f"/api/veo/admin/orders/{o['order_code']}/mark-paid", headers=admin_h).json()["activated"] is True
    dev = world["dev"]
    rf = c.post("/api/veo/token/refresh", json={"refresh_token": dev["refresh_token"], "machine_hash": MACH2}).json()
    from gateway.auth import verify_token
    p = verify_token(world["pub"], rf["access_token"])
    exp = datetime.strptime(p.sub_expires, "%Y-%m-%dT%H:%M:%SZ")
    assert timedelta(days=119) < exp - datetime.utcnow() < timedelta(days=121)   # 90 + 30 cộng dồn
    assert c.post("/api/veo/admin/orders/X/mark-paid", headers=world["web"](world["ids"]["owner"])).status_code == 403


def test_webhook_disabled_flag(world, monkeypatch):
    monkeypatch.setenv("VEO_WEBHOOK_ENABLED", "false")
    r = world["c"].post("/api/veo/webhook/sepay", content="{}", headers={"Authorization": "Apikey sekret"}).json()
    assert r["reason"] == "webhook_disabled"


def test_reconcile_activates_from_d100_transaction_table(world):
    """SePay chỉ gọi webhook D100: giao dịch AV3- nằm ở payment_transactions phải tự kích hoạt gói Veo (đọc-không-sửa)."""
    from datetime import datetime
    from app.services import veo_reconcile
    c, m, vm = world["c"], world["m"], world["vm"]
    H = {"Authorization": "Bearer " + world["dev"]["access_token"]}
    o = c.post("/api/veo/orders", json={"plan_code": "pro", "months": 1}, headers=H).json()
    code_nohyphen = o["order_code"].replace("-", "")                 # ngân hàng bỏ dấu '-' trong nội dung
    s = world["Session"]()
    s.add(m.PaymentTransaction(gateway="sepay", gateway_transaction_id="D100TX-RECON-1", amount=o["amount"],
                               raw_content=f"AUTOVEO3 {code_nohyphen} CKN 123456 d1B4XYZ - MBBANK IBFT", status="unmatched",
                               raw_payload=json.dumps({"id": "D100TX-RECON-1"}), received_at=datetime.utcnow()))
    s.add(m.PaymentTransaction(gateway="sepay", gateway_transaction_id="D100TX-OTHER", amount=500000,
                               raw_content="D100RADAR D100-ABC123", status="unmatched", raw_payload="{}",
                               received_at=datetime.utcnow()))       # giao dịch D100: phải bị bỏ qua
    s.commit()
    assert veo_reconcile.reconcile_once(s) == 1
    assert c.get(f"/api/veo/orders/{o['order_code']}", headers=H).json()["status"] == "paid"
    assert veo_reconcile.reconcile_once(s) == 0                      # chạy lại: không kích hoạt lần 2
    txns = s.query(vm.VeoPaymentTxn).filter_by(gateway_txn_id="D100TX-RECON-1").all()
    assert len(txns) == 1 and txns[0].status == "matched_paid"
    # webhook Veo riêng nhận CÙNG giao dịch sau đó: chỉ báo duplicate
    body = json.dumps({"id": "D100TX-RECON-1", "referenceCode": "D100TX-RECON-1", "transferType": "in",
                       "transferAmount": o["amount"], "content": f"AUTOVEO3 {o['order_code']}"})
    r = c.post("/api/veo/webhook/sepay", content=body, headers={"Authorization": "Apikey sekret"}).json()
    assert r["reason"] == "duplicate"
    s.close()
