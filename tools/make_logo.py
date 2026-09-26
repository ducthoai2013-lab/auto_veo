"""Vẽ logo tạm Auto_veo3 (thay bằng logo thật của bạn: chỉ cần ghi đè client/resources/logo.png và app.ico)."""
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parents[1] / "client" / "resources"
S = 512


def make() -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    # nền gradient chàm -> lục lam, bo góc
    grad = Image.new("RGB", (S, S))
    px = grad.load()
    for y in range(S):
        for x in range(S):
            t = (x + y) / (2 * S)
            px[x, y] = (int(99 + (28 - 99) * t), int(102 + (181 - 102) * t), int(241 + (208 - 241) * t))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle((16, 16, S - 16, S - 16), radius=110, fill=255)
    img.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(img)
    # tam giác phát (play)
    d.polygon([(190, 150), (190, 362), (372, 256)], fill=(255, 255, 255, 255))
    # tia chớp nhỏ = "Auto"
    d.polygon([(392, 80), (330, 190), (372, 190), (340, 280), (440, 158), (394, 158), (424, 80)],
              fill=(253, 224, 71, 255))
    return img


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    logo = make()
    logo.save(OUT / "logo.png")
    logo.save(OUT / "app.ico", sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
    print("saved", OUT / "logo.png", OUT / "app.ico")
