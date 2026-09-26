"""Widget dùng chung: danh sách ảnh (bấm để thay), hàng nhân vật, biểu tượng cờ."""
from __future__ import annotations

from pathlib import Path

from PIL.ImageQt import ImageQt
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap, QPolygonF
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListView, QListWidget, QListWidgetItem, QMenu,
    QPushButton, QWidget,
)

from ... import imaging
from ...i18n import tr

IMG_FILTER = "Ảnh (*.jpg *.jpeg *.png *.webp *.bmp)"
THUMB = 88


def pixmap_of(path: str, size: int = THUMB, ratio: str | None = None) -> QPixmap:
    try:
        return QPixmap.fromImage(ImageQt(imaging.thumbnail(path, size, ratio)))
    except Exception:  # noqa: BLE001 - ảnh hỏng: hiện ô trống
        pm = QPixmap(size, size)
        pm.fill(QColor("#D1D5DB"))
        return pm


def flag_icon(w: int = 22, h: int = 15) -> QIcon:
    """Cờ Việt Nam vẽ bằng code (emoji cờ không hiện trên Windows)."""
    pm = QPixmap(w, h)
    pm.fill(QColor("#DA251D"))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor("#FFDD00"))
    p.setPen(Qt.NoPen)
    cx, cy, r = w / 2, h / 2 + 0.5, h * 0.36
    import math
    pts = []
    for i in range(10):
        ang = -math.pi / 2 + i * math.pi / 5
        rad = r if i % 2 == 0 else r * 0.4
        pts.append(QPointF(cx + rad * math.cos(ang), cy + rad * math.sin(ang)))
    p.drawPolygon(QPolygonF(pts))
    p.end()
    return QIcon(pm)


class ImageList(QListWidget):
    """Lưới ảnh có đánh số; bấm vào ảnh để chọn ảnh thay thế; chuột phải để xóa; kéo thả file vào được."""
    paths_changed = Signal()

    def __init__(self, ratio: str = "16:9", parent=None):
        super().__init__(parent)
        self._ratio = ratio
        self._paths: list[str] = []
        self.setViewMode(QListView.IconMode)
        self.setIconSize(QSize(THUMB, THUMB))
        self.setResizeMode(QListView.Adjust)
        self.setMovement(QListView.Static)
        self.setWordWrap(True)
        self.setSpacing(6)
        self.setAcceptDrops(True)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.itemClicked.connect(self._replace)
        self.setMinimumHeight(THUMB + 46)

    def set_ratio(self, ratio: str) -> None:
        self._ratio = ratio
        self._render()

    def paths(self) -> list[str]:
        return list(self._paths)

    def set_paths(self, paths: list[str], sort: bool = True) -> None:
        self._paths = imaging.sort_paths(paths) if sort else list(paths)
        self._render()
        self.paths_changed.emit()

    def pick_many(self, title: str = "Chọn ảnh") -> None:
        files, _ = QFileDialog.getOpenFileNames(self, title, "", IMG_FILTER)
        if files:
            self.set_paths(files)

    def _render(self) -> None:
        self.clear()
        for i, p in enumerate(self._paths):
            it = QListWidgetItem(QIcon(pixmap_of(p, THUMB, self._ratio)), f"{i + 1}. {Path(p).name}")
            it.setSizeHint(QSize(THUMB + 24, THUMB + 42))
            it.setToolTip(p)
            self.addItem(it)

    def _replace(self, item: QListWidgetItem) -> None:
        idx = self.row(item)
        f, _ = QFileDialog.getOpenFileName(self, "Chọn ảnh thay thế", "", IMG_FILTER)
        if f and 0 <= idx < len(self._paths):
            self._paths[idx] = f
            self._render()
            self.paths_changed.emit()

    def _menu(self, pos) -> None:
        it = self.itemAt(pos)
        if not it:
            return
        m = QMenu(self)
        act = m.addAction("Xóa ảnh này")
        if m.exec(self.mapToGlobal(pos)) == act:
            del self._paths[self.row(it)]
            self._render()
            self.paths_changed.emit()

    def dragEnterEvent(self, e) -> None:
        e.acceptProposedAction() if e.mimeData().hasUrls() else e.ignore()

    def dragMoveEvent(self, e) -> None:
        e.acceptProposedAction()

    def dropEvent(self, e) -> None:
        files = [u.toLocalFile() for u in e.mimeData().urls()
                 if u.toLocalFile().lower().endswith(imaging.IMAGE_EXTS)]
        if files:
            self.set_paths(self._paths + files)


class CharacterRow(QWidget):
    """Thẻ nhân vật kiểu Veo3 Go: ảnh 220×124 có nút × ở góc, ô đặt tên ngay bên dưới."""
    removed = Signal(object)
    W, H = 220, 124

    def __init__(self, path: str, name: str = "", parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QVBoxLayout
        self.path = path
        self.setFixedWidth(self.W)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 6)
        lay.setSpacing(4)
        box = QWidget()
        box.setFixedSize(self.W, self.H)
        self.thumb = QLabel(box)
        self.thumb.setGeometry(0, 0, self.W, self.H)
        self.thumb.setAlignment(Qt.AlignCenter)
        self.thumb.setStyleSheet("background:#E5E7EB;border-radius:6px;")
        pm = pixmap_of(path, 440).scaled(self.W, self.H, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        self.thumb.setPixmap(pm.copy((pm.width() - self.W) // 2, (pm.height() - self.H) // 2, self.W, self.H))
        self.x = QPushButton("×", box)
        self.x.setGeometry(self.W - 24, 6, 18, 18)
        self.x.setCursor(Qt.PointingHandCursor)
        self.x.setToolTip("Bỏ nhân vật này")
        self.x.setStyleSheet("QPushButton{background:rgba(15,23,42,190);color:white;border:none;border-radius:9px;"
                             "font-weight:700;padding:0;}QPushButton:hover{background:#DC2626;}")
        self.x.clicked.connect(lambda: self.removed.emit(self))
        self.name = QLineEdit(name)
        self.name.setPlaceholderText("Đặt tên nhân vật cho ảnh này...")
        self.name.setToolTip(f"{Path(path).name} — tên này dùng trong prompt (hoặc @tên) để giữ đúng nhân vật.")
        lay.addWidget(box)
        lay.addWidget(self.name)

    def character_name(self) -> str:
        return " ".join(self.name.text().split())
