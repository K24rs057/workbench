"""区切り10・11 Google カレンダーを読む・書く(F12・F13、Q8・Q9)。Google にはつながず、作り物のカレンダーを使う。"""
from datetime import datetime, timedelta

import pytest

import db
import gcal
import tasks

NOW = datetime(2026, 10, 19, 9, 0)


class FakeCal:
    def __init__(self, events=None):
        self.events = {e["id"]: e for e in (events or [])}
        self.n = 0
        self.fail = False

    def list(self, tmin, tmax):
        if self.fail:
            raise RuntimeError("connection refused")
        return list(self.events.values())

    def insert(self, body):
        self.n += 1
        ev = {"id": f"new{self.n}", "organizer": {"self": True}, **body}
        self.events[ev["id"]] = ev
        return ev

    def patch(self, eid, body):
        self.events[eid].update(body)
        return self.events[eid]

    def delete(self, eid):
        self.events.pop(eid)


def timed(eid, day, start, end, name, self_=True):
    return {"id": eid, "summary": name, "start": {"dateTime": f"{day}T{start}:00+09:00"}, "end": {"dateTime": f"{day}T{end}:00+09:00"},
            "organizer": {"self": self_}}


def allday(eid, day, name):
    d = datetime.fromisoformat(day)
    return {"id": eid, "summary": name, "start": {"date": day}, "end": {"date": (d + timedelta(days=1)).date().isoformat()}, "organizer": {"self": True}}


@pytest.fixture(autouse=True)
def fresh_cache():
    gcal._cache.update(at=None, items=[], error=None)


def setup(db_path):
    db.init(db_path)
    with db.session(db_path) as con:
        cid = con.execute("INSERT INTO containers(kind_id, name) VALUES (1, '情報演習')").lastrowid
    return cid


def run(con, cal, now=NOW):
    return gcal.refresh(con, now=now, api=cal, force=True)


def test_read_events_show_on_top_without_task_deadlines(db_path):
    setup(db_path)
    cal = FakeCal([timed("a", "2026-10-19", "18:00", "19:00", "歯医者"), timed("b", "2026-10-20", "10:00", "11:00", "説明会", self_=False),
                   {**allday("c", "2026-10-19", "締切 第3回"), "extendedProperties": {"private": {"dandori": "task", "dandori_task": "1"}}}])
    with db.session(db_path) as con:
        assert run(con, cal)
        import top
        t = top.build(con, today=NOW.date())
    assert [e["name"] for e in t["events_today"]] == ["歯医者"]
    assert t["events_tomorrow"][0]["invited"] is True


def test_task_deadline_written_all_day_with_time_in_name(db_path):
    cid = setup(db_path)
    cal = FakeCal()
    with db.session(db_path) as con:
        tid = tasks.add(con, {"container_id": cid, "name": "第3回レポート", "due_date": "2026-10-23", "due_time": "23:59"})
        tasks.add(con, {"container_id": cid, "name": "古い課題", "due_date": "2026-10-01"})  # 過ぎた締切は書かない
        run(con, cal)
        ev = list(cal.events.values())
        assert len(ev) == 1
        assert ev[0]["summary"] == "締切 23:59 第3回レポート" and ev[0]["start"] == {"date": "2026-10-23"}
        assert ev[0]["extendedProperties"]["private"]["dandori_task"] == str(tid)
        # 完了 → 「済」、締切を変える → 書き直す
        tasks.set_done(con, tid, True)
        con.execute("UPDATE tasks SET due_date = '2026-10-24' WHERE id = ?", (tid,))
        run(con, cal)
        assert ev[0]["summary"] == "済 締切 23:59 第3回レポート" and ev[0]["start"] == {"date": "2026-10-24"}
        # タスクを消す → 予定も消す
        tasks.delete(con, tid)
        run(con, cal)
        assert cal.events == {}


def test_same_deadline_already_on_calendar_is_not_written(db_path):
    cid = setup(db_path)
    cal = FakeCal([allday("x", "2026-10-23", "締切 第3回レポート")])  # モーニングブリーフが書いたもの
    with db.session(db_path) as con:
        tasks.add(con, {"container_id": cid, "name": "第3回レポート", "due_date": "2026-10-23", "due_time": "23:59"})
        run(con, cal)
    assert len(cal.events) == 1


