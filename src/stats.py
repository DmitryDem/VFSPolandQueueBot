"""Статистика и прогноз очереди по анкетам пользователей.

Терминология:
- «завершённая» анкета — есть и дата постановки в очередь, и дата письма-приглашения;
- «ожидающая» — письмо ещё не пришло;
- скорость очереди — приглашений в день за последние N дней;
- горизонт записи — через сколько дней после письма дают ближайший слот в ВЦ;
- фронт очереди — доля получивших письмо в разрезе месяца постановки;
- выбросы — даты, по которым анкет аномально мало на фоне остальных
  (вероятно, дата указана ошибочно), из сводки исключаются.

Результаты кешируются на CACHE_TTL секунд; новая/изменённая анкета сбрасывает
кеш своей пары (город, тип визы) — см. note_write.
"""
from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from statistics import median
from tempfile import NamedTemporaryFile

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from src import db

VELOCITY_WINDOW_DAYS = 14   # окно для скорости очереди
WAIT_WINDOW_DAYS = 60       # окно «свежих» приглашений для медианного ожидания
LAST_DATES_SHOWN = 7        # сколько последних дат письма показывать
MIN_DATES_FOR_OUTLIERS = 4  # с какого числа разных дат включать отсев выбросов
OUTLIER_WINDOW_DAYS = 30    # выбросы ищем среди свежих дат
HORIZON_WINDOW_DAYS = 30    # окно «текущего» горизонта записи
MONTHS_SHOWN = 6            # сколько месяцев постановки показывать
CACHE_TTL = 3600            # кеш статистики, секунд
CACHE_MAX_WRITES = 1        # сколько новых анкет кеш может «пережить» до сброса
                            # (1 = сброс на каждую запись; кеш ускоряет только чтение)
SPIKE_MIN_COUNT = 3         # минимум приглашений за дату для алерта
SPIKE_VELOCITY_FACTOR = 2   # во сколько раз выше средней скорости
SUSPECT_MIN_DAYS = 7        # абсолютный пол правдоподобного ожидания письма
SUSPECT_MEDIAN_FRACTION = 0.25  # подозрительно, если ожидание < 25% медианы

BOT_TAG = "@Visa_Poland_Info_Bot"

# палитра графиков (валидированная, светлая тема)
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK2 = "#52514e"
BLUE = "#2a78d6"
GREEN = "#008300"
NEUTRAL = "#d8d7d3"
GRID = "#e6e5e1"


def _d(iso: str) -> date:
    return datetime.strptime(iso, "%Y-%m-%d").date()


def _fmt(d: date) -> str:
    return d.strftime("%d.%m.%Y")


@dataclass
class Stats:
    city: str
    visa_type: str
    total: int = 0
    completed: list[tuple[date, date]] = field(default_factory=list)  # (в очередь, письмо)
    pending: list[date] = field(default_factory=list)                 # в очередь, ждут письмо
    counts: dict[date, int] = field(default_factory=dict)             # приглашений на дату письма
    outliers: dict[date, int] = field(default_factory=dict)           # отброшенные даты
    median_wait: int | None = None       # медианное ожидание письма, дней
    velocity: float | None = None        # приглашений/день, последние 14 дн.
    velocity_prev: float | None = None   # приглашений/день, предыдущие 14 дн.
    forecast_wait: int | None = None     # прогноз ожидания для вставших сегодня
    horizon_median: int | None = None    # горизонт записи, дней (последние 30 дн.)
    horizon_prev: int | None = None      # горизонт записи в предыдущие 30 дн.
    months: list[tuple[str, int, int]] = field(default_factory=list)  # (MM.YYYY, с письмом, всего)
    queue_months: list[tuple[str, int]] = field(default_factory=list)  # (MM.YYYY, постановок)
    queue_days: dict[date, int] = field(default_factory=dict)          # постановки по дням акт. месяца
    queue_day_outliers: dict[date, int] = field(default_factory=dict)
    active_month: str | None = None
    weekly_medians: list[tuple[str, int]] = field(default_factory=list)  # (дата нач. недели, медиана)
    passport_median: int | None = None   # подача -> паспорт, дней (медиана)
    approved: int = 0                    # виз получено
    refused: int = 0                     # отказов
    invites_today: int = 0               # приглашений с сегодняшней датой письма
    recent_7d: int = 0                   # анкет за последние 7 дней
    suspect_count: int = 0               # сомнительных анкет (исключены из расчётов)
    last_letter: date | None = None      # дата самого свежего письма
    front_queue_date: date | None = None # самая поздняя постановка среди получивших письмо
    front_queue_time: str | None = None  # её время (если указано)


