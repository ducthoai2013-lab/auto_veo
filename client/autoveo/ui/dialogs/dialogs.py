"""Hộp thoại: đăng nhập thiết bị (Google qua trình duyệt), mua gói bằng QR, hỗ trợ."""
from __future__ import annotations

import os
import threading
import time

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication, QPixmap
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFrame, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QPushButton, QStackedWidget,
    QVBoxLayout, QWidget,
)

from ... import config
from ...api import AccountApi, ApiError, GatewayApi, Session
from ...i18n import tr
from ..async_util import run_async


class LoginDialog(QDialog):
    """Bấm 'Đăng nhập bằng Google' → mở trình duyệt → người dùng bấm 'Cho phép thiết bị này' → app nhận token."""
    _approved = Signal()
    _failed = Signal(str)

    def __init__(self, session: Session, parent=None):
        super().__init__(parent)
        self.session = session
        self.setWindowTitle(tr("login_title"))
        self.setMinimumWidth(460)
        v = QVBoxLayout(self)
        v.setSpacing(10)
        head = QLabel("<h2>Auto_veo3</h2>")
        self.intro = QLabel(tr("login_intro"))
        self.intro.setWordWrap(True)
        self.btn = QPushButton(tr("login_btn"))
        self.btn.setObjectName("startBtn")
        self.info = QLabel("")
        self.info.setWordWrap(True)
        self.code = QLabel("")
        self.code.setStyleSheet("font-size:22px;font-weight:700;letter-spacing:3px;")
        self.reopen = QPushButton(tr("login_open"))
        self.reopen.setObjectName("linkBtn")
        self.reopen.hide()
        for w in (head, self.intro, self.btn, self.code, self.info, self.reopen):
            v.addWidget(w)
        self._stop = threading.Event()
        self._url = ""
        self.btn.clicked.connect(self._start)
        self.reopen.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(self._url)))
        self._approved.connect(self.accept)
        self._failed.connect(self._show_error)

    def _show_error(self, msg: str) -> None:
        self.btn.setEnabled(True)
        self.info.setText(f"<span style='color:#DC2626'>{msg}</span>")

    def _start(self) -> None:
        self.btn.setEnabled(False)
        self.info.setText("Đang kết nối…")
        run_async(self.session.login_start, self._got_code, lambda e: self._show_error(getattr(e, "message", str(e))))

    def _got_code(self, d: dict) -> None:
        self._url = d["verification_url"]
        self.code.setText(tr("login_code", code=d["user_code"]))
        self.info.setText(tr("login_wait"))
        self.reopen.show()
        QDesktopServices.openUrl(QUrl(self._url))
        threading.Thread(target=self._poll, args=(d["device_code"], d.get("interval", 3), d.get("expires_in", 600)),
                         daemon=True).start()

    def _poll(self, device_code: str, interval: int, expires: int) -> None:
        end = time.time() + expires
        while not self._stop.is_set() and time.time() < end:
            time.sleep(interval)
            try:
                d = self.session.login_poll(device_code)
            except ApiError as e:
                if e.is_network:
                    continue
                self._failed.emit(e.message)
                return
            if d["status"] == "approved":
                self._approved.emit()
                return
            if d["status"] in ("denied", "expired"):
                self._failed.emit("Bạn đã từ chối hoặc mã đã hết hạn. Hãy thử lại.")
                return
        if not self._stop.is_set():
            self._failed.emit("Hết thời gian chờ. Hãy thử lại.")

    def done(self, r: int) -> None:
        self._stop.set()
        super().done(r)


