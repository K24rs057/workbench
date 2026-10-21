"""モーニングブリーフとの連携(F22 1.07・2026-10-21 本人の決定 モッチ-5 A)。

段取りさんが予定・締切・大学の連絡・カレンダーの持ち主。ブリーフ(Claude Code の morning-brief)は、
夜の PC の回でここの窓口を読み、「今日の段取り」「期限」「段取りさんの様子」を載せる。
ブリーフが Web で見つけた締切は、ここに送られ、「確認してほしいこと」に入る(モッチが「タスクにする?」と聞ける)。
"""
import json
from datetime import date, datetime, timedelta

import containers
import gcal
import status
import timetable


def summary(con, day=None, now=None):
    """対象日の段取り(ブリーフの「今日の段取り」「期限」)。day はブリーフの対象日。"""
    import top
    day = day or date.today()
    now = now or datetime.now()
    t = top.build(con, today=day)
    pick = lambda x: {k: x.get(k) for k in ("name", "container", "due_date", "due_time", "start_date")}
    week_end = (day + timedelta(days=7)).isoformat()
    due = [dict(r) for r in con.execute(
        """SELECT t.name, t.due_date, t.due_time, c.name AS container, k.name AS kind FROM tasks t JOIN containers c ON c.id = t.container_id
           LEFT JOIN kinds k ON k.id = c.kind_id WHERE t.done = 0 AND c.ended = 0 AND t.due_date >= ? AND t.due_date <= ?
           ORDER BY t.due_date, t.due_time IS NULL, t.due_time""", (day.isoformat(), week_end))]
    return {
        "date": day.isoformat(),
        "classes": [{"name": c["name"], "start": c["start"], "end": c["end"]} for c in timetable.classes_on(con, day)],
        "events": t.get("events_today") or [],
        "held": t.get("held_today") or [],
        "due_today": [pick(x) for x in t.get("today_tasks") or []],
        "overdue": [pick(x) for x in t.get("overdue") or []],
        "due_7days": due,
        "started": [pick(x) for x in (t.get("today_tasks") or []) if x.get("started")],
    }


def health(con, since=None, now=None):
    """段取りさんの様子(ブリーフの「段取りさんの様子」)。since から後に起きたこと。"""
    now = now or datetime.now()
    since = since or (now - timedelta(days=1))
    s = since.isoformat(timespec="seconds")
    jobs = status.jobs(con, now)
    late = [j for j in jobs if j["late"] and j["last_run_at"]]
    errors = [{"job": j["job"], "error": j["error"]} for j in jobs if j.get("error")]
    sync = gcal.sync_state(con) or {}
    count = lambda sql, *a: con.execute(sql, a).fetchone()[0]
    return {
        "checked_at": now.isoformat(timespec="seconds"),
        "since": s,
        "ok": not late and not errors and not (sync.get("bad") and sync.get("streak", 0) >= 2),
        "jobs": [{"job": j["job"], "last_run_at": j["last_run_at"], "late": j["late"]} for j in jobs],
        "late": [j["job"] for j in late],
        "errors": errors,
        "calendar": {"checked_at": sync.get("at"), "bad": len(sync.get("bad") or []), "streak": sync.get("streak", 0), "written": sync.get("checked")},
        "new_mail": count("SELECT COUNT(*) FROM messages WHERE received_at >= ? AND category NOT IN ('Forms', '提出受付')", s),
        "auto_done": [r[0] for r in con.execute("SELECT t.name FROM tasks t WHERE t.auto_done_by IS NOT NULL AND t.done_at >= ?", (s,))],
        "mochi_actions": count("SELECT COUNT(*) FROM agent_actions WHERE state = '済' AND created_at >= ?", s),
        "held_waiting": len(gcal.held_waiting(con)),
        "questions_waiting": count("SELECT COUNT(*) FROM notices WHERE answered = 0"),
        "unsorted": count("SELECT COUNT(*) FROM tasks WHERE done = 0 AND container_id = ?", containers.unsorted_id(con)),
    }


def add_findings(con, items):
    """ブリーフが見つけた締切を「確認してほしいこと」に入れる。同じものは二度入れない。入れた数を返す。"""
    n = 0
    for it in items[:20]:
        title = str(it.get("title") or "").strip()[:80]
        day = str(it.get("date") or "")
        try:
            date.fromisoformat(day)
        except ValueError:
            continue
        if not title:
            continue
        data = {"title": title, "date": day, "time": it.get("time") or None, "source": str(it.get("source") or "")[:80],
                "url": it.get("url") if str(it.get("url") or "").startswith(("https://", "http://")) else None}
        if con.execute("SELECT 1 FROM notices WHERE kind = 'ブリーフの締切' AND body LIKE ?", (f'%"title": {json.dumps(title, ensure_ascii=False)}%"date": "{day}"%',)).fetchone():
            continue
        if con.execute("SELECT 1 FROM tasks WHERE name = ? AND due_date = ?", (title, day)).fetchone():
            continue
        con.execute("INSERT INTO notices(kind, body) VALUES ('ブリーフの締切', ?)", (json.dumps(data, ensure_ascii=False),))
        n += 1
    return n


def answer_finding(con, n, container_id=None, none=False):
    """「ブリーフが見つけた締切」に答える:入れ物を選べばタスクにする。none ならいらない。"""
    import tasks
    if not none:
        if not container_id:
            raise ValueError("どの授業・会社・開発のタスクにするかを選んでください")
        d = json.loads(n["body"])
        tasks.add(con, {"container_id": int(container_id), "name": d["title"], "due_date": d["date"], "due_time": d.get("time"),
                        "open_url": d.get("url")})
    con.execute("UPDATE notices SET answered = 1 WHERE id = ?", (n["id"],))