# ---------- кеш ----------
# Инвалидация: по TTL ИЛИ по числу новых анкет с момента расчёта — что раньше.

_CACHE: dict[tuple[str, str], tuple[float, Stats]] = {}
_WRITES: dict[tuple[str, str], int] = {}


def collect_cached(city: str, visa_type: str) -> Stats:
    key = (city, visa_type)
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < CACHE_TTL and _WRITES.get(key, 0) < CACHE_MAX_WRITES:
        return hit[1]
    s = collect(city, visa_type)
    _CACHE[key] = (time.time(), s)
    _WRITES[key] = 0
    return s


def note_write(city: str, visa_type: str) -> None:
    key = (city, visa_type)
    _WRITES[key] = _WRITES.get(key, 0) + 1
    if _WRITES[key] >= CACHE_MAX_WRITES:
        invalidate(city, visa_type)


def invalidate(city: str, visa_type: str) -> None:
    _CACHE.pop((city, visa_type), None)
    _WRITES.pop((city, visa_type), None)


# ---------- расчёты ----------

def drop_outliers(
    counts: dict[date, int], today: date | None = None
) -> tuple[dict[date, int], dict[date, int]]:
    """Свежие даты с аномально малым числом анкет (< медианы окна / 5) — ошибки ввода."""
    today = today or date.today()
    window_start = today - timedelta(days=OUTLIER_WINDOW_DAYS)
    window = {d: c for d, c in counts.items() if d >= window_start}
    if len(window) < MIN_DATES_FOR_OUTLIERS:
        return counts, {}
    med = median(window.values())
    threshold = med / 5
    dropped = {d: c for d, c in window.items() if c < threshold}
    kept = {d: c for d, c in counts.items() if d not in dropped}
    return kept, dropped


def _filter_day_outliers(days: dict[date, int]) -> tuple[dict[date, int], dict[date, int]]:
    if len(days) < MIN_DATES_FOR_OUTLIERS:
        return days, {}
    med = median(days.values())
    threshold = med / 5
    kept = {d: c for d, c in days.items() if c >= threshold}
    dropped = {d: c for d, c in days.items() if c < threshold}
    return kept, dropped


