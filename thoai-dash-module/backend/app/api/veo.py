"""
Auto_veo3 — router /api/veo/* (2026-09-19). Cắm thêm vào thoai-dash, KHÔNG sửa luồng D100:
tài khoản dùng chung đăng nhập Google (User/Team), còn gói/đơn/thiết bị nằm ở bảng veo_* riêng.

Ba nhóm route:
- Công khai: plans, device/start, device/poll, token/refresh, webhook/sepay.
- Người dùng web (JWT D100 như mọi trang khác): device/info|approve|deny, devices (danh sách/gỡ).
- App desktop (token thiết bị Ed25519): me, orders (tạo/xem).
- Super admin: admin/plans (tạo/sửa gói), admin/orders/{code}/mark-paid (xác nhận tay khi webhook lỡ).
"""
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_role
from app.database import get_db
from app.models.models import User
from app.models.veo_models import VeoDevice, VeoOrder, VeoPlan
from app.services import veo_service as svc

router = APIRouter(prefix="/api/veo", tags=["veo"])


# ---- bảng veo_* tự tạo khi import router (giống cơ chế create_all của D100) ----
def _ensure_tables() -> None:
    from app.database import Base, engine
    from app.models import veo_models  # noqa: F401  (đăng ký bảng vào Base)
    Base.metadata.create_all(bind=engine, tables=[
        t for name, t in Base.metadata.tables.items() if name.startswith("veo_")])


try:
    _ensure_tables()
except Exception:  # noqa: BLE001 - không để lỗi DB lúc import làm sập cả app D100; create_all chính vẫn chạy
    pass

try:  # đối soát tự động giao dịch AV3- (bật bằng VEO_RECONCILE_SECONDS>0; mặc định tắt)
    from app.services import veo_reconcile
    veo_reconcile.start_background()
except Exception:  # noqa: BLE001 - lỗi ở đây không được làm sập app D100
    pass


def _err(e: svc.VeoError) -> HTTPException:
    return HTTPException(e.status, {"code": e.code, "message": e.message})


def _email_of(db: Session):
    def f(user_id: str) -> str:
        u = db.query(User).filter_by(id=user_id).first()
        return u.email if u else ""
    return f


def device_dep(authorization: str = Header(default=None), db: Session = Depends(get_db)) -> VeoDevice:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, {"code": "no_token", "message": "Thiếu token"})
    try:
        return svc.device_from_access(db, authorization.split(" ", 1)[1].strip())
    except svc.VeoError as e:
        raise _err(e)


# ------------------------------------------------------------------ công khai
@router.get("/plans")
def plans(db: Session = Depends(get_db)):
    svc.ensure_plans(db)
    return [svc.plan_view(p) for p in
            db.query(VeoPlan).filter_by(is_active=True).order_by(VeoPlan.sort_order, VeoPlan.price_month)]


@router.get("/public-key")
def public_key():
    """Khóa công khai để đưa vào Gateway (GW_JWT_PUBKEY). Không phải bí mật."""
    try:
        return {"algorithm": "EdDSA", "pem": svc.public_pem()}
    except svc.VeoError as e:
        raise _err(e)


class DeviceStartIn(BaseModel):
    machine_hash: str
    device_name: str = ""


@router.post("/device/start")
def device_start(body: DeviceStartIn, db: Session = Depends(get_db)):
    try:
        return svc.start_device_login(db, body.machine_hash, body.device_name)
    except svc.VeoError as e:
        raise _err(e)


class PollIn(BaseModel):
    device_code: str


@router.post("/device/poll")
def device_poll(body: PollIn, db: Session = Depends(get_db)):
    try:
        return svc.poll_device_login(db, body.device_code, _email_of(db))
    except svc.VeoError as e:
        raise _err(e)


class RefreshIn(BaseModel):
    refresh_token: str
    machine_hash: str


@router.post("/token/refresh")
def token_refresh(body: RefreshIn, db: Session = Depends(get_db)):
    try:
        return svc.refresh_access(db, body.refresh_token, body.machine_hash, _email_of(db))
    except svc.VeoError as e:
        raise _err(e)


@router.post("/webhook/sepay")
async def webhook_sepay(request: Request, db: Session = Depends(get_db)):
    """Webhook SePay RIÊNG cho đơn AV3-… Trả 200 cho mọi giao dịch không thuộc Veo để SePay không
    retry. Đặt trong SePay một webhook thứ hai trỏ tới đường dẫn này (hoặc xem README nếu SePay chỉ
    cho một webhook)."""
    try:
        return svc.handle_sepay(db, request.headers.get("authorization", ""), await request.body())
    except svc.VeoError as e:
        raise _err(e)


