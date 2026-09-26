"""Xác thực token truy cập do thoai-dash ký (EdDSA/Ed25519). Gateway chỉ giữ khóa công khai.

Claims: iss=autoveo3, aud=gateway, sub=team_id, email, dev=device_id, plan, plan_name,
cc=số video chạy đồng thời, k4=cho 4K, q=hạn mức (None=không giới hạn), qp=chu kỳ (total|day|month),
sexp=hạn gói (ISO UTC hoặc None), exp=hạn token (~6 giờ)."""
from __future__ import annotations

from dataclasses import dataclass

import jwt
from fastapi import HTTPException, Request

from .db import DB, iso, now

ISSUER = "autoveo3"
AUDIENCE = "gateway"


def api_error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status, {"code": code, "message": message})


@dataclass
class Principal:
    team_id: str
    email: str
    device_id: str
    plan: str
    plan_name: str
    max_concurrent: int
    allow_4k: bool
    quota: int | None
    quota_period: str
    sub_expires: str | None

    @property
    def expired(self) -> bool:
        return bool(self.sub_expires) and self.sub_expires < iso(now())


def verify_token(pubkey: str, token: str) -> Principal:
    if not pubkey:
        raise api_error(503, "no_pubkey", "Gateway chưa cấu hình khóa công khai (GW_JWT_PUBKEY)")
    try:
        c = jwt.decode(token, pubkey, algorithms=["EdDSA"], audience=AUDIENCE, issuer=ISSUER,
                       options={"require": ["exp", "sub", "dev"]})
    except jwt.ExpiredSignatureError:
        raise api_error(401, "token_expired", "Token hết hạn, app sẽ tự làm mới")
    except jwt.PyJWTError:
        raise api_error(401, "bad_token", "Token không hợp lệ")
    return Principal(
        team_id=str(c["sub"]), email=str(c.get("email", "")), device_id=str(c["dev"]),
        plan=str(c.get("plan", "")), plan_name=str(c.get("plan_name", c.get("plan", ""))),
        max_concurrent=max(1, int(c.get("cc", 1))), allow_4k=bool(c.get("k4", False)),
        quota=c.get("q"), quota_period=str(c.get("qp", "total")), sub_expires=c.get("sexp"))


def authenticate(request: Request, db: DB, pubkey: str) -> Principal:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise api_error(401, "no_token", "Thiếu token")
    p = verify_token(pubkey, auth[7:].strip())
    db.run("INSERT INTO teams(team_id,email,plan,max_concurrent,last_seen) VALUES (?,?,?,?,?) "
           "ON CONFLICT(team_id) DO UPDATE SET email=excluded.email, plan=excluded.plan, "
           "max_concurrent=excluded.max_concurrent, last_seen=excluded.last_seen",
           (p.team_id, p.email, p.plan, p.max_concurrent, iso()))
    return p
