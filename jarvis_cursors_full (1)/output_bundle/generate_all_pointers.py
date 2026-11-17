import struct, math, io, os
from PIL import Image, ImageDraw, ImageFilter, ImageFont

CYAN = (0, 190, 255)
CYAN_GLOW = (0, 220, 255)
DARK = (3, 10, 18)

SS = 4
FINAL = 32
OUT_DIR = "cursors"
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"  # Windows'ta yoksa kod otomatik varsayilan fonta duser

os.makedirs(OUT_DIR, exist_ok=True)


# ---------- temel motor ----------

def rgba_to_cur_bytes(img, hotspot=(0, 0)):
    assert img.mode == "RGBA"
    w, h = img.size
    px = img.load()
    xor_rows = []
    for y in range(h - 1, -1, -1):
        row = bytearray()
        for x in range(w):
            r, g, b, a = px[x, y]
            row += bytes((b, g, r, a))
        xor_rows.append(bytes(row))
    xor_data = b"".join(xor_rows)
    and_row_bytes = ((w + 31) // 32) * 4
    and_rows = []
    for y in range(h - 1, -1, -1):
        row = bytearray(and_row_bytes)
        for x in range(w):
            if px[x, y][3] == 0:
                row[x // 8] |= (1 << (7 - (x % 8)))
        and_rows.append(bytes(row))
    and_data = b"".join(and_rows)
    bmp_header = struct.pack("<IiiHHIIiiII", 40, w, h * 2, 1, 32, 0, len(xor_data), 0, 0, 0, 0)
    dib_data = bmp_header + xor_data + and_data
    hx, hy = hotspot
    buf = io.BytesIO()
    buf.write(struct.pack("<HHH", 0, 2, 1))
    buf.write(struct.pack("<BBBBHHII", w if w < 256 else 0, h if h < 256 else 0,
                           0, 0, hx, hy, len(dib_data), 22))
    buf.write(dib_data)
    return buf.getvalue()


def save_cur(img, out_path, hotspot=(0, 0)):
    with open(out_path, "wb") as f:
        f.write(rgba_to_cur_bytes(img, hotspot))


def riff_chunk(fourcc, data):
    padded = data + (b"\x00" if len(data) % 2 else b"")
    return fourcc + struct.pack("<I", len(data)) + padded


def save_ani(frames, out_path, jiffy_rate, hotspot=(0, 0)):
    frame_bytes = [rgba_to_cur_bytes(f, hotspot) for f in frames]
    n = len(frame_bytes)
    anih = struct.pack("<9I", 36, n, n, 0, 0, 0, 0, jiffy_rate, 1)
    fram_chunks = b"".join(riff_chunk(b"icon", d) for d in frame_bytes)
    fram_list = b"LIST" + struct.pack("<I", len(fram_chunks) + 4) + b"fram" + fram_chunks
    body = riff_chunk(b"anih", anih) + fram_list
    riff = b"RIFF" + struct.pack("<I", len(body) + 4) + b"ACON" + body
    with open(out_path, "wb") as f:
        f.write(riff)


def render(draw_callback, size=FINAL, ss=SS, glow_mult=1.6):
    big = size * ss
    shape = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(shape)
    draw_callback(d, ss, big)
    alpha = shape.split()[3]
    glow = Image.new("RGBA", (big, big), CYAN_GLOW + (255,))
    glow.putalpha(alpha)
    glow = glow.filter(ImageFilter.GaussianBlur(radius=ss * glow_mult))
    composed = Image.alpha_composite(Image.new("RGBA", (big, big), (0, 0, 0, 0)), glow)
    composed = Image.alpha_composite(composed, shape)
    return composed.resize((size, size), Image.LANCZOS)


def rot(pt, cx, cy, deg):
    a = math.radians(deg)
    x, y = pt[0] - cx, pt[1] - cy
    return (cx + x * math.cos(a) - y * math.sin(a), cy + x * math.sin(a) + y * math.cos(a))


def arrow_points(ss):
    return [(x * ss, y * ss) for x, y in
            [(0, 0), (0, 20), (5, 15), (8, 22), (11, 21), (8, 13), (14, 13)]]


def draw_arrow_base(d, ss, big):
    pts = arrow_points(ss)
    d.polygon(pts, fill=DARK + (235,))
    d.line(pts + [pts[0]], fill=CYAN + (255,), width=int(ss * 1.3), joint="curve")


def double_arrow(d, ss, big, angle_deg, length=13, width=2.4):
    cx = cy = big / 2
    half = length * ss
    lw = max(2, int(width * ss))
    p1 = rot((cx - half, cy), cx, cy, angle_deg)
    p2 = rot((cx + half, cy), cx, cy, angle_deg)
    d.line([p1, p2], fill=CYAN + (255,), width=lw)
    for base, tip_dir in [(p1, -1), (p2, 1)]:
        a = math.radians(angle_deg)
        dx, dy = math.cos(a) * tip_dir, math.sin(a) * tip_dir
        px_, py_ = -dy, dx
        h = 6 * ss
        wid = 4.5 * ss
        tip = (base[0] - dx * h * 0.2, base[1] - dy * h * 0.2)
        back = (base[0] + dx * h, base[1] + dy * h)
        b1 = (back[0] + px_ * wid, back[1] + py_ * wid)
        b2 = (back[0] - px_ * wid, back[1] - py_ * wid)
        d.polygon([tip, b1, b2], fill=CYAN + (255,))


# ---------- her rol icin cizim ----------

def draw_normal_select(d, ss, big):
    draw_arrow_base(d, ss, big)


def draw_help_select(d, ss, big):
    draw_arrow_base(d, ss, big)
    try:
        font = ImageFont.truetype(FONT_PATH, int(11 * ss))
    except Exception:
        font = ImageFont.load_default()
    d.text((15 * ss, 12 * ss), "?", font=font, fill=CYAN + (255,))


def draw_precision_select(d, ss, big):
    cx = cy = big / 2
    r = 9 * ss
    gap = 3 * ss
    lw = max(2, int(1.6 * ss))
    d.line([(cx - r, cy), (cx - gap, cy)], fill=CYAN + (255,), width=lw)
    d.line([(cx + gap, cy), (cx + r, cy)], fill=CYAN + (255,), width=lw)
    d.line([(cx, cy - r), (cx, cy - gap)], fill=CYAN + (255,), width=lw)
    d.line([(cx, cy + gap), (cx, cy + r)], fill=CYAN + (255,), width=lw)
    d.rectangle([cx - gap, cy - gap, cx + gap, cy + gap], outline=CYAN + (255,), width=lw)


def draw_text_select(d, ss, big):
    cx = big / 2
    top = 4 * ss
    bot = big - 4 * ss
    lw = max(2, int(1.6 * ss))
    d.line([(cx, top), (cx, bot)], fill=CYAN + (255,), width=lw)
    serif = 4 * ss
    d.line([(cx - serif, top), (cx + serif, top)], fill=CYAN + (255,), width=lw)
    d.line([(cx - serif, bot), (cx + serif, bot)], fill=CYAN + (255,), width=lw)


def draw_unavailable(d, ss, big):
    cx = cy = big / 2
    r = 11 * ss
    lw = max(2, int(2.2 * ss))
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=CYAN + (255,), width=lw)
    off = r * 0.7
    d.line([(cx - off, cy - off), (cx + off, cy + off)], fill=CYAN + (255,), width=lw)


def draw_move(d, ss, big):
    cx = cy = big / 2
    for ang in (0, 90, 180, 270):
        tip = rot((cx, cy - 12 * ss), cx, cy, ang)
        b1 = rot((cx - 3.5 * ss, cy - 7 * ss), cx, cy, ang)
        b2 = rot((cx + 3.5 * ss, cy - 7 * ss), cx, cy, ang)
        d.polygon([tip, b1, b2], fill=CYAN + (255,))
    lw = max(2, int(1.6 * ss))
    d.line([(cx - 9 * ss, cy), (cx + 9 * ss, cy)], fill=CYAN + (255,), width=lw)
    d.line([(cx, cy - 9 * ss), (cx, cy + 9 * ss)], fill=CYAN + (255,), width=lw)


def hand_mask_primitives(d, ss, extra=None):
    """El siluetini (isaret parmagi + yumruk + bas parmak) ayri primitifler olarak cizer.
    d: 'L' modunda bir ImageDraw (255 = dolu). extra: opsiyonel ek rozet cizim fonksiyonu."""
    s = lambda v: v * ss
    # isaret parmagi (dikey, sola yakin konumda -> gercek isaret parmagi hissi)
    d.rounded_rectangle([s(9), s(2), s(13), s(15)], radius=s(1.5), fill=255)
    # yumruk govdesi
    d.rounded_rectangle([s(6), s(13), s(21), s(25)], radius=s(3), fill=255)
    # bas parmak (yumruğun soluna dogru cikinti)
    d.polygon([(s(4), s(17)), (s(8), s(13.5)), (s(10), s(16)), (s(9), s(20)), (s(5), s(21))], fill=255)
    if extra:
        extra(d, ss)


def render_outlined_silhouette(mask_primitives_cb, size=FINAL, ss=SS, outline_px=1.3, glow_mult=1.6):
    """Coklu primitiften (rounded_rect, ellipse, polygon...) olusan bir siluete
    otomatik cyan kontur + glow ekler. Karmasik el/rozet sekilleri icin daha saglam."""
    big = size * ss
    mask = Image.new("L", (big, big), 0)
    dm = ImageDraw.Draw(mask)
    mask_primitives_cb(dm, ss)

    ring_px = max(2, int(ss * outline_px * 2))
    if ring_px % 2 == 0:
        ring_px += 1
    dilated = mask.filter(ImageFilter.MaxFilter(ring_px))

    outline_layer = Image.new("RGBA", (big, big), CYAN + (255,))
    outline_layer.putalpha(dilated)

    body_layer = Image.new("RGBA", (big, big), DARK + (235,))
    body_layer.putalpha(mask)

    glow_layer = Image.new("RGBA", (big, big), CYAN_GLOW + (255,))
    glow_layer.putalpha(dilated)
    glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(radius=ss * glow_mult))

    composed = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    composed = Image.alpha_composite(composed, glow_layer)
    composed = Image.alpha_composite(composed, outline_layer)
    composed = Image.alpha_composite(composed, body_layer)
    return composed.resize((size, size), Image.LANCZOS)


