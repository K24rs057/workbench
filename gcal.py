"""Google カレンダー(要件 F12・F13・F19、基本設計 Q8・Q9、表 event_extras・held_events)。

予定の本体は Google カレンダー(メインのカレンダー)に置き、段取りさんは写しを持たない。
読んだ予定は、本体が動いている間だけメモリに置く(10分ごとに読み直す)。
段取りさんが書いた予定には、見えない目印(extendedProperties.private.dandori)をつけ、直す・消すのは目印のある予定だけ。
"""
import re
import threading
from datetime import date, datetime, timedelta

import mails

EVERY = timedelta(minutes=10)
BACK_DAYS = 70         # 読む範囲:今日の70日前から(予定の画面の「月」で先月まで、月末の日でも読みおきだけで出せるように)
AHEAD_DAYS = 100       # 100日先まで(再来月まで)
EXTRA_FOR = timedelta(minutes=10)  # 範囲の外の月は、一度聞いたら10分覚えておく
MARK = "dandori"
HM_RE = re.compile(r"^\d{1,2}:\d{2}$")
PREFIX_RE = re.compile(r"^(済\s+)?(締切\s+(\d{1,2}:\d{2}\s+)?)?")

_lock = threading.Lock()
_cache = {"at": None, "from": None, "to": None, "items": [], "error": None}
_extra = {}  # 範囲の外を聞いたときの写し。(from, to) → (聞いた時刻, 予定)。動いている間だけ覚える


# ---------- Google とのやりとり(テストでは作り物に差しかえる) ----------
class GoogleCalendar:
    def __init__(self, creds=None):
        import gmail
        from googleapiclient.discovery import build
        creds = creds or gmail.credentials()
        if not creds:
            raise PermissionError("Google の許可がまだありません")
        self.svc = build("calendar", "v3", credentials=creds, cache_discovery=False)

    def list(self, time_min, time_max):
        out, page = [], None
        while True:
            r = self.svc.events().list(calendarId="primary", timeMin=time_min, timeMax=time_max, singleEvents=True,
                                       orderBy="startTime", maxResults=250, pageToken=page).execute()
            out += r.get("items", [])
            page = r.get("nextPageToken")
            if not page:
                return out

    def get(self, eid):
        return self.svc.events().get(calendarId="primary", eventId=eid).execute()

    def insert(self, body):
        return self.svc.events().insert(calendarId="primary", body=body).execute()

    def patch(self, eid, body):
        return self.svc.events().patch(calendarId="primary", eventId=eid, body=body).execute()

    def delete(self, eid):
        self.svc.events().delete(calendarId="primary", eventId=eid).execute()


def _api():
    import gmail
    if not gmail.calendar_allowed():
        return None
    return GoogleCalendar()


# ---------- 予定の形 ----------
def _rfc(d, end=False):
    t = datetime.combine(d, datetime.min.time())
    return t.astimezone().isoformat()


def normalize(ev):
    """Google の予定を、画面で使う形にする。"""
    s, e = ev.get("start", {}), ev.get("end", {})
    all_day = "date" in s
    priv = (ev.get("extendedProperties") or {}).get("private") or {}
    org = ev.get("organizer") or {}
    start = s.get("date") or s.get("dateTime", "")[:16]
    end = e.get("date") or e.get("dateTime", "")[:16]
    return {"id": ev["id"], "name": ev.get("summary") or "(名前なし)", "all_day": all_day,
            "date": start[:10], "start": None if all_day else start[11:16], "end": None if all_day else end[11:16],
            "end_date": end[:10], "last": last_day(all_day, start, end), "location": ev.get("location"), "marked": priv.get(MARK),
            "task_id": int(priv["dandori_task"]) if priv.get("dandori_task", "").isdigit() else None,
            "invited": not org.get("self", True), "guests_can_modify": bool(ev.get("guestsCanModify")),
            "link": ev.get("htmlLink")}


