"""Khung 'Thông tin tài khoản' (Email, Loại tài khoản, Ngày hết hạn, Đã sử dụng, Hạn mức video)."""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QProgressBar, QVBoxLayout, QWidget

from ..i18n import tr


def _fmt_date(iso: str | None) -> str:
    if not iso:
        return tr("acc_unlimited")
    try:
        return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").strftime("%Y-%m-%d")
    except ValueError:
        return iso


class AccountPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        self.title = QLabel(tr("acc_title"))
        self.title.setObjectName("accTitle")
        v.addWidget(self.title)
        box = QFrame()
        box.setObjectName("account")
        g = QGridLayout(box)
        g.setContentsMargins(14, 10, 14, 10)
        g.setHorizontalSpacing(12)
        self.keys = [QLabel(tr(k)) for k in ("acc_email", "acc_type", "acc_exp", "acc_used", "acc_quota")]
        for k in self.keys:
            k.setObjectName("accKey")
        self.email, self.type, self.exp, self.used = (QLabel("—") for _ in range(4))
        for lab in (self.email, self.type, self.exp, self.used):
            lab.setObjectName("accVal")
            lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.quota = QProgressBar()
        self.quota.setObjectName("quotaBar")
        self.quota.setRange(0, 100)
        self.quota.setValue(100)
        self.quota.setFormat("—")
        g.addWidget(self.keys[0], 0, 0)
        g.addWidget(self.email, 0, 1)
        g.addWidget(self.keys[1], 0, 2)
        g.addWidget(self.type, 0, 3)
        g.addWidget(self.keys[2], 1, 0)
        g.addWidget(self.exp, 1, 1)
        g.addWidget(self.keys[3], 1, 2)
        g.addWidget(self.used, 1, 3)
        g.addWidget(self.keys[4], 2, 0)
        g.addWidget(self.quota, 2, 1, 1, 3)
        g.setColumnStretch(1, 1)
        g.setColumnStretch(3, 1)
        v.addWidget(box)
        self.info: dict = {}

    def retranslate(self) -> None:
        self.title.setText(tr("acc_title"))
        for k, key in zip(self.keys, ("acc_email", "acc_type", "acc_exp", "acc_used", "acc_quota")):
            k.setText(tr(key))
        if self.info:
            self.show_info(self.info)

    def show_offline(self) -> None:
        self.quota.setFormat("—")

    def show_info(self, d: dict) -> None:
        """d là kết quả /v1/me của Gateway (hoặc phần tương đương từ /api/veo/me)."""
        self.info = d
        self.email.setText(d.get("email") or "—")
        self.type.setText(tr("acc_type_val", n=d.get("max_concurrent", 1)))
        exp = _fmt_date(d.get("expires_at"))
        self.exp.setText(exp + (" (đã hết hạn)" if d.get("expired") else ""))
        self.exp.setStyleSheet("color:#DC2626;font-weight:600;" if d.get("expired") else "")
        self.used.setText(str(d.get("used_total", "—")))
        quota = d.get("quota")
        if quota is None:
            self.quota.setRange(0, 100)
            self.quota.setValue(100)
            self.quota.setFormat(tr("acc_quota_free"))
        else:
            left = d.get("remaining", 0)
            self.quota.setRange(0, max(1, quota))
            self.quota.setValue(left)
            self.quota.setFormat(tr("acc_quota_left", left=left, quota=quota))
