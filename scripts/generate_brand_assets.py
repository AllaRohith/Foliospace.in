from PIL import Image, ImageDraw
from pathlib import Path

INK = (15, 20, 25)
ACCENT = (255, 107, 53)
CREAM = (250, 247, 242)

BASE = Path(__file__).resolve().parent.parent
OUT_DIR = BASE / "app" / "static" / "img"

F_PATH = [
    (8, 8), (8, 48), (16, 48), (16, 33), (30, 33),
    (30, 26), (16, 26), (16, 15), (38, 15), (38, 8),
]
ACC_X, ACC_Y, ACC_W = 32, 40, 10


def render(size, padding=0, background=None):
    canvas = size + padding * 2
    img = Image.new("RGBA", (canvas, canvas), background or (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    scale = size / 56
    if background:
        d.rectangle([0, 0, canvas, canvas], fill=background)
    f_coords = [
        (padding + int(x * scale), padding + int(y * scale)) for x, y in F_PATH
    ]
    d.polygon(f_coords, fill=INK)
    ax = padding + int(ACC_X * scale)
    ay = padding + int(ACC_Y * scale)
    aw = max(1, int(ACC_W * scale))
    d.rectangle([ax, ay, ax + aw, ay + aw], fill=ACCENT)
    return img


def main():
    targets = [
        ("apple-touch-icon.png", 180, 0, CREAM),
        ("mark-32.png", 32, 0, (0, 0, 0, 0)),
        ("mark-128.png", 128, 0, (0, 0, 0, 0)),
        ("mark-512.png", 512, 0, (0, 0, 0, 0)),
    ]
    for name, size, padding, bg in targets:
        img = render(size, padding, bg)
        out = OUT_DIR / name
        img.save(out, "PNG", optimize=True)
        print(f"wrote {out.name} {size}x{size} ({out.stat().st_size} B)")


if __name__ == "__main__":
    main()
