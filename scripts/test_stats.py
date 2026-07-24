"""Самопроверка статистики: сеет синтетические анкеты, печатает сводку, чистит за собой."""
import random
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import db, stats

random.seed(42)
CITY, VISA, LABEL = "Минск", "D_OTHER", "Национальная D (Other)"
today = date.today()

seeded_ids = []
try:
    # 45 завершённых анкет с письмами старше 30 дней (вне окна выбросов)
    for i in range(45):
        ld = today - timedelta(days=random.randint(31, 90))
        qd = ld - timedelta(days=random.randint(75, 95))
        seeded_ids.append(db.save_report(
            user_id=900000 + i, username=f"demo{i}", city=CITY, visa_type=VISA,
            queue_date=qd.isoformat(), letter_date=ld.isoformat(), slots=None,
        ))
    # 12 ожидающих
    for i in range(12):
        qd = today - timedelta(days=random.randint(5, 70))
        seeded_ids.append(db.save_report(
            user_id=910000 + i, username=f"wait{i}", city=CITY, visa_type=VISA,
            queue_date=qd.isoformat(), letter_date=None, slots=None,
        ))
    # выброс: одиночная "ошибочная" дата письма среди плотных дат
    lonely = today - timedelta(days=3)
    seeded_ids.append(db.save_report(
        user_id=920000, username="typo", city=CITY, visa_type=VISA,
        queue_date=(lonely - timedelta(days=200)).isoformat(),
        letter_date=lonely.isoformat(), slots=None,
    ))
    # полные жизненные циклы: подача + паспорт + результат
    for i in range(10):
        qd = today - timedelta(days=150 + i)
        ld = qd + timedelta(days=80)
        sub = ld + timedelta(days=30)
        pas = sub + timedelta(days=7 + i % 5)
        seeded_ids.append(db.save_report(
            user_id=940000 + i, username=f"full{i}", city=CITY, visa_type=VISA,
            queue_date=qd.isoformat(), letter_date=ld.isoformat(), slots=None,
            submit_date=sub.isoformat(), passport_date=pas.isoformat(),
            outcome="APPROVED" if i % 5 else "REFUSED",
        ))
    # плотные свежие даты (по 15-20 анкет), контраст для выброса; часть со слотами
    import json as _json
    for offset, n in [(1, 18), (2, 15), (4, 20), (5, 16), (6, 17)]:
        for i in range(n):
            ld = today - timedelta(days=offset)
            qd = ld - timedelta(days=random.randint(75, 95))
            slots = None
            if i % 2 == 0:
                slot_start = ld + timedelta(days=random.randint(25, 40))
                slots = _json.dumps([[slot_start.isoformat(), (slot_start + timedelta(days=5)).isoformat()]])
            seeded_ids.append(db.save_report(
                user_id=930000 + offset * 100 + i, username=f"dense{offset}_{i}",
                city=CITY, visa_type=VISA,
                queue_date=qd.isoformat(), letter_date=ld.isoformat(), slots=slots,
            ))

    def clean(t):
        return t.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", "")

    s = stats.collect(CITY, VISA)
    print(clean(stats.build_text(s, LABEL)))
    print()
    import shutil
    charts = stats.charts_for(s, LABEL)
    print(f"charts: {len(charts)}")
    for i, c in enumerate(charts, 1):
        shutil.copy(c, ROOT / "assets" / f"test_chart_{i}.png")
    ranking = stats.render_city_ranking(LABEL, [(CITY, 82), ("Гомель", 74), ("Брест", 90)])
    if ranking:
        shutil.copy(ranking, ROOT / "assets" / "test_ranking.png")
    print(f"outliers: { {d.isoformat(): c for d, c in s.outliers.items()} }")
    print(f"weekly medians: {s.weekly_medians}")
    print(f"passport median: {s.passport_median}, approved: {s.approved}, refused: {s.refused}")
    print()
    print("=== персональный прогноз ===")
    print(clean(stats.build_personal_forecast(s, LABEL, today - timedelta(days=40))))
    print()
    print("=== ежедневная сводка ===")
    summary = stats.build_daily_summary([CITY], {VISA: LABEL})
    print(clean(summary) if summary else "нет данных")
    print()
    print("=== кеш ===")
    import time as _t
    t0 = _t.perf_counter(); stats.collect_cached(CITY, VISA); t1 = _t.perf_counter()
    stats.invalidate(CITY, VISA)
    print(f"повторный вызов из кеша: {(t1 - t0) * 1000:.2f} мс")
    print()
    print("=== всплеск ===")
    spike = stats.check_spike(CITY, VISA, (today - timedelta(days=1)).isoformat())
    print(f"check_spike вчера: {spike}")
finally:
    import sqlite3
    conn = sqlite3.connect(db.DB_PATH)
    conn.execute(f"DELETE FROM reports WHERE id IN ({','.join('?' * len(seeded_ids))})", seeded_ids)
    conn.commit()
    conn.close()
    print(f"cleaned: {len(seeded_ids)} rows")
