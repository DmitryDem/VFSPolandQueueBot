"""Анализ внесённых номеров очереди (первые 5 цифр PLB) vs дата постановки."""
from pathlib import Path

import paramiko

REMOTE = r'''
import sqlite3
c = sqlite3.connect("/opt/vfsbot/data/reports.db"); c.row_factory = sqlite3.Row
rows = c.execute(
    "SELECT id, city, visa_type, queue_date, queue_time, queue_num "
    "FROM reports WHERE queue_num IS NOT NULL AND queue_num != '' "
    "ORDER BY queue_date, queue_time").fetchall()
print("анкет с номером:", len(rows))
print()
print("  id | город        | виза     | дата постан.  время | номер")
print("  " + "-"*66)
pts = []
for r in rows:
    t = r["queue_time"] or "  -  "
    print("  %3d | %-12s | %-8s | %s  %5s | %s" % (
        r["id"], r["city"], r["visa_type"], r["queue_date"], t, r["queue_num"]))
    try:
        s = r["queue_num"].strip()
        # приводим к 6-значной шкале: старые 5-значные *10 (нижняя граница, погрешность ≤9)
        val = int(s) * 10 ** (6 - len(s)) if len(s) <= 6 else int(s[:6])
        pts.append((r["queue_date"], r["queue_time"], val, r["city"]))
    except (TypeError, ValueError, AttributeError):
        pass
print()

# корреляция номер vs дата (порядковый день)
from datetime import date
if len(pts) >= 2:
    d0 = min(date.fromisoformat(p[0]) for p in pts)
    xs = [(date.fromisoformat(p[0]) - d0).days + (int(p[1][:2])/24 if p[1] else 0) for p in pts]
    ys = [p[2] for p in pts]
    n = len(xs)
    mx = sum(xs)/n; my = sum(ys)/n
    sxx = sum((x-mx)**2 for x in xs); sxy = sum((x-mx)*(y-my) for x,y in zip(xs,ys))
    syy = sum((y-my)**2 for y in ys)
    if sxx > 0 and syy > 0:
        slope = sxy/sxx
        r_corr = sxy/(sxx**0.5 * syy**0.5)
        intercept = my - slope*mx
        print("=== номер = a*день + b (день 0 = %s) ===" % d0.isoformat())
        print("наклон (номеров/день): %.1f" % slope)
        print("коэф. корреляции r: %.4f (r^2=%.4f)" % (r_corr, r_corr**2))
        print("оценка номера в день 0: %.0f" % intercept)
        print("min номер: %d | max номер: %d | размах: %d" % (min(ys), max(ys), max(ys)-min(ys)))
c.close()
'''
ROOT = Path(__file__).resolve().parent.parent
key = paramiko.Ed25519Key.from_private_key_file(str(ROOT / ".ssh" / "vfsbot_deploy"))
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("83.168.90.41", username="root", pkey=key, timeout=30)
sftp = ssh.open_sftp()
with sftp.open("/tmp/qn.py", "wb") as fh:
    fh.write(REMOTE.encode("utf-8"))
sftp.close()
_, out, err = ssh.exec_command(
    "runuser -u vfsbot -- /opt/vfsbot/.venv/bin/python /tmp/qn.py; rm -f /tmp/qn.py", timeout=60)
print(out.read().decode())
e = err.read().decode()
if e.strip():
    print("ERR:", e)
ssh.close()