def last_day(all_day, start, end):
    """予定がかかる最後の日。終日の予定は Google では終わりの日を含まないので1日もどす。
    時刻つきで 0:00 に終わる予定も、その日にはかからない。"""
    first = start[:10]
    if not end or end[:10] <= first:
        return first
    if all_day:
        return max(first, (date.fromisoformat(end[:10]) - timedelta(days=1)).isoformat())
    if end[11:16] == "00:00":
        return max(first, (date.fromisoformat(end[:10]) - timedelta(days=1)).isoformat())
    return end[:10]


def covers(e, day):
    """その日にかかる予定か(何日も続く予定は、間の日にもかかる)。"""
    return e["date"] <= day <= e.get("last", e["date"])


def task_summary(t):
    """締切は終日の予定にし、時刻は名前に書く(F13)。完了したら頭に「済」。"""
    s = f"締切 {t['due_time']} {t['name']}" if t["due_time"] else f"締切 {t['name']}"
    return ("済 " + s) if t["done"] else s


def bare_name(summary):
    return PREFIX_RE.sub("", summary or "").strip()


def _all_day_body(day, summary, private):
    d = date.fromisoformat(day)
    return {"summary": summary, "start": {"date": d.isoformat()}, "end": {"date": (d + timedelta(days=1)).isoformat()},
            "extendedProperties": {"private": private}}


def _timed_body(day, start, end, summary, private):
    st = datetime.fromisoformat(f"{day}T{start}")
    en = datetime.fromisoformat(f"{day}T{end}") if end else st + timedelta(hours=1)
    return {"summary": summary, "start": {"dateTime": st.astimezone().isoformat()}, "end": {"dateTime": en.astimezone().isoformat()},
            "extendedProperties": {"private": private}}


def overlaps(items, day, start, end):
    """同じ日に時間帯が重なる予定(名前がちがっても同じとみなす。F13)。"""
    if not start:
        return []
    s = datetime.fromisoformat(f"{day}T{start}")
    e = datetime.fromisoformat(f"{day}T{end}") if end else s + timedelta(hours=1)
    out = []
    for it in items:
        if it["all_day"] or it["date"] != day or not it["start"]:
            continue
        a = datetime.fromisoformat(f"{it['date']}T{it['start']}")
        b = datetime.fromisoformat(f"{it['end_date']}T{it['end']}") if it["end"] else a + timedelta(hours=1)
        if a < e and s < b:
            out.append(it)
    return out


# ---------- 読む(F12) ----------
def cached(day_from=None, day_to=None):
    """読んである予定のうち、その日の範囲にかかるもの(前から続いている予定も入れる)。読めていなければ None。"""
    with _lock:
        if _cache["at"] is None:
            return None
        items = list(_cache["items"])
    return [i for i in items if (not day_from or i.get("last", i["date"]) >= day_from) and (not day_to or i["date"] <= day_to)]


def error():
    return _cache["error"]


def extra(day_from, day_to, now=None):
    """範囲の外の月を、10分以内に聞いていればその写し。なければ None。"""
    now = now or datetime.now()
    with _lock:
        got = _extra.get((day_from, day_to))
    return list(got[1]) if got and now - got[0] < EXTRA_FOR else None


def keep_extra(day_from, day_to, items, now=None):
    with _lock:
        _extra[(day_from, day_to)] = (now or datetime.now(), list(items))


def remember(ev):
    """画面で足した予定を、次に読むまでの間も出せるようにする。"""
    with _lock:
        _extra.clear()
        if _cache["at"] is not None:
            _cache["items"] = [i for i in _cache["items"] if i["id"] != ev["id"]] + [normalize(ev)]


def forget(gid):
    """直した・消した予定は、次に読むまで出さない(古い形のまま出さないため)。"""
    with _lock:
        _extra.clear()
        _cache["items"] = [i for i in _cache["items"] if i["id"] != gid]


