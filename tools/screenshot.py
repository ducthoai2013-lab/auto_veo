"""Chup anh cua so chinh (offscreen) de so voi anh Veo3 Go:  python tools/screenshot.py out.png"""
import os, sys, tempfile
from pathlib import Path
os.environ["AUTOVEO_DATA"] = tempfile.mkdtemp()
os.environ["AUTOVEO_ACCOUNT_URL"] = "http://127.0.0.1:9"
os.environ["AUTOVEO_GATEWAY_URL"] = "http://127.0.0.1:9"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "client"))
from PySide6.QtWidgets import QApplication
from autoveo import config
from autoveo.api import Session
from autoveo.store import Store
from autoveo.ui.main_window import MainWindow
from autoveo.ui.theme import QSS

app = QApplication([])
app.setStyleSheet(QSS)
st = config.Settings()
win = MainWindow(st, Session(st), Store(config.data_dir() / "jobs.db"))
win.account_panel.show_info({"email": "vanderbergcantornbnzs1541@gmail.com", "max_concurrent": 3,
    "expires_at": "2026-06-22T00:00:00Z", "used_total": 35303, "quota": None})
win.show()
app.processEvents()
out = sys.argv[1] if len(sys.argv) > 1 else "screenshot.png"
win.grab().save(out)
print("saved", out, win.size().width(), win.size().height())
win.manager.stop()
