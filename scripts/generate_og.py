from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

W, H = 1200, 630
INK = (15, 20, 25)
CREAM = (250, 247, 242)
CREAM_2 = (242, 237, 227)
ACCENT = (255, 107, 53)
MUTED = (92, 100, 112)
HAIRLINE = (232, 227, 217)

FONT_DIR = Path(__file__).resolve().parent.parent / "app" / "static" / "fonts"
STALINIST = FONT_DIR / "StalinistOne-Regular.ttf"
SAIRA = FONT_DIR / "Saira-Variable.ttf"
SAIRA_ITALIC = FONT_DIR / "Saira-Italic-Variable.ttf"


def font(size, weight="Regular"):
    if weight in ("Bold", "SemiBold", "Medium"):
        return _saira(size, weight)
    if weight == "Italic":
        return _saira_italic(size, "Regular")
    if weight == "ItalicMedium":
        return _saira_italic(size, "Medium")
    return _saira(size, "Regular")


def _saira(size, weight="Regular"):
    if not SAIRA.exists():
        return _fallback(size, "Regular")
    try:
        f = ImageFont.truetype(str(SAIRA), size)
        try:
            f.set_variation_by_name(weight)
        except (AttributeError, OSError):
            pass
        return f
    except (OSError, TypeError):
        return _fallback(size, "Regular")


def _saira_italic(size, weight="Regular"):
    if not SAIRA_ITALIC.exists():
        return _fallback(size, "Regular")
    try:
        f = ImageFont.truetype(str(SAIRA_ITALIC), size)
        try:
            f.set_variation_by_name(weight)
        except (AttributeError, OSError):
            pass
        return f
    except (OSError, TypeError):
        return _fallback(size, "Regular")


def _stalinist(size):
    if not STALINIST.exists():
        return _fallback(size, "Bold")
    try:
        return ImageFont.truetype(str(STALINIST), size)
    except (OSError, TypeError):
        return _fallback(size, "Bold")


def _fallback(size, weight="Regular"):
    candidates = {
        "Bold": [
            "/System/Library/Fonts/Supplemental/Arial Black.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
        ],
        "Regular": [
            "/System/Library/Fonts/Helvetica.ttc",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
        ],
    }
    for path in candidates.get(weight, candidates["Regular"]):
        if Path(path).exists():
            try:
                face_index = 1 if weight == "Bold" else 0
                return ImageFont.truetype(path, size, index=face_index)
            except (OSError, TypeError):
                continue
    return ImageFont.load_default()


def font_saira_bold(size):
    return _saira(size, "Bold")


def font_saira_semibold(size):
    return _saira(size, "SemiBold")


def font_saira_medium(size):
    return _saira(size, "Medium")


def font_saira_regular(size):
    return _saira(size, "Regular")


def font_saira_italic(size):
    return _saira_italic(size, "Regular")


def font_stalinist(size):
    return _stalinist(size)


def measure(draw, text, fnt):
    bbox = draw.textbbox((0, 0), text, font=fnt)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def highlight_text(img, x, y, text, fnt, hl_color, hl_alpha=85, pad_x=14):
    draw = ImageDraw.Draw(img)
    bbox = draw.textbbox((0, 0), text, font=fnt)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    bar_top = y + int(h * 0.26)
    bar_bot = y + int(h * 0.90)
    od.rectangle(
        [x - pad_x, bar_top, x + w + pad_x, bar_bot],
        fill=(*hl_color, hl_alpha),
    )
    img_rgba = img.convert("RGBA")
    img_rgba.alpha_composite(overlay)
    return img_rgba.convert("RGB")


F_PATH = [
    (8, 8), (8, 48), (16, 48), (16, 33), (30, 33),
    (30, 26), (16, 26), (16, 15), (38, 15), (38, 8),
]
ACC_X, ACC_Y, ACC_W = 32, 40, 10


def draw_brand_mark(draw, x, y, size=56):
    scale = size / 56
    poly = [(x + int(px * scale), y + int(py * scale)) for px, py in F_PATH]
    draw.polygon(poly, fill=INK)
    ax = x + int(ACC_X * scale)
    ay = y + int(ACC_Y * scale)
    aw = max(1, int(ACC_W * scale))
    draw.rectangle([ax, ay, ax + aw, ay + aw], fill=ACCENT)


