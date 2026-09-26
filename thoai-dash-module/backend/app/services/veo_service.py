"""
Auto_veo3 — nghiệp vụ: gói, token thiết bị (Ed25519), đơn hàng + QR VietQR, kích hoạt gói.

Cấu hình đọc thẳng từ biến môi trường VEO_* (không sửa app/config.py của D100):
  VEO_JWT_PRIVATE_KEY / VEO_JWT_PRIVATE_KEY_FILE   khóa riêng Ed25519 (PEM) — CHỈ nằm trên VPS
  VEO_ACCESS_TOKEN_HOURS                           mặc định 6
  VEO_DEVICE_VERIFY_URL                            trang duyệt thiết bị, mặc định https://d100radar.com/veo3/device.html
  VEO_WEBHOOK_ENABLED                              "true" mới xử lý webhook (mặc định tắt như D100)
  VEO_SEPAY_WEBHOOK_API_KEY                        khóa webhook SePay riêng; trống thì dùng SEPAY_WEBHOOK_API_KEY
Ngân hàng nhận tiền dùng lại PAYMENT_BANK_* của D100 (cùng tài khoản, khác tiền tố mã đơn AV3-).
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import secrets
import string
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import jwt
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.veo_models import (
    VeoDevice, VeoDeviceCode, VeoOrder, VeoPaymentTxn, VeoPlan, VeoSubscription,
)

ISSUER = "autoveo3"
AUDIENCE = "gateway"
# Giảm giá theo chu kỳ — giống BILLING_CYCLE_DISCOUNTS của D100 (sửa ở đây nếu muốn khác).
CYCLE_DISCOUNT = {1: 0.0, 3: 0.05, 6: 0.10, 12: 0.20}
_CODE_RE = re.compile(r"AV3[-\s]?([A-Z0-9]{6})")
MAX_PENDING_ORDERS = 5

# GIÁ MẪU, CHƯA PHẢI GIÁ BÁN THẬT — sửa bằng PUT /api/veo/admin/plans/{code}.
DEFAULT_PLANS = [
    dict(code="trial", name="Dùng thử", price_month=0, max_concurrent=1, max_devices=1,
         video_quota=3, quota_period="total", allow_4k=False, sort_order=0),
    dict(code="pro", name="Pro", price_month=199000, max_concurrent=3, max_devices=1,
         video_quota=None, quota_period="total", allow_4k=False, sort_order=1),
    dict(code="ultra", name="Ultra", price_month=399000, max_concurrent=5, max_devices=2,
         video_quota=None, quota_period="total", allow_4k=True, sort_order=2),
]


class VeoError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


# ---------------------------------------------------------------- cấu hình
def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default)


def webhook_enabled() -> bool:
    return _env("VEO_WEBHOOK_ENABLED", "false").lower() == "true"


def verify_url() -> str:
    return _env("VEO_DEVICE_VERIFY_URL", "https://d100radar.com/veo3/device.html")


def access_ttl() -> timedelta:
    return timedelta(hours=int(_env("VEO_ACCESS_TOKEN_HOURS", "6")))


def _private_pem() -> str:
    f = _env("VEO_JWT_PRIVATE_KEY_FILE")
    if f and Path(f).is_file():
        return Path(f).read_text(encoding="utf-8")
    pem = _env("VEO_JWT_PRIVATE_KEY").replace("\\n", "\n")
    if not pem:
        raise VeoError(503, "no_signing_key", "Máy chủ chưa cấu hình khóa ký VEO_JWT_PRIVATE_KEY")
    return pem


def public_pem() -> str:
    from cryptography.hazmat.primitives import serialization
    key = serialization.load_pem_private_key(_private_pem().encode(), password=None)
    return key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()


# ---------------------------------------------------------------- gói
def ensure_plans(db: Session) -> None:
    if db.query(VeoPlan).first():
        return
    for p in DEFAULT_PLANS:
        db.add(VeoPlan(**p))
    db.commit()


def order_amount(price_month: int, months: int) -> int:
    return round(price_month * months * (1 - CYCLE_DISCOUNT[months]))


def plan_view(p: VeoPlan) -> dict:
    return {"code": p.code, "name": p.name, "price_month": p.price_month,
            "max_concurrent": p.max_concurrent, "max_devices": p.max_devices,
            "video_quota": p.video_quota, "quota_period": p.quota_period, "allow_4k": bool(p.allow_4k),
            "cycles": [{"months": m, "amount": order_amount(p.price_month, m),
                        "discount_percent": round(d * 100)} for m, d in CYCLE_DISCOUNT.items()]}


def current_entitlement(db: Session, team_id: str) -> tuple[VeoPlan, Optional[datetime]]:
    """(gói, hạn). Ưu tiên gói trả phí active mới nhất (kể cả đã hết hạn để Gateway báo 'hết hạn');
    chưa từng mua thì gói dùng thử không hạn."""
    ensure_plans(db)
    sub = (db.query(VeoSubscription).filter_by(team_id=team_id, status="active")
           .order_by(VeoSubscription.started_at.desc()).first())
    if sub:
        plan = db.query(VeoPlan).filter_by(id=sub.plan_id).first()
        if plan:
            return plan, sub.expires_at
    return db.query(VeoPlan).filter_by(code="trial").one(), None


# ---------------------------------------------------------------- token
def hash_secret(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def issue_access_token(db: Session, device: VeoDevice, email: str) -> tuple[str, int]:
    plan, sexp = current_entitlement(db, device.team_id)
    ttl = access_ttl()
    now_ts = int(time.time())  # KHÔNG dùng datetime.utcnow().timestamp(): lệch múi giờ máy chủ
    claims = {
        "iss": ISSUER, "aud": AUDIENCE, "sub": device.team_id, "email": email, "dev": device.id,
        "plan": plan.code, "plan_name": plan.name, "cc": plan.max_concurrent, "k4": bool(plan.allow_4k),
        "q": plan.video_quota, "qp": plan.quota_period,
        "sexp": sexp.strftime("%Y-%m-%dT%H:%M:%SZ") if sexp else None,
        "iat": now_ts, "exp": now_ts + int(ttl.total_seconds()),
    }
    return jwt.encode(claims, _private_pem(), algorithm="EdDSA"), int(ttl.total_seconds())


def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(token, public_pem(), algorithms=["EdDSA"], audience=AUDIENCE, issuer=ISSUER)
    except jwt.ExpiredSignatureError:
        raise VeoError(401, "token_expired", "Token hết hạn")
    except jwt.PyJWTError:
        raise VeoError(401, "bad_token", "Token không hợp lệ")


# ---------------------------------------------------------------- đăng nhập thiết bị
def _user_code() -> str:
    alphabet = "".join(c for c in string.ascii_uppercase + string.digits if c not in "0O1I")
    return "-".join("".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(2))


def start_device_login(db: Session, machine_hash: str, device_name: str) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", machine_hash or ""):
        raise VeoError(400, "bad_machine", "Mã máy không hợp lệ")
    row = VeoDeviceCode(device_code=secrets.token_urlsafe(32), user_code=_user_code(),
                        machine_hash=machine_hash, device_name=(device_name or "")[:80],
                        expires_at=datetime.utcnow() + timedelta(minutes=10))
    db.add(row)
    db.commit()
    return {"device_code": row.device_code, "user_code": row.user_code, "expires_in": 600, "interval": 3,
            "verification_url": f"{verify_url()}?code={row.user_code}"}


def _find_code(db: Session, user_code: str) -> VeoDeviceCode:
    row = db.query(VeoDeviceCode).filter_by(user_code=(user_code or "").strip().upper()).first()
    if not row or row.expires_at < datetime.utcnow():
        raise VeoError(404, "no_code", "Mã không đúng hoặc đã hết hạn")
    return row


def device_code_info(db: Session, user_code: str) -> dict:
    row = _find_code(db, user_code)
    return {"user_code": row.user_code, "device_name": row.device_name, "status": row.status}


def approve_device(db: Session, user_code: str, user_id: str, team_id: str, approve: bool = True) -> dict:
    row = _find_code(db, user_code)
    if row.status != "pending":
        raise VeoError(409, "already_done", "Mã này đã được xử lý")
    if not approve:
        row.status = "denied"
        db.commit()
        return {"status": "denied"}
    plan, _ = current_entitlement(db, team_id)
    active = db.query(VeoDevice).filter_by(team_id=team_id, status="active").all()
    if not any(d.machine_hash == row.machine_hash for d in active) and len(active) >= plan.max_devices:
        raise VeoError(403, "device_limit",
                       f"Gói {plan.name} chỉ cho {plan.max_devices} máy. Gỡ máy cũ ở trang quản lý thiết bị.")
    row.status, row.team_id, row.user_id = "approved", team_id, user_id
    db.commit()
    return {"status": "approved"}


def poll_device_login(db: Session, device_code: str, email_of) -> dict:
    row = db.query(VeoDeviceCode).filter_by(device_code=device_code).first()
    if not row:
        raise VeoError(404, "no_code", "Không có mã này")
    if row.status == "denied":
        return {"status": "denied"}
    if row.expires_at < datetime.utcnow() and row.status == "pending":
        return {"status": "expired"}
    if row.status == "pending":
        return {"status": "pending"}
    if row.status == "used":
        raise VeoError(409, "already_used", "Mã đã dùng, hãy đăng nhập lại")
    # approved -> cấp thiết bị (thay thế bản ghi cũ của cùng máy nếu có)
    for old in db.query(VeoDevice).filter_by(team_id=row.team_id, machine_hash=row.machine_hash, status="active"):
        old.status = "revoked"
    refresh = "avr_" + secrets.token_urlsafe(40)
    dev = VeoDevice(team_id=row.team_id, user_id=row.user_id, machine_hash=row.machine_hash,
                    name=row.device_name, refresh_hash=hash_secret(refresh))
    db.add(dev)
    row.status = "used"
    db.commit()
    token, ttl = issue_access_token(db, dev, email_of(row.user_id))
    return {"status": "approved", "access_token": token, "refresh_token": refresh,
            "expires_in": ttl, "device_id": dev.id}


def refresh_access(db: Session, refresh_token: str, machine_hash: str, email_of) -> dict:
    dev = db.query(VeoDevice).filter_by(refresh_hash=hash_secret(refresh_token or "")).first()
    if not dev or dev.status != "active":
        raise VeoError(401, "device_revoked", "Thiết bị đã bị gỡ hoặc phiên không hợp lệ, hãy đăng nhập lại")
    if dev.machine_hash != machine_hash:
        raise VeoError(401, "machine_mismatch", "Phiên không thuộc máy này")
    dev.last_seen = datetime.utcnow()
    db.commit()
    token, ttl = issue_access_token(db, dev, email_of(dev.user_id))
    return {"access_token": token, "expires_in": ttl, "device_id": dev.id}


def device_from_access(db: Session, token: str) -> VeoDevice:
    c = decode_access_token(token)
    dev = db.query(VeoDevice).filter_by(id=c["dev"], status="active").first()
    if not dev:
        raise VeoError(401, "device_revoked", "Thiết bị đã bị gỡ")
    return dev


# ---------------------------------------------------------------- đơn hàng + QR
def build_qr_url(order_code: str, amount: int) -> str:
    bin_, acc = _env("PAYMENT_BANK_BIN"), _env("PAYMENT_BANK_ACCOUNT_NO")
    if not bin_ or not acc:
        raise VeoError(503, "payment_not_configured",
                       "Chưa cấu hình ngân hàng VietQR (PAYMENT_BANK_BIN/PAYMENT_BANK_ACCOUNT_NO)")
    name = quote(_env("PAYMENT_BANK_ACCOUNT_NAME"))
    return (f"https://img.vietqr.io/image/{bin_}-{acc}-compact2.png?amount={amount}"
            f"&addInfo={quote('AUTOVEO3 ' + order_code)}&accountName={name}")


def order_view(o: VeoOrder, plan: Optional[VeoPlan] = None) -> dict:
    d = {"order_code": o.order_code, "plan_code": plan.code if plan else None,
         "plan_name": plan.name if plan else None, "months": o.months, "amount": o.amount,
         "status": o.payment_status, "expires_at": o.expires_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
         "paid_at": o.paid_at.strftime("%Y-%m-%dT%H:%M:%SZ") if o.paid_at else None,
         "transfer_content": f"AUTOVEO3 {o.order_code}",
         "bank_short_name": _env("PAYMENT_BANK_SHORT_NAME"), "bank_account_no": _env("PAYMENT_BANK_ACCOUNT_NO"),
         "bank_account_name": _env("PAYMENT_BANK_ACCOUNT_NAME")}
    if o.payment_status == "pending":
        d["qr_url"] = build_qr_url(o.order_code, o.amount)
    return d


def _gen_code(db: Session) -> str:
    for _ in range(20):
        code = "AV3-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
        if not db.query(VeoOrder).filter_by(order_code=code).first():
            return code
    raise VeoError(500, "code_gen", "Không tạo được mã đơn, thử lại")


def create_order(db: Session, team_id: str, user_id: str, plan_code: str, months: int) -> dict:
    ensure_plans(db)
    if months not in CYCLE_DISCOUNT:
        raise VeoError(400, "bad_cycle", f"Chu kỳ chỉ nhận {sorted(CYCLE_DISCOUNT)} tháng")
    plan = db.query(VeoPlan).filter_by(code=plan_code, is_active=True).first()
    if not plan:
        raise VeoError(404, "no_plan", "Gói không tồn tại")
    if plan.price_month <= 0:
        raise VeoError(400, "free_plan", "Gói miễn phí không cần thanh toán")
    pending = db.query(VeoOrder).filter_by(team_id=team_id, payment_status="pending").filter(
        VeoOrder.expires_at > datetime.utcnow()).count()
    if pending >= MAX_PENDING_ORDERS:
        raise VeoError(429, "too_many_orders", "Bạn đang có quá nhiều đơn chờ thanh toán. Hãy thanh toán hoặc đợi đơn cũ hết hạn.")
    amount = order_amount(plan.price_month, months)
    code = _gen_code(db)
    build_qr_url(code, amount)  # báo lỗi cấu hình sớm, trước khi ghi đơn
    o = VeoOrder(order_code=code, team_id=team_id, plan_id=plan.id, months=months, amount=amount,
                 created_by_user_id=user_id,
                 expires_at=datetime.utcnow() + timedelta(hours=int(_env("PAYMENT_ORDER_EXPIRY_HOURS", "24"))))
    db.add(o)
    db.commit()
    return order_view(o, plan)


def get_order(db: Session, team_id: str, code: str) -> dict:
    o = db.query(VeoOrder).filter_by(order_code=code, team_id=team_id).first()
    if not o:
        raise VeoError(404, "no_order", "Không có đơn này")
    if o.payment_status == "pending" and o.expires_at < datetime.utcnow():
        o.payment_status = "expired"
        db.commit()
    return order_view(o, db.query(VeoPlan).filter_by(id=o.plan_id).first())


def activate_order(db: Session, o: VeoOrder) -> None:
    """Chỉ đụng bảng veo_*: cùng gói còn hạn thì cộng dồn, khác gói thì thay gói cũ."""
    now = datetime.utcnow()
    subs = db.query(VeoSubscription).filter_by(team_id=o.team_id, status="active").all()
    base = now
    for s in subs:
        if s.plan_id == o.plan_id and s.expires_at and s.expires_at > base:
            base = s.expires_at
        s.status = "replaced"
    db.add(VeoSubscription(team_id=o.team_id, plan_id=o.plan_id, order_id=o.id,
                           started_at=now, expires_at=base + timedelta(days=30 * o.months)))
    o.payment_status, o.paid_at = "paid", now
    db.commit()


def mark_paid(db: Session, code: str) -> bool:
    o = db.query(VeoOrder).filter_by(order_code=code).with_for_update().first()
    if not o or o.payment_status == "paid":
        return False
    activate_order(db, o)
    return True


# ---------------------------------------------------------------- webhook SePay
def parse_order_code(content: str) -> Optional[str]:
    m = _CODE_RE.search((content or "").upper())
    return f"AV3-{m.group(1)}" if m else None


def handle_sepay(db: Session, auth_header: str, body: bytes) -> dict:
    if not webhook_enabled():
        return {"ok": True, "processed": False, "reason": "webhook_disabled"}
    key = _env("VEO_SEPAY_WEBHOOK_API_KEY") or _env("SEPAY_WEBHOOK_API_KEY")
    if not key or (auth_header or "").strip() != f"Apikey {key}":
        raise VeoError(401, "bad_webhook_auth", "Xác thực webhook thất bại")
    try:
        p = json.loads(body)
    except ValueError:
        raise VeoError(400, "bad_payload", "Payload không hợp lệ")
    if p.get("transferType") != "in":
        return {"ok": True, "processed": False, "reason": "not_incoming"}
    txn = str(p.get("referenceCode") or p.get("id") or "")
    if not txn:
        raise VeoError(400, "no_txn", "Thiếu mã giao dịch")
    code = parse_order_code(str(p.get("content") or ""))
    if not code:  # tiền của luồng khác (D100-…): bỏ qua, không phải lỗi
        return {"ok": True, "processed": False, "reason": "not_autoveo3"}
    try:
        amount = int(p.get("transferAmount") or 0)
    except (TypeError, ValueError):
        raise VeoError(400, "bad_amount", "transferAmount không hợp lệ")
    return process_sepay_event(db, txn, code, amount, body.decode("utf-8", "replace"))


def process_sepay_event(db: Session, txn: str, code: str, amount: int, raw_text: str) -> dict:
    """Đối chiếu MỘT giao dịch đã xác thực với đơn AV3-…: dùng chung cho webhook Veo riêng và cho nhánh chuyển tiếp
    từ webhook D100 (khi SePay chỉ gọi một địa chỉ). Idempotent theo (gateway, mã giao dịch)."""
    if db.query(VeoPaymentTxn).filter_by(gateway="sepay", gateway_txn_id=txn).first():
        return {"ok": True, "processed": False, "reason": "duplicate"}
    o = db.query(VeoOrder).filter_by(order_code=code).with_for_update().first()
    if not o:
        status = "unmatched"
    elif o.payment_status == "paid":
        status = "matched_duplicate"
    elif o.expires_at < datetime.utcnow():
        status = "matched_expired"      # tiền về sau hạn: cần xử lý tay (mark-paid)
    elif amount < o.amount:
        status = "matched_amount_mismatch"
    else:
        status = "matched_paid"
    try:
        db.add(VeoPaymentTxn(gateway="sepay", gateway_txn_id=txn, order_code=code, amount=amount,
                             status=status, raw=raw_text))
        if status == "matched_paid":
            activate_order(db, o)     # commit cả giao dịch lẫn gói trong MỘT transaction
        else:
            db.commit()
    except IntegrityError:            # webhook trùng chạy đồng thời: bản kia đã ghi giao dịch này
        db.rollback()
        return {"ok": True, "processed": False, "reason": "duplicate"}
    return {"ok": True, "processed": True, "status": status, "order_code": code}
