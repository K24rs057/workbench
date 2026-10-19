"""区切り3 トップと時間割(F3・F6・F10・F21)。"""
from datetime import date, datetime, timedelta

import db
import timetable
import top

MON = date(2026, 10, 19)   # 月曜
WED = date(2026, 10, 21)


def test_parse_reads_only_name_and_periods(sample_timetable):
    week = timetable.parse(sample_timetable.read_text(encoding="utf-8"))
    assert week[0] == [{"name": "設計演習", "periods": [1, 2], "start": "09:00", "end": "12:40"}]
    assert [i["name"] for i in week[2]] == ["デザイン", "情報演習"]  # 時刻順
    assert 4 not in week  # 授業なし
    assert "先生" not in str(week)


def test_refresh_creates_containers_once_and_keeps_link_after_rename(db_path):
    db.init(db_path)
    with db.session(db_path) as con:
        timetable.refresh(con, force=True)
        timetable.refresh(con, force=True)
        names = sorted(r["name"] for r in con.execute("SELECT name FROM containers WHERE auto_source = '時間割'"))
        assert names == ["デザイン", "情報演習", "設計演習"]
        con.execute("UPDATE containers SET name = '設計演習(月)' WHERE source_key = '設計演習'")
        timetable.refresh(con, force=True)
        assert con.execute("SELECT COUNT(*) FROM containers WHERE auto_source = '時間割'").fetchone()[0] == 3
        assert [c["name"] for c in timetable.classes_on(con, MON)] == ["設計演習(月)"]


def test_refresh_every_ten_minutes_and_error_keeps_cache(db_path, sample_timetable):
    db.init(db_path)
    t = datetime(2026, 10, 19, 9, 0)
    with db.session(db_path) as con:
        timetable.refresh(con, now=t)
        sample_timetable.unlink()
        timetable.refresh(con, now=t + timedelta(minutes=5))   # まだ読まない
        assert timetable.error(con) is None
        timetable.refresh(con, now=t + timedelta(minutes=11))
        assert timetable.error(con)
        assert len(timetable.classes_on(con, WED)) == 2         # 前に読んだものを使う


def test_term_notice_from_one_week_before(db_path):
    db.init(db_path)
    with db.session(db_path) as con:
        timetable.refresh(con, force=True)
        assert timetable.term_notice(con, date(2027, 1, 14)) is None
        assert "学期が終わります" in timetable.term_notice(con, date(2027, 1, 15))
        assert timetable.term_notice(con, date(2027, 1, 23)) is None


def _setup(con):
    timetable.refresh(con, force=True)
    uni = con.execute("SELECT id FROM kinds WHERE name = '大学'").fetchone()["id"]
    dev = con.execute("SELECT id FROM kinds WHERE name = '開発'").fetchone()["id"]
    a = con.execute("SELECT id FROM containers WHERE source_key = '設計演習'").fetchone()["id"]
    fx = con.execute("INSERT INTO containers(kind_id, name) VALUES (?, 'fx-practice')", (dev,)).lastrowid
    ins = "INSERT INTO tasks(container_id, name, due_date, due_time, created_at) VALUES (?, ?, ?, ?, ?)"
    con.execute(ins, (a, "遅れたレポート", "2026-10-15", None, "2026-10-01 00:00:00"))
    con.execute(ins, (fx, "今日の開発", "2026-10-19", "12:00", "2026-10-01 00:00:00"))
    con.execute(ins, (a, "今日の課題", "2026-10-19", "12:00", "2026-10-02 00:00:00"))
    con.execute(ins, (a, "今日の朝", "2026-10-19", "09:00", "2026-10-03 00:00:00"))
    con.execute(ins, (a, "6日後", "2026-10-25", None, "2026-10-01 00:00:00"))
    con.execute(ins, (a, "7日後", "2026-10-26", None, "2026-10-01 00:00:00"))
    con.execute(ins, (fx, "締切なし", None, None, "2026-10-01 00:00:00"))
    con.execute("INSERT INTO links(container_id, name, target) VALUES (?, '学習サイト', 'https://example.ac.jp')", (a,))
    con.execute("INSERT INTO links(container_id, name, target) VALUES (?, 'GitHub', 'https://github.com')", (fx,))
    return a, fx


def test_top_sections_and_order(db_path):
    db.init(db_path)
    with db.session(db_path) as con:
        _setup(con)
        t = top.build(con, MON)
    assert [x["name"] for x in t["overdue"]] == ["遅れたレポート"]
    # 時刻順 → 同じ時刻なら「先に並べる」(大学)が先
    assert [x["name"] for x in t["today_tasks"]] == ["今日の朝", "今日の課題", "今日の開発"]
    assert [x["name"] for x in t["week"]] == ["6日後"]          # 今日を入れて7日間
    assert [x["name"] for x in t["nodue"]] == ["締切なし"]
    assert [c["name"] for c in t["classes_today"]] == ["設計演習"]
    assert t["classes_tomorrow"] == []
    assert [l["name"] for l in t["links"]] == ["学習サイト"]     # 今日の授業のリンクだけ
    assert t["gauge"]["overall"] == 0


def test_links_always_top_and_gauge_items(db_path):
    db.init(db_path)
    with db.session(db_path) as con:
        a, fx = _setup(con)
        con.execute("UPDATE containers SET links_always_top = 1 WHERE id = ?", (fx,))
        con.execute("UPDATE tasks SET done = 1 WHERE name = '今日の朝'")
        t = top.build(con, MON)
    assert [l["name"] for l in t["links"]] == ["学習サイト", "GitHub"]
    assert {i["name"] for i in t["gauge"]["items"]} == {"設計演習", "fx-practice"}
    assert t["gauge"]["overall"] == round(1 * 100 / 7)


def test_top_api_and_links_api(client, tmp_path):
    cid = client.post("/api/containers", json={"name": "卒論", "kind_id": 1}).get_json()["id"]
    assert client.post("/api/links", json={"container_id": cid, "name": "", "target": "x"}).status_code == 400
    folder = tmp_path / "sotsuron"
    folder.mkdir()
    lid = client.post("/api/links", json={"container_id": cid, "name": "原稿", "target": str(folder)}).get_json()["id"]
    assert [l["name"] for l in client.get(f"/api/containers/{cid}/links").get_json()] == ["原稿"]
    res = client.get("/api/top").get_json()
    assert "gauge" in res and "classes_today" in res
    client.delete(f"/api/links/{lid}")
    assert client.get(f"/api/containers/{cid}/links").get_json() == []


def test_open_missing_local_path_is_error(client):
    cid = client.post("/api/containers", json={"name": "卒論", "kind_id": 1}).get_json()["id"]
    lid = client.post("/api/links", json={"container_id": cid, "name": "原稿", "target": "C:/no/such/place"}).get_json()["id"]
    assert "見つかりません" in client.post(f"/api/links/{lid}/open").get_json()["error"]
