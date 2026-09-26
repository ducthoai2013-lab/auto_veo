"""Khung bên phải: thanh 6 nút, hướng dẫn (khi trống), danh sách thẻ kết quả."""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QPainter, QPixmap, QPolygonF
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from .. import config
from ..i18n import tr
from ..jobs import MODE_LABEL
from ..store import files_of

STATUS_TEXT = {
    "sending": "Đang gửi lên máy chủ…", "queued": "Đang chờ trong hàng đợi", "running": "Đang tạo…",
    "downloading": "Đang tải về máy…", "completed": "Hoàn thành", "failed": "Lỗi", "cancelled": "Đã hủy",
}


def _tb(name: str, text: str) -> QPushButton:
    b = QPushButton(text)
    b.setObjectName(name)
    b.setProperty("tb", "true")
    b.setCursor(Qt.PointingHandCursor)
    return b


def pencil_icon() -> QIcon:
    """Bút chì màu (thân vàng, tẩy đỏ, đầu chì hướng xuống-trái) tự vẽ bằng nét vector, không cần file ảnh."""
    px = QPixmap(96, 96)
    px.fill(Qt.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing)
    p.translate(48, 48)
    p.rotate(45)                         # đầu chì (đáy) xoay về góc dưới-trái, tẩy ở góc trên-phải
    p.scale(2.0, 2.0)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#EF4444"))        # tẩy
    p.drawRoundedRect(QRectF(-5.5, -23, 11, 10), 3.5, 3.5)
    p.setBrush(QColor("#E5E7EB"))        # vòng kim loại
    p.drawRect(QRectF(-5.5, -14, 11, 4))
    p.setBrush(QColor("#FACC15"))        # thân
    p.drawRect(QRectF(-5.5, -10, 11, 21))
    p.setBrush(QColor("#EAB308"))        # mặt khuất của thân
    p.drawRect(QRectF(0.5, -10, 5, 21))
    p.setBrush(QColor("#FDBA8C"))        # phần gỗ vót nhọn
    p.drawPolygon(QPolygonF([QPointF(-5.5, 11), QPointF(5.5, 11), QPointF(0, 23.5)]))
    p.setBrush(QColor("#F59E6B"))
    p.drawPolygon(QPolygonF([QPointF(0.5, 11), QPointF(5.5, 11), QPointF(0.5, 22)]))
    p.setBrush(QColor("#1F2937"))        # ruột chì
    p.drawPolygon(QPolygonF([QPointF(-2, 19), QPointF(2, 19), QPointF(0, 23.5)]))
    p.end()
    return QIcon(px)


VIDEO_EXT = (".mp4", ".mov", ".webm", ".mkv")
_playing: "ThumbView | None" = None      # chỉ một ô phát tại một thời điểm


class ThumbView(QWidget):
    """Ảnh đại diện 112×64. Video đã xong: có nút ▶ ở giữa; bấm vào thì phát NGAY TRONG Ô NÀY (bấm lại để tạm dừng /
    tiếp tục), phát hết thì trở về ảnh đại diện. Nút '▶ Mở' bên phải vẫn mở bằng trình phát của máy."""
    W, H = 112, 64

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(self.W, self.H)
        self.image = QLabel(self)
        self.image.setGeometry(0, 0, self.W, self.H)
        self.image.setAlignment(Qt.AlignCenter)
        self.image.setStyleSheet("background:#E5E7EB;border-radius:4px;")
        self.badge = QLabel("▶", self)
        self.badge.setGeometry((self.W - 30) // 2, (self.H - 30) // 2, 30, 30)
        self.badge.setAlignment(Qt.AlignCenter)
        self.badge.setStyleSheet("background:rgba(15,23,42,165);color:white;border-radius:15px;"
                                 "font-size:13px;padding-left:2px;")
        self.badge.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.badge.hide()
        self.video = None            # QVideoWidget, dựng lúc bấm lần đầu để app mở nhanh
        self.player = None
        self.path: str | None = None
        self.playable = False

    # --- ảnh + trạng thái
    def set_pixmap(self, pm) -> None:
        self.image.setPixmap(pm)

    def clear(self) -> None:
        self.image.clear()

    def set_video(self, path: str | None) -> None:
        if path != self.path:
            self.stop()
        self.path = path
        self.playable = bool(path) and path.lower().endswith(VIDEO_EXT) and Path(path).is_file()
        self.setCursor(Qt.PointingHandCursor if self.playable else Qt.ArrowCursor)
        self.setToolTip("Bấm để xem nhanh" if self.playable else "")
        if not self.playable:
            self.stop()
        self.badge.setVisible(self.playable and not self._is_playing())

    def _is_playing(self) -> bool:
        return bool(self.video and self.video.isVisible())

    # --- phát
    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.LeftButton and self.playable:
            self.toggle()
        else:
            super().mousePressEvent(e)

    def toggle(self) -> None:
        global _playing
        try:
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
            from PySide6.QtMultimediaWidgets import QVideoWidget
        except Exception:  # noqa: BLE001 - thiếu thành phần đa phương tiện: mở bằng trình phát của máy
            self._open_external()
            return
        if self.player is None:
            self.video = QVideoWidget(self)
            self.video.setGeometry(0, 0, self.W, self.H)
            self.video.setStyleSheet("background:black;")
            self.audio = QAudioOutput(self)
            self.player = QMediaPlayer(self)
            self.player.setAudioOutput(self.audio)
            self.player.setVideoOutput(self.video)
            self.player.mediaStatusChanged.connect(self._status)
            self.player.errorOccurred.connect(lambda *_: self._failed())
        State = QMediaPlayer.PlaybackState
        if self.video.isVisible() and self.player.playbackState() == State.PlayingState:
            self.player.pause()
            self.badge.show()
            self.badge.raise_()
            return
        if _playing is not None and _playing is not self:
            _playing.stop()
        _playing = self
        if not self.video.isVisible() or self.player.source().isEmpty():
            self.player.setSource(QUrl.fromLocalFile(self.path))
        self.video.show()
        self.badge.hide()
        self.player.play()

    def _status(self, status) -> None:
        from PySide6.QtMultimedia import QMediaPlayer
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.stop()

    def _failed(self) -> None:
        self.stop()
        self._open_external()

    def stop(self) -> None:
        """Về lại ảnh đại diện và nhả file (để có thể ghi đè/xóa khi tạo lại video)."""
        global _playing
        if _playing is self:
            _playing = None
        if self.player is not None:
            self.player.stop()
            self.player.setSource(QUrl())
        if self.video is not None:
            self.video.hide()
        self.badge.setVisible(self.playable)

    def _open_external(self) -> None:
        if self.path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.path))


