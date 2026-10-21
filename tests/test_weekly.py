"""週の振り返り(要件 F24 1.09、基本設計 Q40・AI ⑪)。Claude は作り物を渡す。"""
import json
from datetime import date, datetime, timedelta

import agent
import db
import weekly

WS = date(2026, 10, 12)  # 月曜
NOW = datetime(2026, 10, 21, 10, 0)


def setup(db_path):
    db.init(db_path)
    with db.session(db_path) as con:
        uni = con.execute("SELECT id FROM kinds WHERE name = '大学'").fetchone()["id"]
        a = con.execute("INSERT INTO containers(kind_id, name) VALUES (?, '情報演習')", (uni,)).lastrowid
        b = con.execute("INSERT INTO containers(kind_id, name) VALUES (?, '工業デザイン')", (uni,)).lastrowid
        logs = [(a, "2026-10-12T09:00", "2026-10-12T11:30"), (a, "2026-10-16T23:00", "2026-10-17T01:00"),  # 日をまたぐ
                (b, "2026-10-17T13:00", "2026-10-17T13:30"), (a, "2026-10-11T10:00", "2026-10-11T12:00")]   # 前の週は数えない
        for cid, s, e in logs:
            con.execute("INSERT INTO work_logs(container_id, started_at, ended_at) VALUES (?, ?, ?)", (cid, s, e))
        ins = lambda **k: con.execute("INSERT INTO tasks(container_id, name, due_date, done, done_at, created_at) VALUES (:c, :n, :d, :done, :at, :cr)",
                                      {"c": a, "n": "", "d": None, "done": 0, "at": None, "cr": "2026-10-01 09:00:00", **k})
        ins(n="第2回レポート", d="2026-10-14", done=1, at="2026-10-13T20:00:00")          # 締切前に終わった
        ins(n="課題3", c=b, d="2026-10-16", done=1, at="2026-10-18T10:00:00")             # 2日遅れで終わった
        ins(n="課題4", c=b, d="2026-10-17")                                               # まだ終わっていない
        ins(n="来週の課題", d="2026-10-22")
    return a, b


def test_compute_counts_the_week(db_path):
    a, b = setup(db_path)
    with db.session(db_path) as con:
        d = weekly.compute(con, WS, NOW)
    assert d["total_min"] == 150 + 120 + 30
    day = {x["date"]: x["min"] for x in d["by_day"]}
    assert day["2026-10-12"] == 150 and day["2026-10-16"] == 60 and day["2026-10-17"] == 60 + 30  # 日をまたぐ記録は日ごとに分ける
    assert [(x["name"], x["min"]) for x in d["by_container"]] == [("情報演習", 270), ("工業デザイン", 30)]
    assert {x["name"] for x in d["done"]} == {"第2回レポート", "課題3"}
    late = {x["name"]: x["days"] for x in d["late"]}
    assert late == {"課題3": 2, "課題4": 4}  # 終わった日か今日まで
    assert [x["name"] for x in d["next_week"]] == ["来週の課題"]
    assert d["prev"] == "2026-10-05" and d["next"] == "2026-10-19" and d["finished"] and not d["this_week"]


def test_comment_gets_only_numbers_and_failure_is_kept(db_path):
    setup(db_path)
    got = {}

    def fake(system, prompt):
        got["p"] = json.loads(prompt)
        return {"comment": "今週は情報演習に一番時間を使いました。"}

    with db.session(db_path) as con:
        assert weekly.make_comment(con, WS, fake, NOW).startswith("今週は")
        assert got["p"]["作業した時間(分)"] == 300 and "締切を過ぎたもの" in got["p"]
        assert weekly.compute(con, WS, NOW)["comment"].startswith("今週は")

        def broken(s, p):
            raise agent.AgentError("だめ")
        weekly.make_comment(con, WS, broken, NOW)
        d = weekly.compute(con, WS, NOW)
        assert d["comment"] is None and d["comment_error"]  # 推測で埋めない


def test_run_makes_once_after_sunday_night(db_path):
    setup(db_path)
    calls = []
    fake = lambda s, p: calls.append(1) or {"comment": "よくできました。"}
    with db.session(db_path) as con:
        assert weekly.due_week(datetime(2026, 10, 18, 20, 0)) == date(2026, 10, 5)   # 日曜の21時前は先週
        assert weekly.due_week(datetime(2026, 10, 18, 21, 5)) == WS
        weekly.run(con, fake, datetime(2026, 10, 18, 21, 5))
        weekly.run(con, fake, datetime(2026, 10, 18, 21, 6))
        weekly.run(con, fake, datetime(2026, 10, 19, 8, 0))  # 月曜も、もう作ってある
        assert len(calls) == 1
        assert weekly.run(con, fake, datetime(2026, 10, 5, 9, 0)) is False  # 何もない週(9/28〜)は作らない


def test_api_and_monday_greeting(client, db_path):
    setup(db_path)
    d = client.get("/api/weekly?week=2026-10-14").get_json()  # 週の途中の日でも、その週の月曜から
    assert d["week_start"] == "2026-10-12"
    assert client.get("/api/weekly?week=x").status_code == 400
    with db.session(db_path) as con:
        con.execute("INSERT INTO weekly_reviews(week_start, comment, made_at) VALUES ('2026-10-12', 'よい週でした。', '2026-10-18T21:05')")
        text = agent.greeting(con, today=date(2026, 10, 19))
    assert "先週の振り返りができています" in text