def draw_link_select_mask(d, ss):
    hand_mask_primitives(d, ss)


def draw_location_select_mask(d, ss):
    s = lambda v: v * ss
    def pin(dd, ss_):
        cx, cy, r = s(24), s(22), s(5)
        dd.ellipse([cx - r, cy - r, cx + r, cy + r], fill=255)
        dd.polygon([(cx - r * 0.7, cy + r * 0.5), (cx + r * 0.7, cy + r * 0.5), (cx, cy + r * 2.1)], fill=255)
        dd.ellipse([cx - r * 0.4, cy - r * 0.4, cx + r * 0.4, cy + r * 0.4], fill=0)
    hand_mask_primitives(d, ss, extra=pin)


def draw_person_select_mask(d, ss):
    s = lambda v: v * ss
    def person(dd, ss_):
        cx, cy = s(24), s(21)
        r = s(2.6)
        dd.ellipse([cx - r, cy - r * 2.2, cx + r, cy - r * 0.2], fill=255)  # kafa
        dd.rounded_rectangle([cx - r * 1.6, cy - r * 0.1, cx + r * 1.6, cy + r * 2.6], radius=s(1.5), fill=255)  # govde
    hand_mask_primitives(d, ss, extra=person)


def draw_up_arrow_mask(d, ss):
    s = lambda v: v * ss
    d.polygon([(s(16), s(2)), (s(25), s(13)), (s(19.5), s(13)), (s(19.5), s(27)),
               (s(12.5), s(27)), (s(12.5), s(13)), (s(7), s(13))], fill=255)


