from __future__ import annotations

from pathlib import Path

ACCENT = (37, 99, 235, 255)
WHITE = (255, 255, 255, 255)


def make_icon(size: int = 256):
    from PIL import Image, ImageDraw

    scale = 4
    big = size * scale
    image = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    radius = int(big * 0.24)
    draw.rounded_rectangle([0, 0, big - 1, big - 1], radius=radius, fill=ACCENT)
    cx = cy = big / 2
    w = big * 0.36
    h = big * 0.22
    stroke = max(2, int(big * 0.07))
    top = [(cx - w + i * (2 * w) / 40, cy - h * (1 - ((i - 20) / 20) ** 2)) for i in range(41)]
    bottom = [(cx - w + i * (2 * w) / 40, cy + h * (1 - ((i - 20) / 20) ** 2)) for i in range(41)]
    draw.line(top, fill=WHITE, width=stroke, joint="curve")
    draw.line(bottom, fill=WHITE, width=stroke, joint="curve")
    r = big * 0.1
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=WHITE)
    return image.resize((size, size), Image.LANCZOS)


def save_ico(path: Path) -> Path:
    image = make_icon(256)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    return path


def save_png(path: Path, size: int = 256) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    make_icon(size).save(path, format="PNG")
    return path