class JobCard(QFrame):
    edit_retry = Signal(str, str)      # (id dòng, prompt mới): sửa lệnh rồi tạo lại đúng dòng này

    def __init__(self, row, parent=None):
        super().__init__(parent)
        self.setObjectName("jobCard")
        self.job_id = row["id"]
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        self.check = QCheckBox()
        self.thumb = ThumbView()
        col = QVBoxLayout()
        self.title = QLabel()
        self.title.setStyleSheet("font-weight:700;")
        self.prompt = QLabel()
        self.prompt.setObjectName("jobPrompt")
        self.prompt.setWordWrap(True)
        self.status = QLabel()
        self.status.setObjectName("jobStatus")
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        self.pen = QPushButton()
        self.pen.setIcon(pencil_icon())
        self.pen.setIconSize(QSize(20, 20))
        self.pen.setFixedSize(28, 26)
        self.pen.setCursor(Qt.PointingHandCursor)
        self.pen.setToolTip("Sửa lệnh (prompt) rồi tạo lại video này")
        self.pen.setStyleSheet("QPushButton{border:none;background:transparent;}"
                               "QPushButton:hover{background:#FEF3C7;border-radius:5px;}")
        status_row = QHBoxLayout()
        status_row.setSpacing(4)
        status_row.addWidget(self.status)
        status_row.addWidget(self.pen)
        status_row.addStretch(1)
        self.editor = QPlainTextEdit()                 # ô sửa lệnh ngay trong thẻ
        self.editor.setFixedHeight(76)
        self.editor.hide()
        self.edit_bar = QWidget()
        eb = QHBoxLayout(self.edit_bar)
        eb.setContentsMargins(0, 0, 0, 0)
        self.ok_btn = QPushButton("⟳ Tạo lại với lệnh này")
        self.cancel_btn = QPushButton("Hủy")
        self.ok_btn.setStyleSheet("QPushButton{background:#6366F1;color:white;border:none;border-radius:6px;"
                                  "padding:4px 12px;font-weight:600;}QPushButton:hover{background:#4F46E5;}")
        self.cancel_btn.setStyleSheet("QPushButton{background:#F3F4F6;border:none;border-radius:6px;padding:4px 12px;}"
                                      "QPushButton:hover{background:#E5E7EB;}")
        for b in (self.ok_btn, self.cancel_btn):
            b.setCursor(Qt.PointingHandCursor)
            eb.addWidget(b)
        eb.addStretch(1)
        self.edit_bar.hide()
        col.addWidget(self.title)
        col.addWidget(self.prompt)
        col.addWidget(self.editor)
        col.addWidget(self.edit_bar)
        col.addLayout(status_row)
        col.addWidget(self.bar)
        btns = QVBoxLayout()
        self.open_btn = QPushButton("▶ Mở")
        self.dir_btn = QPushButton("📂 Thư mục")
        for b in (self.open_btn, self.dir_btn):
            b.setObjectName("linkBtn")
            b.setCursor(Qt.PointingHandCursor)
            btns.addWidget(b)
        btns.addStretch(1)
        lay.addWidget(self.check)
        lay.addWidget(self.thumb)
        lay.addLayout(col, 1)
        lay.addLayout(btns)
        self.open_btn.clicked.connect(self._open)
        self.dir_btn.clicked.connect(self._open_dir)
        self.pen.clicked.connect(self.begin_edit)
        self.ok_btn.clicked.connect(self._submit_edit)
        self.cancel_btn.clicked.connect(self.end_edit)
        self.editor.installEventFilter(self)
        self._prompt_text = row["prompt"] or ""
        self.files: list[str] = []
        self.update_row(row)

    def update_row(self, row) -> None:
        st = row["status"]
        self.setProperty("state", st)
        self.style().unpolish(self)
        self.style().polish(self)
        self.title.setText(f"#{(row['line_no'] or 0):03d} · {MODE_LABEL.get(row['mode'], row['mode'])}")
        self._prompt_text = row["prompt"] or ""
        fm = self.prompt.fontMetrics()
        self.prompt.setText(fm.elidedText(row["prompt"] or "", Qt.ElideRight, 520))
        self.prompt.setToolTip(row["prompt"] or "")
        text = STATUS_TEXT.get(st, st)
        if st == "queued" and row["queue_pos"]:
            text += f" (số {row['queue_pos']})"
        if st == "failed" and row["error"]:
            text = f"Lỗi: {row['error']}"
        self.status.setText(text)
        self.status.setStyleSheet({"failed": "color:#DC2626;", "completed": "color:#15803D;"}.get(st, ""))
        self.bar.setVisible(st in ("running", "downloading", "queued", "sending"))
        self.bar.setRange(0, 0 if st in ("sending", "downloading") else 100)
        self.bar.setValue(int(row["progress"] or 0))
        self.files = files_of(row)
        self.open_btn.setVisible(st == "completed" and bool(self.files))
        self.dir_btn.setVisible(st == "completed" and bool(self.files))
        if row["thumb"] and Path(row["thumb"]).is_file():
            pm = QPixmap(row["thumb"])
            self.thumb.set_pixmap(pm.scaled(self.thumb.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.thumb.clear()                       # dòng được tạo lại: bỏ ảnh của kết quả cũ
        self.thumb.set_video(self.files[0] if st == "completed" and self.files else None)
        idle = st in ("completed", "failed", "cancelled")
        if not idle:
            self._close_editor()                 # dòng đang gửi/chạy: không sửa được nữa
        self.pen.setVisible(idle and self.editor.isHidden())

    def begin_edit(self) -> None:
        self.editor.setPlainText(self._prompt_text)
        self.prompt.hide()
        self.pen.hide()
        self.editor.show()
        self.edit_bar.show()
        self.editor.setFocus()
        cur = self.editor.textCursor()
        cur.movePosition(cur.MoveOperation.End)
        self.editor.setTextCursor(cur)

    def _close_editor(self) -> None:
        self.editor.hide()
        self.edit_bar.hide()
        self.prompt.show()

    def end_edit(self) -> None:
        self._close_editor()
        self.pen.show()

    def _submit_edit(self) -> None:
        text = self.editor.toPlainText().strip()
        if not text:
            self.editor.setFocus()
            return
        self._close_editor()
        self.edit_retry.emit(self.job_id, text)     # thẻ chuyển sang 'Đang gửi' khi quản lý job cập nhật dòng

    def eventFilter(self, obj, ev):
        if obj is self.editor and ev.type() == QEvent.KeyPress:
            if ev.key() == Qt.Key_Escape:
                self.end_edit()
                return True
            if ev.key() in (Qt.Key_Return, Qt.Key_Enter) and ev.modifiers() & Qt.ControlModifier:
                self._submit_edit()
                return True
        return super().eventFilter(obj, ev)

    def _open(self) -> None:
        if self.files:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.files[0]))

    def _open_dir(self) -> None:
        if self.files:
            d = str(Path(self.files[0]).parent)
            os.startfile(d) if os.name == "nt" else QDesktopServices.openUrl(QUrl.fromLocalFile(d))


