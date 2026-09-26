"""Cửa sổ chính: bố cục hai cột giống Veo3 Go."""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox,
    QPushButton, QSizePolicy, QTabWidget, QToolButton, QVBoxLayout, QWidget,
)

from .. import config, ffmpeg_tools, i18n
from ..api import AccountApi, ApiError, GatewayApi, Session, check_update
from ..i18n import tr
from ..jobs import JobManager
from ..store import Store, files_of
from .account_panel import AccountPanel
from .async_util import run_async
from .dialogs.dialogs import BuyDialog, LoginDialog, SupportDialog
from .result_panel import ResultPanel
from .tabs.tabs import CharactersTab, ImageToVideoTab, StartEndTab, TextToVideoTab
from .widgets.common import flag_icon

RESOLUTIONS = ["720p", "1080p", "4K"]


def _card(title: str) -> tuple[QFrame, QVBoxLayout, QLabel]:
    f = QFrame()
    f.setObjectName("card")
    v = QVBoxLayout(f)
    v.setContentsMargins(12, 8, 12, 10)
    t = QLabel(title)
    t.setObjectName("cardTitle")
    v.addWidget(t)
    return f, v, t


class MainWindow(QMainWindow):
    signed_out = Signal()

    def __init__(self, settings: config.Settings, session: Session, store: Store):
        super().__init__()
        self.settings, self.session, self.store = settings, session, store
        self.account = AccountApi(session)
        self.gateway = GatewayApi(session)
        self.manager = JobManager(self.gateway, store, self)
        self.info: dict = {}
        self.max_devices = 1
        i18n.set_lang(settings["lang"])
        logo = config.resource_path("app.ico")
        if logo.exists():
            self.setWindowIcon(QIcon(str(logo)))
        self.resize(1310, 770)
        self._build()
        self._wire()
        self.retranslate()
        self._load_history()
        session.on_signed_out = self.signed_out.emit
        self.manager.start()
        self.refresh_account()
        run_async(lambda: check_update(session), self._update_found)

    # ---------------------------------------------------------------- dựng giao diện
    def _build(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        h = QHBoxLayout(root)
        h.setContentsMargins(10, 8, 10, 6)
        h.setSpacing(10)

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        self.tab_text, self.tab_image = TextToVideoTab(), ImageToVideoTab()
        self.tab_se, self.tab_chars = StartEndTab(), CharactersTab()
        for t in (self.tab_text, self.tab_image, self.tab_se, self.tab_chars):
            self.tabs.addTab(t, "")
        lv.addWidget(self.tabs, 1)

        row = QHBoxLayout()
        self.start_btn = QPushButton()
        self.start_btn.setObjectName("startBtn")
        self.start_btn.setCursor(Qt.PointingHandCursor)
        self.start_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.res_btn = QToolButton()
        self.res_btn.setObjectName("chip")
        self.res_btn.setPopupMode(QToolButton.InstantPopup)
        self.res_menu = QMenu(self)
        self.res_btn.setMenu(self.res_menu)
        self.lang_btn = QToolButton()
        self.lang_btn.setObjectName("chip")
        self.lang_btn.setIcon(flag_icon())
        self.lang_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.lang_btn.setPopupMode(QToolButton.InstantPopup)
        lm = QMenu(self)
        lm.addAction("VI - Tiếng Việt", lambda: self._set_lang("vi"))
        lm.addAction("EN - English", lambda: self._set_lang("en"))
        self.lang_btn.setMenu(lm)
        self.buy_btn = QPushButton()
        self.buy_btn.setObjectName("buyBtn")
        self.buy_btn.setCursor(Qt.PointingHandCursor)
        self.buy_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        row.addWidget(self.start_btn, 5)
        row.addWidget(self.res_btn)
        row.addWidget(self.lang_btn)
        row.addWidget(self.buy_btn, 4)
        lv.addLayout(row)

        row2 = QHBoxLayout()
        f1, v1, self.ratio_title = _card("")
        self.ratio = QComboBox()
        self.ratio.setMinimumWidth(190)
        v1.addWidget(self.ratio)
        f2, v2, self.dir_title = _card("")
        dir_row = QHBoxLayout()
        self.dir_edit = QLineEdit(self.settings["out_dir"])
        self.dir_edit.setReadOnly(True)
        self.dir_pick = QPushButton("📁")
        self.dir_pick.setFixedWidth(36)
        dir_row.addWidget(self.dir_edit)
        dir_row.addWidget(self.dir_pick)
        v2.addLayout(dir_row)
        row2.addWidget(f1, 2)
        row2.addWidget(f2, 5)
        lv.addLayout(row2)

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        self.results = ResultPanel()
        self.account_panel = AccountPanel()
        rv.addWidget(self.results, 1)
        rv.addWidget(self.account_panel)

        h.addWidget(left, 52)
        h.addWidget(right, 48)

        self.status_label = QLabel()
        self.status_label.setObjectName("statusMsg")
        self.statusBar().addWidget(self.status_label, 1)
        self.update_label = QLabel()
        self.update_label.setOpenExternalLinks(True)
        self.statusBar().addPermanentWidget(self.update_label)

    def _wire(self) -> None:
        self.start_btn.clicked.connect(self.on_start)
        self.buy_btn.clicked.connect(self.open_buy)
        self.dir_pick.clicked.connect(self._pick_dir)
        self.ratio.currentIndexChanged.connect(self._ratio_changed)
        self.results.merge.connect(self.on_merge)
        self.results.retry.connect(self.on_retry)
        self.results.retry_failed.connect(self.on_retry_failed)
        self.results.edit_retry.connect(self.manager.edit_and_retry)
        self.results.last_frame.connect(self.on_last_frame)
        self.results.clear.connect(self.on_clear)
        self.results.zalo.connect(lambda: QDesktopServices.openUrl(QUrl(config.ZALO_GROUP_URL)))
        self.results.support.connect(lambda: SupportDialog(self.session, self.gateway, self).exec())
        self.manager.changed.connect(self._job_changed)
        self.manager.online.connect(self._online_changed)
        self.manager.notice.connect(self._notice)
        self.manager.usage_dirty.connect(self.refresh_account)
        self.signed_out.connect(self._relogin)

    # ---------------------------------------------------------------- ngôn ngữ
    def retranslate(self) -> None:
        self.setWindowTitle(tr("title", ver=config.VERSION, n=self.max_devices))
        for i, key in enumerate(("tab_text", "tab_image", "tab_startend", "tab_chars")):
            icon = ("📝 ", "🖼 ", "🎬 ", "🍀 ")[i]
            self.tabs.setTabText(i, icon + tr(key))
        self.start_btn.setText("🚀  " + tr("btn_start"))
        self.buy_btn.setText("💳  " + tr("btn_buy"))
        self.lang_btn.setText(" " + i18n.lang().upper())
        self.ratio_title.setText(tr("ratio"))
        self.dir_title.setText(tr("outdir"))
        cur = self.settings["ratio"]
        self.ratio.blockSignals(True)
        self.ratio.clear()
        self.ratio.addItem(tr("ratio_land"), "16:9")
        self.ratio.addItem(tr("ratio_port"), "9:16")
        self.ratio.setCurrentIndex(0 if cur == "16:9" else 1)
        self.ratio.blockSignals(False)
        self._build_res_menu()
        self.tab_text.retranslate()
        self.results.retranslate()
        self.account_panel.retranslate()
        self.status_label.setText(tr("ready"))

    def _set_lang(self, lang: str) -> None:
        self.settings.set("lang", lang)
        i18n.set_lang(lang)
        self.retranslate()

    def _build_res_menu(self) -> None:
        self.res_menu.clear()
        allow_4k = bool(self.info.get("allow_4k", False))
        for r in RESOLUTIONS:
            a = self.res_menu.addAction(r, lambda r=r: self._set_res(r))
            if r == "4K" and not allow_4k:
                a.setEnabled(False)
                a.setText("4K (cần gói Ultra)")
        cur = self.settings["resolution"]
        if cur == "4K" and not allow_4k:
            cur = "1080p"
            self.settings.set("resolution", cur)
        self.res_btn.setText(f"✔ {cur}")

    def _set_res(self, r: str) -> None:
        self.settings.set("resolution", r)
        self._build_res_menu()

    def _ratio_changed(self) -> None:
        r = self.ratio.currentData()
        self.settings.set("ratio", r)
        for t in (self.tab_image, self.tab_se):
            t.set_ratio(r)

    def _pick_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, tr("outdir"), self.settings["out_dir"])
        if d:
            self.settings.set("out_dir", d)
            self.dir_edit.setText(d)

    # ---------------------------------------------------------------- tài khoản
    def refresh_account(self) -> None:
        def work():
            try:
                return self.gateway.me()
            except ApiError as e:
                if not e.is_network:
                    raise
                d = self.account.me()        # Gateway tắt: vẫn hiện gói/hạn từ máy chủ tài khoản
                p = d["plan"]
                return {"email": d["email"], "max_concurrent": p["max_concurrent"], "allow_4k": p["allow_4k"],
                        "expires_at": d["expires_at"], "expired": d["expired"], "used_total": "—",
                        "quota": p["video_quota"], "remaining": p["video_quota"], "max_devices": p["max_devices"]}
        run_async(work, self._account_loaded, self._account_error)

    def _account_loaded(self, d: dict) -> None:
        self.info = d
        self.max_devices = d.get("max_devices", self.max_devices)
        self.account_panel.show_info(d)
        self._build_res_menu()
        self.setWindowTitle(tr("title", ver=config.VERSION, n=self.max_devices))

    def _account_error(self, e) -> None:
        if isinstance(e, ApiError) and e.code in ("device_revoked", "not_signed_in"):
            return   # _relogin sẽ xử lý
        self.account_panel.show_offline()

    def open_buy(self) -> None:
        dlg = BuyDialog(self.account, self)
        dlg.paid.connect(self._after_paid)
        dlg.exec()

    def _after_paid(self) -> None:
        """Token cũ còn mang gói cũ (tới 6 giờ): làm mới ngay để gói mới có hiệu lực tức thì."""
        run_async(lambda: self.session.token(force=True), lambda _: self.refresh_account(),
                  lambda _: self.refresh_account())

    def _relogin(self) -> None:
        QMessageBox.warning(self, "Auto_veo3", "Phiên đăng nhập không còn hiệu lực (thiết bị đã bị gỡ hoặc hết hạn). "
                                               "Hãy đăng nhập lại.")
        if LoginDialog(self.session, self).exec():
            self.refresh_account()

    def _update_found(self, info) -> None:
        if info:
            self.update_label.setText(f"<a href='{info['url']}'>Có bản mới {info['version']} — bấm để tải</a>")

    # ---------------------------------------------------------------- job
    def _load_history(self) -> None:
        for row in self.store.all()[-300:]:
            self.results.upsert(row)

    def _job_changed(self, jid: str) -> None:
        row = self.store.get(jid)
        if row:
            self.results.upsert(row)

    def _online_changed(self, ok: bool) -> None:
        self.status_label.setText(tr("ready") if ok else tr("offline"))
        self.status_label.setStyleSheet("" if ok else "color:#B91C1C;font-weight:600;")

    def _notice(self, code: str, msg: str) -> None:
        if code in ("device_revoked", "not_signed_in"):
            self._relogin()
            return
        if code in ("expired", "quota_exceeded"):
            run_async(lambda: self.session.token(force=True))   # có thể vừa mua/gia hạn bằng cách khác
            r = QMessageBox.question(self, "Auto_veo3", msg + "\n\nMua gói ngay bây giờ?")
            if r == QMessageBox.Yes:
                self.open_buy()
        else:
            QMessageBox.warning(self, "Auto_veo3", msg)

    def _current_tab(self):
        return self.tabs.currentWidget()

    def on_start(self) -> None:
        if not self.session.signed_in:
            if not LoginDialog(self.session, self).exec():
                return
            self.refresh_account()
        res = self.settings["resolution"]
        built = self._current_tab().build(self.settings["ratio"], [res])
        if built.errors:
            QMessageBox.warning(self, "Auto_veo3", "\n".join(built.errors))
            return
        out = self.settings["out_dir"]
        try:
            Path(out).mkdir(parents=True, exist_ok=True)
            probe = Path(out) / ".write_test"
            probe.write_text("x")
            probe.unlink()
        except OSError:
            QMessageBox.warning(self, "Auto_veo3", f"Không ghi được vào thư mục lưu:\n{out}\nHãy chọn thư mục khác.")
            return
        msg = f"Sẽ tạo {len(built.specs)} video ({self.settings['ratio']}, {res})."
        if built.warnings:
            box = QMessageBox(self)
            box.setWindowTitle("Auto_veo3")
            box.setIcon(QMessageBox.Warning)
            box.setText(msg + "\n\nLưu ý:\n• " + "\n• ".join(built.warnings[:8]) + "\n\nTiếp tục?")
            box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            if box.exec() != QMessageBox.Yes:
                return
        self.manager.submit(built.specs, out)
        self.status_label.setText(f"Đã gửi {len(built.specs)} video vào hàng đợi")

    def _rows(self, ids: list[str]) -> list:
        return [r for r in (self.store.get(i) for i in ids) if r]

    def on_retry(self) -> None:
        ids = self.results.selected_ids()
        if not ids:
            QMessageBox.information(self, "Auto_veo3", "Hãy tick chọn các video cần tạo lại.")
            return
        self.manager.retry(ids)

    def on_retry_failed(self) -> None:
        ids = [r["id"] for r in self.store.all("WHERE status='failed'")]
        if not ids:
            QMessageBox.information(self, "Auto_veo3", "Không có video lỗi nào.")
            return
        self.manager.retry(ids)

    def _completed_videos(self, ids: list[str]) -> list:
        rows = [r for r in self._rows(ids) if r["status"] == "completed" and files_of(r)
                and files_of(r)[0].lower().endswith((".mp4", ".mov", ".webm"))]
        return sorted(rows, key=lambda r: (r["batch_id"] or "", r["line_no"] or 0))

    def on_merge(self) -> None:
        ids = self.results.selected_ids() or self.results.ordered_ids()
        rows = self._completed_videos(ids)
        if len(rows) < 2:
            QMessageBox.information(self, "Auto_veo3", "Cần ít nhất 2 video đã hoàn thành (tick chọn để nối theo thứ tự dòng).")
            return
        files = [Path(files_of(r)[0]) for r in rows]
        out = Path(self.settings["out_dir"]) / f"merged_{datetime.now():%Y%m%d_%H%M%S}.mp4"
        self.status_label.setText("Đang nối video…")

        def done(_):
            self.status_label.setText(tr("ready"))
            r = QMessageBox.question(self, "Auto_veo3", f"Đã nối {len(files)} video:\n{out}\n\nMở thư mục?")
            if r == QMessageBox.Yes:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(out.parent)))

        def fail(e):
            self.status_label.setText(tr("ready"))
            QMessageBox.warning(self, "Auto_veo3", f"Không nối được: {e}")
        run_async(lambda: ffmpeg_tools.concat(files, out), done, fail)

    def on_last_frame(self) -> None:
        ids = self.results.selected_ids() or self.results.ordered_ids()
        rows = self._completed_videos(ids)
        if not rows:
            QMessageBox.information(self, "Auto_veo3", "Hãy tick chọn video đã hoàn thành cần cắt ảnh cuối.")
            return
        outs: list[str] = []

        def work():
            for r in rows:
                v = Path(files_of(r)[0])
                o = v.with_name(v.stem + "_last.jpg")
                ffmpeg_tools.last_frame(v, o)
                outs.append(str(o))
            return outs

        def done(paths):
            r = QMessageBox.question(self, "Auto_veo3", f"Đã cắt {len(paths)} ảnh cuối (cạnh file video).\n\n"
                                                        "Dùng làm ảnh bắt đầu ở tab Image to Video?")
            if r == QMessageBox.Yes:
                self.tab_image.images.set_paths(self.tab_image.images.paths() + paths)
                self.tabs.setCurrentWidget(self.tab_image)
        run_async(work, done, lambda e: QMessageBox.warning(self, "Auto_veo3", f"Không cắt được: {e}"))

    def on_clear(self) -> None:
        ids = self.results.ordered_ids()
        if not ids:
            return
        if QMessageBox.question(self, "Auto_veo3", "Xóa toàn bộ danh sách kết quả?") != QMessageBox.Yes:
            return
        rm = QMessageBox.question(self, "Auto_veo3", "Xóa luôn các file video/ảnh đã tải trên máy?\n"
                                                     "(Chọn 'No' để giữ file, chỉ xóa danh sách)",
                                  QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes
        self.manager.remove(ids, delete_files=rm)
        self.results.remove(ids)

    def closeEvent(self, e) -> None:
        self.manager.stop()
        super().closeEvent(e)