CARD_QSS = """
QDialog { background: #F3F4F6; }
QLabel#buyTitle { font-size: 20px; font-weight: 800; color: #1F2937; }
QLabel#buyHint { color: #6B7280; }
QFrame#planCard { background: white; border: 1px solid #E5E7EB; border-radius: 12px; }
QLabel#planName { font-size: 20px; font-weight: 800; color: #111827; }
QLabel[pill="green"] { background: #E8FBF0; color: #166534; border: 1px solid #BBF7D0; border-radius: 14px; padding: 6px 10px; font-weight: 600; }
QLabel[pill="purple"] { background: #EEEBFF; color: #4338CA; border: 1px solid #DDD6FE; border-radius: 14px; padding: 6px 10px; font-weight: 600; }
QLabel[pill="orange"] { background: #FFF3D6; color: #B45309; border: 1px solid #FBBF24; border-radius: 14px; padding: 6px 10px; font-weight: 700; }
QLabel#planPrice { font-size: 24px; font-weight: 800; color: #111827; background: #F9FAFB; border-radius: 6px; padding: 8px; }
QLabel#planNote { color: #6B7280; }
QPushButton#pickBtn { background: #22C55E; color: white; border: none; border-radius: 6px; padding: 11px; font-weight: 700; font-size: 14px; }
QPushButton#pickBtn:hover { background: #16A34A; }
QPushButton#pickBtn:disabled { background: #A7E9BF; }
QLabel#payError { color: #DC2626; font-weight: 600; }
"""


def money(v: int) -> str:
    return f"{v:,.0f}" + " VNĐ"


def _pill(text: str, kind: str) -> QLabel:
    lab = QLabel(text)
    lab.setProperty("pill", kind)
    lab.setAlignment(Qt.AlignCenter)
    lab.setWordWrap(True)
    return lab


class PlanCard(QFrame):
    """Một thẻ gói (giống bảng chọn gói của Veo3 Go): tên, thời gian, hạn mức, số luồng, số máy, giá, nút chọn."""

    def __init__(self, plan: dict, parent=None):
        super().__init__(parent)
        self.plan = plan
        self.setObjectName("planCard")
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 16, 16, 16)
        v.setSpacing(8)
        name = QLabel(plan["name"])
        name.setObjectName("planName")
        name.setAlignment(Qt.AlignCenter)
        self.duration = _pill("", "green")
        quota = "Tạo video không giới hạn" if plan["video_quota"] is None else f"Hạn mức {plan['video_quota']} video"
        v.addWidget(name)
        v.addWidget(self.duration)
        v.addWidget(_pill(quota, "purple"))
        v.addWidget(_pill(f"⚡ Xử lý {plan['max_concurrent']} video cùng lúc", "orange"))
        v.addWidget(_pill(f"💻 Dùng trên {plan['max_devices']} máy" + (" · Có 4K" if plan["allow_4k"] else ""), "purple"))
        self.price = QLabel()
        self.price.setObjectName("planPrice")
        self.price.setAlignment(Qt.AlignCenter)
        self.note = QLabel()
        self.note.setObjectName("planNote")
        self.note.setAlignment(Qt.AlignCenter)
        self.note.setWordWrap(True)
        self.button = QPushButton("Chọn gói này")
        self.button.setObjectName("pickBtn")
        self.button.setCursor(Qt.PointingHandCursor)
        for w in (self.price, self.note, self.button):
            v.addWidget(w)
        self.set_months(1)

    def set_months(self, months: int) -> None:
        c = next((x for x in self.plan["cycles"] if x["months"] == months), self.plan["cycles"][0])
        self.duration.setText(f"Thời gian sử dụng: {30 * c['months']} ngày")
        self.price.setText(money(c["amount"]))
        per_day = c["amount"] / (30 * c["months"])
        off = f" · giảm {c['discount_percent']}%" if c["discount_percent"] else ""
        self.note.setText(f"≈ {money(per_day)} / ngày{off}")


