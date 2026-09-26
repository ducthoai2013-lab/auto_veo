"""Mọi file mã nguồn phải biên dịch được và app phải import được (bắt lỗi cú pháp trước khi đóng gói)."""
import compileall
import importlib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_all_sources_compile():
    for sub in ("client", "gateway", "thoai-dash-module", "tools", "tests"):
        assert compileall.compile_dir(str(ROOT / sub), quiet=1, force=True,
                                      rx=__import__("re").compile(r"(\.venv|vendor|__pycache__)")), sub


def test_client_entry_importable():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    sys.path.insert(0, str(ROOT / "client"))
    m = importlib.import_module("autoveo.main")
    assert callable(m.main) and callable(m.selftest)