# ------------------------------------------------------------------ người dùng web
class CodeIn(BaseModel):
    user_code: str


@router.get("/device/info")
def device_info(user_code: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        return svc.device_code_info(db, user_code)
    except svc.VeoError as e:
        raise _err(e)


@router.post("/device/approve")
def device_approve(body: CodeIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        return svc.approve_device(db, body.user_code, user.id, user.team_id, True)
    except svc.VeoError as e:
        raise _err(e)


@router.post("/device/deny")
def device_deny(body: CodeIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        return svc.approve_device(db, body.user_code, user.id, user.team_id, False)
    except svc.VeoError as e:
        raise _err(e)


def _device_view(d: VeoDevice) -> dict:
    return {"id": d.id, "name": d.name, "status": d.status,
            "created_at": d.created_at.isoformat() if d.created_at else None,
            "last_seen": d.last_seen.isoformat() if d.last_seen else None}


@router.get("/devices")
def devices(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(VeoDevice).filter_by(team_id=user.team_id).order_by(VeoDevice.created_at.desc()).all()
    plan, sexp = svc.current_entitlement(db, user.team_id)
    return {"plan": svc.plan_view(plan), "expires_at": sexp.isoformat() if sexp else None,
            "devices": [_device_view(d) for d in rows]}


@router.delete("/devices/{device_id}")
def device_remove(device_id: str, db: Session = Depends(get_db),
                  user: User = Depends(require_role("owner", "admin"))):
    d = db.query(VeoDevice).filter_by(id=device_id, team_id=user.team_id).first()
    if not d:
        raise HTTPException(404, {"code": "no_device", "message": "Không có thiết bị này"})
    d.status = "revoked"
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ app desktop
@router.get("/me")
def me(db: Session = Depends(get_db), dev: VeoDevice = Depends(device_dep)):
    plan, sexp = svc.current_entitlement(db, dev.team_id)
    return {"email": _email_of(db)(dev.user_id), "plan": svc.plan_view(plan),
            "expires_at": sexp.strftime("%Y-%m-%dT%H:%M:%SZ") if sexp else None,
            "expired": bool(sexp and sexp < datetime.utcnow()),
            "device_id": dev.id}


class OrderIn(BaseModel):
    plan_code: str
    months: int = 1


@router.post("/orders")
def order_create(body: OrderIn, db: Session = Depends(get_db), dev: VeoDevice = Depends(device_dep)):
    try:
        return svc.create_order(db, dev.team_id, dev.user_id, body.plan_code, body.months)
    except svc.VeoError as e:
        raise _err(e)


@router.get("/orders/{code}")
def order_get(code: str, db: Session = Depends(get_db), dev: VeoDevice = Depends(device_dep)):
    try:
        return svc.get_order(db, dev.team_id, code)
    except svc.VeoError as e:
        raise _err(e)


# ------------------------------------------------------------------ super admin
def _super(user: User = Depends(get_current_user)) -> User:
    if not user.is_super_admin:
        raise HTTPException(403, {"code": "forbidden", "message": "Chỉ super admin"})
    return user


class PlanIn(BaseModel):
    name: str
    price_month: int
    max_concurrent: int = 1
    max_devices: int = 1
    video_quota: int | None = None
    quota_period: str = "total"
    allow_4k: bool = False
    is_active: bool = True
    sort_order: int = 0


@router.put("/admin/plans/{code}")
def admin_plan_put(code: str, body: PlanIn, db: Session = Depends(get_db), user: User = Depends(_super)):
    if body.quota_period not in ("total", "day", "month"):
        raise HTTPException(400, {"code": "bad_period", "message": "quota_period: total|day|month"})
    p = db.query(VeoPlan).filter_by(code=code).first()
    if not p:
        p = VeoPlan(code=code, name=body.name)
        db.add(p)
    for k, v in body.model_dump().items():
        setattr(p, k, v)
    db.commit()
    return svc.plan_view(p)


@router.post("/admin/orders/{code}/mark-paid")
def admin_mark_paid(code: str, db: Session = Depends(get_db), user: User = Depends(_super)):
    return {"activated": svc.mark_paid(db, code.upper())}


@router.get("/admin/orders")
def admin_orders(db: Session = Depends(get_db), user: User = Depends(_super)):
    rows = db.query(VeoOrder).order_by(VeoOrder.created_at.desc()).limit(100).all()
    return [{"order_code": o.order_code, "team_id": o.team_id, "months": o.months, "amount": o.amount,
             "status": o.payment_status, "created_at": o.created_at.isoformat()} for o in rows]