class BuyDialog(QDialog):
    """Bước 1: chọn gói (thẻ giống Veo3 Go). Bước 2: QR VietQR + tự kiểm tra thanh toán → kích hoạt."""
    paid = Signal()

    def __init__(self, account: AccountApi, parent=None):
        super().__init__(parent)
        self.account = account
        self.plans: list[dict] = []
        self.cards: dict[str, PlanCard] = {}
        self.order: dict | None = None
        self.setWindowTitle("Mua gói cước - Auto_veo3")
        self.setMinimumWidth(640)
        self.setStyleSheet(CARD_QSS)
        root = QVBoxLayout(self)
        self.stack = QStackedWidget()
        root.addWidget(self.stack)

        # ---- trang 1: chọn gói ----
        page1 = QWidget()
        p1 = QVBoxLayout(page1)
        title = QLabel("Chọn gói cước phù hợp")
        title.setObjectName("buyTitle")
        title.setAlignment(Qt.AlignCenter)
        cyc = QHBoxLayout()
        cyc.addStretch(1)
        cyc.addWidget(QLabel("Thời hạn:"))
        self.cycle_box = QComboBox()
        self.cycle_box.setMinimumWidth(190)
        cyc.addWidget(self.cycle_box)
        cyc.addStretch(1)
        self.cards_row = QHBoxLayout()
        self.cards_row.setSpacing(14)
        self.msg = QLabel("Đang tải danh sách gói…")
        self.msg.setObjectName("buyHint")
        self.msg.setAlignment(Qt.AlignCenter)
        self.msg.setWordWrap(True)
        p1.addWidget(title)
        p1.addLayout(cyc)
        p1.addLayout(self.cards_row)
        p1.addWidget(self.msg)
        self.stack.addWidget(page1)

        # ---- trang 2: thanh toán ----
        page2 = QWidget()
        p2 = QVBoxLayout(page2)
        self.back = QPushButton("← Chọn gói khác")
        self.back.setObjectName("linkBtn")
        self.back.setCursor(Qt.PointingHandCursor)
        self.pay_title = QLabel("Quét mã QR để thanh toán")
        self.pay_title.setObjectName("buyTitle")
        self.pay_title.setAlignment(Qt.AlignCenter)
        self.qr = QLabel()
        self.qr.setAlignment(Qt.AlignCenter)
        self.info = QLabel("")
        self.info.setWordWrap(True)
        self.info.setAlignment(Qt.AlignCenter)
        self.info.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        self.copy = QPushButton("Sao chép nội dung chuyển khoản")
        self.copy.setObjectName("linkBtn")
        self.pay_status = QLabel("")
        self.pay_status.setAlignment(Qt.AlignCenter)
        for w in (self.back, self.pay_title, self.qr, self.info, self.copy, self.pay_status):
            p2.addWidget(w)
        self.stack.addWidget(page2)

        self.timer = QTimer(self)
        self.timer.setInterval(4000)
        self.timer.timeout.connect(self._check)
        self.cycle_box.currentIndexChanged.connect(self._cycle_changed)
        self.back.clicked.connect(self._back)
        self.copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.order["transfer_content"]))
        run_async(self.account.plans, self._plans_loaded,
                  lambda e: self.msg.setText(f"Không tải được danh sách gói: {getattr(e, 'message', e)}"))

    # ---- trang 1 ----
    def _plans_loaded(self, plans: list) -> None:
        self.plans = [p for p in plans if p["price_month"] > 0]
        if not self.plans:
            self.msg.setText("Hiện chưa có gói nào để mua.")
            return
        self.msg.setText("")
        self.cycle_box.blockSignals(True)
        for c in self.plans[0]["cycles"]:
            off = f" (giảm {c['discount_percent']}%)" if c["discount_percent"] else ""
            self.cycle_box.addItem(f"{c['months']} tháng{off}", c["months"])
        self.cycle_box.blockSignals(False)
        for p in self.plans:
            card = PlanCard(p)
            card.button.clicked.connect(lambda _=False, code=p["code"]: self._pick(code))
            self.cards[p["code"]] = card
            self.cards_row.addWidget(card)
        self.adjustSize()

    def _cycle_changed(self) -> None:
        months = self.cycle_box.currentData()
        for card in self.cards.values():
            card.set_months(months)

    def _pick(self, code: str) -> None:
        self.msg.setText("Đang tạo đơn hàng…")
        self.msg.setObjectName("buyHint")
        for c in self.cards.values():
            c.button.setEnabled(False)
        months = self.cycle_box.currentData() or 1
        run_async(lambda: self.account.create_order(code, months), self._order_created, self._order_error)

    def _order_error(self, e) -> None:
        for c in self.cards.values():
            c.button.setEnabled(True)
        self.msg.setText(f"<span style='color:#DC2626'>{getattr(e, 'message', e)}</span>")

    # ---- trang 2 ----
    def _order_created(self, o: dict) -> None:
        self.order = o
        self.msg.setText("")
        self.info.setText(f"Số tiền: <b>{money(o['amount'])}</b><br>Nội dung chuyển khoản: <b>{o['transfer_content']}</b><br>"
                          f"{o.get('bank_short_name', '')} {o.get('bank_account_no', '')} - {o.get('bank_account_name', '')}<br>"
                          f"<span style='color:#6B7280'>{tr('buy_scan')}</span>")
        self.pay_status.setText(f"<i>{tr('buy_waiting')}</i>")
        self.qr.clear()
        self.back.setEnabled(True)
        self.stack.setCurrentIndex(1)
        run_async(lambda: self.account.fetch_bytes(o["qr_url"]), self._qr_loaded, lambda e: self.qr.setText("Không tải được ảnh QR"))
        self.timer.start()

    def _qr_loaded(self, data: bytes) -> None:
        pm = QPixmap()
        pm.loadFromData(data)
        self.qr.setPixmap(pm.scaledToWidth(320, Qt.SmoothTransformation))
        self.adjustSize()

    def _back(self) -> None:
        self.timer.stop()
        for c in self.cards.values():
            c.button.setEnabled(True)
        self.stack.setCurrentIndex(0)
        self.adjustSize()

    def _check(self) -> None:
        if not self.order:
            return
        code = self.order["order_code"]
        run_async(lambda: self.account.get_order(code), self._checked, lambda e: None)

    def _checked(self, o: dict) -> None:
        if not self.order or o.get("order_code") != self.order["order_code"]:
            return
        if o["status"] == "paid":
            self.timer.stop()
            QMessageBox.information(self, "Mua gói cước", tr("buy_paid"))
            self.paid.emit()
            self.accept()
        elif o["status"] == "expired":
            self.timer.stop()
            self.pay_status.setText(f"<span style='color:#DC2626'>{tr('buy_expired')}</span>")

    def done(self, r: int) -> None:
        self.timer.stop()
        super().done(r)