def collect(city: str, visa_type: str, today: date | None = None) -> Stats:
    today = today or date.today()
    s = Stats(city=city, visa_type=visa_type)
    horizons: list[tuple[date, int]] = []
    month_totals: Counter = Counter()
    month_completed: Counter = Counter()
    queue_dates: list[date] = []
    passport_waits: list[int] = []

    for row in db.reports_for(city, visa_type):
        s.total += 1
        if row["suspect"]:
            s.suspect_count += 1
            continue  # сомнительные анкеты в расчёты не идут
        qd = _d(row["queue_date"])
        queue_dates.append(qd)
        month = qd.strftime("%m.%Y")
        month_totals[month] += 1
        if row["outcome"] == "APPROVED":
            s.approved += 1
        elif row["outcome"] == "REFUSED":
            s.refused += 1
        if row["submit_date"] and row["passport_date"]:
            pw = (_d(row["passport_date"]) - _d(row["submit_date"])).days
            if pw >= 0:
                passport_waits.append(pw)
        if row["letter_date"]:
            ld = _d(row["letter_date"])
            s.completed.append((qd, ld))
            month_completed[month] += 1
            # фронт очереди: до кого дошли приглашения (по позиции постановки)
            key = (qd, row["queue_time"] or "")
            if s.front_queue_date is None or key > (s.front_queue_date, s.front_queue_time or ""):
                s.front_queue_date, s.front_queue_time = qd, row["queue_time"]
            if s.last_letter is None or ld > s.last_letter:
                s.last_letter = ld
            if row["slots"]:
                try:
                    first_slot = min(_d(pair[0]) for pair in json.loads(row["slots"]))
                    h = (first_slot - ld).days
                    if h >= 0:
                        horizons.append((ld, h))
                except (ValueError, TypeError):
                    pass
        else:
            s.pending.append(qd)

    raw_counts = Counter(ld for _, ld in s.completed)
    s.counts, s.outliers = drop_outliers(dict(raw_counts), today)
    s.invites_today = s.counts.get(today, raw_counts.get(today, 0))
    s.recent_7d = db.count_recent(city, visa_type, days=7)

    # медианное ожидание по свежим приглашениям (окно), фолбэк — по всем
    recent = [
        (ld - qd).days
        for qd, ld in s.completed
        if ld >= today - timedelta(days=WAIT_WINDOW_DAYS) and ld in s.counts
    ]
    all_waits = [(ld - qd).days for qd, ld in s.completed if ld in s.counts]
    if recent:
        s.median_wait = round(median(recent))
    elif all_waits:
        s.median_wait = round(median(all_waits))

    # скорость: текущее окно и предыдущее (для тренда)
    if s.counts:
        w1 = today - timedelta(days=VELOCITY_WINDOW_DAYS)
        w2 = today - timedelta(days=2 * VELOCITY_WINDOW_DAYS)
        s.velocity = sum(c for d, c in s.counts.items() if d > w1) / VELOCITY_WINDOW_DAYS
        s.velocity_prev = (
            sum(c for d, c in s.counts.items() if w2 < d <= w1) / VELOCITY_WINDOW_DAYS
        )

    # горизонт записи
    h1 = today - timedelta(days=HORIZON_WINDOW_DAYS)
    h2 = today - timedelta(days=2 * HORIZON_WINDOW_DAYS)
    cur = [h for ld, h in horizons if ld >= h1]
    prev = [h for ld, h in horizons if h2 <= ld < h1]
    if cur:
        s.horizon_median = round(median(cur))
    if prev:
        s.horizon_prev = round(median(prev))

    # фронт очереди по месяцам постановки
    ordered = sorted(month_totals, key=lambda m: (m[3:], m[:2]))[-MONTHS_SHOWN:]
    s.months = [(m, month_completed.get(m, 0), month_totals[m]) for m in ordered]

    # постановки: все месяцы + дни последнего активного месяца
    all_months = sorted(month_totals, key=lambda m: (m[3:], m[:2]))
    s.queue_months = [(m, month_totals[m]) for m in all_months]
    if queue_dates:
        last = max((qd.year, qd.month) for qd in queue_dates)
        s.active_month = f"{last[1]:02d}.{last[0]}"
        days = Counter(qd for qd in queue_dates if (qd.year, qd.month) == last)
        s.queue_days, s.queue_day_outliers = _filter_day_outliers(dict(days))

    # тренд медианы ожидания по неделям (последние 8 недель, недели с >=2 письмами)
    by_week: dict[date, list[int]] = {}
    for qd, ld in s.completed:
        if ld not in s.counts:
            continue
        week_start = ld - timedelta(days=ld.weekday())
        by_week.setdefault(week_start, []).append((ld - qd).days)
    for wk in sorted(by_week)[-8:]:
        waits = by_week[wk]
        if len(waits) >= 2:
            s.weekly_medians.append((wk.strftime("%d.%m"), round(median(waits))))

    if passport_waits:
        s.passport_median = round(median(passport_waits))

    s.forecast_wait = s.median_wait
    return s


def _trend_arrow(cur: float | None, prev: float | None) -> str:
    if cur is None or prev is None or prev == 0:
        return ""
    ratio = cur / prev
    if ratio >= 1.2:
        return " ↗ ускоряется"
    if ratio <= 0.8:
        return " ↘ замедляется"
    return " → стабильно"


def _bar(pct: float, width: int = 12) -> str:
    filled = round(pct / 100 * width)
    return "█" * filled + "░" * (width - filled)


