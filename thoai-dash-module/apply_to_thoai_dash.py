"""Áp module Auto_veo3 vào bản thoai-dash: chép file mới + thêm 2 dòng vào app/main.py (idempotent).

  python apply_to_thoai_dash.py D:\\claude\\app_b1\\thoai-dash\\backend          # áp dụng
  python apply_to_thoai_dash.py D:\\claude\\app_b1\\thoai-dash\\backend --check  # chỉ kiểm tra đã áp chưa

Chỉ THÊM file veo_*, các trang tĩnh frontend/public/veo3/ và sửa app/main.py (2 dòng). Không đụng payments.py/billing.py/admin.py/deps.py/config.py.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent / "backend"
WEB = Path(__file__).resolve().parent / "frontend" / "public" / "veo3"
WEB_FILES = ["index.html", "device.html", "devices.html", "latest.json"]
FILES = ["app/models/veo_models.py", "app/services/veo_service.py", "app/services/veo_reconcile.py", "app/api/veo.py"]
IMPORT_ANCHOR = "from app.api import study\n"
IMPORT_LINE = "from app.api import veo  # Auto_veo3 (d100radar.com/veo3)\n"
ROUTER_ANCHOR = "app.include_router(study.router)"
ROUTER_LINE = "app.include_router(veo.router)  # Auto_veo3: /api/veo/*\n"


def _same(a: Path, b: Path) -> bool:
    return b.is_file() and a.read_bytes() == b.read_bytes()


def apply(backend: Path, check_only: bool = False) -> bool:
    """Đồng bộ module vào backend: chép file mới/đã đổi, thêm 2 dòng vào main.py. Chạy lại được nhiều lần."""
    main = backend / "app" / "main.py"
    text = main.read_text(encoding="utf-8")
    web_dir = backend.parent / "frontend" / "public" / "veo3"     # chỉ áp nếu có thư mục frontend/public
    has_web = (backend.parent / "frontend" / "public").is_dir()
    files = [(HERE / f, backend / f) for f in FILES]
    if has_web:      # latest.json là dữ liệu phát hành: chỉ tạo nếu chưa có, không đè
        files += [(WEB / f, web_dir / f) for f in WEB_FILES if f != "latest.json" or not (web_dir / f).is_file()]
    stale = [dst for src, dst in files if not _same(src, dst)]
    main_ok = IMPORT_LINE in text and ROUTER_LINE in text
    if check_only or (not stale and main_ok):
        return not stale and main_ok
    for src, dst in files:
        if not _same(src, dst):
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
    if IMPORT_LINE not in text:
        if IMPORT_ANCHOR not in text:
            raise SystemExit("Không tìm thấy dòng 'from app.api import study' trong main.py — sửa tay.")
        text = text.replace(IMPORT_ANCHOR, IMPORT_ANCHOR + IMPORT_LINE, 1)
    if ROUTER_LINE not in text:
        lines = text.split("\n")
        idx = next((i for i, l in enumerate(lines) if l.startswith(ROUTER_ANCHOR)), None)
        if idx is None:
            raise SystemExit("Không tìm thấy 'app.include_router(study.router)' trong main.py — sửa tay.")
        lines.insert(idx + 1, ROUTER_LINE.rstrip("\n"))
        text = "\n".join(lines)
    main.write_text(text, encoding="utf-8")
    return True


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    ok = apply(Path(sys.argv[1]), "--check" in sys.argv)
    print("ĐÃ ÁP DỤNG" if ok else "CHƯA ÁP DỤNG")
    sys.exit(0 if ok else 1)