def draw_countdown_poster(draw, img, cx, top_y):
    f_eyebrow = font_saira_bold(15)
    eyebrow = "→ PUBLIC LAUNCH IN"
    ew, _ = measure(draw, eyebrow, f_eyebrow)
    draw.text((cx - ew // 2, top_y), eyebrow, fill=ACCENT, font=f_eyebrow)

    f_days = font_stalinist(180)
    days_text = "20"
    dw, dh = measure(draw, days_text, f_days)
    days_y = top_y + 35
    img = highlight_text(img, cx - dw // 2, days_y, days_text, f_days, ACCENT, hl_alpha=85, pad_x=14)
    draw = ImageDraw.Draw(img)
    draw.text((cx - dw // 2, days_y), days_text, fill=INK, font=f_days)

    f_label = font_saira_bold(18)
    label = "DAYS TO LAUNCH"
    lw, _ = measure(draw, label, f_label)
    label_y = days_y + dh + 14
    draw.text((cx - lw // 2, label_y), label, fill=MUTED, font=f_label)

    f_date = font_saira_regular(20)
    date_line1 = "September 2, 2026"
    date_line2 = "12:00 AM IST"
    d1w, _ = measure(draw, date_line1, f_date)
    d2w, _ = measure(draw, date_line2, f_date)
    date_y = label_y + 50
    draw.text((cx - d1w // 2, date_y), date_line1, fill=INK, font=f_date)
    draw.text((cx - d2w // 2, date_y + 28), date_line2, fill=MUTED, font=f_date)

    return img, draw


def main():
    img = Image.new("RGB", (W, H), CREAM)
    draw = ImageDraw.Draw(img)

    for y in range(0, H, 4):
        draw.line([(0, y), (W, y)], fill=HAIRLINE)

    mark_size = 56
    mark_x, mark_y = 80, 70
    draw_brand_mark(draw, mark_x, mark_y, mark_size)

    f_brand = font_stalinist(34)
    word_x = mark_x + mark_size + 18
    draw.text((word_x, mark_y + 8), "FolioSpace", fill=INK, font=f_brand)
    word_bbox = draw.textbbox((0, 0), "FolioSpace", font=f_brand)
    word_w = word_bbox[2] - word_bbox[0]
    word_h = word_bbox[3] - word_bbox[1]
    acc_size = 12
    acc_x = word_x + word_w + 4
    acc_y = mark_y + 8 + word_h - acc_size - 4
    draw.rectangle([acc_x, acc_y, acc_x + acc_size, acc_y + acc_size], fill=ACCENT)

    y_eyebrow = 170
    f_eyebrow = font_saira_bold(15)
    draw.text((80, y_eyebrow), "→ PRIVATE BETA  ·  WAITLIST OPEN", fill=ACCENT, font=f_eyebrow)

    y_lead = 200
    f_small_lead = font_saira_semibold(50)
    draw.text((80, y_lead), "Stop sending", fill=INK, font=f_small_lead)

    y_pdfs = y_lead + 60
    f_big_pdfs = font_stalinist(120)
    img = highlight_text(img, 80, y_pdfs, "PDFs.", f_big_pdfs, ACCENT, hl_alpha=90, pad_x=10)
    draw = ImageDraw.Draw(img)
    draw.text((80, y_pdfs), "PDFs.", fill=INK, font=f_big_pdfs)

    y_sub1 = y_pdfs + 130
    f_sub = font_saira_semibold(46)
    draw.text((80, y_sub1), "Start sharing a link", fill=INK, font=f_sub)
    y_sub2 = y_sub1 + 52
    draw.text((80, y_sub2), "that lands.", fill=INK, font=f_sub)

    f_for = font_saira_regular(22)
    draw.text((80, y_sub2 + 70), "For every Indian professional.", fill=MUTED, font=f_for)

    f_persona = font_saira_bold(18)
    persona_y = y_sub2 + 100
    personas = "Chefs · devs · students · consultants · shops · agencies"
    draw.text((80, persona_y), personas, fill=INK, font=f_persona)

    right_cx = 920
    img, draw = draw_countdown_poster(draw, img, right_cx, top_y=195)

    out = Path(__file__).resolve().parent.parent / "app" / "static" / "img" / "og.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG", optimize=True)
    print(f"wrote {out} ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
