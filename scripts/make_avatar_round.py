"""Круглая версия аватарки (без слова «живая») + предпросмотр как в Telegram."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(r"c:\Work\Скриншоты")
SIZE = 640
WHITE = (255, 255, 255)
RED = (215, 20, 55)
DARK = (26, 34, 51)
FONTS = Path(r"C:\Windows\Fonts")


def font(size):
    return ImageFont.truetype(str(FONTS / "arialbd.ttf"), size)


def queue_figures(d, y, xs, color=WHITE):
    for x in xs:
        r = 15
        d.ellipse([x - r, y - 42 - r, x + r, y - 42 + r], fill=color)
        d.rounded_rectangle([x - 23, y - 22, x + 23, y + 30], radius=20, fill=color)


def build() -> Image.Image:
    img = Image.new("RGB", (SIZE, SIZE), WHITE)
    d = ImageDraw.Draw(img)
    cx = cy = SIZE // 2
    R = 318
    # круглая композиция: верхняя половина белая, нижняя красная, кольцо по краю
    d.ellipse([cx - R, cy - R, cx + R, cy + R], fill=WHITE)
    d.pieslice([cx - R, cy - R, cx + R, cy + R], 0, 180, fill=RED)
    d.ellipse([cx - R, cy - R, cx + R, cy + R], outline=RED, width=12)
    d.text((cx, 165), "ВИЗА", font=font(128), fill=DARK, anchor="mm")
    d.text((cx, 272), "в Польшу", font=font(64), fill=RED, anchor="mm")
    queue_figures(d, cy + 130, range(cx - 190, cx + 200, 95))
    d.text((cx, cy + 235), "очередь VFS", font=font(48), fill=WHITE, anchor="mm")
    return img


def telegram_preview(img: Image.Image) -> Image.Image:
    """Как это увидят в Telegram: круглая обрезка на фоне списка чатов."""
    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, SIZE, SIZE], fill=255)
    sizes = [(360, 60), (160, 470), (86, 470 + 200)]
    canvas = Image.new("RGB", (900, 700), "#ffffff")
    d = ImageDraw.Draw(canvas)
    d.text((450, 24), "Предпросмотр: так аватарку обрежет Telegram", font=font(30),
           fill="#333333", anchor="mm")
    x = 70
    for s, y in [(360, 80), (170, 480), (90, 480)]:
        cropped = img.resize((s, s), Image.LANCZOS)
        m = mask.resize((s, s), Image.LANCZOS)
        px = 450 - s // 2 if s == 360 else x
        canvas.paste(cropped, (px, y), m)
        if s != 360:
            x += s + 60
    return canvas


img = build()
img.save(OUT / "аватар_5_круглый.png")
telegram_preview(img).save(OUT / "аватар_5_круглый_превью.png")
print("saved")
