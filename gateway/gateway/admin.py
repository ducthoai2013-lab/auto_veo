"""Công cụ dòng lệnh: python -m gateway admin <lệnh>. Chủ yếu để phát triển/kiểm thử."""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .auth import AUDIENCE, ISSUER
from .config import load_settings
from .db import DB, iso


def make_keypair() -> tuple[str, str]:
    k = Ed25519PrivateKey.generate()
    priv = k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                           serialization.NoEncryption()).decode()
    pub = k.public_key().public_bytes(serialization.Encoding.PEM,
                                      serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    return priv, pub


def sign_token(priv_pem: str, *, team: str = "team1", email: str = "dev@example.com", device: str = "dev1",
               plan: str = "pro", plan_name: str = "Pro", cc: int = 3, k4: bool = False,
               q: int | None = None, qp: str = "total", sexp: str | None = None, ttl: int = 6 * 3600) -> str:
    claims = {"iss": ISSUER, "aud": AUDIENCE, "sub": team, "email": email, "dev": device, "plan": plan,
              "plan_name": plan_name, "cc": cc, "k4": k4, "q": q, "qp": qp, "sexp": sexp,
              "iat": int(time.time()), "exp": int(time.time()) + ttl}
    return jwt.encode(claims, priv_pem, algorithm="EdDSA")


def run(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="gateway admin")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("dev-keygen", help="Sinh khóa Ed25519 thử nghiệm vào thư mục dữ liệu")
    t = sub.add_parser("dev-token", help="Ký token thử nghiệm bằng khóa dev")
    t.add_argument("--team", default="team1"); t.add_argument("--email", default="dev@example.com")
    t.add_argument("--device", default="dev1"); t.add_argument("--cc", type=int, default=3)
    t.add_argument("--quota", type=int); t.add_argument("--k4", action="store_true")
    t.add_argument("--sexp", help="Hạn gói ISO, ví dụ 2027-01-01T00:00:00Z")
    sub.add_parser("jobs", help="Thống kê job theo trạng thái")
    a = p.parse_args(argv)
    s = load_settings()
    priv_f, pub_f = s.data_dir / "dev_private.pem", s.data_dir / "dev_public.pem"
    if a.cmd == "dev-keygen":
        priv, pub = make_keypair()
        priv_f.write_text(priv); pub_f.write_text(pub)
        print(f"Đã ghi {priv_f} và {pub_f}\nĐặt GW_JWT_PUBKEY_FILE={pub_f}")
    elif a.cmd == "dev-token":
        if not priv_f.is_file():
            print("Chưa có khóa dev: chạy dev-keygen trước"); return 1
        print(sign_token(priv_f.read_text(), team=a.team, email=a.email, device=a.device, cc=a.cc,
                         k4=a.k4, q=a.quota, sexp=a.sexp))
    elif a.cmd == "jobs":
        db = DB(s.db_path)
        for r in db.all("SELECT status, COUNT(*) c FROM jobs GROUP BY status"):
            print(f"{r['status']:<10} {r['c']}")
        db.close()
    return 0