def refresh(con, now=None, api=None, force=False):
    """10分ごとに読み、目印のある予定の変化をタスクに戻し、書いていないものを書く。"""
    now = now or datetime.now()
    if api is None:
        try:
            api = _api()
        except Exception as e:
            api, err = None, e
        else:
            err = None
        if api is None:
            if err:
                _fail(con, err)
            return False
    last = _cache["at"]
    dirty = mails.setting(con, "calendar_dirty") == "1"
    if not force and last and now - last < EVERY and not dirty:
        return False
    today = now.date()
    t_min, t_max = today - timedelta(days=BACK_DAYS), today + timedelta(days=AHEAD_DAYS)
    def read():
        raw = api.list(_rfc(t_min), _rfc(t_max))
        got = [normalize(e) for e in raw if e.get("status") != "cancelled"]
        with _lock:
            _extra.clear()
            _cache.update(at=now, items=got, error=None, **{"from": t_min.isoformat(), "to": t_max.isoformat()})
        return got

    try:
        items = read()
        pull_changes(con, items, t_min.isoformat(), t_max.isoformat())
        counted = _Counting(api)
        push_tasks(con, counted, items, today)
        write_held(con, counted, items)
        if counted.writes:  # 書いたら読み直して、本当に Google に入ったかを照らし合わせる
            items = read()
        state = verify(con, items, today, t_max, now)
    except Exception as e:  # つながらない・許可切れなど。推測で埋めない
        _fail(con, e)
        return False
    con.execute("DELETE FROM settings WHERE key IN ('calendar_error', 'calendar_dirty')")
    if state["bad"] and state["streak"] < 2:
        mark_dirty(con)  # ずれていたら、次の1分の見回りでもう一度直す。2回続けて直せなければ知らせる
    con.execute("INSERT INTO job_status(job, last_run_at, last_error) VALUES ('Google カレンダー', ?, NULL) "
                "ON CONFLICT(job) DO UPDATE SET last_run_at = excluded.last_run_at, last_error = NULL", (now.isoformat(timespec="seconds"),))
    return True


class _Counting:
    """書き込みの回数を数える(書いたときだけ読み直すため)。"""
    def __init__(self, api):
        self.api, self.writes = api, 0

    def list(self, *a):
        return self.api.list(*a)

    def insert(self, body):
        self.writes += 1
        return self.api.insert(body)

    def patch(self, eid, body):
        self.writes += 1
        return self.api.patch(eid, body)

    def delete(self, eid):
        self.writes += 1
        return self.api.delete(eid)


# ---------- 同期の確かめ(照らし合わせ) ----------
def verify(con, items, today, t_max, now):
    """段取りさんが書いた締切が、Google カレンダーとそろっているか。手やスマホで足した予定は見ない。
    ずれていたものは、次の見回りで書き直すように印をつけ直す。結果を settings の sync_state に置く。"""
    import json
    by_id = {i["id"]: i for i in items}
    bad, checked = [], 0
    rows = con.execute("SELECT * FROM tasks WHERE due_date >= ? AND due_date < ? AND calendar_deleted = 0",
                       (today.isoformat(), t_max.isoformat())).fetchall()
    for t in rows:
        x = con.execute("SELECT * FROM event_extras WHERE marked = 1 AND task_id = ?", (t["id"],)).fetchone()
        if not x and (t["done"] or not t["calendar_written"] or not _writable(con, t)):
            if not t["done"] and not t["calendar_written"] and _writable(con, t):
                bad.append({"task_id": t["id"], "name": t["name"], "date": t["due_date"], "why": "Google にまだ書けていません"})
                checked += 1
            continue
        checked += 1
        if not x:  # 同じ名前の締切がもうあったので書かなかったもの(モーニングブリーフなど)
            if not any(i["all_day"] and i["date"] == t["due_date"] and bare_name(i["name"]) == t["name"] for i in items):
                con.execute("UPDATE tasks SET calendar_written = 0 WHERE id = ?", (t["id"],))
                bad.append({"task_id": t["id"], "name": t["name"], "date": t["due_date"], "why": "Google にありません"})
            continue
        ev = by_id.get(x["google_event_id"])
        if not ev:
            con.execute("DELETE FROM event_extras WHERE id = ?", (x["id"],))
            con.execute("UPDATE tasks SET calendar_written = 0 WHERE id = ?", (t["id"],))
            bad.append({"task_id": t["id"], "name": t["name"], "date": t["due_date"], "why": "Google にありません"})
            continue
        if ev["name"] != task_summary(t) or ev["date"] != t["due_date"]:
            # Google の今の形を覚え直す。こうすると次の見回りで「Google 側で変えた」とはみなさず、タスクの形で書き直す
            con.execute("UPDATE event_extras SET synced_summary = ?, synced_date = ? WHERE id = ?", (ev["name"], ev["date"], x["id"]))
            bad.append({"task_id": t["id"], "name": t["name"], "date": t["due_date"], "why": "Google の名前か日付が古いままです"})
    prev = json.loads(mails.setting(con, "sync_state") or "{}")
    streak = (prev.get("streak", 0) + 1) if bad else 0
    state = {"at": now.isoformat(timespec="seconds"), "checked": checked, "bad": bad[:30], "streak": streak,
             "held": len(held_waiting(con))}
    mails.set_setting(con, "sync_state", json.dumps(state, ensure_ascii=False))
    return state


