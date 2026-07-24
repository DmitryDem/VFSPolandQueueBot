"""Мокапы улучшений бота: графики (matplotlib) и телеграм-сообщения (PIL).

Складывает PNG в c:/Work/Скриншоты.
"""
import re
from datetime import date, timedelta
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from PIL import Image, ImageDraw, ImageFont

OUT = Path(r"c:\Work\Скриншоты")
OUT.mkdir(parents=True, exist_ok=True)

# валидированная палитра (dataviz reference)
SURFACE = "#fcfcfb"
TEXT = "#0b0b0b"
TEXT2 = "#52514e"
BLUE = "#2a78d6"
GREEN = "#008300"
NEUTRAL = "#d8d7d3"
GRID = "#e6e5e1"


def style_ax(ax, title):
    ax.set_facecolor(SURFACE)
    ax.set_title(title, color=TEXT, fontsize=12, loc="left", pad=12, fontweight="bold")
    ax.tick_params(colors=TEXT2, labelsize=9)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def fig_new(h=4.8):
    fig, ax = plt.subplots(figsize=(8.4, h), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    return fig, ax


# ---------------- 1. Приглашения: бары + скользящее среднее ----------------
def chart_invitations():
    today = date(2026, 7, 20)
    days = [today - timedelta(days=i) for i in range(29, -1, -1)]
    vals = [3, 4, 2, 5, 6, 4, 1, 5, 7, 6, 8, 5, 2, 6, 9, 7, 8, 10, 4, 2,
            9, 11, 10, 12, 8, 3, 12, 15, 13, 17]
    ma = [sum(vals[max(0, i - 6):i + 1]) / len(vals[max(0, i - 6):i + 1]) for i in range(len(vals))]

    fig, ax = fig_new()
    style_ax(ax, "Минск — D (Other) · Приглашения в визовый центр, 30 дней")
    ax.bar(days, vals, color=BLUE, width=0.72, zorder=2)
    ax.plot(days, ma, color=GREEN, linewidth=2, zorder=3)
    ax.annotate("среднее за 7 дней", xy=(days[22], ma[22]), xytext=(days[13], 15.3),
                color=GREEN, fontsize=9,
                arrowprops=dict(arrowstyle="-", color=GREEN, lw=0.8))
    # выборочные подписи: пик и последний день
    peak = max(range(len(vals)), key=lambda i: vals[i])
    for i in {peak, len(vals) - 1}:
        ax.text(days[i], vals[i] + 0.4, str(vals[i]), ha="center",
                color=TEXT, fontsize=9, fontweight="bold")
    ax.set_ylabel("приглашений (по анкетам)", color=TEXT2, fontsize=9)
    ax.set_xticks(days[::5])
    ax.set_xticklabels([d.strftime("%d.%m") for d in days[::5]])
    ax.margins(x=0.02)
    fig.text(0.055, 0.015, "исключены как ошибки: 17.07 (1 анкета) · срез 20.07.2026",
             color=TEXT2, fontsize=8)
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(OUT / "01_приглашения_бары_и_среднее.png", facecolor=SURFACE)
    plt.close(fig)


# ---------------- 2. Фронт очереди: месяц × (получили | ждут) ----------------
def chart_months_progress():
    months = ["02.2026", "03.2026", "04.2026", "05.2026", "06.2026", "07.2026"]
    done = [20, 21, 80, 7, 0, 0]
    wait = [0, 0, 0, 2, 7, 3]

    fig, ax = fig_new(4.2)
    style_ax(ax, "Минск — D (Other) · Фронт очереди по месяцам постановки")
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    y = range(len(months))
    ax.barh(y, done, color=BLUE, height=0.62, zorder=2, label="письмо получено")
    ax.barh(y, wait, left=[d + 0.6 for d in done], color=NEUTRAL, height=0.62,
            zorder=2, label="ещё ждут")
    for i, (d, w) in enumerate(zip(done, wait)):
        pct = round(100 * d / (d + w)) if d + w else 0
        ax.text(d + w + 2.2, i, f"{pct}%  ({d} из {d + w})", va="center",
                color=TEXT, fontsize=9, fontweight="bold")
    ax.set_yticks(list(y))
    ax.set_yticklabels(months)
    ax.invert_yaxis()
    ax.set_xlim(0, 100)
    ax.legend(loc="lower right", frameon=False, fontsize=9, labelcolor=TEXT2)
    fig.text(0.055, 0.015, "видно, до какого месяца «дошла» очередь · срез 20.07.2026",
             color=TEXT2, fontsize=8)
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(OUT / "02_фронт_очереди_по_месяцам.png", facecolor=SURFACE)
    plt.close(fig)


# ---------------- 3. Тренд медианы ожидания ----------------
def chart_median_trend():
    weeks = ["01.06", "08.06", "15.06", "22.06", "29.06", "06.07", "13.07", "20.07"]
    med = [96, 94, 90, 91, 88, 86, 84, 82]

    fig, ax = fig_new(4.2)
    style_ax(ax, "Минск — D (Other) · Медианное ожидание письма, по неделям")
    ax.plot(weeks, med, color=BLUE, linewidth=2, marker="o", markersize=5, zorder=3)
    ax.fill_between(weeks, med, 75, color=BLUE, alpha=0.06, zorder=1)
    ax.text(weeks[-1], med[-1] - 2.6, f"{med[-1]} дн.", color=TEXT,
            fontsize=10, fontweight="bold", ha="center")
    ax.annotate("очередь ускоряется: −14 дн. за 2 месяца", xy=(weeks[5], med[5]),
                xytext=(weeks[1], 79), color=TEXT2, fontsize=9,
                arrowprops=dict(arrowstyle="-", color=TEXT2, lw=0.8))
    ax.set_ylabel("дней от постановки до письма", color=TEXT2, fontsize=9)
    ax.set_ylim(74, 100)
    fig.tight_layout()
    fig.savefig(OUT / "03_тренд_медианы_ожидания.png", facecolor=SURFACE)
    plt.close(fig)


# ---------------- 4. Сравнение городов ----------------
def chart_cities():
    cities = ["Минск", "Гомель", "Брест", "Гродно", "Витебск", "Могилев",
              "Барановичи", "Лида", "Пинск"]
    med = [82, 74, 90, 95, 71, 78, 66, 62, 58]
    order = sorted(range(len(cities)), key=lambda i: med[i])

    fig, ax = fig_new(4.8)
    style_ax(ax, "D (Other) · Медианное ожидание письма по городам")
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    y = range(len(order))
    ax.barh(y, [med[i] for i in order], color=BLUE, height=0.62, zorder=2)
    for pos, i in enumerate(order):
        ax.text(med[i] + 1.5, pos, f"{med[i]} дн.", va="center", color=TEXT, fontsize=9)
    ax.set_yticks(list(y))
    ax.set_yticklabels([cities[i] for i in order])
    ax.invert_yaxis()
    ax.set_xlim(0, 108)
    fig.text(0.055, 0.015, "для ежедневной сводки в теме «Статистика» · срез 20.07.2026",
             color=TEXT2, fontsize=8)
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(OUT / "04_сравнение_городов.png", facecolor=SURFACE)
    plt.close(fig)


# ---------------- телеграм-мокапы ----------------
EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF☀-➿←-⇿⬀-⯿️⏩-⏺]"
)


