"""K'sLife の課題の読み込み(要件 F23 1.09、基本設計 Q39・AI ⑩)。ページと Claude は作り物を渡す(本物の K'sLife には行かない)。"""
import json
from datetime import datetime

import agent
import db
import kslife
import sitebrowser

NOW = datetime(2026, 10, 22, 7, 5)
PAGE = "課題一覧\nモデリングとシミュレーション 第5回 演習課題 10/27 23:59\n工業デザイン 課題4 プレゼン資料 11/2 13:00\n前回の課題(締切 10/1)"


def setup(db_path, url="https://kslife.example.ac.jp/portal/assignments"):
    db.init(db_path)
    with db.session(db_path) as con:
        uni = con.execute("SELECT id FROM kinds WHERE name = '大学'").fetchone()["id"]
        m = con.execute("INSERT INTO containers(kind_id, name) VALUES (?, 'モデリングとシミュレーション')", (uni,)).lastrowid
        sitebrowser.add_site(con, "K'sLife", "https://kslife.example.ac.jp/", login="auto")
        if url:
            kslife.set_tasks_url(con, "K'sLife", url)
    return m


def items(*xs):
    return lambda s, p: {"items": list(xs)}


A = {"course": "モデリングとシミュレーション", "title": "第5回 演習課題", "due_date": "2026-10-27", "due_time": "23:59"}
B = {"course": "工業デザイン", "title": "課題4 プレゼン資料", "due_date": "2026-11-02", "due_time": "13:00"}
OLD = {"course": "情報演習", "title": "前回の課題", "due_date": "2026-10-01", "due_time": None}
NODATE = {"course": "情報演習", "title": "いつかの課題", "due_date": None}


def notices(con):
    return [dict(n) | {"data": json.loads(n["body"])} for n in con.execute("SELECT * FROM notices WHERE kind = ? AND answered = 0", (kslife.KIND,))]


def test_read_adds_new_once_and_matches_course(db_path):
    m = setup(db_path)
    seen = {}

    def opener(site, url):
        seen["url"] = url
        return PAGE

    with db.session(db_path) as con:
        assert kslife.read(con, opener, items(A, B, OLD, NODATE), NOW) == 2  # 締切を過ぎた・日付のないものは出さない
        assert seen["url"].endswith("/portal/assignments")
        ns = {n["data"]["title"]: n["data"] for n in notices(con)}
        assert ns["第5回 演習課題"]["container_id"] == m and ns["第5回 演習課題"]["due_time"] == "23:59"
        assert ns["課題4 プレゼン資料"]["container_id"] is None  # 合う入れ物がない
        assert kslife.read(con, opener, items(A, B), NOW) == 0     # 同じものは二度出さない
        # 締切が変わったら、印をつけてもう一度(前の答えていない質問は入れかえる)
        moved = A | {"due_date": "2026-10-29"}
        assert kslife.read(con, opener, items(moved, B), NOW) == 1
        ns = [n for n in notices(con) if n["data"]["title"] == "第5回 演習課題"]
        assert len(ns) == 1 and ns[0]["data"]["changed"] and ns[0]["data"]["due_date"] == "2026-10-29"
        assert kslife.last(con)["count"] == 1


def test_answer_makes_task(client, db_path):
    m = setup(db_path)
    with db.session(db_path) as con:
        kslife.read(con, lambda s, u: PAGE, items(A), NOW)
        nid = notices(con)[0]["id"]
    assert client.post(f"/api/notices/{nid}/answer", json={}).status_code == 400
    assert client.post(f"/api/notices/{nid}/answer", json={"container_id": m}).status_code == 200
    t = [x for x in client.get(f"/api/containers/{m}").get_json()["tasks"] if x["name"] == "第5回 演習課題"][0]
    assert t["due_date"] == "2026-10-27" and t["due_time"] == "23:59" and t["open_url"].endswith("/assignments")


def test_run_twice_a_day_and_errors(db_path):
    setup(db_path)
    calls = []
    op = lambda s, u: calls.append(1) or PAGE
    with db.session(db_path) as con:
        assert kslife.slot(datetime(2026, 10, 22, 6, 0)) == "2026-10-21-夜"
        kslife.run(con, op, items(A), datetime(2026, 10, 22, 7, 1))
        kslife.run(con, op, items(A), datetime(2026, 10, 22, 12, 0))   # 同じ朝の回は読まない
        kslife.run(con, op, items(A), datetime(2026, 10, 22, 19, 2))   # 夜の回
        assert len(calls) == 2

        def blocked(s, u):
            raise sitebrowser.SiteError("2段階認証が出たので、ログインをやめました")
        kslife.run(con, blocked, items(A), datetime(2026, 10, 23, 7, 1))
        assert "2段階認証" in kslife.last(con)["error"]
        assert "2段階認証" in con.execute("SELECT last_error FROM job_status WHERE job = 'K''sLife'").fetchone()[0]

        def broken(s, p):
            raise agent.AgentError("形がちがう")
        try:
            kslife.read(con, op, broken, NOW)
            assert False
        except sitebrowser.SiteError:
            pass


def test_tasks_url_must_be_inside_site(client, db_path):
    setup(db_path, url=None)
    with db.session(db_path) as con:
        assert kslife.run(con, None, None, NOW) is None  # 課題のページがなければ読まない
    assert client.patch("/api/sites/K'sLife", json={"tasks_url": "https://evil.example.com/x"}).status_code == 400
    assert client.patch("/api/sites/K'sLife", json={"tasks_url": "https://kslife.example.ac.jp/a"}).status_code == 200
    d = client.get("/api/sites").get_json()
    assert d["sites"][0]["tasks_url"].endswith("/a") and "kslife_last" in d


def test_read_api_reports_error(client, db_path, monkeypatch):
    setup(db_path)
    monkeypatch.setattr(kslife, "read", lambda con, *a, **k: (_ for _ in ()).throw(sitebrowser.SiteError("サイトが答えませんでした")))
    r = client.post("/api/kslife/read")
    assert r.status_code == 400 and "答えませんでした" in r.get_json()["error"]