def test_google_side_move_rename_delete(db_path):
    cid = setup(db_path)
    cal = FakeCal()
    with db.session(db_path) as con:
        tid = tasks.add(con, {"container_id": cid, "name": "ES", "due_date": "2026-10-25"})
        run(con, cal)
        ev = next(iter(cal.events.values()))
        ev["start"], ev["end"] = {"date": "2026-10-27"}, {"date": "2026-10-28"}
        ev["summary"] = "締切 ES(本選考)"
        run(con, cal)
        t = tasks.get(con, tid)
        assert (t["due_date"], t["name"]) == ("2026-10-27", "ES(本選考)")
        assert len(cal.events) == 1  # 書き戻しで増えない
        cal.events.clear()
        run(con, cal)
        t = tasks.get(con, tid)
        assert t["calendar_deleted"] == 1  # タスクは消さずに印
        run(con, cal)
        assert cal.events == {}  # 書き直さない


def test_unsorted_task_from_other_mail_is_not_written_until_sorted(db_path):
    cid = setup(db_path)
    cal = FakeCal()
    with db.session(db_path) as con:
        mid = con.execute("INSERT INTO messages(source, external_id, category, subject, sender, received_at) VALUES ('Outlook', 'o1', 'その他', '説明会', 'a@u', '2026-10-18')").lastrowid
        uid = con.execute("SELECT id FROM containers WHERE is_unsorted = 1").fetchone()[0]
        tid = con.execute("INSERT INTO tasks(container_id, name, due_date, from_message_id) VALUES (?, '説明会', '2026-10-30', ?)", (uid, mid)).lastrowid
        run(con, cal)
        assert cal.events == {}
        con.execute("UPDATE tasks SET container_id = ? WHERE id = ?", (cid, tid))  # 自分で仕分けた(Q8)
        run(con, cal)
        assert len(cal.events) == 1


def test_held_events_written_or_kept_when_overlapping(db_path):
    setup(db_path)
    cal = FakeCal([timed("a", "2026-10-26", "16:00", "18:00", "面接(Indeed経由)")])
    with db.session(db_path) as con:
        con.execute("INSERT INTO held_events(title, start_at, reason) VALUES ('面接', '2026-10-26T16:00', 'カレンダーがまだつながっていない')")
        con.execute("INSERT INTO held_events(title, start_at, end_at, reason) VALUES ('補講:情報演習', '2026-10-24T13:00', '2026-10-24T14:30', 'カレンダーがまだつながっていない')")
        run(con, cal)
        left = con.execute("SELECT title, reason FROM held_events").fetchall()
        assert [tuple(r) for r in left] == [("面接", "重なる予定がある")]
        assert any(e["summary"] == "補講:情報演習" for e in cal.events.values())
        assert len(gcal.held_waiting(con)) == 1
        import top
        assert any(n["kind"] == "held" for n in top.build(con, today=NOW.date())["notices"])


def test_cannot_connect_shows_error_and_keeps_tasks(db_path):
    cid = setup(db_path)
    cal = FakeCal()
    cal.fail = True
    with db.session(db_path) as con:
        tasks.add(con, {"container_id": cid, "name": "ES", "due_date": "2026-10-25"})
        assert run(con, cal) is False
        assert "接続できませんでした" in con.execute("SELECT value FROM settings WHERE key = 'calendar_error'").fetchone()[0]
        assert con.execute("SELECT calendar_written FROM tasks").fetchone()[0] == 0
        cal.fail = False
        run(con, cal)
        assert con.execute("SELECT calendar_written FROM tasks").fetchone()[0] == 1


def test_task_change_marks_dirty(client, db_path):
    cid = client.post("/api/containers", json={"name": "A", "kind_id": 1}).get_json()["id"]
    client.post("/api/tasks", json={"container_id": cid, "name": "x", "due_date": "2026-10-30"})
    with db.session(db_path) as con:
        assert con.execute("SELECT value FROM settings WHERE key = 'calendar_dirty'").fetchone()[0] == "1"