def load_fonts():
    base = Path(r"C:\Windows\Fonts")
    return {
        "regular": ImageFont.truetype(str(base / "segoeui.ttf"), 30),
        "bold": ImageFont.truetype(str(base / "segoeuib.ttf"), 30),
        "small": ImageFont.truetype(str(base / "segoeui.ttf"), 24),
        "mono": ImageFont.truetype(str(base / "consola.ttf"), 28),
        "emoji": ImageFont.truetype(str(base / "seguiemj.ttf"), 28),
    }


def draw_mixed(draw, pos, text, fonts, font_key="regular", fill=TEXT):
    """Рисует строку, переключаясь на эмодзи-шрифт для эмодзи (цветные, если поддерживается)."""
    x, y = pos
    runs = []
    cur, cur_emoji = "", False
    for ch in text:
        is_e = bool(EMOJI_RE.match(ch))
        if cur and is_e != cur_emoji:
            runs.append((cur, cur_emoji))
            cur = ""
        cur += ch
        cur_emoji = is_e
    if cur:
        runs.append((cur, cur_emoji))
    for run, is_e in runs:
        if is_e:
            f = fonts["emoji"]
            try:
                draw.text((x, y + 3), run, font=f, embedded_color=True)
            except TypeError:
                draw.text((x, y + 3), run, font=f, fill=fill)
            x += draw.textlength(run, font=f)
        else:
            f = fonts[font_key]
            draw.text((x, y), run, font=f, fill=fill)
            x += draw.textlength(run, font=f)


