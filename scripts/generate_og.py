from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

W, H = 1200, 630
INK = (15, 20, 25)
CREAM = (250, 247, 242)
CREAM_2 = (242, 237, 227)
ACCENT = (255, 107, 53)
MUTED = (92, 100, 112)


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


def measure(draw, text, fnt):
    bbox = draw.textbbox((0, 0), text, font=fnt)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def highlight_text(img, x, y, text, fnt, hl_color, hl_alpha=85, pad_x=12):
    draw = ImageDraw.Draw(img)
    bbox = draw.textbbox((0, 0), text, font=fnt)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    bar_top = y + int(h * 0.28)
    bar_bot = y + int(h * 0.88)
    od.rectangle(
        [x - pad_x, bar_top, x + w + pad_x, bar_bot],
        fill=(*hl_color, hl_alpha),
    )
    img_rgba = img.convert("RGBA")
    img_rgba.alpha_composite(overlay)
    return img_rgba.convert("RGB")


def main():
    img = Image.new("RGB", (W, H), CREAM)
    draw = ImageDraw.Draw(img)

    for y in range(0, H, 4):
        alpha = int(8 + 6 * (y / H))
        draw.line([(0, y), (W, y)], fill=(232, 227, 217))

    mark_size = 56
    mark_x, mark_y = 80, 80
    draw.rounded_rectangle(
        [mark_x, mark_y, mark_x + mark_size, mark_y + mark_size],
        radius=14,
        fill=INK,
    )
    half = mark_size // 2
    draw.rectangle(
        [mark_x + 10, mark_y + 10, mark_x + 10 + half - 5, mark_y + 10 + half - 5],
        fill=CREAM,
    )
    draw.rectangle(
        [mark_x + half + 5, mark_y + 10, mark_x + mark_size - 10, mark_y + 10 + half - 5],
        fill=CREAM,
    )
    draw.rectangle(
        [mark_x + 10, mark_y + half + 5, mark_x + 10 + half - 5, mark_y + mark_size - 10],
        fill=CREAM,
    )
    draw.rounded_rectangle(
        [mark_x + half + 5, mark_y + half + 5, mark_x + mark_size - 10, mark_y + mark_size - 10],
        radius=4,
        fill=ACCENT,
    )

    f_brand = font(34, "Bold")
    draw.text((mark_x + mark_size + 16, mark_y + 8), "FolioSpace", fill=INK, font=f_brand)

    f_eyebrow = font(20, "Bold")
    draw.text((80, 200), "NOW IN PRIVATE BETA", fill=ACCENT, font=f_eyebrow)

    f_title = font(86, "Bold")
    title1 = "A portfolio"
    title2 = "for everyone."
    w1, _ = measure(draw, title1, f_title)
    w2, _ = measure(draw, title2, f_title)
    draw.text((80, 240), title1, fill=INK, font=f_title)
    draw.text((80, 340), title2, fill=INK, font=f_title)

    f_under = font(86, "Bold")
    img = highlight_text(img, 80, 340, "for everyone.", f_under, ACCENT, hl_alpha=85)
    draw = ImageDraw.Draw(img)

    f_sub = font(26, "Regular")
    sub = "Students, chefs, artists, consultants, developers."
    draw.text((80, 460), sub, fill=MUTED, font=f_sub)

    f_launch = font_arial_bold(22)
    draw.text((80, 500), "→ Launching September 2, 2026", fill=ACCENT, font=f_launch)

    pill_x, pill_y, pill_w, pill_h = 80, 555, 240, 50
    draw.rounded_rectangle(
        [pill_x, pill_y, pill_x + pill_w, pill_y + pill_h],
        radius=25,
        fill=INK,
    )
    f_pill = font(20, "Bold")
    pill_text = "₹150 setup  ·  ₹99/mo"
    pw, ph = measure(draw, pill_text, f_pill)
    draw.text(
        (pill_x + (pill_w - pw) // 2, pill_y + (pill_h - ph) // 2 - 2),
        pill_text,
        fill=CREAM,
        font=f_pill,
    )

    card_x, card_y, card_w, card_h = 760, 200, 360, 320
    draw.rounded_rectangle(
        [card_x, card_y, card_x + card_w, card_y + card_h],
        radius=20,
        fill="#FFFFFF",
        outline=(232, 227, 217),
        width=2,
    )

    bar_h = 36
    draw.rounded_rectangle(
        [card_x, card_y, card_x + card_w, card_y + bar_h],
        radius=20,
        fill=CREAM_2,
    )
    draw.rectangle(
        [card_x, card_y + bar_h // 2, card_x + card_w, card_y + bar_h],
        fill=CREAM_2,
    )
    draw.line(
        [(card_x, card_y + bar_h), (card_x + card_w, card_y + bar_h)],
        fill=(232, 227, 217),
        width=1,
    )
    for i, c in enumerate([(255, 95, 87), (254, 188, 46), (40, 200, 64)]):
        cx = card_x + 18 + i * 18
        cy = card_y + bar_h // 2
        draw.ellipse([cx - 6, cy - 6, cx + 6, cy + 6], fill=c)

    f_url = font(14, "Regular")
    draw.text(
        (card_x + 90, card_y + bar_h // 2 - 8),
        "foliospace.in/yourname",
        fill=MUTED,
        font=f_url,
    )

    av_x, av_y = card_x + 24, card_y + bar_h + 30
    draw.ellipse([av_x, av_y, av_x + 48, av_y + 48], fill=ACCENT)
    f_name = font(20, "Bold")
    f_role = font(14, "Regular")
    draw.text((av_x + 64, av_y + 4), "Your Name", fill=INK, font=f_name)
    draw.text((av_x + 64, av_y + 28), "Consultant  ·  Available for work", fill=MUTED, font=f_role)

    tile_y = av_y + 80
    tile_w = (card_w - 24 * 2 - 10) // 2
    tile_h = 70
    for i in range(2):
        tx = card_x + 24 + i * (tile_w + 10)
        draw.rounded_rectangle(
            [tx, tile_y, tx + tile_w, tile_y + tile_h],
            radius=10,
            fill=CREAM_2,
        )
        f_lbl = font(11, "Bold")
        draw.text((tx + 12, tile_y + 10), "CASE STUDY", fill=MUTED, font=f_lbl)
        f_strong = font(13, "Bold")
        draw.text((tx + 12, tile_y + 30), f"Project #{i+1}", fill=INK, font=f_strong)

    badge_y = tile_y + tile_h + 18
    draw.rounded_rectangle(
        [card_x + 24, badge_y, card_x + 130, badge_y + 30],
        radius=15,
        fill=INK,
    )
    f_badge = font(12, "Bold")
    draw.text(
        (card_x + 24 + 18, badge_y + 8),
        "Download PDF",
        fill=CREAM,
        font=f_badge,
    )
    draw.rounded_rectangle(
        [card_x + 140, badge_y, card_x + 280, badge_y + 30],
        radius=15,
        outline=(232, 227, 217),
        width=1,
    )
    draw.text(
        (card_x + 140 + 18, badge_y + 8),
        "Share on WhatsApp",
        fill=INK,
        font=f_badge,
    )

    out = Path(__file__).resolve().parent.parent / "app" / "static" / "img" / "og.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG", optimize=True)
    print(f"wrote {out} ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