# ---------- 区切り12 予定の画面(F19、A17〜A19) ----------
@pytest.fixture
def fake(monkeypatch):
    cal = FakeCal([timed("own", "2026-10-21", "13:00", "14:00", "サークル"), timed("inv", "2026-10-21", "18:00", "19:00", "説明会", self_=False)])
    monkeypatch.setattr(gcal, "_api", lambda: cal)
    import gmail
    monkeypatch.setattr(gmail, "calendar_allowed", lambda env=None: True)
    return cal


def test_schedule_lists_events_tasks_classes(client, db_path, fake):
    cid = client.post("/api/containers", json={"name": "A社", "kind_id": 2}).get_json()["id"]
    client.post("/api/tasks", json={"container_id": cid, "name": "ES", "due_date": "2026-10-21", "due_time": "23:59"})
    d = client.get("/api/schedule?from=2026-10-19&to=2026-10-25").get_json()
    day = next(x for x in d["days"] if x["date"] == "2026-10-21")
    kinds = [(i["type"], i["name"]) for i in day["items"]]
    assert kinds == [("event", "サークル"), ("event", "説明会"), ("task", "ES")]
    inv = day["items"][1]
    assert inv["invited"] and not inv["editable"]
    assert len(d["days"]) == 7


def test_add_edit_delete_event(client, db_path, fake):
    r = client.post("/api/events", json={"name": "歯医者", "date": "2026-10-22", "start": "10:00", "end": "11:00"})
    gid = r.get_json()["id"]
    ev = fake.events[gid]
    assert ev["summary"] == "歯医者" and "extendedProperties" not in ev  # 手で足した予定には目印をつけない
    assert client.post("/api/events", json={"name": "x", "date": "2026-10-22", "start": "11:00", "end": "10:00"}).status_code == 400
    client.patch(f"/api/events/{gid}", json={"name": "歯医者(再診)", "date": "2026-10-22", "start": "10:00", "end": "10:30"})
    assert fake.events[gid]["summary"] == "歯医者(再診)"
    client.delete(f"/api/events/{gid}")
    assert gid not in fake.events


def test_invited_event_needs_toggle(client, db_path, fake):
    with db.session(db_path) as con:
        gcal.refresh(con, now=NOW, api=fake, force=True)
    r = client.patch("/api/events/inv", json={"name": "説明会", "date": "2026-10-21", "start": "18:00", "end": "20:00"})
    assert r.status_code == 400 and "見るだけ" in r.get_json()["error"]
    client.patch("/api/events/inv", json={"edit_allowed": True})
    assert client.patch("/api/events/inv", json={"name": "説明会", "date": "2026-10-21", "start": "18:00", "end": "20:00"}).status_code == 200
    assert client.delete("/api/events/inv").status_code == 400


def test_held_force_and_drop(client, db_path, fake):
    with db.session(db_path) as con:
        mid = con.execute("INSERT INTO messages(source, external_id, category, subject, sender, received_at) VALUES ('Gmail', 'g9', 'アルバイト', '面接', 'a@indeedemail.com', '2026-10-18')").lastrowid
        a = con.execute("INSERT INTO held_events(title, start_at, reason, from_message_id) VALUES ('面接', '2026-10-21T13:00', 'カレンダーがまだつながっていない', ?)", (mid,)).lastrowid
        b = con.execute("INSERT INTO held_events(title, start_at, reason) VALUES ('補講', '2026-10-21T13:30', 'カレンダーがまだつながっていない')").lastrowid
        gcal.refresh(con, now=NOW, api=fake, force=True)
    assert len(client.get("/api/schedule?from=2026-10-19&to=2026-10-25").get_json()["held"]) == 2
    client.post(f"/api/held-events/{a}/drop")
    assert client.post(f"/api/held-events/{b}/force").get_json()["written"] is True
    with db.session(db_path) as con:
        assert con.execute("SELECT COUNT(*) FROM held_events").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM deleted_items WHERE what = '予定'").fetchone()[0] == 1


def test_schedule_without_calendar_still_shows_tasks(client, db_path):
    d = client.get("/api/schedule?from=2026-10-19&to=2026-10-20").get_json()
    assert d["connected"] in (True, False) and len(d["days"]) == 2