class SupportDialog(QDialog):
    def __init__(self, session: Session, gateway: GatewayApi, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("support_title"))
        self.setMinimumSize(520, 360)
        v = QVBoxLayout(self)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        row = QHBoxLayout()
        b1, b2, b3 = QPushButton("Sao chép thông tin"), QPushButton("Mở thư mục log"), QPushButton("Trang tải về")
        b4 = QPushButton("Nhóm Zalo hỗ trợ")
        b4.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(config.ZALO_GROUP_URL)))
        for b in (b1, b2, b3, b4):
            row.addWidget(b)
        v.addWidget(self.text)
        v.addLayout(row)
        self.log_dir = config.data_dir() / "logs"
        base = (f"{config.APP_NAME} {config.VERSION}\nMáy: {config.device_name()} ({config.machine_hash()[:12]}…)\n"
                f"Máy chủ tài khoản: {session.account_url}\nMáy chủ tạo video: {gateway.base}\n"
                f"Đăng nhập: {'có' if session.signed_in else 'chưa'}\n")
        self.text.setPlainText(base + "Trạng thái Gateway: đang kiểm tra…")

        def show(h):
            self.text.setPlainText(base + f"Trạng thái Gateway: G-Labs {h.get('glabs')}, chờ {h.get('queued')}, chạy {h.get('running')}")
        run_async(gateway.health, show,
                  lambda e: self.text.setPlainText(base + f"Trạng thái Gateway: lỗi — {getattr(e, 'message', e)}"))
        b1.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.text.toPlainText()))
        b2.clicked.connect(lambda: os.startfile(self.log_dir) if os.name == "nt" else None)
        b3.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(config.DOWNLOAD_PAGE_URL)))