def sync_state(con):
    import json
    v = mails.setting(con, "sync_state")
    return json.loads(v) if v else None


def _fail(con, e):
    with _lock:
        _cache["error"] = "Google に接続できませんでした"
    expired = "invalid_grant" in str(e) or isinstance(e, PermissionError)
    mails.set_setting(con, "calendar_error", "Google に接続できませんでした" + ("(設定の「Google」から許可し直してください)" if expired else ""))
    con.execute("INSERT INTO job_status(job, last_error) VALUES ('Google カレンダー', ?) ON CONFLICT(job) DO UPDATE SET last_error = excluded.last_error", (str(e)[:200],))


def mark_dirty(con):
    """タスクが変わったら、次の1分の見回りでカレンダーを直す。"""
    mails.set_setting(con, "calendar_dirty", "1")


def pull_changes(con, items, day_from, day_to):
    """Google 側(スマホなど)での変化を、目印のある締切の予定からタスクに戻す(F13・Q9)。"""
    by_id = {i["id"]: i for i in items}
    for x in con.execute("SELECT * FROM event_extras WHERE marked = 1 AND task_id IS NOT NULL").fetchall():
        ev = by_id.get(x["google_event_id"])
        t = con.execute("SELECT * FROM tasks WHERE id = ?", (x["task_id"],)).fetchone()
        if not ev:
            if x["synced_date"] and day_from <= x["synced_date"] < day_to and t:
                # 読んだ範囲にあるはずなのにない → Google 側で消された。タスクは消さずに印をつける
                con.execute("UPDATE tasks SET calendar_deleted = 1 WHERE id = ?", (t["id"],))
                con.execute("DELETE FROM event_extras WHERE id = ?", (x["id"],))
            continue
        if not t:
            continue
        if ev["date"] != x["synced_date"]:  # Google 側で動かした
            con.execute("UPDATE tasks SET due_date = ? WHERE id = ?", (ev["date"], t["id"]))
            con.execute("UPDATE event_extras SET synced_date = ? WHERE id = ?", (ev["date"], x["id"]))
        if ev["name"] != x["synced_summary"]:  # Google 側で名前を変えた → タスク名もそろえる
            nm = bare_name(ev["name"])
            if nm:
                con.execute("UPDATE tasks SET name = ? WHERE id = ?", (nm, t["id"]))
            con.execute("UPDATE event_extras SET synced_summary = ? WHERE id = ?", (ev["name"], x["id"]))


def _writable(con, t):
    """書いてよいタスクか。「その他」のメールから未分類に入ったままのものは書かない(F13・Q8)。"""
    if not t["due_date"] or t["calendar_deleted"]:
        return False
    if t["from_message_id"]:
        r = con.execute("SELECT m.category, c.is_unsorted FROM messages m, containers c WHERE m.id = ? AND c.id = ?",
                        (t["from_message_id"], t["container_id"])).fetchone()
        if r and r["category"] == "その他" and r["is_unsorted"]:
            return False
    return True