# ---------- тексты ----------

def build_text(s: Stats, visa_label: str, today: date | None = None) -> str:
    today = today or date.today()
    lines = [f"📊 <b>{s.city} — {visa_label}</b>"]
    if s.total == 0:
        lines.append("")
        lines.append("Данных пока нет — станьте первым, кто заполнит анкету!")
        return "\n".join(lines)

    lines.append("")
    lines.append(
        f"Анкет <b>{s.total}</b> · ✉️ получили <b>{len(s.completed)}</b> · "
        f"⏳ ждут <b>{len(s.pending)}</b>"
    )
    lines.append("")
    if s.median_wait is not None:
        lines.append(f"⏱ Ожидание письма: <b>{s.median_wait} дн.</b> (медиана)")
    if s.velocity is not None:
        lines.append(
            f"🚀 Скорость: <b>~{s.velocity:.1f} приглашений/день</b>"
            f"{_trend_arrow(s.velocity, s.velocity_prev)}"
        )
    if s.horizon_median is not None:
        horizon = f"🗓 Слот после письма: ~<b>{s.horizon_median} дн.</b>"
        if s.horizon_prev is not None and s.horizon_prev != s.horizon_median:
            direction = "дальше" if s.horizon_median > s.horizon_prev else "ближе"
            horizon += f" (было {s.horizon_prev} — {direction})"
        lines.append(horizon)
    if s.passport_median is not None:
        lines.append(f"🛂 Паспорт после подачи: ~<b>{s.passport_median} дн.</b>")
    if s.approved or s.refused:
        lines.append(f"Результаты: ✅ <b>{s.approved}</b> · ❌ <b>{s.refused}</b>")
    if s.last_letter and s.front_queue_date:
        front = _fmt(s.front_queue_date)
        if s.front_queue_time:
            front += f" в {s.front_queue_time}"
        lines.append(
            f"📨 Последнее приглашение: письмо <b>{_fmt(s.last_letter)}</b> — "
            f"дошли до вставших <b>{front}</b>"
        )
    if s.invites_today:
        lines.append(f"🔥 Сегодня уже <b>{s.invites_today}</b> приглашений!")

    if s.counts:
        lines.append("")
        lines.append("📅 <b>Приглашения по датам</b>")
        shown = sorted(s.counts)[-LAST_DATES_SHOWN:]
        peak = max(s.counts[d] for d in shown)
        for d in shown:
            c = s.counts[d]
            lines.append(f"<code>{d.strftime('%d.%m')} {_bar(100 * c / peak, 10)} {c}</code>")
        if s.outliers:
            dropped = ", ".join(_fmt(d) for d in sorted(s.outliers))
            lines.append(f"<i>исключены как вероятные ошибки: {dropped}</i>")

    if s.months:
        lines.append("")
        lines.append("📈 <b>Фронт очереди</b> (% получивших письмо)")
        for month, done, total in s.months:
            pct = round(100 * done / total) if total else 0
            lines.append(f"<code>{month} {_bar(pct, 10)} {pct}% ({done}/{total})</code>")

    if s.active_month and s.queue_days:
        joined = sum(s.queue_days.values())
        lines.append("")
        lines.append(
            f"📥 В {s.active_month} встали в очередь <b>{joined}</b> чел. "
            "(по дням — на графике)"
        )
        if s.queue_day_outliers:
            dropped = ", ".join(_fmt(d) for d in sorted(s.queue_day_outliers))
            lines.append(f"<i>исключены как вероятные ошибки: {dropped}</i>")

    lines.append("")
    if s.forecast_wait is not None:
        eta = today + timedelta(days=s.forecast_wait)
        lines.append(
            f"🔮 Встали сегодня → письмо ≈ <b>{_fmt(eta)}</b> (~{s.forecast_wait} дн.)"
        )
    else:
        lines.append("🔮 Для прогноза пока мало данных: нужны анкеты с письмами.")

    footer = f"<i>Срез {_fmt(today)} · за 7 дней +{s.recent_7d} анкет"
    if s.suspect_count:
        footer += f" · исключено сомнительных: {s.suspect_count}"
    footer += f" · {BOT_TAG}</i>"
    lines.append(footer)
    return "\n".join(lines)


