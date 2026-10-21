"""予定の画面(要件 F19、基本設計 S2、API A17〜A19)。予定の本体は Google カレンダーで、ここでは読み書きの窓になる。"""
from datetime import date, timedelta

from flask import jsonify, request

import containers
import gcal
import mails
import timetable
from api import body, bp, con
from containers import UserError

NOT_CONNECTED = "Google に接続できませんでした"


def _cal():
    try:
        api = gcal._api()
    except Exception:
        api = None
    if api is None:
        raise UserError(NOT_CONNECTED + "(設定の「Google」で許可してください)")
    return api


def _google(fn, *a):
    try:
        return fn(*a)
    except UserError:
        raise
    except Exception as e:
        if "forbidden" in str(e).lower() or "403" in str(e):
            raise UserError("主催者が変更を許可していないため、直せませんでした")
        raise UserError(NOT_CONNECTED)


def _labels(c):
    out = {}
    for r in c.execute("SELECT c.id, c.name, c.is_unsorted, k.name AS kind, k.color FROM containers c LEFT JOIN kinds k ON k.id = c.kind_id"):
        out[r["id"]] = {"name": r["name"], "color": containers.GRAY if r["is_unsorted"] else r["color"], "kind": r["kind"]}
    return out


def _events(day_from, day_to):
    """読んである予定を使う。読んだ範囲の外なら、その場で Google に聞き、10分だけ覚えておく。"""
    got = None
    c = gcal._cache
    if c["at"] and c["from"] <= day_from and day_to <= c["to"]:
        got = gcal.cached(day_from, day_to)
    if got is None:
        got = gcal.extra(day_from, day_to)
    if got is None:
        api = _cal()
        d0, d1 = date.fromisoformat(day_from), date.fromisoformat(day_to) + timedelta(days=1)
        raw = _google(api.list, gcal._rfc(d0), gcal._rfc(d1))
        got = [gcal.normalize(e) for e in raw if e.get("status") != "cancelled"]
        gcal.keep_extra(day_from, day_to, got)
    return got


@bp.get("/schedule")
def schedule():
    """日付ごとに、授業のまとめ・予定・締切・預かった予定(A17)。"""
    today = date.today()
    d0 = date.fromisoformat(request.args.get("from") or today.isoformat())
    d1 = date.fromisoformat(request.args.get("to") or (d0 + timedelta(days=13)).isoformat())
    if (d1 - d0).days > 62:
        raise UserError("一度に見られるのは2か月までです")
    with con() as c:
        labels = _labels(c)
        extras = {x["google_event_id"]: x for x in c.execute("SELECT * FROM event_extras")}
        error = None
        try:
            events = _events(d0.isoformat(), d1.isoformat())
        except UserError as e:
            events, error = [], str(e)
        days = []
        d = d0
        while d <= d1:
            iso = d.isoformat()
            cls = timetable.classes_on(c, d)
            items = []
            for e in events:
                # 何日も続く予定は、かかる日のすべてに出す。段取りさんが書いた締切は、タスクとして1回だけ出す
                if not gcal.covers(e, iso) or e["marked"] == "task":
                    continue
                x = extras.get(e["id"])
                cid = x["container_id"] if x else None
                last = e.get("last", e["date"])
                multi = last > e["date"]
                # 続く予定は、ここの小窓(1日分の形)で直すと1日に縮んでしまうので、Google カレンダーで直してもらう
                editable = (not e["invited"] or bool(x and x["edit_allowed"])) and not multi
                pos = "only" if not multi else "first" if iso == e["date"] else "last" if iso == last else "mid"
                items.append({"type": "event", "id": e["id"], "name": e["name"], "start": e["start"], "end": e["end"],
                              "all_day": e["all_day"], "invited": e["invited"], "editable": editable, "edit_allowed": bool(x and x["edit_allowed"]),
                              "first": e["date"], "last": last, "multi": multi, "pos": pos, "link": e.get("link"),
                              "location": e["location"], "container_id": cid, "label": labels.get(cid)})
            for t in c.execute("SELECT t.* FROM tasks t JOIN containers c ON c.id = t.container_id WHERE t.due_date = ? AND c.ended = 0", (iso,)):
                items.append({"type": "task", "id": t["id"], "name": t["name"], "start": t["due_time"], "done": bool(t["done"]),
                              "calendar_deleted": bool(t["calendar_deleted"]), "label": labels.get(t["container_id"])})
            for h in c.execute("SELECT * FROM held_events WHERE substr(start_at, 1, 10) = ?", (iso,)):
                items.append({"type": "held", "id": h["id"], "name": h["title"], "start": h["start_at"][11:16] or None,
                              "end": h["end_at"][11:16] if h["end_at"] else None, "reason": h["reason"], "label": labels.get(h["container_id"])})
            def order(i):  # 終日・続く予定の間の日 → 時刻順 → 時刻なしの締切
                if i["type"] == "task":
                    return i["start"] or "99:99"
                if i.get("pos") in ("mid", "last") or i.get("all_day"):
                    return "00:00"
                return i["start"] or "00:00"
            items.sort(key=order)
            classes = {"count": len(cls), "start": cls[0]["start"], "end": max(x["end"] for x in cls), "names": [x["name"] for x in cls]} if cls else None
            days.append({"date": iso, "classes": classes, "items": items})
            d += timedelta(days=1)
        held = [{"id": h["id"], "name": h["title"], "start_at": h["start_at"], "reason": h["reason"]} for h in gcal.held_waiting(c)]
        import gmail
        return jsonify(days=days, error=error, connected=gmail.calendar_allowed(), held=held, sync=gcal.sync_state(c),
                       kinds={k["name"]: k["color"] for k in c.execute("SELECT name, color FROM kinds")})


