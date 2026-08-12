from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

W, H = 1200, 630
INK = (15, 20, 25)
CREAM = (250, 247, 242)
CREAM_2 = (242, 237, 227)
ACCENT = (255, 107, 53)
MUTED = (92, 100, 112)
HAIRLINE = (232, 227, 217)


def font(size, weight="Regular"):
    candidates = {
        "Bold": [
            "/System/Library/Fonts/Helvetica.ttc",
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "/Library/Fonts/Arial Bold.ttf",
        ],
        "Regular": [
            "/System/Library/Fonts/Helvetica.ttc",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/Library/Fonts/Arial.ttf",
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


def font_arial_bold(size):
    path = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
    if Path(path).exists():
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return font(size, "Bold")


def font_helvetica_regular(size):
    path = "/System/Library/Fonts/Helvetica.ttc"
    if Path(path).exists():
        try:
            return ImageFont.truetype(path, size, index=0)
        except (OSError, TypeError):
            pass
    return font(size, "Regular")


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


def draw_brand_mark(draw, x, y, size=56):
    draw.rounded_rectangle(
        [x, y, x + size, y + size],
        radius=14,
        fill=INK,
    )
    half = size // 2
    draw.rectangle(
        [x + 10, y + 10, x + 10 + half - 5, y + 10 + half - 5],
        fill=CREAM,
    )
    draw.rectangle(
        [x + half + 5, y + 10, x + size - 10, y + 10 + half - 5],
        fill=CREAM,
    )
    draw.rectangle(
        [x + 10, y + half + 5, x + 10 + half - 5, y + size - 10],
        fill=CREAM,
    )
    draw.rounded_rectangle(
        [x + half + 5, y + half + 5, x + size - 10, y + size - 10],
        radius=4,
        fill=ACCENT,
    )


def draw_countdown_poster(draw, img, cx, top_y):
    f_eyebrow = font_arial_bold(15)
    eyebrow = "→ PUBLIC LAUNCH IN"
    ew, _ = measure(draw, eyebrow, f_eyebrow)
    draw.text((cx - ew // 2, top_y), eyebrow, fill=ACCENT, font=f_eyebrow)

    f_days = font(220, "Bold")
    days_text = "20"
    dw, dh = measure(draw, days_text, f_days)
    days_y = top_y + 35
    img = highlight_text(img, cx - dw // 2, days_y, days_text, f_days, ACCENT, hl_alpha=85, pad_x=14)
    draw = ImageDraw.Draw(img)
    draw.text((cx - dw // 2, days_y), days_text, fill=INK, font=f_days)

    f_label = font_arial_bold(18)
    label = "DAYS TO LAUNCH"
    lw, _ = measure(draw, label, f_label)
    label_y = days_y + dh + 14
    draw.text((cx - lw // 2, label_y), label, fill=MUTED, font=f_label)

    f_date = font_helvetica_regular(20)
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

    f_brand = font(34, "Bold")
    draw.text((mark_x + mark_size + 18, mark_y + 10), "FolioSpace", fill=INK, font=f_brand)

    y_eyebrow = 170
    f_eyebrow = font_arial_bold(15)
    draw.text((80, y_eyebrow), "→ PRIVATE BETA  ·  WAITLIST OPEN", fill=ACCENT, font=f_eyebrow)

    y_lead = 195
    f_small_lead = font(50, "Bold")
    draw.text((80, y_lead), "Stop sending", fill=INK, font=f_small_lead)

    y_pdfs = y_lead + 60
    f_big_pdfs = font(110, "Bold")
    img = highlight_text(img, 80, y_pdfs, "PDFs.", f_big_pdfs, ACCENT, hl_alpha=90, pad_x=10)
    draw = ImageDraw.Draw(img)
    draw.text((80, y_pdfs), "PDFs.", fill=INK, font=f_big_pdfs)

    y_sub1 = y_pdfs + 125
    f_sub = font(50, "Bold")
    draw.text((80, y_sub1), "Start sharing a link", fill=INK, font=f_sub)
    y_sub2 = y_sub1 + 55
    draw.text((80, y_sub2), "that lands.", fill=INK, font=f_sub)

    f_for = font(22, "Regular")
    draw.text((80, y_sub2 + 72), "For Indian professionals.", fill=MUTED, font=f_for)

    f_persona = font(20, "Bold")
    persona_y = y_sub2 + 102
    personas = "Chefs · developers · students · designers · artists"
    draw.text((80, persona_y), personas, fill=INK, font=f_persona)

    right_cx = 920
    img, draw = draw_countdown_poster(draw, img, right_cx, top_y=195)

    out = Path(__file__).resolve().parent.parent / "app" / "static" / "img" / "og.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG", optimize=True)
    print(f"wrote {out} ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()