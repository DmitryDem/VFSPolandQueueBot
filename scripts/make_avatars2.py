"""Варианты аватарки группы с русским текстом (640x640) -> c:/Work/Скриншоты."""
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(r"c:\Work\Скриншоты")
OUT.mkdir(parents=True, exist_ok=True)

SIZE = 640
WHITE = (255, 255, 255)
RED = (215, 20, 55)
DARK = (26, 34, 51)
GREEN = (34, 160, 82)
FONTS = Path(r"C:\Windows\Fonts")


def font(size, bold=True):
    return ImageFont.truetype(str(FONTS / ("arialbd.ttf" if bold else "arial.ttf")), size)


def queue_figures(d, y, xs, r=17, color=WHITE):
    """Ряд человечков (голова + плечи)."""
    for x in xs:
        d.ellipse([x - r, y - 46 - r, x + r, y - 46 + r], fill=color)
        d.rounded_rectangle([x - 26, y - 24, x + 26, y + 34], radius=22, fill=color)


# ---- 1. «ВИЗА PL» на флаге + очередь ----
def v1():
    img = Image.new("RGB", (SIZE, SIZE), WHITE)
    d = ImageDraw.Draw(img)
    d.rectangle([0, SIZE // 2, SIZE, SIZE], fill=RED)
    d.text((SIZE // 2, 148), "ВИЗА", font=font(150), fill=DARK, anchor="mm")
    d.text((SIZE // 2, 288), "в Польшу", font=font(72), fill=RED, anchor="mm")
    queue_figures(d, SIZE - 150, range(105, SIZE - 60, 108))
    d.text((SIZE // 2, SIZE - 62), "живая очередь VFS", font=font(44), fill=WHITE, anchor="mm")
    img.save(OUT / "аватар_1_виза_в_польшу.png")


# ---- 2. «ОЧЕРЕДЬ» + календарь ----
def v2():
    img = Image.new("RGB", (SIZE, SIZE), RED)
    d = ImageDraw.Draw(img)
    # календарь
    cx, cy, w, h = SIZE // 2, 260, 300, 260
    x0, y0, x1, y1 = cx - w // 2, cy - h // 2, cx + w // 2, cy + h // 2
    d.rounded_rectangle([x0, y0, x1, y1], radius=28, fill=WHITE)
    d.rounded_rectangle([x0, y0, x1, y0 + 74], radius=28, fill=DARK)
    d.rectangle([x0, y0 + 46, x1, y0 + 74], fill=DARK)
    for rx in (cx - w // 4, cx + w // 4):
        d.rounded_rectangle([rx - 10, y0 - 26, rx + 10, y0 + 14], radius=10, fill=DARK)
    d.text((cx, y0 + 40), "ПОЛЬША", font=font(40), fill=WHITE, anchor="mm")
    d.text((cx, cy + 40), "PL", font=font(120), fill=RED, anchor="mm")
    d.text((SIZE // 2, 490), "ОЧЕРЕДЬ", font=font(96), fill=WHITE, anchor="mm")
    d.text((SIZE // 2, 575), "на подачу в VFS", font=font(46), fill=WHITE, anchor="mm")
    img.save(OUT / "аватар_2_очередь_календарь.png")


# ---- 3. Печать-штамп ----
def circular_text(img, text, cx, cy, radius, fnt, fill, start_deg=-90):
    n = len(text)
    step = 360 / max(n, 1)
    for i, ch in enumerate(text):
        ang = math.radians(start_deg + i * step)
        x = cx + radius * math.cos(ang)
        y = cy + radius * math.sin(ang)
        ch_img = Image.new("RGBA", (80, 80), (0, 0, 0, 0))
        cd = ImageDraw.Draw(ch_img)
        cd.text((40, 40), ch, font=fnt, fill=fill, anchor="mm")
        ch_img = ch_img.rotate(-(math.degrees(ang) + 90), resample=Image.BICUBIC, center=(40, 40))
        img.paste(ch_img, (int(x) - 40, int(y) - 40), ch_img)


def v3():
    img = Image.new("RGB", (SIZE, SIZE), (246, 243, 236))
    d = ImageDraw.Draw(img)
    cx = cy = SIZE // 2
    for r, wd in ((292, 12), (216, 6)):
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=RED, width=wd)
    circular_text(img, "ПОЛЬСКАЯ ВИЗА • ОЧЕРЕДЬ VFS • ", cx, cy, 253, font(46), RED)
    d = ImageDraw.Draw(img)
    d.text((cx, cy - 40), "PL", font=font(160), fill=RED, anchor="mm")
    d.text((cx, cy + 78), "ЖДЁМ", font=font(58), fill=RED, anchor="mm")
    d.text((cx, cy + 138), "ВМЕСТЕ", font=font(58), fill=RED, anchor="mm")
    img.save(OUT / "аватар_3_штамп.png")


# ---- 4. Письмо-приглашение ----
def v4():
    img = Image.new("RGB", (SIZE, SIZE), DARK)
    d = ImageDraw.Draw(img)
    # конверт
    ex, ey, ew, eh = SIZE // 2, 230, 340, 220
    x0, y0, x1, y1 = ex - ew // 2, ey - eh // 2, ex + ew // 2, ey + eh // 2
    d.rounded_rectangle([x0, y0, x1, y1], radius=18, fill=WHITE)
    d.polygon([(x0, y0 + 8), (ex, ey + 20), (x1, y0 + 8)], fill=(228, 228, 232), outline=DARK)
    d.line([(x0, y0 + 8), (ex, ey + 20), (x1, y0 + 8)], fill=DARK, width=6)
    # марка-флаг
    d.rectangle([x1 - 74, y0 + 16, x1 - 18, y0 + 44], fill=WHITE, outline=RED, width=3)
    d.rectangle([x1 - 74, y0 + 30, x1 - 18, y0 + 44], fill=RED)
    # галочка
    d.line([(ex - 55, ey + 55), (ex - 12, ey + 95), (ex + 68, ey + 5)], fill=GREEN, width=22, joint="curve")
    d.text((SIZE // 2, 470), "ЖДЁШЬ ПИСЬМО?", font=font(64), fill=WHITE, anchor="mm")
    d.text((SIZE // 2, 553), "очередь на визу • Польша", font=font(42), fill=(255, 130, 150), anchor="mm")
    img.save(OUT / "аватар_4_письмо.png")


v1()
v2()
v3()
v4()
print("saved 4 variants")