def _event_body(b):
    name = (b.get("name") or "").strip()
    if not name:
        raise UserError("予定の名前を入れてください")
    day = b.get("date") or ""
    try:
        date.fromisoformat(day)
    except ValueError:
        raise UserError("日付を選んでください")
    start, end = (b.get("start") or None), (b.get("end") or None)
    for v in (start, end):
        if v and not gcal.HM_RE.match(v):
            raise UserError("時刻は 13:00 のように入れてください")
    if end and not start:
        raise UserError("終わりの時刻を入れるときは、始まりの時刻も入れてください")
    if start and end and end <= start:
        raise UserError("終わりの時刻は、始まりより後にしてください")
    # 画面で手で足した予定には、段取りさんの目印をつけない(F13・F19)
    return gcal._timed_body(day, start, end, name, {}) if start else gcal._all_day_body(day, name, {})


def _strip_private(bd):
    bd.pop("extendedProperties", None)
    return bd


def _set_extra(c, gid, **f):
    c.execute("INSERT INTO event_extras(google_event_id) VALUES (?) ON CONFLICT(google_event_id) DO NOTHING", (gid,))
    for k, v in f.items():
        c.execute(f"UPDATE event_extras SET {k} = ? WHERE google_event_id = ?", (v, gid))


@bp.post("/events")
def events_add():
    b = body()
    bd = _strip_private(_event_body(b))
    api = _cal()
    ev = _google(api.insert, bd)
    with con() as c:
        if b.get("container_id"):
            containers.get_row(c, int(b["container_id"]))
            _set_extra(c, ev["id"], container_id=int(b["container_id"]))
        gcal.mark_dirty(c)
    gcal.remember(ev)
    return jsonify(id=ev["id"]), 201


def _current(gid):
    """いまの予定。読んであればそれを、なければ Google に1件だけ聞く(招待か・続く予定かを見分けるため)。"""
    for e in gcal.cached() or []:
        if e["id"] == gid:
            return e
    try:
        api = gcal._api()
        return gcal.normalize(api.get(gid)) if api else None
    except Exception:
        return None