def push_tasks(con, api, items, today):
    """タスクの締切を書く・書き直す・消す。"""
    # 消したタスクの予定を消す
    for x in con.execute("SELECT * FROM event_extras WHERE marked = 1 AND task_id IS NOT NULL AND task_id NOT IN (SELECT id FROM tasks)").fetchall():
        try:
            api.delete(x["google_event_id"])
        except Exception as e:
            if "404" not in str(e) and "410" not in str(e):
                raise
        con.execute("DELETE FROM event_extras WHERE id = ?", (x["id"],))
    # 書いたタスクの変化を直す(締切・名前・完了の「済」)
    for x in con.execute("SELECT x.*, t.name, t.due_date, t.due_time, t.done FROM event_extras x JOIN tasks t ON t.id = x.task_id WHERE x.marked = 1").fetchall():
        if not x["due_date"]:
            api.delete(x["google_event_id"])
            con.execute("DELETE FROM event_extras WHERE id = ?", (x["id"],))
            con.execute("UPDATE tasks SET calendar_written = 0 WHERE id = ?", (x["task_id"],))
            continue
        want = task_summary(x)
        if want != x["synced_summary"] or x["due_date"] != x["synced_date"]:
            d = date.fromisoformat(x["due_date"])
            api.patch(x["google_event_id"], {"summary": want, "start": {"date": d.isoformat()}, "end": {"date": (d + timedelta(days=1)).isoformat()}})
            con.execute("UPDATE event_extras SET synced_summary = ?, synced_date = ? WHERE id = ?", (want, x["due_date"], x["id"]))
    # まだ書いていないものを書く(初めては、締切が今日以降で終わっていないものだけ。Claude の案)
    rows = con.execute("SELECT * FROM tasks WHERE calendar_written = 0 AND done = 0 AND due_date >= ?", (today.isoformat(),)).fetchall()
    for t in rows:
        if not _writable(con, t):
            continue
        want = task_summary(t)
        same = [i for i in items if i["all_day"] and i["date"] == t["due_date"] and bare_name(i["name"]) == t["name"]]
        if same:  # 同じ日に同じ名前の締切がもうある(モーニングブリーフが書いたものなど)→ 書かない
            con.execute("UPDATE tasks SET calendar_written = 1 WHERE id = ?", (t["id"],))
            continue
        ev = api.insert(_all_day_body(t["due_date"], want, {MARK: "task", "dandori_task": str(t["id"])}))
        con.execute("INSERT INTO event_extras(google_event_id, marked, task_id, container_id, synced_date, synced_summary) VALUES (?, 1, ?, ?, ?, ?)",
                    (ev["id"], t["id"], t["container_id"], t["due_date"], want))
        con.execute("UPDATE tasks SET calendar_written = 1 WHERE id = ?", (t["id"],))
        items.append(normalize(ev))


WRITE_REASONS = ("カレンダーがまだつながっていない", "つながらなかった")


def write_held(con, api, items, only=None, force=False):
    """預かった予定(面接・休講・補講)を書く。時間帯が重なる予定があれば書かずに残し、選んでもらう(F13)。"""
    q = "SELECT * FROM held_events WHERE " + ("id = ?" if only else "reason IN (?, ?)")
    args = (only,) if only else WRITE_REASONS
    for h in con.execute(q, args).fetchall():
        day, start = h["start_at"][:10], (h["start_at"][11:16] or None)
        end = h["end_at"][11:16] if h["end_at"] else None
        if not force:
            if (start and overlaps(items, day, start, end)) or (not start and any(i["all_day"] and i["date"] == day and i["name"] == h["title"] for i in items)):
                con.execute("UPDATE held_events SET reason = '重なる予定がある' WHERE id = ?", (h["id"],))
                continue
        priv = {MARK: "held"}
        body = _timed_body(day, start, end, h["title"], priv) if start else _all_day_body(day, h["title"], priv)
        ev = api.insert(body)
        con.execute("INSERT INTO event_extras(google_event_id, marked, container_id, synced_date, synced_summary) VALUES (?, 1, ?, ?, ?)",
                    (ev["id"], h["container_id"], day, h["title"]))
        con.execute("DELETE FROM held_events WHERE id = ?", (h["id"],))
        items.append(normalize(ev))


def held_waiting(con):
    """書けずに残っている予定(トップ2段目⑥・予定の画面 S2-3)。"""
    return con.execute("SELECT * FROM held_events WHERE reason != 'カレンダーがまだつながっていない' ORDER BY start_at").fetchall()
