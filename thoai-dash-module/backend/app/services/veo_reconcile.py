"""
Auto_veo3 — đối soát tự động: kích hoạt gói cho giao dịch mang mã AV3-… dù SePay chỉ gửi vào webhook D100.

Bối cảnh (2026-09-19): SePay gọi webhook D100 (/api/payments/webhook/sepay) cho MỌI giao dịch tiền vào, D100 ghi vào bảng
`payment_transactions` (trạng thái unmatched với mã AV3-). Webhook riêng của Veo (/api/veo/webhook/sepay) chưa nhận được giao
dịch thật. Bộ đối soát này ĐỌC bảng `payment_transactions` (chỉ đọc, không sửa dòng D100) và đẩy giao dịch AV3- vào đúng hàm
xử lý của Veo. Idempotent: khóa duy nhất (gateway, mã giao dịch) của veo_payment_txns chặn kích hoạt trùng, kể cả khi
webhook Veo riêng cũng nhận được cùng giao dịch.

Bật bằng biến môi trường VEO_RECONCILE_SECONDS (>0 = chu kỳ giây; mặc định 0 = tắt) VÀ VEO_WEBHOOK_ENABLED=true.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models.veo_models import VeoPaymentTxn
from app.services import veo_service as svc

log = logging.getLogger("veo.reconcile")
LOOKBACK_DAYS = 3
BATCH = 100
_started = False


def reconcile_once(db: Session) -> int:
    """Xử lý các giao dịch D100 mang mã AV3- chưa có trong veo_payment_txns. Trả về số giao dịch đã xử lý."""
    from app.models.models import PaymentTransaction        # bảng của D100: CHỈ ĐỌC
    since = datetime.utcnow() - timedelta(days=LOOKBACK_DAYS)
    rows = (db.query(PaymentTransaction)
            .filter(PaymentTransaction.received_at >= since, PaymentTransaction.raw_content.ilike("%AV3%"))
            .order_by(PaymentTransaction.received_at).limit(BATCH).all())
    done = 0
    for r in rows:
        code = svc.parse_order_code(r.raw_content or "")
        if not code or not r.gateway_transaction_id:
            continue
        if db.query(VeoPaymentTxn).filter_by(gateway="sepay", gateway_txn_id=str(r.gateway_transaction_id)).first():
            continue
        res = svc.process_sepay_event(db, str(r.gateway_transaction_id), code, int(r.amount or 0), r.raw_payload or "")
        if res.get("processed"):
            done += 1
            log.info("Veo đối soát: %s -> %s (%s đ)", code, res.get("status"), r.amount)
    return done


def _loop(interval: int) -> None:
    from app.database import SessionLocal
    while True:
        db = SessionLocal()
        try:
            reconcile_once(db)
        except Exception:  # noqa: BLE001 - vòng lặp nền không được chết
            log.exception("Veo đối soát lỗi")
            db.rollback()
        finally:
            db.close()
        time.sleep(interval)


def start_background() -> bool:
    """Khởi động luồng nền một lần mỗi tiến trình nếu VEO_RECONCILE_SECONDS > 0 và webhook Veo bật."""
    global _started
    try:
        interval = int(os.getenv("VEO_RECONCILE_SECONDS", "0"))
    except ValueError:
        interval = 0
    if _started or interval <= 0 or not svc.webhook_enabled():
        return False
    _started = True
    threading.Thread(target=_loop, args=(max(5, interval),), name="veo-reconcile", daemon=True).start()
    log.info("Veo đối soát bật, chu kỳ %ss", interval)
    return True
