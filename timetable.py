"""時間割の読み込み(要件 F10)。

モーニングブリーフの timetable.md を読むだけ(書き換えない)。読むのは曜日・時限・科目名だけで、
先生の名前や教室は読み捨てる。科目ごとに「大学」の入れ物を1回だけ作り、名前を変えても
source_key(科目名)でつながりを保つ(基本設計 Q1・Q27)。
"""
import json
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path

DEFAULT_PATH = Path(os.path.expanduser("~")) / ".claude" / "scheduled-tasks" / "morning-brief" / "timetable.md"
DAYS = {"月": 0, "火": 1, "水": 2, "木": 3, "金": 4, "土": 5, "日": 6}
PERIOD_TIME_RE = re.compile(r"(\d)限\s*(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})")
CLASS_RE = re.compile(r"^\s*-\s*((?:\d限[・、,]?\s*)+)[::]\s*(.+)$")
READ_EVERY = timedelta(minutes=10)  # Claude の案(要件 F10)
TERM_END_DEFAULT = "2027-01-22"      # 基本設計 Q7(2026年度後期)


class TimetableError(Exception):
    pass


def path_from_settings(con):
    row = con.execute("SELECT value FROM settings WHERE key = 'timetable_path'").fetchone()
    return Path(os.environ.get("DANDORI_TIMETABLE") or (row["value"] if row else DEFAULT_PATH))


def parse(text):
    """{曜日の番号: [{name, periods, start, end}]} を返す。"""
    times = {int(p): (s.zfill(5), e.zfill(5)) for p, s, e in PERIOD_TIME_RE.findall(text)}
    if not times:
        raise TimetableError("時限の時刻が書いてありません")
    week, current = {}, None
    for line in text.splitlines():
        if line.startswith("## "):
            current = [DAYS[ch] for ch in line[3:] if ch in DAYS]
            continue
        m = CLASS_RE.match(line)
        if not m or current is None:
            continue
        periods = [int(p) for p in re.findall(r"(\d)限", m.group(1))]
        name = re.split(r"[((/]", m.group(2), maxsplit=1)[0].strip()
        if not name or any(p not in times for p in periods):
            continue
        item = {"name": name, "periods": periods, "start": times[min(periods)][0], "end": times[max(periods)][1]}
        for d in current:
            week.setdefault(d, []).append(item)
    for d in week:
        week[d].sort(key=lambda i: i["start"])
    return week


def _set(con, key, value):
    con.execute("INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))


def _get(con, key):
    row = con.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def refresh(con, now=None, force=False):
    """10分ごとに読む。読めたら入れ物を作り、読めなかったら前に読んだものを使い続ける。"""
    now = now or datetime.now()
    last = _get(con, "timetable_read_at")
    if not force and last and now - datetime.fromisoformat(last) < READ_EVERY:
        return
    if _get(con, "term_end") is None:
        _set(con, "term_end", TERM_END_DEFAULT)
    _set(con, "timetable_read_at", now.isoformat(timespec="seconds"))
    try:
        week = parse(path_from_settings(con).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, TimetableError) as e:
        _set(con, "timetable_error", str(e) or "読めませんでした")
        con.execute("INSERT INTO job_status(job, last_error) VALUES ('時間割の読み込み', ?) ON CONFLICT(job) DO UPDATE SET last_error = excluded.last_error", (str(e),))
        return
    con.execute("DELETE FROM settings WHERE key = 'timetable_error'")
    _set(con, "timetable_cache", json.dumps(week, ensure_ascii=False))
    con.execute("INSERT INTO job_status(job, last_run_at, last_error) VALUES ('時間割の読み込み', ?, NULL) ON CONFLICT(job) DO UPDATE SET last_run_at = excluded.last_run_at, last_error = NULL", (now.isoformat(timespec="seconds"),))
    sync_containers(con, week)


def sync_containers(con, week):
    """科目ごとに大学の入れ物を作る。すでにあれば(種類を移していても、終了していても)作り直さない。"""
    uni = con.execute("SELECT id FROM kinds WHERE builtin = 1 ORDER BY id LIMIT 1").fetchone()["id"]
    names = {i["name"] for items in week.values() for i in items}
    for name in sorted(names):
        if not con.execute("SELECT 1 FROM containers WHERE source_key = ? AND auto_source = '時間割'", (name,)).fetchone():
            con.execute("INSERT INTO containers(kind_id, name, auto_source, source_key) VALUES (?, ?, '時間割', ?)", (uni, name, name))


def classes_on(con, day):
    """その日の授業。入れ物の番号と今の名前をつけて返す。"""
    cache = _get(con, "timetable_cache")
    if not cache:
        return []
    items = json.loads(cache).get(str(day.weekday()), [])
    out = []
    for i in items:
        c = con.execute("SELECT id, name, ended FROM containers WHERE source_key = ? AND auto_source = '時間割'", (i["name"],)).fetchone()
        if c and c["ended"]:
            continue
        out.append({**i, "container_id": c["id"] if c else None, "name": c["name"] if c else i["name"]})
    return out


def term_notice(con, today=None):
    """学期の終わりの1週間前から、米印のお知らせを出す(基本設計 Q7)。"""
    today = today or date.today()
    end = _get(con, "term_end")
    if not end:
        return None
    end_d = date.fromisoformat(end)
    if end_d - timedelta(days=7) <= today <= end_d:
        return f"※学期が終わります({end_d.month}/{end_d.day})。時間割の入れ替えを Claude に頼んでください"
    return None


def error(con):
    return _get(con, "timetable_error")
