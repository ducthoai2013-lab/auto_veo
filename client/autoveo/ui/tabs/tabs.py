"""4 tab tạo video: Text to Video, Image to Video, Start-End, Đồng bộ nhân vật.

Mỗi tab có build(ratio, resolution) -> BuildResult(specs, warnings, errors). Việc kiểm tra số lượng,
gán prompt theo dòng, dò tên nhân vật đều nằm ở đây (thuần logic, có test không cần giao diện)."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QScrollArea, QVBoxLayout,
    QWidget,
)

from ... import imaging
from ...i18n import tr
from ...jobs import JobSpec
from ...voices import VOICES
from ..widgets.common import IMG_FILTER, CharacterRow, ImageList

MAX_CHARACTERS = 10
MAX_REFS_PER_CLIP = 3        # Veo nhận tối đa 3 ảnh tham chiếu/clip (Omni Flash 7)
MIN_NAME_LEN = 5             # G-Labs khớp @tag theo chuỗi con: tên ngắn dễ trùng


@dataclass
class BuildResult:
    specs: list[JobSpec] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def split_prompts(text: str) -> list[str]:
    """Mỗi dòng không rỗng là một prompt; số thứ tự dòng tính trên các dòng không rỗng."""
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def pair_by_line(prompts: list[str], images: list[str], label: str = "ảnh") -> tuple[int, list[str]]:
    """Ghép prompt dòng i với ảnh i. Trả về (số cặp, cảnh báo về phần dư)."""
    n = min(len(prompts), len(images))
    warns = []
    if len(images) > len(prompts):
        warns.append(f"Có {len(images)} {label} nhưng chỉ có {len(prompts)} prompt: {len(images) - n} {label} cuối sẽ bị bỏ qua.")
    elif len(prompts) > len(images):
        warns.append(f"Có {len(prompts)} prompt nhưng chỉ có {len(images)} {label}: {len(prompts) - n} prompt cuối sẽ bị bỏ qua.")
    return n, warns


def name_slug(name: str) -> str:
    """Tên gắn @tag gửi sang G-Labs: chữ không dấu, khoảng trắng thành '_' (ví dụ 'Bé Na' -> 'Be_Na')."""
    t = unicodedata.normalize("NFKD", name.replace("đ", "d").replace("Đ", "D")).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9_]+", "_", t).strip("_")


def _name_regex(name: str) -> re.Pattern:
    """Khớp CHÍNH XÁC tên nhân vật (không phân biệt hoa thường; dấu cách và '_' coi như nhau), có thể kèm @ phía trước,
    và không nằm giữa một từ dài hơn ('Lan' không khớp trong 'Lanh')."""
    parts = [re.escape(x) for x in re.split(r"[\s_]+", unicodedata.normalize("NFC", name).strip()) if x]
    return re.compile(r"(?<!\w)@?" + r"[\s_]+".join(parts) + r"(?!\w)", re.IGNORECASE)


def find_characters(prompt: str, names: list[str]) -> list[str]:
    """Các tên nhân vật xuất hiện trong prompt (khớp chính xác tên, có hoặc không có @), theo thứ tự xuất hiện."""
    text = unicodedata.normalize("NFC", prompt)
    hits = []
    for n in names:
        m = _name_regex(n).search(text) if n and name_slug(n) else None
        if m:
            hits.append((m.start(), n))
    return [n for _, n in sorted(hits)]


def tag_characters(prompt: str, names: list[str]) -> str:
    """Đổi mỗi lần nhắc tên nhân vật thành @tên (đã có @ thì chuẩn hóa lại) để G-Labs gắn đúng ảnh."""
    out = unicodedata.normalize("NFC", prompt)
    for n in sorted(names, key=len, reverse=True):
        if n and name_slug(n):
            out = _name_regex(n).sub("@" + name_slug(n), out)
    return out


class BaseTab(QWidget):
    def build(self, ratio: str, resolution: list[str]) -> BuildResult:  # pragma: no cover - giao diện con ghi đè
        raise NotImplementedError

    def set_ratio(self, ratio: str) -> None:
        pass

    def retranslate(self) -> None:
        pass


def _prompt_edit(placeholder: str) -> QPlainTextEdit:
    e = QPlainTextEdit()
    e.setPlaceholderText(placeholder)
    return e


class TextToVideoTab(BaseTab):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.edit = _prompt_edit(tr("ph_text"))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.addWidget(self.edit)

    def retranslate(self) -> None:
        self.edit.setPlaceholderText(tr("ph_text"))

    def build(self, ratio, resolution) -> BuildResult:
        r = BuildResult()
        prompts = split_prompts(self.edit.toPlainText())
        if not prompts:
            r.errors.append("Chưa có prompt nào. Hãy dán prompt vào ô nhập (mỗi dòng một prompt).")
        for i, p in enumerate(prompts, 1):
            r.specs.append(JobSpec("text_to_video", p, i, ratio, list(resolution)))
        return r


class ImageToVideoTab(BaseTab):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        top = QHBoxLayout()
        self.pick = QPushButton("📁 Chọn ảnh (chọn tất cả ảnh cần tạo video)")
        self.count = QLabel("0 ảnh")
        top.addWidget(self.pick)
        top.addWidget(self.count)
        top.addStretch(1)
        self.images = ImageList()
        self.edit = _prompt_edit(tr("ph_prompts"))
        lay.addLayout(top)
        lay.addWidget(self.images, 3)
        lay.addWidget(self.edit, 4)
        self.pick.clicked.connect(self.images.pick_many)
        self.images.paths_changed.connect(lambda: self.count.setText(f"{len(self.images.paths())} ảnh"))

    def set_ratio(self, ratio: str) -> None:
        self.images.set_ratio(ratio)

    def build(self, ratio, resolution) -> BuildResult:
        r = BuildResult()
        prompts, imgs = split_prompts(self.edit.toPlainText()), self.images.paths()
        if not imgs:
            r.errors.append("Chưa chọn ảnh nào.")
        if not prompts:
            r.errors.append("Chưa có prompt nào.")
        if r.errors:
            return r
        n, r.warnings = pair_by_line(prompts, imgs)
        for i in range(n):
            r.specs.append(JobSpec("start_image", prompts[i], i + 1, ratio, list(resolution),
                                   [{"name": Path(imgs[i]).name, "path": imgs[i]}]))
        return r


class StartEndTab(BaseTab):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        self.start = ImageList()
        self.end = ImageList()
        self.edit = _prompt_edit("Dán prompt cho từng cặp ảnh bắt đầu – kết thúc (mỗi dòng một prompt)…")
        for title, lst in (("Ảnh bắt đầu", self.start), ("Ảnh kết thúc", self.end)):
            row = QHBoxLayout()
            b = QPushButton(f"📁 Chọn {title.lower()}")
            c = QLabel("0 ảnh")
            b.clicked.connect(lambda _=False, l=lst, t=title: l.pick_many(f"Chọn {t.lower()}"))
            lst.paths_changed.connect(lambda l=lst, lab=c: lab.setText(f"{len(l.paths())} ảnh"))
            row.addWidget(b)
            row.addWidget(c)
            row.addStretch(1)
            lay.addLayout(row)
            lay.addWidget(lst, 2)
        lay.addWidget(self.edit, 3)

    def set_ratio(self, ratio: str) -> None:
        self.start.set_ratio(ratio)
        self.end.set_ratio(ratio)

    def add_start_images(self, paths: list[str]) -> None:
        self.start.set_paths(self.start.paths() + paths)

    def build(self, ratio, resolution) -> BuildResult:
        r = BuildResult()
        prompts, s, e = split_prompts(self.edit.toPlainText()), self.start.paths(), self.end.paths()
        if not s:
            r.errors.append("Chưa chọn ảnh bắt đầu.")
        if not e:
            r.errors.append("Chưa chọn ảnh kết thúc.")
        if s and e and len(s) != len(e):
            r.errors.append(f"Số ảnh kết thúc ({len(e)}) phải bằng số ảnh bắt đầu ({len(s)}).")
        if not prompts:
            r.errors.append("Chưa có prompt nào.")
        if r.errors:
            return r
        n, r.warnings = pair_by_line(prompts, s, "cặp ảnh")
        for i in range(n):
            r.specs.append(JobSpec("start_end_image", prompts[i], i + 1, ratio, list(resolution),
                                   [{"name": Path(s[i]).name, "path": s[i]}, {"name": Path(e[i]).name, "path": e[i]}]))
        return r


PROMPT_HINT = ("- Dán hàng loạt prompt, mỗi dòng 1 prompt\n\n"
               "- Chọn 10 ảnh nhân vật và đặt tên riêng cho nhân vật\n\n"
               "- Gọi tên nhân vật (chỉ tên) và mô tả hành động của nhân vật, bối cảnh..\n\n"
               "*LƯU Ý:\n"
               "- Ảnh nhân vật nên up ảnh nền trắng hoặc png ko nền.\n"
               "- Tên nhân vật nên đặt từ 4 ký tự trở lên\n"
               "- 1 Prompt có tối đa 3 nhân vật, nếu nhiều hơn, hãy ghép 2 nhân vật trong 1 ảnh")


class CharactersTab(BaseTab):
    """Bố cục giống Veo3 Go: bên trái 'Prompt hàng loạt'; bên phải cột nhân vật (nút chọn ảnh, danh sách thẻ ảnh + tên,
    ô chọn giọng đọc). Tên trong prompt (hoặc @tên) phải khớp chính xác tên đã đặt thì nhân vật mới được giữ đồng nhất."""

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QHBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(10)

        left = QVBoxLayout()
        self.title = QLabel("Prompt hàng loạt")
        self.title.setStyleSheet("font-weight:600;")
        self.edit = _prompt_edit(PROMPT_HINT)
        left.addWidget(self.title)
        left.addWidget(self.edit, 1)

        right = QFrame()
        right.setObjectName("charColumn")
        right.setFixedWidth(250)
        rv = QVBoxLayout(right)
        rv.setContentsMargins(8, 8, 8, 8)
        rv.setSpacing(8)
        self.add = QPushButton()
        self.add.setObjectName("charAdd")
        self.add.setCursor(Qt.PointingHandCursor)
        self.add.setStyleSheet("QPushButton#charAdd{border:1px dashed #9CA3AF;border-radius:6px;padding:7px 6px;"
                               "background:#FAFAFA;}QPushButton#charAdd:hover{background:#EEF2FF;}")
        self.rows: list[CharacterRow] = []
        self.holder = QWidget()
        self.rows_lay = QVBoxLayout(self.holder)
        self.rows_lay.setContentsMargins(0, 0, 0, 0)
        self.rows_lay.setSpacing(6)
        self.rows_lay.addStretch(1)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setWidget(self.holder)
        self.voice = QComboBox()
        self.voice.setObjectName("voiceCombo")
        self.voice.addItem("🔊 Chọn giọng đọc", "")
        for code, label in VOICES:
            self.voice.addItem(label, code)
        self.voice.setToolTip("Giọng đọc cho lời thoại trong video (không chọn = để Veo tự chọn)")
        self.voice.setMaxVisibleItems(12)
        rv.addWidget(self.add)
        rv.addWidget(self.scroll, 1)
        rv.addWidget(self.voice)

        root.addLayout(left, 1)
        root.addWidget(right)
        self.add.clicked.connect(self._pick)
        self._refresh_count()

    def _refresh_count(self) -> None:
        n = len(self.rows)
        self.add.setText("📷 Chọn ảnh nhân vật (tối đa %d)" % MAX_CHARACTERS if n == 0
                         else "📷 Chọn ảnh nhân vật (%d/%d)" % (n, MAX_CHARACTERS))

    def _pick(self) -> None:
        if len(self.rows) >= MAX_CHARACTERS:
            return
        files, _ = QFileDialog.getOpenFileNames(self, "Chọn ảnh nhân vật", "", IMG_FILTER)
        self.add_files(files)

    def add_files(self, files: list[str]) -> None:
        for f in files:
            if len(self.rows) >= MAX_CHARACTERS:
                break
            row = CharacterRow(f)
            row.removed.connect(self._remove)
            self.rows.append(row)
            self.rows_lay.insertWidget(self.rows_lay.count() - 1, row)
        self._refresh_count()

    def _remove(self, row: CharacterRow) -> None:
        self.rows.remove(row)
        row.setParent(None)
        row.deleteLater()
        self._refresh_count()

    def selected_voice(self) -> str:
        return self.voice.currentData() or ""

    def build(self, ratio, resolution) -> BuildResult:
        r = BuildResult()
        prompts = split_prompts(self.edit.toPlainText())
        if not self.rows:
            r.errors.append("Chưa thêm nhân vật nào. Bấm 'Chọn ảnh nhân vật' rồi đặt tên cho từng ảnh.")
        unnamed = [i for i, row in enumerate(self.rows, 1) if not row.character_name()]
        if unnamed:
            r.errors.append("Nhân vật số " + ", ".join(map(str, unnamed)) + " chưa có tên. Mỗi ảnh phải có tên "
                            "riêng để gọi trong prompt.")
        if not prompts:
            r.errors.append("Chưa có prompt nào.")
        chars = [(row.character_name(), row.path) for row in self.rows if row.character_name()]
        names = [n for n, _ in chars]
        bad = [n for n in names if not name_slug(n)]
        if bad:
            r.errors.append("Tên nhân vật cần có chữ hoặc số: " + ", ".join(bad))
        slugs = [name_slug(n).lower() for n in names if name_slug(n)]
        if len(set(slugs)) != len(slugs):
            r.errors.append("Có hai nhân vật trùng tên.")
        if r.errors:
            return r
        for n in names:
            if len(n) < MIN_NAME_LEN:
                r.warnings.append(f"Tên '{n}' quá ngắn (nên từ 4 ký tự trở lên), dễ bị nhận nhầm trong prompt.")
            for o in names:
                if o != n and name_slug(n).lower() in name_slug(o).lower():
                    r.warnings.append(f"Tên '{n}' nằm trong tên '{o}': có thể gắn nhầm ảnh.")
        path_of = dict(chars)
        voice = self.selected_voice()
        for i, p in enumerate(prompts, 1):
            found = find_characters(p, names)
            if not found:
                r.warnings.append(f"Prompt {i} không nhắc đúng tên nhân vật nào (gọi 'Tên' hoặc '@Tên'), bỏ qua.")
                continue
            if len(found) > MAX_REFS_PER_CLIP:
                r.warnings.append(f"Prompt {i} nhắc {len(found)} nhân vật, Veo chỉ nhận {MAX_REFS_PER_CLIP}: "
                                  f"chỉ dùng {', '.join(found[:MAX_REFS_PER_CLIP])}.")
                found = found[:MAX_REFS_PER_CLIP]
            r.specs.append(JobSpec("components", tag_characters(p, found), i, ratio, list(resolution),
                                   [{"name": name_slug(n), "path": path_of[n]} for n in found], voice))
        if not r.specs:
            r.errors.append("Không có prompt nào nhắc đúng tên nhân vật.")
        return r