@bp.patch("/events/<gid>")
def events_update(gid):
    b = body()
    with con() as c:
        x = c.execute("SELECT * FROM event_extras WHERE google_event_id = ?", (gid,)).fetchone()
        if "edit_allowed" in b:  # 招待された予定の編集を許すトグル(見るだけ ↔ 直せる)
            _set_extra(c, gid, edit_allowed=1 if b["edit_allowed"] else 0)
            return jsonify(ok=True)
        if "container_id" in b:
            cid = int(b["container_id"]) if b["container_id"] else None
            if cid:
                containers.get_row(c, cid)
            _set_extra(c, gid, container_id=cid)
        e = _current(gid)
        if e and e["invited"] and not (x and x["edit_allowed"]):
            raise UserError("招待された予定は見るだけです。直すときは、予定の「直せるようにする」をオンにしてください")
        if any(k in b for k in ("name", "date", "start", "end")):
            if e and e.get("last", e["date"]) > e["date"]:
                raise UserError("何日も続く予定は、ここでは直せません。Google カレンダーで直してください")
            bd = _strip_private(_event_body(b))
            ev = _google(_cal().patch, gid, bd)
            gcal.mark_dirty(c)
            gcal.remember(ev)  # 直したあとの形で出す
        return jsonify(ok=True)


@bp.delete("/events/<gid>")
def events_delete(gid):
    e = _current(gid)
    if e and e["invited"]:
        raise UserError("招待された予定は、ここでは消せません。Google カレンダーで「参加しない」にしてください")
    _google(_cal().delete, gid)
    with con() as c:
        x = c.execute("SELECT * FROM event_extras WHERE google_event_id = ?", (gid,)).fetchone()
        if x and x["task_id"]:  # 締切の予定を消した → タスクは残し、印をつける(Q9 と同じ)
            c.execute("UPDATE tasks SET calendar_deleted = 1 WHERE id = ?", (x["task_id"],))
        c.execute("DELETE FROM event_extras WHERE google_event_id = ?", (gid,))
        gcal.mark_dirty(c)
    gcal.forget(gid)
    return jsonify(ok=True)


@bp.post("/calendar/check")
def calendar_check():
    """[今すぐ確かめる]。読んで、書いて、照らし合わせる。"""
    with con() as c:
        api = _cal()
        if not gcal.refresh(c, api=api, force=True):
            raise UserError(NOT_CONNECTED)
        return jsonify(gcal.sync_state(c))


# ---------- シフト表の写真(F14、A20・A21) ----------
@bp.post("/shift-photo")
def shift_photo():
    """落とした写真を Claude に読ませて、自分のシフトを返す。写真は残さない。"""
    import shift
    f = request.files.get("photo")
    if not f:
        raise UserError("写真を落としてください")
    with con() as c:
        try:
            got = shift.read_photo(c, f.read(), f.filename)
        except shift.ShiftError as e:
            raise UserError(str(e))
        places = [dict(p) for p in c.execute("SELECT id, name FROM baito_places ORDER BY id")]
    return jsonify(shifts=got, baito=places)


@bp.post("/shift-photo/commit")
def shift_commit():
    """[書き込む]。× で外した日は画面から送らない。"""
    import shift
    b = body()
    shifts = b.get("shifts") or []
    if not shifts:
        raise UserError("書き込むシフトはありません")
    with con() as c:
        try:
            summary = shift.title(c, int(b["baito_id"]) if b.get("baito_id") else None)
        except shift.ShiftError as e:
            raise UserError(str(e))
    days = sorted(s.get("date") or "" for s in shifts)
    api = _cal()
    try:
        date.fromisoformat(days[0]), date.fromisoformat(days[-1])
    except ValueError:
        raise UserError("日付の形がちがいます")
    items = _events(days[0], days[-1])
    res = _google(shift.commit, None, api, items, shifts, summary)
    return jsonify(**res, summary=summary)


# ---------- Google に書けなかった予定(A19) ----------
@bp.post("/held-events/<int:hid>/<action>")
def held_action(hid, action):
    with con() as c:
        h = c.execute("SELECT * FROM held_events WHERE id = ?", (hid,)).fetchone()
        if not h:
            raise UserError("その予定はもうありません")
        if action == "drop":  # 書かない
            mails.delete_held(c, hid)  # メールから入ったものは、次に読んでも戻さない
            return jsonify(ok=True)
        if action not in ("retry", "force"):
            raise UserError("その操作はありません")
        api = _cal()
        items = gcal.cached() or []
        _google(gcal.write_held, c, api, items, hid, action == "force")
        left = c.execute("SELECT reason FROM held_events WHERE id = ?", (hid,)).fetchone()
        return jsonify(ok=True, written=left is None, reason=left["reason"] if left else None)