def build_personal_forecast(
    s: Stats,
    visa_label: str,
    queue_date: date,
    queue_time: str | None = None,
    today: date | None = None,
) -> str:
    today = today or date.today()
    ahead = db.count_ahead(s.city, s.visa_type, queue_date.isoformat())
    when = _fmt(queue_date) + (f" в {queue_time}" if queue_time else "")
    lines = [
        f"🔮 <b>Персональный прогноз: {s.city} — {visa_label}</b>",
        f"Постановка в очередь: <b>{when}</b> "
        f"(в очереди уже {(today - queue_date).days} дн.)",
        "",
        f"Перед вами по анкетам ждут письма: <b>~{ahead} чел.</b> "
        "(только те, кто заполнил анкету — реальная очередь больше)",
    ]
    if queue_time:
        same_day = db.count_ahead_same_date(
            s.city, s.visa_type, queue_date.isoformat(), queue_time
        )
        lines.append(
            f"Из вставших {_fmt(queue_date)} раньше вас по времени: <b>{same_day} чел.</b> "
            "— если очередь стоит на вашей дате, они получат письмо первыми"
        )
    if s.median_wait is not None:
        eta = queue_date + timedelta(days=s.median_wait)
        if eta <= today:
            lines.append(
                f"Медианное ожидание ({s.median_wait} дн.) уже прошло — "
                "письмо может прийти со дня на день. Проверяйте почту!"
            )
        else:
            lines.append(
                f"Письмо ориентировочно: <b>{_fmt(eta)}</b> "
                f"(осталось ~{(eta - today).days} дн. при медиане {s.median_wait} дн.)"
            )
    else:
        lines.append("Оценки срока пока нет — мало анкет с полученными письмами.")
    lines.append("")
    lines.append("<i>Оценка по анкетам участников, не официальные данные VFS.</i>")
    return "\n".join(lines)


# ---------- прогноз раздач приглашений по городам ----------

_WD_FULL = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
_WD_SHORT = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
WAVE_MIN_LETTERS = 3    # меньше писем по городу — «данных мало», не прогнозируем
WAVE_MAX_UPCOMING = 4   # сколько ближайших дат раздач показать


def _city_cadence(dates: list[date]) -> tuple[int, int, date] | None:
    """(день недели, интервал 7/14, дата последней волны) или None, если ритм не выделяется.

    Волны — дни, где писем >=2 (гасим одиночный шум). Ритм — по последнему интервалу
    между волнами того же дня недели (свежее поведение важнее старого).
    """
    daycnt = Counter(dates)
    waves = sorted([d for d, n in daycnt.items() if n >= 2]) or sorted(set(dates))
    wd = Counter(d.weekday() for d in waves).most_common(1)[0][0]
    same = [d for d in waves if d.weekday() == wd]
    gaps = [(same[i + 1] - same[i]).days for i in range(len(same) - 1)]
    if not gaps:
        return None
    last_gap, mid = gaps[-1], median(gaps)
    if last_gap <= 8 or mid <= 8:
        interval = 7
    elif 12 <= last_gap <= 16 or 12 <= mid <= 16:
        interval = 14
    else:
        return None
    return wd, interval, max(same)


