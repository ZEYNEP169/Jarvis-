from PIL import Image, ImageDraw, ImageFilter
import struct

# JARVIS arayüzünden alınan renkler
CYAN = (0, 180, 255)
CYAN_GLOW = (0, 220, 255)
GOLD = (198, 155, 10)
DARK = (3, 10, 18)

SS = 4          # supersample çarpanı (anti-aliasing için)
FINAL = 32      # gerçek cursor boyutu


def build_cur_from_rgba(img: Image.Image, hotspot=(0, 0), out_path="jarvis_cursor.cur"):
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
            a = px[x, y][3]
            if a == 0:
                row[x // 8] |= (1 << (7 - (x % 8)))
        and_rows.append(bytes(row))
    and_data = b"".join(and_rows)

    bmp_header = struct.pack(
        "<IiiHHIIiiII",
        40, w, h * 2, 1, 32, 0, len(xor_data), 0, 0, 0, 0
    )
    dib_data = bmp_header + xor_data + and_data

    hx, hy = hotspot
    with open(out_path, "wb") as f:
        f.write(struct.pack("<HHH", 0, 2, 1))
        f.write(struct.pack(
            "<BBBBHHII",
            w if w < 256 else 0, h if h < 256 else 0,
            0, 0, hx, hy, len(dib_data), 22
        ))
        f.write(dib_data)
    return out_path


def make_arrow_points(scale):
    return [(x * scale, y * scale) for x, y in
            [(0, 0), (0, 20), (5, 15), (8, 22), (11, 21), (8, 13), (14, 13)]]


def create_jarvis_cursor(out_name="jarvis_cursor.cur"):
    big = FINAL * SS
    mask = Image.new('L', (big, big), 0)
    ImageDraw.Draw(mask).polygon(make_arrow_points(SS), fill=255)

    base = Image.new('RGBA', (big, big), (0, 0, 0, 0))

    # Dış parlama (glow)
    glow = Image.new('RGBA', (big, big), (0, 0, 0, 0))
    glow.paste(Image.new('RGBA', (big, big), CYAN_GLOW + (255,)), (0, 0), mask)
    glow = glow.filter(ImageFilter.GaussianBlur(radius=SS * 1.6))

    # Koyu lacivert gövde
    core = Image.new('RGBA', (big, big), (0, 0, 0, 0))
    core.paste(Image.new('RGBA', (big, big), DARK + (235,)), (0, 0), mask)

    # Cyan kontur + altın aksan noktası
    outline_img = Image.new('RGBA', (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(outline_img)
    pts = make_arrow_points(SS)
    d.line(pts + [pts[0]], fill=CYAN + (255,), width=int(SS * 1.3), joint='curve')

    composed = Image.alpha_composite(base, glow)
    composed = Image.alpha_composite(composed, core)
    composed = Image.alpha_composite(composed, outline_img)

    final_img = composed.resize((FINAL, FINAL), Image.LANCZOS)

    path = build_cur_from_rgba(final_img, hotspot=(0, 0), out_path=out_name)
    print(f"İmleç oluşturuldu: {path}")
    return path


if __name__ == "__main__":
    create_jarvis_cursor() 
import struct
import math
import io

CYAN = (0, 180, 255)
CYAN_GLOW = (0, 220, 255)
DARK = (3, 10, 18)

SS = 4
FINAL = 32
FRAME_COUNT = 16      # bir nefes alma dongusunde kac kare olsun
JIFFY_RATE = 5         # kare basina jiffy (1 jiffy = 1/60 sn) -> 5 jiffy ~ 0.083 sn/kare


def make_arrow_points(scale):
    return [(x * scale, y * scale) for x, y in
            [(0, 0), (0, 20), (5, 15), (8, 22), (11, 21), (8, 13), (14, 13)]]


def render_frame(glow_alpha, glow_radius):
    big = FINAL * SS
    mask = Image.new('L', (big, big), 0)
    ImageDraw.Draw(mask).polygon(make_arrow_points(SS), fill=255)

    base = Image.new('RGBA', (big, big), (0, 0, 0, 0))

    glow = Image.new('RGBA', (big, big), (0, 0, 0, 0))
    glow.paste(Image.new('RGBA', (big, big), CYAN_GLOW + (int(glow_alpha),)), (0, 0), mask)
    glow = glow.filter(ImageFilter.GaussianBlur(radius=glow_radius))

    core = Image.new('RGBA', (big, big), (0, 0, 0, 0))
    core.paste(Image.new('RGBA', (big, big), DARK + (235,)), (0, 0), mask)

    outline_img = Image.new('RGBA', (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(outline_img)
    pts = make_arrow_points(SS)
    d.line(pts + [pts[0]], fill=CYAN + (255,), width=int(SS * 1.3), joint='curve')

    composed = Image.alpha_composite(base, glow)
    composed = Image.alpha_composite(composed, core)
    composed = Image.alpha_composite(composed, outline_img)

    return composed.resize((FINAL, FINAL), Image.LANCZOS)


def rgba_to_cur_bytes(img: Image.Image, hotspot=(0, 0)) -> bytes:
    """Tek bir karenin tam .cur dosyasi icerigini bytes olarak uretir (ANI icindeki 'icon' chunk'i icin)."""
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
            a = px[x, y][3]
            if a == 0:
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


def riff_chunk(fourcc: bytes, data: bytes) -> bytes:
    padded = data + (b"\x00" if len(data) % 2 else b"")
    return fourcc + struct.pack("<I", len(data)) + padded


def build_ani(frames_cur_bytes, jiffy_rate, out_path):
    n = len(frames_cur_bytes)

    # ANIHEADER: 9 DWORD alan, toplam 36 bayt
    # [cbSizeof, cFrames, cSteps, cx, cy, cBitCount, cPlanes, JifRate, flags]
    anih = struct.pack(
        "<9I",
        36, n, n, 0, 0, 0, 0, jiffy_rate, 1  # flags=1 -> AF_ICON (kareler .cur verisi)
    )

    fram_chunks = b"".join(riff_chunk(b"icon", data) for data in frames_cur_bytes)
    fram_list = b"LIST" + struct.pack("<I", len(fram_chunks) + 4) + b"fram" + fram_chunks

    body = riff_chunk(b"anih", anih) + fram_list
    riff = b"RIFF" + struct.pack("<I", len(body) + 4) + b"ACON" + body

    with open(out_path, "wb") as f:
        f.write(riff)
    return out_path


def create_animated_jarvis_cursor(out_name="jarvis_cursor.ani"):
    frames = []
    for i in range(FRAME_COUNT):
        t = i / FRAME_COUNT
        pulse = (math.sin(t * 2 * math.pi) + 1) / 2   # 0..1 nefes egrisi
        glow_alpha = 130 + pulse * 125                # 130..255
        glow_radius = SS * (1.1 + pulse * 1.3)         # 1.1SS..2.4SS
        frames.append(render_frame(glow_alpha, glow_radius))

    frame_bytes = [rgba_to_cur_bytes(f, hotspot=(0, 0)) for f in frames]
    path = build_ani(frame_bytes, JIFFY_RATE, out_name)
    print(f"Animasyonlu imlec olusturuldu: {path} ({FRAME_COUNT} kare)")
    return path, frames


if __name__ == "__main__":
    create_animated_jarvis_cursor()