"""Хранилище отчётов пользователей (SQLite)."""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "reports.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    username TEXT,
    city TEXT NOT NULL,
    visa_type TEXT NOT NULL,          -- D_OTHER | D_DRIVER | C_OTHER
    queue_date TEXT NOT NULL,         -- ISO YYYY-MM-DD: дата постановки в очередь
    queue_time TEXT,                  -- ЧЧ:ММ время постановки (NULL = не указано)
    letter_date TEXT,                 -- дата письма-приглашения (NULL = ещё не пришло)
    slots TEXT,                       -- доступные интервалы записи: JSON [["от","до"], ...]
    submit_date TEXT,                 -- дата подачи документов в ВЦ
    passport_date TEXT,               -- дата получения паспорта обратно
    outcome TEXT,                     -- APPROVED | REFUSED (NULL = результата нет)
    created_at TEXT NOT NULL,
    message_id INTEGER,               -- id сообщения бота в теме группы
    updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_reports_city_type ON reports (city, visa_type);
CREATE INDEX IF NOT EXISTS idx_reports_user ON reports (user_id);
CREATE TABLE IF NOT EXISTS alerts (
    city TEXT NOT NULL,
    visa_type TEXT NOT NULL,
    letter_date TEXT NOT NULL,        -- дата письма, о всплеске на которую уже сообщили
    created_at TEXT NOT NULL,
    PRIMARY KEY (city, visa_type, letter_date)
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    event TEXT NOT NULL,              -- шаг воронки анкеты (start/city/.../saved_new)
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_created ON events (created_at);
CREATE TABLE IF NOT EXISTS membership (
    user_id INTEGER PRIMARY KEY,
    in_group INTEGER NOT NULL,        -- 1 = в группе, 0 = ушёл/не участник
    checked_at TEXT NOT NULL
);
"""

_MIGRATIONS = [
    "ALTER TABLE reports ADD COLUMN message_id INTEGER",
    "ALTER TABLE reports ADD COLUMN updated_at TEXT",
    # список доступных интервалов записи: JSON [["YYYY-MM-DD","YYYY-MM-DD"], ...]
    "ALTER TABLE reports ADD COLUMN slots TEXT",
    "ALTER TABLE reports ADD COLUMN queue_time TEXT",
    "ALTER TABLE reports ADD COLUMN submit_date TEXT",
    "ALTER TABLE reports ADD COLUMN passport_date TEXT",
    "ALTER TABLE reports ADD COLUMN outcome TEXT",
    # 1 = сомнительная (аномальный срок ожидания, в статистике не учитывается)
    "ALTER TABLE reports ADD COLUMN suspect INTEGER DEFAULT 0",
    # причина пометки «сомнительная»: NULL/'short' = аномально короткий срок, 'jump' = мимо очереди
    "ALTER TABLE reports ADD COLUMN suspect_reason TEXT",
    # срок выданной визы в днях (NULL = не указан)
    "ALTER TABLE reports ADD COLUMN visa_days INTEGER",
    # уточнение категории для D (Other): KARTA | STUDY | NULL
    "ALTER TABLE reports ADD COLUMN subcategory TEXT",
    # метка заявителя при групповой подаче (обезличенная роль): «Моя», «Ребёнок 2» и т.п.
    "ALTER TABLE reports ADD COLUMN label TEXT",
    # первые 6 цифр номера очереди (после префикса PLB); инкрементальны — для оценки размера очереди
    "ALTER TABLE reports ADD COLUMN queue_num TEXT",
    # 1 = о получении письма-приглашения уже опубликовано в тему-ленту (публикуем один раз)
    "ALTER TABLE reports ADD COLUMN invite_announced INTEGER DEFAULT 0",
    # message_id записи в теме-ленте «Получили приглашение» — чтобы обновлять её на месте при правках
    "ALTER TABLE reports ADD COLUMN invite_msg_id INTEGER",
]


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    for migration in _MIGRATIONS:
        try:
            conn.execute(migration)
        except sqlite3.OperationalError:
            pass  # колонка уже есть
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def save_report(
    user_id: int,
    username: str | None,
    city: str,
    visa_type: str,
    queue_date: str,
    letter_date: str | None,
    slots: str | None,
    queue_time: str | None = None,
    submit_date: str | None = None,
    passport_date: str | None = None,
    outcome: str | None = None,
    suspect: int = 0,
    suspect_reason: str | None = None,
    visa_days: int | None = None,
    subcategory: str | None = None,
    label: str | None = None,
    queue_num: str | None = None,
) -> int:
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO reports
               (user_id, username, city, visa_type, queue_date, queue_time,
                letter_date, slots, submit_date, passport_date, outcome, suspect,
                suspect_reason, visa_days, subcategory, label, queue_num, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, username, city, visa_type, queue_date, queue_time,
             letter_date, slots, submit_date, passport_date, outcome, suspect,
             suspect_reason, visa_days, subcategory, label, queue_num, _now()),
        )
        return cur.lastrowid


def update_report(
    report_id: int,
    queue_date: str,
    letter_date: str | None,
    slots: str | None,
    queue_time: str | None = None,
    submit_date: str | None = None,
    passport_date: str | None = None,
    outcome: str | None = None,
    suspect: int = 0,
    suspect_reason: str | None = None,
    username: str | None = None,
    visa_days: int | None = None,
    subcategory: str | None = None,
    label: str | None = None,
    queue_num: str | None = None,
) -> None:
    """Обновляет анкету; username освежается при каждой правке (мог появиться/смениться)."""
    with _connect() as conn:
        conn.execute(
            """UPDATE reports SET queue_date = ?, queue_time = ?, letter_date = ?,
               slots = ?, submit_date = ?, passport_date = ?, outcome = ?,
               suspect = ?, suspect_reason = ?, username = ?, visa_days = ?, subcategory = ?,
               label = ?, queue_num = ?, updated_at = ? WHERE id = ?""",
            (queue_date, queue_time, letter_date, slots, submit_date,
             passport_date, outcome, suspect, suspect_reason, username, visa_days, subcategory,
             label, queue_num, _now(), report_id),
        )


def log_event(user_id: int, event: str) -> None:
    """Телеметрия воронки анкеты (fire-and-forget)."""
    try:
        with _connect() as conn:
            conn.execute(
                "INSERT INTO events (user_id, event, created_at) VALUES (?, ?, ?)",
                (user_id, event, _now()),
            )
    except Exception:
        pass  # телеметрия не должна ломать анкету


def funnel_counts(days: int = 7) -> dict[str, int]:
    """Уникальные пользователи по каждому шагу воронки за `days` дней."""
    from datetime import timedelta

    threshold = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    with _connect() as conn:
        rows = conn.execute(
            """SELECT event, COUNT(DISTINCT user_id) FROM events
               WHERE created_at > ? GROUP BY event""",
            (threshold,),
        ).fetchall()
        return {r[0]: r[1] for r in rows}


def set_suspect(report_id: int, suspect: int, reason: str | None = None) -> None:
    """suspect=0 сбрасывает причину; suspect=1 без reason сохраняет уже записанную причину."""
    with _connect() as conn:
        if not suspect:
            conn.execute(
                "UPDATE reports SET suspect = 0, suspect_reason = NULL, updated_at = ? WHERE id = ?",
                (_now(), report_id),
            )
        elif reason is not None:
            conn.execute(
                "UPDATE reports SET suspect = 1, suspect_reason = ?, updated_at = ? WHERE id = ?",
                (reason, _now(), report_id),
            )
        else:
            conn.execute(
                "UPDATE reports SET suspect = 1, updated_at = ? WHERE id = ?",
                (_now(), report_id),
        )


def delete_report(report_id: int) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM reports WHERE id = ?", (report_id,))


def count_recent(city: str, visa_type: str, days: int = 7) -> int:
    """Сколько анкет добавлено за последние `days` дней (свежесть данных)."""
    from datetime import timedelta

    threshold = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    with _connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM reports WHERE city = ? AND visa_type = ? AND created_at > ?",
            (city, visa_type, threshold),
        ).fetchone()
        return row[0]


def update_city_type(report_id: int, city: str, visa_type: str) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE reports SET city = ?, visa_type = ?, updated_at = ? WHERE id = ?",
            (city, visa_type, _now(), report_id),
        )


def set_message_id(report_id: int, message_id: int) -> None:
    with _connect() as conn:
        conn.execute("UPDATE reports SET message_id = ? WHERE id = ?", (message_id, report_id))


def mark_invite_announced(report_id: int, msg_id: int | None = None) -> None:
    """Отмечает публикацию в тему-ленту и (если передан) сохраняет id сообщения для правок на месте.

    COALESCE: передача None не затирает уже сохранённый id.
    """
    with _connect() as conn:
        conn.execute(
            "UPDATE reports SET invite_announced = 1, invite_msg_id = COALESCE(?, invite_msg_id) WHERE id = ?",
            (msg_id, report_id),
        )


def get_report(report_id: int) -> sqlite3.Row | None:
    with _connect() as conn:
        return conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone()


def find_latest(user_id: int) -> sqlite3.Row | None:
    """Последняя анкета пользователя (независимо от давности)."""
    with _connect() as conn:
        return conn.execute(
            "SELECT * FROM reports WHERE user_id = ? ORDER BY created_at DESC LIMIT 1",
            (user_id,),
        ).fetchone()


def reports_by_user(user_id: int) -> list[sqlite3.Row]:
    """Все анкеты пользователя (для мульти-анкет), свежие сверху."""
    with _connect() as conn:
        return conn.execute(
            "SELECT * FROM reports WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()


def count_recent_by_user(user_id: int, days: int) -> int:
    """Сколько анкет пользователь создал за последние `days` дней (лимит групповой подачи)."""
    from datetime import timedelta

    threshold = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    with _connect() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM reports WHERE user_id = ? AND created_at > ?",
            (user_id, threshold),
        ).fetchone()[0]


def labels_recent_by_user(user_id: int, days: int) -> list[str]:
    """Метки анкет пользователя за последние `days` дней — для автонумерации в пределах окна."""
    from datetime import timedelta

    threshold = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    with _connect() as conn:
        rows = conn.execute(
            "SELECT label FROM reports WHERE user_id = ? AND created_at > ?",
            (user_id, threshold),
        ).fetchall()
        return [r[0] for r in rows]


def recent_reports(city: str, visa_type: str, limit: int = 50) -> list[sqlite3.Row]:
    with _connect() as conn:
        return conn.execute(
            """SELECT * FROM reports WHERE city = ? AND visa_type = ?
               ORDER BY created_at DESC LIMIT ?""",
            (city, visa_type, limit),
        ).fetchall()


def reports_by_city(city: str, offset: int, limit: int) -> list[sqlite3.Row]:
    """Страница анкет города (все типы визы) в порядке постановки в очередь."""
    with _connect() as conn:
        return conn.execute(
            """SELECT * FROM reports WHERE city = ?
               ORDER BY queue_date, COALESCE(queue_time, '99:99'), id
               LIMIT ? OFFSET ?""",
            (city, limit, offset),
        ).fetchall()


def count_by_city(city: str) -> int:
    with _connect() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM reports WHERE city = ?", (city,)
        ).fetchone()[0]


def reports_by_city_visa(city: str, visa_type: str, offset: int, limit: int) -> list[sqlite3.Row]:
    """Страница анкет города и типа визы в порядке постановки в очередь."""
    with _connect() as conn:
        return conn.execute(
            """SELECT * FROM reports WHERE city = ? AND visa_type = ?
               ORDER BY queue_date, COALESCE(queue_time, '99:99'), id
               LIMIT ? OFFSET ?""",
            (city, visa_type, limit, offset),
        ).fetchall()


def reports_for_survival() -> list[sqlite3.Row]:
    """Данные для анализа выживаемости: (user_id, city, visa_type, queue_date, letter_date, suspect)."""
    with _connect() as conn:
        return conn.execute(
            "SELECT user_id, city, visa_type, queue_date, letter_date, COALESCE(suspect,0) AS suspect "
            "FROM reports"
        ).fetchall()


def waiting_user_ids() -> list[int]:
    """user_id всех, у кого есть ожидающая (без письма) анкета — их членство важно для цензурирования."""
    with _connect() as conn:
        return [r[0] for r in conn.execute(
            "SELECT DISTINCT user_id FROM reports WHERE letter_date IS NULL AND COALESCE(suspect,0)=0"
        ).fetchall()]


def set_membership(user_id: int, in_group: bool) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO membership (user_id, in_group, checked_at) VALUES (?,?,?) "
            "ON CONFLICT(user_id) DO UPDATE SET in_group=excluded.in_group, checked_at=excluded.checked_at",
            (user_id, 1 if in_group else 0, _now()),
        )


def left_user_ids() -> set[int]:
    """user_id, помеченные как ушедшие (in_group=0)."""
    with _connect() as conn:
        return {r[0] for r in conn.execute("SELECT user_id FROM membership WHERE in_group=0").fetchall()}


def letters_for_waves() -> list[sqlite3.Row]:
    """(city, letter_date) всех пришедших приглашений (без сомнительных) — для прогноза раздач."""
    with _connect() as conn:
        return conn.execute(
            "SELECT city, letter_date FROM reports "
            "WHERE letter_date IS NOT NULL AND (suspect IS NULL OR suspect = 0)"
        ).fetchall()


def pending_behind_front() -> list[sqlite3.Row]:
    """Анкеты без письма (не сомнительные), вставшие СТРОГО раньше фронта своего города×визы.
    Фронт = макс. дата постановки среди получивших письмо. Поле `front` — в строке."""
    with _connect() as conn:
        return conn.execute(
            """SELECT r.id, r.user_id, r.username, r.city, r.visa_type, r.queue_date, r.queue_time,
                      r.queue_num, r.message_id, r.invite_msg_id, r.created_at, r.updated_at, f.front
               FROM reports r
               JOIN (SELECT city, visa_type, MAX(queue_date) AS front FROM reports
                     WHERE letter_date IS NOT NULL AND COALESCE(suspect, 0) = 0
                     GROUP BY city, visa_type) f
                 ON f.city = r.city AND f.visa_type = r.visa_type
               WHERE r.letter_date IS NULL AND COALESCE(r.suspect, 0) = 0 AND r.queue_date < f.front
               ORDER BY r.city, r.visa_type, r.queue_date"""
        ).fetchall()


def visa_days_for(visa_type: str) -> list[int]:
    """Сроки выданных виз (дни) по типу визы, все города; без сомнительных и отказов."""
    with _connect() as conn:
        return [r[0] for r in conn.execute(
            """SELECT visa_days FROM reports
               WHERE visa_type = ? AND visa_days IS NOT NULL
                 AND COALESCE(suspect, 0) = 0 AND COALESCE(outcome, '') != 'REFUSED'""",
            (visa_type,),
        ).fetchall()]


def pending_ahead_users(
    city: str, visa_type: str, queue_date: str, queue_time: str | None, exclude_id: int | None = None
) -> list[int]:
    """user_id ждущих (без письма, не сомнительных) в том же городе×визе, вставших СТРОГО раньше
    позиции (queue_date, queue_time). Одинаковая дата сравнивается по времени только когда
    оно указано у обоих; без времени — не считается «раньше» (консервативно)."""
    with _connect() as conn:
        return [r[0] for r in conn.execute(
            """SELECT user_id FROM reports
               WHERE city = ? AND visa_type = ? AND letter_date IS NULL
                 AND COALESCE(suspect, 0) = 0 AND id != COALESCE(?, -1)
                 AND (queue_date < ?
                      OR (queue_date = ? AND ? IS NOT NULL AND queue_time IS NOT NULL AND queue_time < ?))""",
            (city, visa_type, exclude_id, queue_date, queue_date, queue_time, queue_time),
        ).fetchall()]


def reports_for(city: str, visa_type: str) -> list[sqlite3.Row]:
    """Все анкеты по городу и типу визы (для статистики)."""
    with _connect() as conn:
        return conn.execute(
            "SELECT * FROM reports WHERE city = ? AND visa_type = ? ORDER BY queue_date",
            (city, visa_type),
        ).fetchall()


def reports_page(city: str, visa_type: str, offset: int, limit: int) -> list[sqlite3.Row]:
    """Страница анкет для просмотра (свежие сверху)."""
    with _connect() as conn:
        return conn.execute(
            """SELECT * FROM reports WHERE city = ? AND visa_type = ?
               ORDER BY queue_date DESC, id DESC LIMIT ? OFFSET ?""",
            (city, visa_type, limit, offset),
        ).fetchall()


def count_reports(city: str, visa_type: str) -> int:
    with _connect() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM reports WHERE city = ? AND visa_type = ?",
            (city, visa_type),
        ).fetchone()[0]


def reports_near(city: str, visa_type: str, start: str, end: str) -> list[sqlite3.Row]:
    """Анкеты с постановкой в окне дат (для «Людей рядом»), без сомнительных."""
    with _connect() as conn:
        return conn.execute(
            """SELECT * FROM reports
               WHERE city = ? AND visa_type = ? AND suspect = 0
                 AND queue_date BETWEEN ? AND ?
               ORDER BY queue_date, COALESCE(queue_time, '99'), id""",
            (city, visa_type, start, end),
        ).fetchall()


def count_ahead(city: str, visa_type: str, queue_date: str) -> int:
    """Сколько человек с более ранней (или той же) датой постановки ещё ждут письма."""
    with _connect() as conn:
        row = conn.execute(
            """SELECT COUNT(*) FROM reports
               WHERE city = ? AND visa_type = ? AND letter_date IS NULL AND queue_date <= ?""",
            (city, visa_type, queue_date),
        ).fetchone()
        return row[0]


def count_ahead_same_date(city: str, visa_type: str, queue_date: str, queue_time: str) -> int:
    """Сколько ждущих встали в ту же дату, но раньше по времени (у кого время указано)."""
    with _connect() as conn:
        row = conn.execute(
            """SELECT COUNT(*) FROM reports
               WHERE city = ? AND visa_type = ? AND letter_date IS NULL
                 AND queue_date = ? AND queue_time IS NOT NULL AND queue_time < ?""",
            (city, visa_type, queue_date, queue_time),
        ).fetchone()
        return row[0]


def alert_sent(city: str, visa_type: str, letter_date: str) -> bool:
    with _connect() as conn:
        return (
            conn.execute(
                "SELECT 1 FROM alerts WHERE city = ? AND visa_type = ? AND letter_date = ?",
                (city, visa_type, letter_date),
            ).fetchone()
            is not None
        )


def mark_alert(city: str, visa_type: str, letter_date: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO alerts (city, visa_type, letter_date, created_at) VALUES (?, ?, ?, ?)",
            (city, visa_type, letter_date, _now()),
        )