def build_wave_forecast(cities: list[str], today: date | None = None) -> str | None:
    """Блок «сегодня/ближайшие раздачи приглашений по городам» из фактических данных."""
    today = today or date.today()
    dates_by: dict[str, list[date]] = {}
    for r in db.letters_for_waves():
        try:
            dt = _d(r["letter_date"])
        except (TypeError, ValueError):
            continue
        dates_by.setdefault(r["city"], []).append(dt)

    today_cities: list[str] = []
    upcoming: dict[date, list[str]] = {}
    for city in cities:
        ds = dates_by.get(city, [])
        if len(ds) < WAVE_MIN_LETTERS:
            continue
        cad = _city_cadence(ds)
        if not cad:
            continue
        wd, interval, last = cad
        if today.weekday() == wd and today >= last and (today - last).days % interval == 0:
            today_cities.append(city)
            continue
        nd = last
        while nd < today:
            nd += timedelta(days=interval)
        upcoming.setdefault(nd, []).append(city)

    if not today_cities and not upcoming:
        return None
    lines = []
    if today_cities:
        lines.append(
            f"📬 <b>Сегодня ({_WD_FULL[today.weekday()]}) ожидается раздача приглашений:</b> "
            + " · ".join(today_cities) + "."
        )
    else:
        lines.append("📭 <b>Сегодня раздача приглашений обычно не ожидается.</b>")
    if upcoming:
        lines.append("📅 <b>Ближайшие ожидаемые раздачи:</b>")
        for nd in sorted(upcoming)[:WAVE_MAX_UPCOMING]:
            lines.append(f"• {nd.strftime('%d.%m')} ({_WD_SHORT[nd.weekday()]}) — {', '.join(upcoming[nd])}")
    lines.append("<i>Ориентир по статистике участников, не гарантия.</i>")
    return "\n".join(lines)


def build_daily_summary(
    cities: list[str], visa_types: dict[str, str], today: date | None = None
) -> str | None:
    today = today or date.today()
    lines = [f"📊 <b>Сводка очереди на {_fmt(today)}</b>", ""]
    forecast = build_wave_forecast(cities, today)
    if forecast:
        lines.append(forecast)
        lines.append("")
    has_data = False
    for city in cities:
        for visa, label in visa_types.items():
            s = collect_cached(city, visa)
            if s.total == 0:
                continue
            has_data = True
            parts = [f"анкет {s.total}"]
            if s.median_wait is not None:
                parts.append(f"медиана {s.median_wait} дн.")
            if s.velocity is not None:
                parts.append(f"~{s.velocity:.1f}/день{_trend_arrow(s.velocity, s.velocity_prev)}")
            if s.last_letter and s.front_queue_date:
                front = s.front_queue_date.strftime("%d.%m")
                if s.front_queue_time:
                    front += f" {s.front_queue_time}"
                parts.append(
                    f"посл. письмо {s.last_letter.strftime('%d.%m')} → очередь дошла до {front}"
                )
            lines.append(f"• <b>{city}, {label}</b>: {', '.join(parts)}")
    if not has_data:
        return None
    lines.append("")
    lines.append(f"Подробнее и графики — /stats в личке с ботом. {BOT_TAG}")
    return "\n".join(lines)


def wait_suspicion(city: str, visa_type: str, queue_iso: str, letter_iso: str) -> tuple[bool, int, int | None]:
    """Правдоподобен ли срок ожидания письма.

    Возвращает (подозрительно, ожидание_дней, медиана_или_None).
    Подозрительно = ожидание < max(SUSPECT_MIN_DAYS, 25% медианы города).
    Пока медианы нет (мало данных) — не срабатывает.
    """
    wait = (_d(letter_iso) - _d(queue_iso)).days
    med = collect_cached(city, visa_type).median_wait
    if med is None:
        return False, wait, None
    threshold = max(SUSPECT_MIN_DAYS, round(med * SUSPECT_MEDIAN_FRACTION))
    return wait < threshold, wait, med


# ---------- алерт о всплеске ----------

def check_spike(city: str, visa_type: str, letter_iso: str, today: date | None = None) -> int | None:
    today = today or date.today()
    ld = _d(letter_iso)
    if (today - ld).days > 2:
        return None
    s = collect(city, visa_type, today)  # свежий расчёт, без кеша
    count = sum(1 for _, l in s.completed if l == ld)
    velocity = s.velocity or 0.0
    if count >= SPIKE_MIN_COUNT and count >= SPIKE_VELOCITY_FACTOR * velocity:
        return count
    return None


# ---------- графики ----------

