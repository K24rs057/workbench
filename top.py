"""トップ画面の中身をまとめて作る(要件 F3・F6・F16・F17・F21、基本設計 S1、API A1)。"""
from datetime import date, timedelta

import containers
import quick
import tasks
import timetable


def _task_key(t, sort_first):
    # 同じ日の中は ①時刻順(時刻なしは最後)②「先に並べる」種類が先 ③登録が古い順(要件 F3)
    return (t["due_date"] or "9999", t["due_time"] or "99:99", 0 if sort_first.get(t["container_id"]) else 1, t["created_at"])


def build(con, today=None):
    today = today or date.today()
    timetable.refresh(con)
    rows = con.execute(
        """SELECT t.*, c.name AS c_name, c.is_unsorted, k.name AS k_name, k.color AS k_color, k.sort_first
           FROM tasks t JOIN containers c ON c.id = t.container_id LEFT JOIN kinds k ON k.id = c.kind_id
           WHERE t.done = 0 AND c.ended = 0"""
    ).fetchall()
    sort_first = {r["container_id"]: r["sort_first"] for r in rows}

    import notify
    warn = notify.marks(con, today)

    def item(r):
        j = tasks.to_json(con, r)
        j["warn"] = warn.get(r["id"])
        j["label"] = {"name": r["c_name"], "color": containers.GRAY if r["is_unsorted"] else r["k_color"]}
        j["unsorted"] = bool(r["is_unsorted"])
        return j

    t0 = today.isoformat()
    week_end = (today + timedelta(days=6)).isoformat()  # 今日を入れて7日間(基本設計 Q4)
    ordered = sorted(rows, key=lambda r: _task_key(r, sort_first))
    overdue = [item(r) for r in ordered if r["due_date"] and r["due_date"] < t0]
    today_ = [item(r) for r in ordered if r["due_date"] == t0]
    # 着手日で「今日」に上がったタスク:今日が締切のものの下に「今日から始める」でまとめる(F16・Q3)
    def is_started(r):
        return bool(r["start_date"]) and r["start_date"] <= t0 and (not r["due_date"] or r["due_date"] > t0)
    started = [item(r) for r in ordered if is_started(r)]
    week = [item(r) for r in ordered if r["due_date"] and t0 < r["due_date"] <= week_end and not is_started(r)]
    nodue = [item(r) for r in sorted((r for r in rows if not r["due_date"] and not is_started(r)), key=lambda r: r["created_at"])]

    # 今日の時間・明日の時間(①では時間割の授業だけ。予定は作る順番③)
    tomorrow = today + timedelta(days=1)
    classes_today = timetable.classes_on(con, today)
    classes_tomorrow = timetable.classes_on(con, tomorrow)

    def held(day):
        return [{"name": h["title"], "start": (h["start_at"][11:16] or "終日"), "held": True}
                for h in con.execute("SELECT * FROM held_events WHERE substr(start_at, 1, 10) = ? ORDER BY start_at", (day.isoformat(),))]

    import gcal

    def events(day):
        """Google カレンダーの、時刻の決まった予定(F12)。段取りさんが書いた締切は出さない。"""
        got = gcal.cached(day.isoformat(), day.isoformat())
        return [{"name": e["name"], "start": e["start"], "end": e["end"], "invited": e["invited"]}
                for e in (got or []) if not e["all_day"] and e["marked"] != "task"]

    # 今日のリンク:今日の授業の順 → 「いつもトップに出す」(基本設計 S1-12)
    link_rows, seen = [], set()
    def add_links(cid, extra=None):
        if not cid or cid in seen:
            return
        seen.add(cid)
        cname = con.execute("SELECT name FROM containers WHERE id = ?", (cid,)).fetchone()["name"]
        for l in con.execute("SELECT * FROM links WHERE container_id = ? ORDER BY id", (cid,)):
            link_rows.append({"id": l["id"], "name": l["name"], "target": l["target"], "container": cname, "web": is_web(l["target"])})
    for c in classes_today:
        add_links(c["container_id"])
    for c in con.execute("SELECT id FROM containers WHERE links_always_top = 1 AND ended = 0 ORDER BY name"):
        add_links(c["id"])

    # ゲージ:全体1本。押すと種類ごとと、今日・今週にタスクがある入れ物(F6・Q30)
    ov = containers.overview(con, today)
    near = {t["container_id"] for t in today_ + started + week + overdue}
    gauge_items = [i for k in ov["kinds"] for i in k["items"] if i["id"] in near]

    # お知らせ(2段目)。①で出せるものだけ
    notices = []
    import notify as _n
    import status as _st
    for text in _n.take_pending(con):
        notices.append({"kind": "pc", "text": text})
    if _st.late_jobs(con):
        notices.append({"kind": "error", "text": "止まっている仕事があります(設定の「本体の様子」)"})
    term = timetable.term_notice(con, today)
    if term:
        notices.append({"kind": "term", "text": term})
    err = timetable.error(con)
    if err:
        notices.append({"kind": "error", "text": "時間割を読めませんでした。前に読んだ時間割を使っています"})
    import worklog
    waiting = con.execute("SELECT COUNT(*) FROM notices WHERE answered = 0").fetchone()[0]
    if waiting:
        notices.append({"kind": "ask", "text": f"確認してほしいこと {waiting}件", "count": waiting})
    new_mail = con.execute("SELECT COUNT(*) FROM messages WHERE seen = 0 AND category NOT IN ('Forms', '提出受付')").fetchone()[0]
    if new_mail:
        notices.append({"kind": "mail", "text": f"新しい連絡 {new_mail}件", "count": new_mail})
    waiting_held = len(gcal.held_waiting(con))
    if waiting_held:
        notices.append({"kind": "held", "text": f"カレンダーに書かなかった予定 {waiting_held}件", "count": waiting_held})
    import autodone
    maybe = len(autodone.maybe_list(con))
    if maybe:  # 2段目⑧(F18 ④)。押すと [完了] [ちがう] の小窓
        notices.append({"kind": "maybe", "text": f"終わっていそうなタスク {maybe}件", "count": maybe})
    for key in ("outlook_error", "gmail_error", "calendar_error", "git_error", "autodone_error"):
        oe = con.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        if oe:
            notices.append({"kind": "error", "text": oe["value"]})
    if ov["unsorted"]:
        notices.append({"kind": "unsorted", "text": f"未分類 {ov['unsorted']}件", "count": ov["unsorted"]})

    return {
        "today": t0,
        "gauge": {"overall": containers.overall(con),
                  "kinds": [{"name": k["name"], "color": k["color"], "progress": k["progress"]} for k in ov["kinds"]],
                  "items": [{"id": i["id"], "name": i["name"], "progress": i["progress"]} for i in gauge_items]},
        "links": link_rows,
        "notices": notices,
        "done_questions": worklog.open_done_questions(con, today),
        "overdue": overdue, "today_tasks": today_, "started": started, "week": week, "nodue": nodue,
        "quick_ai": quick.ai_on(con),
        "classes_today": classes_today, "classes_tomorrow": classes_tomorrow,
        "held_today": held(today), "held_tomorrow": held(tomorrow),
        "events_today": events(today), "events_tomorrow": events(tomorrow),
        "calendar_on": gcal.cached() is not None,
        "new_mail": new_mail,
    }


def is_web(target):
    return target.startswith(("http://", "https://"))
