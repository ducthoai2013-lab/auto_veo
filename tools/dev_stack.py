"""Môi trường thử toàn tuyến trên máy dev (KHÔNG đụng repo thoai-dash thật, KHÔNG gọi G-Labs thật):

  - bản sao thoai-dash/backend + module Veo (SQLite trong RAM)  -> "máy chủ tài khoản"
  - Gateway chạy G-Labs giả lập                                   -> "máy chủ tạo video"

python tools/dev_stack.py   # chạy và in địa chỉ; dùng cho app: set AUTOVEO_ACCOUNT_URL/AUTOVEO_GATEWAY_URL
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
THOAI_BACKEND = Path(os.getenv("THOAI_BACKEND", r"D:\claude\app_b1\thoai-dash\backend"))
sys.path.insert(0, str(ROOT / "gateway"))
sys.path.insert(0, str(ROOT / "thoai-dash-module"))


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _Server(threading.Thread):
    def __init__(self, app, port: int):
        super().__init__(daemon=True)
        import uvicorn
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))

    def run(self) -> None:
        self.server.run()

    def wait_ready(self) -> None:
        for _ in range(100):
            if self.server.started:
                return
            time.sleep(0.1)
        raise RuntimeError("server không lên")

    def stop(self) -> None:
        self.server.should_exit = True


class Stack:
    def __init__(self, tmp: Path | None = None, mock_delay: float = 0.4):
        from apply_to_thoai_dash import apply
        from gateway.admin import make_keypair
        self.tmp = Path(tmp or tempfile.mkdtemp(prefix="autoveo_stack_"))
        backend = self.tmp / "backend"
        shutil.copytree(THOAI_BACKEND, backend, ignore=shutil.ignore_patterns("__pycache__", "scripts", "*.yaml"))
        apply(backend)
        priv, pub = make_keypair()
        os.environ.update({
            "VEO_JWT_PRIVATE_KEY": priv.replace("\n", "\\n"), "VEO_WEBHOOK_ENABLED": "true",
            "VEO_SEPAY_WEBHOOK_API_KEY": "dev-secret", "PAYMENT_BANK_BIN": "970422",
            "PAYMENT_BANK_ACCOUNT_NO": "0123456789", "PAYMENT_BANK_ACCOUNT_NAME": "NGUYEN VAN A",
            "PAYMENT_BANK_SHORT_NAME": "MB", "POSTGRES_HOST": "127.0.0.1", "POSTGRES_PORT": "1",
        })
        sys.path.insert(0, str(backend))
        from fastapi import FastAPI
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from app.api import veo
        from app.database import Base, get_db
        from app.models import models as m
        from app.services import veo_service as svc

        self.svc, self.m = svc, m
        eng = create_engine(f"sqlite:///{(self.tmp / 'account.db').as_posix()}", connect_args={"check_same_thread": False, "timeout": 30})
        Base.metadata.create_all(eng, tables=[m.Team.__table__, m.User.__table__, m.Plan.__table__,
                                              m.Subscription.__table__, m.Order.__table__,
                                              *[t for n, t in Base.metadata.tables.items() if n.startswith("veo_")]])
        self.Session = sessionmaker(bind=eng, autoflush=False)

        def override():
            s = self.Session()
            try:
                yield s
            finally:
                s.close()

        account = FastAPI()
        account.include_router(veo.router)
        account.dependency_overrides[get_db] = override
        s = self.Session()
        team = m.Team(name="Dev", slug="dev")
        s.add(team)
        s.flush()
        owner = m.User(team_id=team.id, email="nhanvien@congty.vn", role="owner")
        s.add(owner)
        s.commit()
        self.team_id, self.owner_id = team.id, owner.id
        s.close()

        from gateway.app import create_app
        from gateway.config import Settings as GwSettings
        gw_dir = self.tmp / "gw"
        gs = GwSettings(data_dir=gw_dir, glabs_url="", glabs_key="", mock=True, mock_delay=mock_delay,
                        max_inflight_video=4, max_inflight_image=4, video_timeout=30, image_timeout=30,
                        poll_seconds=0.2, public_url="", jwt_pubkey=pub, retention_days=7,
                        client_latest_version="1.0.0", client_download_url="",
                        downloads_dir=self.tmp / "dl")
        for d in (gs.results_dir, gs.payloads_dir, gs.downloads_dir):
            d.mkdir(parents=True, exist_ok=True)
        self.account_port, self.gateway_port = free_port(), free_port()
        self.account_url = f"http://127.0.0.1:{self.account_port}"
        self.gateway_url = f"http://127.0.0.1:{self.gateway_port}"
        self._servers = [_Server(account, self.account_port), _Server(create_app(gs), self.gateway_port)]
        for sv in self._servers:
            sv.start()
        for sv in self._servers:
            sv.wait_ready()

    # ---- thao tác mô phỏng người dùng/ngân hàng ----
    def new_user(self) -> tuple[str, str]:
        """Tạo một team + chủ team mới (mỗi test một team để hạn mức không dính nhau)."""
        s = self.Session()
        try:
            n = s.query(self.m.Team).count() + 1
            t = self.m.Team(name=f"T{n}", slug=f"t{n}")
            s.add(t)
            s.flush()
            u = self.m.User(team_id=t.id, email=f"user{n}@congty.vn", role="owner")
            s.add(u)
            s.commit()
            return u.id, t.id
        finally:
            s.close()

    def approve(self, user_code: str, user: tuple[str, str] | None = None) -> None:
        """Giả lập người dùng bấm 'Cho phép thiết bị này' trên web."""
        uid, tid = user or (self.owner_id, self.team_id)
        s = self.Session()
        try:
            self.svc.approve_device(s, user_code, uid, tid, True)
        finally:
            s.close()

    def pay(self, order: dict, txn: str = "TXN1") -> dict:
        """Giả lập SePay báo tiền về."""
        s = self.Session()
        try:
            body = json.dumps({"id": txn, "referenceCode": txn, "transferType": "in", "transferAmount": order["amount"],
                               "content": f"AUTOVEO3 {order['order_code']}"}).encode()
            return self.svc.handle_sepay(s, "Apikey dev-secret", body)
        finally:
            s.close()

    def stop(self) -> None:
        for sv in self._servers:
            sv.stop()
        for name in [n for n in sys.modules if n == "app" or n.startswith("app.")]:
            del sys.modules[name]
        if str(self.tmp / "backend") in sys.path:
            sys.path.remove(str(self.tmp / "backend"))


if __name__ == "__main__":
    st = Stack()
    print("ACCOUNT_URL", st.account_url)
    print("GATEWAY_URL", st.gateway_url)
    print("Chay app:  set AUTOVEO_ACCOUNT_URL=%s & set AUTOVEO_GATEWAY_URL=%s" % (st.account_url, st.gateway_url))
    print("Duyet thiet bi:  python -c \"...\" hoac dung stack.approve(user_code)  (Ctrl+C de dung)")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        st.stop()