def _style(ax, title: str) -> None:
    ax.set_facecolor(SURFACE)
    ax.set_title(title, color=INK, fontsize=12, loc="left", pad=12, fontweight="bold")
    ax.tick_params(colors=INK2, labelsize=9)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def _save(fig, footnote: str | None = None) -> str:
    if footnote:
        fig.text(0.055, 0.012, footnote, color=INK2, fontsize=8)
    fig.text(0.985, 0.012, BOT_TAG, color=INK2, fontsize=8, ha="right")
    fig.tight_layout(rect=(0, 0.045, 1, 1))
    tmp = NamedTemporaryFile(suffix=".png", delete=False)
    fig.savefig(tmp.name, facecolor=SURFACE)
    plt.close(fig)
    return tmp.name


def _fig(h: float = 4.6):
    fig, ax = plt.subplots(figsize=(8.4, h), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    return fig, ax


def render_chart(s: Stats, visa_label: str, days: int = 30, today: date | None = None) -> str | None:
    """Приглашения за `days` дней: бары + среднее за 7 дней."""
    today = today or date.today()
    start = today - timedelta(days=days - 1)
    xs = [start + timedelta(days=i) for i in range(days)]
    vals = [s.counts.get(d, 0) for d in xs]
    if sum(1 for v in vals if v) < 2:
        return None
    ma = [sum(vals[max(0, i - 6):i + 1]) / len(vals[max(0, i - 6):i + 1]) for i in range(days)]

    fig, ax = _fig()
    _style(ax, f"{s.city} — {visa_label} · Приглашения в ВЦ, {days} дней")
    ax.bar(xs, vals, color=BLUE, width=0.72, zorder=2, label="приглашений за день")
    ax.plot(xs, ma, color=GREEN, linewidth=2, zorder=3, label="среднее за 7 дней")
    nonzero = [i for i, v in enumerate(vals) if v]
    peak = max(nonzero, key=lambda i: vals[i])
    for i in {peak, nonzero[-1]}:
        ax.text(xs[i], vals[i] + max(vals) * 0.03, str(vals[i]), ha="center",
                color=INK, fontsize=9, fontweight="bold")
    ax.set_ylabel("приглашений (по анкетам)", color=INK2, fontsize=9)
    ax.legend(loc="upper left", frameon=False, fontsize=9, labelcolor=INK2)
    ax.set_xticks(xs[::5])
    ax.set_xticklabels([d.strftime("%d.%m") for d in xs[::5]])
    ax.margins(x=0.02)
    note = f"срез {_fmt(today)}"
    if s.outliers:
        note = "исключены как ошибки: " + ", ".join(
            d.strftime("%d.%m") for d in sorted(s.outliers)) + " · " + note
    return _save(fig, note)


def render_front_chart(s: Stats, visa_label: str, today: date | None = None) -> str | None:
    """Фронт очереди: месяц постановки × (письмо получено | ещё ждут)."""
    today = today or date.today()
    if not s.months or all(t == 0 for _, _, t in s.months):
        return None
    months = [m for m, _, _ in s.months]
    done = [d for _, d, _ in s.months]
    wait = [t - d for _, d, t in s.months]

    fig, ax = _fig(4.0)
    _style(ax, f"{s.city} — {visa_label} · Фронт очереди по месяцам постановки")
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    y = range(len(months))
    ax.barh(y, done, color=BLUE, height=0.62, zorder=2, label="письмо получено")
    ax.barh(y, wait, left=[d + 0.4 for d in done], color=NEUTRAL, height=0.62,
            zorder=2, label="ещё ждут")
    xmax = max(d + w for d, w in zip(done, wait))
    for i, (d, w) in enumerate(zip(done, wait)):
        pct = round(100 * d / (d + w)) if d + w else 0
        ax.text(d + w + xmax * 0.03, i, f"{pct}% ({d} из {d + w})", va="center",
                color=INK, fontsize=9, fontweight="bold")
    ax.set_yticks(list(y))
    ax.set_yticklabels(months)
    ax.invert_yaxis()
    ax.set_xlim(0, xmax * 1.32)
    ax.legend(loc="lower right", frameon=False, fontsize=9, labelcolor=INK2)
    return _save(fig, f"до какого месяца «дошла» очередь · срез {_fmt(today)}")


def render_median_trend_chart(s: Stats, visa_label: str, today: date | None = None) -> str | None:
    """Тренд медианного ожидания письма по неделям."""
    today = today or date.today()
    if len(s.weekly_medians) < 3:
        return None
    labels = [w for w, _ in s.weekly_medians]
    med = [m for _, m in s.weekly_medians]

    fig, ax = _fig(4.0)
    _style(ax, f"{s.city} — {visa_label} · Медианное ожидание письма, по неделям")
    ax.plot(labels, med, color=BLUE, linewidth=2, marker="o", markersize=5, zorder=3)
    ax.text(len(labels) - 1, med[-1] - (max(med) - min(med) + 4) * 0.09,
            f"{med[-1]} дн.", color=INK, fontsize=10, fontweight="bold", ha="center")
    delta = med[-1] - med[0]
    word = "ускоряется" if delta < 0 else ("замедляется" if delta > 0 else "стабильна")
    ax.set_ylabel("дней от постановки до письма", color=INK2, fontsize=9)
    return _save(fig, f"очередь {word}: {delta:+d} дн. за период · срез {_fmt(today)}")


def render_queue_chart(s: Stats, visa_label: str) -> str | None:
    """Постановки в очередь: по месяцам + по дням последнего активного месяца."""
    if not s.queue_months:
        return None
    two = len(s.queue_days) >= 2
    fig, axes = plt.subplots(2 if two else 1, 1, figsize=(8.4, 8 if two else 4.6), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    ax1 = axes[0] if two else axes

    labels = [m for m, _ in s.queue_months]
    values = [c for _, c in s.queue_months]
    _style(ax1, f"{s.city} — {visa_label} · Постановки в очередь по месяцам")
    ax1.bar(labels, values, color=BLUE, width=0.6, zorder=2)
    for x, v in zip(labels, values):
        ax1.text(x, v + max(values) * 0.02, str(v), ha="center", color=INK, fontsize=9)
    ax1.set_ylabel("человек (по анкетам)", color=INK2, fontsize=9)
    if len(labels) > 8:
        ax1.tick_params(axis="x", rotation=45)

    if two:
        ax2 = axes[1]
        _style(ax2, f"Постановки по дням, {s.active_month} (без выбросов)")
        xs = sorted(s.queue_days)
        ax2.bar([d.strftime("%d.%m") for d in xs], [s.queue_days[d] for d in xs],
                color=GREEN, width=0.6, zorder=2)
        ax2.set_ylabel("человек", color=INK2, fontsize=9)
        ax2.yaxis.get_major_locator().set_params(integer=True)
        if len(xs) > 10:
            ax2.tick_params(axis="x", rotation=45)
    ax1.yaxis.get_major_locator().set_params(integer=True)
    return _save(fig)


def charts_for(s: Stats, visa_label: str) -> list[str]:
    """Все доступные графики для /stats (пути к PNG)."""
    charts = [
        render_chart(s, visa_label),
        render_front_chart(s, visa_label),
        render_median_trend_chart(s, visa_label),
        render_queue_chart(s, visa_label),
    ]
    return [c for c in charts if c]


def render_city_ranking(
    visa_label: str, entries: list[tuple[str, int]], today: date | None = None
) -> str | None:
    """Рейтинг городов по медианному ожиданию (для ежедневной сводки)."""
    today = today or date.today()
    if len(entries) < 2:
        return None
    entries = sorted(entries, key=lambda e: e[1])
    fig, ax = _fig(1.4 + 0.5 * len(entries))
    _style(ax, f"{visa_label} · Медианное ожидание письма по городам")
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    y = range(len(entries))
    ax.barh(y, [m for _, m in entries], color=BLUE, height=0.62, zorder=2)
    xmax = max(m for _, m in entries)
    for i, (_, m) in enumerate(entries):
        ax.text(m + xmax * 0.02, i, f"{m} дн.", va="center", color=INK, fontsize=9)
    ax.set_yticks(list(y))
    ax.set_yticklabels([c for c, _ in entries])
    ax.invert_yaxis()
    ax.set_xlim(0, xmax * 1.15)
    return _save(fig, f"срез {_fmt(today)}")
