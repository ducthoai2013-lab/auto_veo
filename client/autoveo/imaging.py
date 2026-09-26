"""Xử lý ảnh trước khi gửi: crop giữa theo tỷ lệ, nền trắng cho PNG trong suốt, nén JPEG ≤2048px."""
from __future__ import annotations

import base64
import io
import re
from pathlib import Path

from PIL import Image, ImageOps

RATIOS = {"16:9": (16, 9), "9:16": (9, 16), "1:1": (1, 1), "4:3": (4, 3), "3:4": (3, 4)}
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp")


def natural_key(s: str):
    """Sắp theo tên tự nhiên: 2 trước 10."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def sort_paths(paths: list[str]) -> list[str]:
    return sorted(paths, key=lambda p: natural_key(Path(p).name))


def open_image(path: str) -> Image.Image:
    img = Image.open(path)
    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (255, 255, 255))   # nhân vật PNG không nền -> nền trắng
        bg.paste(img, mask=img.split()[-1])
        return bg
    return img.convert("RGB")


def center_crop(img: Image.Image, ratio: str) -> Image.Image:
    rw, rh = RATIOS[ratio]
    w, h = img.size
    target = rw / rh
    if w / h > target:
        nw = int(h * target)
        x = (w - nw) // 2
        return img.crop((x, 0, x + nw, h))
    nh = int(w / target)
    y = (h - nh) // 2
    return img.crop((0, y, w, y + nh))


def to_data_uri(img: Image.Image, max_side: int = 2048, quality: int = 90) -> str:
    if max(img.size) > max_side:
        img = img.copy()
        img.thumbnail((max_side, max_side), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def prepare(path: str, ratio: str | None) -> str:
    img = open_image(path)
    if ratio:
        img = center_crop(img, ratio)
    return to_data_uri(img)


def thumbnail(path: str, size: int = 96, ratio: str | None = None) -> Image.Image:
    img = open_image(path)
    if ratio:
        img = center_crop(img, ratio)
    img.thumbnail((size * 2, size * 2), Image.LANCZOS)
    return img
