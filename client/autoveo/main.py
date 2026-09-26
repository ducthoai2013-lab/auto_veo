"""Điểm vào của Auto_veo3."""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from . import config


def setup_logging() -> None:
    d = config.data_dir() / "logs"
    d.mkdir(exist_ok=True)
    h = RotatingFileHandler(d / "app.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[h])


def install_excepthook() -> None:
    """Lỗi không bắt được (kể cả trong slot Qt) phải vào log VÀ hiện cho người dùng, không được im lặng."""
    import traceback
    shown = {"n": 0}

    def hook(exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        logging.getLogger("autoveo").error("Lỗi không bắt được:\n%s", text)
        if shown["n"] < 3:                       # tối đa 3 hộp thoại, tránh dội liên tục
            shown["n"] += 1
            try:
                from PySide6.QtWidgets import QApplication, QMessageBox
                if QApplication.instance():
                    QMessageBox.critical(None, "Auto_veo3", f"Có lỗi xảy ra: {exc}\n\nChi tiết đã ghi vào file log "
                                                            f"(nút Hỗ trợ → Mở thư mục log).")
            except Exception:  # noqa: BLE001
                pass
    sys.excepthook = hook


def _play_probe(ffmpeg: str | None) -> str:
    import subprocess
    import tempfile
    import time
    from pathlib import Path
    try:
        from PySide6.QtCore import QUrl
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
        from PySide6.QtMultimediaWidgets import QVideoWidget
        from PySide6.QtWidgets import QApplication
        if not ffmpeg:
            return "LỖI: không có ffmpeg để tạo video thử"
        app = QApplication.instance() or QApplication([])
        clip = Path(tempfile.gettempdir()) / "autoveo_probe.mp4"
        subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=320x180:d=1:r=24",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip)], check=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        video = QVideoWidget()
        player = QMediaPlayer()
        player.setAudioOutput(QAudioOutput())
        player.setVideoOutput(video)
        errors: list[str] = []
        player.errorOccurred.connect(lambda _e, msg: errors.append(msg))
        player.setSource(QUrl.fromLocalFile(str(clip)))
        player.play()
        end = time.time() + 8
        while time.time() < end and not errors and player.position() < 300:
            app.processEvents()
            time.sleep(0.02)
        pos = player.position()
        player.stop()
        player.setSource(QUrl())
        for _ in range(20):                 # bộ phát nhả file hơi trễ
            app.processEvents()
            time.sleep(0.02)
        try:
            clip.unlink(missing_ok=True)
        except OSError:
            pass
        return f"OK (vị trí {pos} ms)" if pos >= 300 else f"LỖI: {errors[0] if errors else 'không chạy được'}"
    except Exception as e:  # noqa: BLE001
        return f"LỖI: {type(e).__name__}: {e}"


def selftest() -> int:
    """Kiểm tra gói cài: import đủ thư viện, có ffmpeg, đọc được tài nguyên. In kết quả, thoát 0 nếu ổn."""
    import httpx  # noqa: F401
    import PIL  # noqa: F401
    from PySide6 import QtCore  # noqa: F401
    from . import ffmpeg_tools
    ff = ffmpeg_tools.ffmpeg_path()
    logo = config.resource_path("logo.png")
    ok = bool(ff and logo.exists())
    tls = "bỏ qua"
    if "--net" in sys.argv:   # kiểm tra HTTPS/chứng chỉ trong bản đóng gói (chỉ lỗi SSL mới tính là hỏng)
        try:
            tls = f"OK (HTTP {httpx.get(config.DEFAULT_ACCOUNT_URL + '/health', timeout=10).status_code})"
        except httpx.ConnectError as e:
            tls = f"LỖI KẾT NỐI/SSL: {e}"
            ok = ok and "CERTIFICATE" not in str(e).upper() and "SSL" not in str(e).upper()
        except httpx.HTTPError as e:
            tls = f"mạng không tới được ({type(e).__name__})"
    play = "bỏ qua"
    if "--play" in sys.argv:   # phát thử một video H.264 bằng bộ phát nhúng trong ô xem nhanh
        play = _play_probe(ff)
        ok = ok and play.startswith("OK")
    lines = [f"{config.APP_NAME} {config.VERSION}", f"https: {tls}", f"play: {play}", f"ffmpeg: {ff or 'KHÔNG THẤY'}",
             f"logo: {logo if logo.exists() else 'KHÔNG THẤY'}", f"data: {config.data_dir()}",
             f"machine: {config.machine_hash()[:12]}…", "KẾT QUẢ: " + ("OK" if ok else "LỖI")]
    text = "\n".join(lines)
    print(text)
    try:   # bản đóng gói chạy không có cửa sổ console nên ghi thêm ra file
        (config.data_dir() / "selftest.txt").write_text(text, encoding="utf-8")
    except OSError:
        pass
    return 0 if ok else 1


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if "--selftest" in sys.argv:
        return selftest()
    setup_logging()
    install_excepthook()
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from .api import Session
    from .store import Store
    from .ui.dialogs.dialogs import LoginDialog
    from .ui.main_window import MainWindow
    from .ui.theme import QSS

    app = QApplication(sys.argv)
    app.setApplicationName(config.APP_NAME)
    app.setStyleSheet(QSS)
    ico = config.resource_path("app.ico")
    if ico.exists():
        app.setWindowIcon(QIcon(str(ico)))
    settings = config.Settings()
    session = Session(settings)
    if not session.signed_in and not LoginDialog(session).exec():
        return 0
    store = Store(config.data_dir() / "jobs.db")
    win = MainWindow(settings, session, store)
    win.show()
    code = app.exec()
    store.close()
    return code


if __name__ == "__main__":
    sys.exit(main())
