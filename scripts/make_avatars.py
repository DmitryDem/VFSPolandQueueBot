"""Генерирует варианты аватарки группы (640x640 PNG)."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent.parent / "assets"
OUT.mkdir(exist_ok=True)

SIZE = 640
WHITE = (255, 255, 255)
RED = (220, 20, 60)       # польский красный (crimson)
DARK = (30, 41, 59)       # тёмно-синий для контуров
BLUE = (47, 128, 237)


def font(size: int) -> ImageFont.FreeTypeFont:
    for name in ("arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw_calendar(d: ImageDraw.ImageDraw, cx: int, cy: int, w: int, h: int,
                  header: tuple, body: tuple = WHITE, outline: tuple = DARK) -> None:
    """Календарь с колечками и сеткой, по центру (cx, cy)."""
    x0, y0 = cx - w // 2, cy - h // 2
    x1, y1 = cx + w // 2, cy + h // 2
    r = 36
    d.rounded_rectangle([x0, y0, x1, y1], radius=r, fill=body, outline=outline, width=10)
    header_h = int(h * 0.28)
    d.rounded_rectangle([x0, y0, x1, y0 + header_h + r], radius=r, fill=header)
    d.rectangle([x0, y0 + header_h, x1, y0 + header_h + 10], fill=header)
    # колечки
    ring_w, ring_h = 22, 60
    for rx in (cx - w // 4, cx + w // 4):
        d.rounded_rectangle(
            [rx - ring_w // 2, y0 - ring_h // 2, rx + ring_w // 2, y0 + ring_h // 3],
            radius=ring_w // 2, fill=outline,
        )
    return y0 + header_h


def variant_flag_calendar() -> None:
    """Флаг Польши фоном + календарь с галочкой."""
    img = Image.new("RGB", (SIZE, SIZE), WHITE)
    d = ImageDraw.Draw(img)
    d.rectangle([0, SIZE // 2, SIZE, SIZE], fill=RED)
    body_top = draw_calendar(d, SIZE // 2, SIZE // 2, 380, 380, header=RED)
    # галочка
    d.line([(SIZE // 2 - 90, SIZE // 2 + 40), (SIZE // 2 - 20, SIZE // 2 + 110),
            (SIZE // 2 + 100, SIZE // 2 - 40)], fill=(34, 160, 82), width=34, joint="curve")
    img.save(OUT / "avatar_1_flag_calendar.png")


def variant_queue() -> None:
    """Красный фон, календарь и «очередь» из точек-людей."""
    img = Image.new("RGB", (SIZE, SIZE), RED)
    d = ImageDraw.Draw(img)
    draw_calendar(d, SIZE // 2, SIZE // 2 - 40, 360, 340, header=DARK)
    f = font(150)
    d.text((SIZE // 2, SIZE // 2 + 10), "PL", font=f, fill=DARK, anchor="mm")
    # очередь из голов внизу
    y = SIZE - 105
    for i, x in enumerate(range(90, SIZE - 60, 82)):
        head_r = 20
        d.ellipse([x - head_r, y - 52 - head_r, x + head_r, y - 52 + head_r], fill=WHITE)
        d.rounded_rectangle([x - 30, y - 26, x + 30, y + 40], radius=26, fill=WHITE)
    img.save(OUT / "avatar_2_queue.png")


def variant_minimal() -> None:
    """Минимализм: бело-красный круг, крупное 'PL' и календарная сетка."""
    img = Image.new("RGB", (SIZE, SIZE), (245, 246, 248))
    d = ImageDraw.Draw(img)
    d.ellipse([40, 40, SIZE - 40, SIZE - 40], fill=WHITE, outline=RED, width=22)
    d.chord([40, 40, SIZE - 40, SIZE - 40], 0, 180, fill=RED)  # нижняя половина красная
    f_big = font(170)
    d.text((SIZE // 2, SIZE // 2 - 130), "PL", font=f_big, fill=DARK, anchor="mm")
    f_small = font(64)
    d.text((SIZE // 2, SIZE // 2 + 120), "VISA", font=f_small, fill=WHITE, anchor="mm")
    d.text((SIZE // 2, SIZE // 2 + 195), "QUEUE", font=f_small, fill=WHITE, anchor="mm")
    img.save(OUT / "avatar_3_minimal.png")


variant_flag_calendar()
variant_queue()
variant_minimal()
print("saved to", OUT)
