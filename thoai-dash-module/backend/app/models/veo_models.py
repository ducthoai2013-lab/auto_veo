"""
Auto_veo3 — bảng RIÊNG cho app tạo video (bản cài Windows tại d100radar.com/veo3).

Tách hẳn khỏi plans/orders/subscriptions của D100Radar (quyết định 2026-09-19): luồng kích hoạt
D100 (`admin._activate_subscription`) tắt MỌI subscription active của team, nên nếu dùng chung bảng
thì mua gói Veo sẽ làm mất gói D100 của cùng team (và ngược lại).

KHÔNG dùng ForeignKey sang teams/users — chỉ lưu id chuỗi. Lý do: module này cắm thêm, không được
ràng buộc/khóa schema D100 (đúng nguyên tắc "không lan sang module khác"). Bảng tự tạo bằng
Base.metadata.create_all() khi import (xem app/api/veo.py), không cần migration.
"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Index, Integer, String, Text, UniqueConstraint

from app.database import Base


def _id() -> str:
    return uuid.uuid4().hex


class VeoPlan(Base):
    __tablename__ = "veo_plans"
    id = Column(String, primary_key=True, default=_id)
    code = Column(String, unique=True, nullable=False)          # trial | pro | ultra ...
    name = Column(String, nullable=False)
    price_month = Column(Integer, nullable=False, default=0)    # VNĐ/tháng
    max_concurrent = Column(Integer, nullable=False, default=1)  # "Tạo N video cùng lúc"
    max_devices = Column(Integer, nullable=False, default=1)     # "1 tài khoản / N máy"
    video_quota = Column(Integer, nullable=True)                 # NULL = không giới hạn
    quota_period = Column(String, nullable=False, default="total")  # total | day | month
    allow_4k = Column(Boolean, nullable=False, default=False)
    is_active = Column(Boolean, nullable=False, default=True)
    sort_order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class VeoSubscription(Base):
    __tablename__ = "veo_subscriptions"
    id = Column(String, primary_key=True, default=_id)
    team_id = Column(String, nullable=False, index=True)
    plan_id = Column(String, nullable=False)
    order_id = Column(String, nullable=True)
    status = Column(String, nullable=False, default="active")   # active | replaced
    started_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)                # NULL = không hết hạn
    created_at = Column(DateTime, default=datetime.utcnow)


class VeoOrder(Base):
    __tablename__ = "veo_orders"
    id = Column(String, primary_key=True, default=_id)
    order_code = Column(String, unique=True, nullable=False)    # AV3-XXXXXX
    team_id = Column(String, nullable=False, index=True)
    plan_id = Column(String, nullable=False)
    months = Column(Integer, nullable=False, default=1)
    amount = Column(Integer, nullable=False)
    payment_status = Column(String, nullable=False, default="pending")  # pending | paid | expired
    created_by_user_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    paid_at = Column(DateTime, nullable=True)


class VeoPaymentTxn(Base):
    """Nhật ký webhook SePay cho đơn Veo. UNIQUE (gateway, txn) chống kích hoạt trùng."""
    __tablename__ = "veo_payment_txns"
    id = Column(String, primary_key=True, default=_id)
    gateway = Column(String, nullable=False)
    gateway_txn_id = Column(String, nullable=False)
    order_code = Column(String, nullable=True)
    amount = Column(Integer, nullable=True)
    status = Column(String, nullable=False)   # matched_paid | matched_duplicate | matched_expired | ...
    raw = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("gateway", "gateway_txn_id", name="uq_veo_txn"),)


class VeoDevice(Base):
    __tablename__ = "veo_devices"
    id = Column(String, primary_key=True, default=_id)
    team_id = Column(String, nullable=False, index=True)
    user_id = Column(String, nullable=False)
    machine_hash = Column(String, nullable=False)
    name = Column(String, nullable=True)
    status = Column(String, nullable=False, default="active")   # active | revoked
    refresh_hash = Column(String, nullable=False, unique=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (Index("ix_veo_dev_team_machine", "team_id", "machine_hash"),)


class VeoDeviceCode(Base):
    """Đăng nhập thiết bị: app xin mã, người dùng duyệt trên web, app hỏi lại để nhận token."""
    __tablename__ = "veo_device_codes"
    id = Column(String, primary_key=True, default=_id)
    device_code = Column(String, unique=True, nullable=False)   # bí mật, chỉ app biết
    user_code = Column(String, unique=True, nullable=False)     # XXXX-XXXX, hiện trên web
    machine_hash = Column(String, nullable=False)
    device_name = Column(String, nullable=True)
    status = Column(String, nullable=False, default="pending")  # pending | approved | denied | used
    team_id = Column(String, nullable=True)
    user_id = Column(String, nullable=True)
    error = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