class GuideCard(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("guide")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(14, 12, 14, 12)
        self.lay.setSpacing(4)
        self.retranslate()

    def retranslate(self) -> None:
        while self.lay.count():
            w = self.lay.takeAt(0).widget()
            if w:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        t = QLabel("📘 " + tr("guide_title"))
        t.setObjectName("guideTitle")
        self.lay.addWidget(t)
        for key in ("g1", "g2", "g3"):
            self.lay.addSpacing(6)
            h = QLabel(tr(key + "_title"))
            h.setObjectName("guideHead")
            self.lay.addWidget(h)
            for line in tr(key):
                row = QLabel(line)
                row.setObjectName("guideRow")
                row.setWordWrap(True)
                self.lay.addWidget(row)


class ResultPanel(QWidget):
    merge = Signal()
    retry = Signal()
    retry_failed = Signal()
    edit_retry = Signal(str, str)
    last_frame = Signal()
    clear = Signal()
    support = Signal()
    zalo = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        self.b_merge = _tb("tbMerge", "🔗 " + tr("tb_merge"))
        self.b_retry = _tb("tbRetry", "⟳ " + tr("tb_retry"))
        self.b_retry_err = _tb("tbRetryErr", "✳ " + tr("tb_retry_err"))
        self.b_last = _tb("tbLast", tr("tb_lastframe"))
        self.b_clear = _tb("tbClear", tr("tb_clear"))
        self.b_help = _tb("tbHelp", " " + tr("tb_help"))       # biểu tượng Zalo + "Hỗ trợ": bấm là vào nhóm Zalo
        self.b_help.setIcon(QIcon(str(config.resource_path("zalo.png"))))
        self.b_help.setIconSize(QSize(20, 20))
        self.b_help.setToolTip(tr("tb_zalo_tip"))
        self.b_help.setContextMenuPolicy(Qt.CustomContextMenu)  # chuột phải: thông tin chẩn đoán/log gửi cho hỗ trợ
        self.b_help.customContextMenuRequested.connect(lambda _p: self._help_menu())
        for b in (self.b_merge, self.b_retry, self.b_retry_err, self.b_last, self.b_clear, self.b_help):
            bar.addWidget(b)
        bar.addStretch(1)
        v.addLayout(bar)

        self.frame = QFrame()
        self.frame.setObjectName("results")
        fv = QVBoxLayout(self.frame)
        fv.setContentsMargins(8, 8, 8, 8)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        self.list_lay = QVBoxLayout(inner)
        self.list_lay.setContentsMargins(4, 4, 4, 4)
        self.guide = GuideCard()
        self.empty = QLabel(tr("empty"))
        self.empty.setObjectName("emptyMsg")
        self.empty.setAlignment(Qt.AlignCenter)
        self.list_lay.addWidget(self.guide)
        self.list_lay.addWidget(self.empty)
        self.list_lay.addStretch(1)
        self.scroll.setWidget(inner)
        fv.addWidget(self.scroll)
        v.addWidget(self.frame, 1)

        self.cards: dict[str, JobCard] = {}
        self.b_merge.clicked.connect(self.merge)
        self.b_retry.clicked.connect(self.retry)
        self.b_retry_err.clicked.connect(self.retry_failed)
        self.b_last.clicked.connect(self.last_frame)
        self.b_clear.clicked.connect(self.clear)
        self.b_help.clicked.connect(self.zalo)

    def _help_menu(self) -> None:
        from PySide6.QtGui import QCursor
        from PySide6.QtWidgets import QMenu
        m = QMenu(self)
        m.addAction("Vào nhóm Zalo hỗ trợ", self.zalo.emit)
        m.addAction("Thông tin chẩn đoán / log…", self.support.emit)
        m.exec(QCursor.pos())

    def retranslate(self) -> None:
        self.b_merge.setText("🔗 " + tr("tb_merge"))
        self.b_retry.setText("⟳ " + tr("tb_retry"))
        self.b_retry_err.setText("✳ " + tr("tb_retry_err"))
        self.b_last.setText(tr("tb_lastframe"))
        self.b_clear.setText(tr("tb_clear"))
        self.b_help.setText(" " + tr("tb_help"))
        self.b_help.setToolTip(tr("tb_zalo_tip"))
        self.empty.setText(tr("empty"))
        self.guide.retranslate()

    def upsert(self, row) -> None:
        card = self.cards.get(row["id"])
        if card:
            card.update_row(row)
        else:
            card = JobCard(row)
            card.edit_retry.connect(self.edit_retry)
            self.cards[row["id"]] = card
            self.list_lay.insertWidget(self.list_lay.count() - 1, card)
        self._toggle_guide()

    def remove(self, ids: list[str]) -> None:
        for i in ids:
            c = self.cards.pop(i, None)
            if c:
                c.setParent(None)
                c.deleteLater()
        self._toggle_guide()

    def _toggle_guide(self) -> None:
        has = bool(self.cards)
        self.guide.setVisible(not has)
        self.empty.setVisible(not has)

    def selected_ids(self) -> list[str]:
        return [i for i, c in self.cards.items() if c.check.isChecked()]

    def ordered_ids(self) -> list[str]:
        return list(self.cards)
