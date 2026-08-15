from PIL import Image, ImageDraw, ImageFont, ImageFilter
import random
import math
from pathlib import Path

CREAM = (250, 247, 242)
INK = (15, 20, 25)
ACCENT = (255, 107, 53)
MUTED = (92, 100, 112)
LINE = (180, 174, 162)
LINE_STRONG = (60, 55, 48)

W, H = 1080, 1350
BASE = Path(__file__).resolve().parent.parent
STALINIST = str(BASE / "app/static/fonts/StalinistOne-Regular.ttf")
SAIRA = str(BASE / "app/static/fonts/Saira-Variable.ttf")


def paper_grain(size):
    w, h = size
    grain = Image.new("L", (w, h), 255)
    px = grain.load()
    for y in range(h):
        for x in range(w):
            v = random.randint(238, 255)
            if random.random() < 0.04:
                v = random.randint(220, 240)
            px[x, y] = v
    return grain.filter(ImageFilter.GaussianBlur(radius=0.6))


img = Image.new("RGB", (W, H), CREAM)
grain = paper_grain((W, H)).convert("RGB")
img = Image.blend(img, grain, 0.18)

draw = ImageDraw.Draw(img)

stalinist = ImageFont.truetype(STALINIST, 1)
saira_h = ImageFont.truetype(SAIRA, 1)


def fit_font(text, font_path, max_w, max_h, max_size=900, min_size=40):
    lo, hi = min_size, max_size
    best = None
    while lo <= hi:
        mid = (lo + hi) // 2
        f = ImageFont.truetype(font_path, mid)
        bbox = f.getbbox(text)
        w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        if w <= max_w and h <= max_h:
            best = (mid, f)
            lo = mid + 1
        else:
            hi = mid - 1
    return best


big_size, big_font = fit_font("80", STALINIST, W - 200, 600, max_size=560)
big_text = "80"
bbox = big_font.getbbox(big_text)
tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
big_x = (W - tw) / 2 - bbox[0]
big_y = 230 - bbox[1]
draw.text((big_x, big_y), big_text, font=big_font, fill=INK)

mark_size = 220
mark_font = ImageFont.truetype(STALINIST, mark_size)
mark_text = "."
mbbox = mark_font.getbbox(mark_text)
mw = mbbox[2] - mbbox[0]
mdraw_x = big_x + tw + 8
mdraw_y = big_y + th - mbbox[3] + 8
draw.text((mdraw_x, mdraw_y), mark_text, font=mark_font, fill=ACCENT)

eyebrow_font = ImageFont.truetype(SAIRA, 26)
eyebrow = "15 AUGUST 2026  ·  INDEPENDENCE DAY"
ebbox = eyebrow_font.getbbox(eyebrow)
ew = ebbox[2] - ebbox[0]
eyebrow_x = (W - ew) / 2 - ebbox[0]
eyebrow_y = 880
draw.text((eyebrow_x, eyebrow_y), eyebrow, font=eyebrow_font, fill=ACCENT)


def hairline_h(y, x_start, x_end, color=LINE_STRONG, width=1):
    draw.line([(x_start, y), (x_end, y)], fill=color, width=width)


hairline_h(940, 80, W - 80)
hairline_h(970, 80, W - 80, color=LINE, width=2)

deck_font = ImageFont.truetype(SAIRA, 44)
deck_lines = [
    "Eighty years.",
    "A crore kitchens, ateliers,",
    "studios, shops, agencies.",
]
deck_total_h = 0
line_metrics = []
for line in deck_lines:
    bbox = deck_font.getbbox(line)
    lw, lh = bbox[2] - bbox[0], bbox[3] - bbox[1]
    line_metrics.append((line, lw, lh, bbox))
    deck_total_h += lh + 14
deck_total_h -= 14

deck_y = 1010
for line, lw, lh, bb in line_metrics:
    deck_x = (W - lw) / 2 - bb[0]
    draw.text((deck_x, deck_y), line, font=deck_font, fill=INK)
    deck_y += lh + 14

hairline_h(deck_y + 14, 80, W - 80, color=LINE, width=2)
hairline_h(deck_y + 44, 80, W - 80)

folio_size, folio_font = fit_font("FolioSpace", STALINIST, W - 200, 120, max_size=88)
fbbox = folio_font.getbbox("FolioSpace")
fw = fbbox[2] - fbbox[0]
fh = fbbox[3] - fbbox[1]
folio_x = (W - fw) / 2 - fbbox[0]
folio_y = deck_y + 80 - fbbox[1]
draw.text((folio_x, folio_y), "FolioSpace", font=folio_font, fill=INK)

dot_size = 22
dot_x = folio_x + fw + 4
dot_y = folio_y + fh - dot_size - 2
draw.rectangle([dot_x, dot_y, dot_x + dot_size, dot_y + dot_size], fill=ACCENT)

cap_font = ImageFont.truetype(SAIRA, 22)
cap = "for the next eighty.  ·  foliospace.in"
cbbox = cap_font.getbbox(cap)
cw = cbbox[2] - cbbox[0]
cap_x = (W - cw) / 2 - cbbox[0]
cap_y = folio_y + fh + 16
draw.text((cap_x, cap_y), cap, font=cap_font, fill=MUTED)

marg_font = ImageFont.truetype(SAIRA, 16)
marg = "№ 01  ·  EDITORIAL  ·  2026"
mbbox = marg_font.getbbox(marg)
mw = mbbox[2] - mbbox[0]
draw.text((60, 60), marg, font=marg_font, fill=MUTED)
draw.text((W - mw - 60, 60), marg, font=marg_font, fill=MUTED)

out = BASE / "app/static/img/independence-2026.png"
img.save(out, "PNG", optimize=True)
print(f"wrote {out} ({out.stat().st_size} bytes, {W}x{H})")