# ---------- spinner (Occupe / Arriere-plan) ----------

def render_spinner_frame(rot_deg, with_arrow=False, ring_r=9, ring_ss_offset=(0, 0)):
    def cb(d, ss, big):
        if with_arrow:
            draw_arrow_base(d, ss, big)
            cx, cy = 22 * ss, 22 * ss
            r = 6 * ss
        else:
            cx, cy = big / 2, big / 2
            r = ring_r * ss
        lw = max(2, int(1.8 * ss))
        n_dots = 8
        for i in range(n_dots):
            ang = rot_deg + i * (360 / n_dots)
            a = math.radians(ang)
            x = cx + math.cos(a) * r
            y = cy + math.sin(a) * r
            fade = 60 + int(195 * (i / n_dots))
            dr = lw * 0.6
            d.ellipse([x - dr, y - dr, x + dr, y + dr], fill=CYAN + (fade,))
    return render(cb, glow_mult=1.3)


# ---------- uret ----------

STATIC = {
    "jarvis_arrow.cur": (draw_normal_select, (0, 0)),
    "jarvis_help.cur": (draw_help_select, (0, 0)),
    "jarvis_precision.cur": (draw_precision_select, (16, 16)),
    "jarvis_text.cur": (draw_text_select, (16, 16)),
    "jarvis_unavailable.cur": (draw_unavailable, (16, 16)),
    "jarvis_move.cur": (draw_move, (16, 16)),
}