def bubble(width, lines, out_name, buttons=None):
    """lines: (text, font_key, color); None = разделитель."""
    fonts = load_fonts()
    pad, lh = 36, 44
    height = pad * 2 + lh * sum(1 for _ in lines) + (90 * len(buttons) if buttons else 0) + 20
    img = Image.new("RGB", (width, height + 40), "#e7ebf0")  # фон чата Telegram
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([20, 20, width - 20, height + 20], radius=26, fill="white")
    y = pad + 10
    for line in lines:
        if line is None:
            d.line([(pad + 10, y + lh // 2 - 4), (width - pad - 20, y + lh // 2 - 4)],
                   fill="#e3e2de", width=2)
            y += lh - 12
            continue
        text, key, color = line
        if key == "mono":
            d.text((pad + 10, y + 2), text, font=fonts["mono"], fill=color)
        else:
            draw_mixed(d, (pad + 10, y), text, fonts, key, color)
        y += lh
    if buttons:
        for label in buttons:
            y += 14
            d.rounded_rectangle([pad + 10, y, width - pad - 20, y + 64], radius=14,
                                outline="#54a0e0", width=2, fill="#f2f8fd")
            w = d.textlength(label, font=fonts["small"])
            draw_mixed(d, ((width - w) // 2 - 10, y + 16), label, fonts, "small", "#1c6fb8")
            y += 64
    img.save(OUT / out_name)


def mock_stats_message():
    bubble(
        980,
        [
            ("📊 МИНСК — Национальная D (Other)", "bold", TEXT),
            None,
            ("Анкет 144   ·   ✉️ получили 132   ·   ⏳ ждут 12", "regular", TEXT),
            None,
            ("⏱ Ожидание письма:  85 дн. (медиана)", "regular", TEXT),
            ("🚀 Скорость:  6.1 приглашений/день  ↗ ускоряется", "regular", TEXT),
            ("🗓 Слот после письма:  ~31 дн.", "regular", TEXT),
            None,
            ("Приглашения по датам", "bold", TEXT),
            ("14.07  █████████░░░  17", "mono", TEXT),
            ("15.07  ████████░░░░  16", "mono", TEXT),
            ("16.07  ████████████  20", "mono", TEXT),
            ("18.07  ███████░░░░░  15", "mono", TEXT),
            ("19.07  ██████████░░  18", "mono", TEXT),
            ("исключено как ошибка: 17.07 (1 анкета)", "small", TEXT2),
            None,
            ("Фронт очереди (% получивших письмо)", "bold", TEXT),
            ("02–04.26  ████████████  100%", "mono", TEXT),
            ("05.2026   █████████░░░  78%", "mono", TEXT),
            ("06.2026   ░░░░░░░░░░░░  0%", "mono", TEXT),
            ("07.2026   ░░░░░░░░░░░░  0%", "mono", TEXT),
            None,
            ("🔮 Встали сегодня → письмо ≈ 13.10.2026 (~85 дн.)", "regular", TEXT),
            ("Срез 20.07 · за неделю +23 анкеты", "small", TEXT2),
        ],
        "05_мокап_сообщения_статистики.png",
        buttons=["🔮 Посчитать мой прогноз"],
    )


def mock_report_message():
    bubble(
        980,
        [
            ("✅ Анкета засчитана — спасибо!", "bold", TEXT),
            None,
            ("🏙 Минск   ·   📄 Национальная D (Other)", "regular", TEXT),
            ("⏳ В очереди:  15.03.2026 в 09:15  (128-й день)", "regular", TEXT),
            ("📬 Письмо:  ещё не пришло", "regular", TEXT),
            ("📆 Даты записи:  —", "regular", TEXT),
            None,
            ("Ваш вклад в статистику: по Минску теперь 145 анкет,", "small", TEXT2),
            ("точность прогноза выросла. Следующая анкета — через 14 дней,", "small", TEXT2),
            ("исправить данные можно в любой момент: /report", "small", TEXT2),
        ],
        "06_мокап_сообщения_анкеты.png",
        buttons=["👀 Посмотреть публикацию", "🔮 Мой прогноз"],
    )


chart_invitations()
chart_months_progress()
chart_median_trend()
chart_cities()
mock_stats_message()
mock_report_message()
print("saved:", *[p.name for p in sorted(OUT.glob('*.png'))], sep="\n  ")