# Silhouette+dilate motoruyla uretilen (el tabanli + ozel) pointer'lar
SILHOUETTE = {
    "jarvis_link.cur": (draw_link_select_mask, (11, 2)),
    "jarvis_location.cur": (draw_location_select_mask, (11, 2)),
    "jarvis_person.cur": (draw_person_select_mask, (11, 2)),
    "jarvis_uparrow.cur": (draw_up_arrow_mask, (16, 2)),
}

RESIZE = {
    "jarvis_ns.cur": 90,
    "jarvis_we.cur": 0,
    "jarvis_nwse.cur": 45,
    "jarvis_nesw.cur": 135,
}

print("Statik pointer'lar uretiliyor...")
for fname, (cb, hotspot) in STATIC.items():
    img = render(cb)
    save_cur(img, os.path.join(OUT_DIR, fname), hotspot)
    print(" ", fname)

for fname, (cb, hotspot) in SILHOUETTE.items():
    img = render_outlined_silhouette(cb)
    save_cur(img, os.path.join(OUT_DIR, fname), hotspot)
    print(" ", fname)

for fname, angle in RESIZE.items():
    img = render(lambda d, ss, big, a=angle: double_arrow(d, ss, big, a))
    save_cur(img, os.path.join(OUT_DIR, fname), (16, 16))
    print(" ", fname)

print("Animasyonlu pointer'lar uretiliyor (Occupe / Arriere-plan)...")
busy_frames = [render_spinner_frame(i * (360 / 12), with_arrow=False, ring_r=8) for i in range(12)]
save_ani(busy_frames, os.path.join(OUT_DIR, "jarvis_busy.ani"), jiffy_rate=4, hotspot=(16, 16))
print("  jarvis_busy.ani")

appstart_frames = [render_spinner_frame(i * (360 / 12), with_arrow=True) for i in range(12)]
save_ani(appstart_frames, os.path.join(OUT_DIR, "jarvis_appstarting.ani"), jiffy_rate=4, hotspot=(0, 0))
print("  jarvis_appstarting.ani")

print("\nTum dosyalar '", OUT_DIR, "' klasorune yazildi.")
