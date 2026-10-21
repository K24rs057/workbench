"""区切り4 作業記録(F4・F5、Q23〜Q25・Q29)。窓の名前は作り物を渡す。"""
from datetime import date, datetime, timedelta

import db
import worklog

T0 = datetime(2026, 10, 19, 9, 0)
VS = ("VS Code", "app.py - fx-practice - Visual Studio Code")


def setup(db_path):
    db.init(db_path)
    with db.session(db_path) as con:
        dev = con.execute("SELECT id FROM kinds WHERE name = '開発'").fetchone()["id"]
        fx = con.execute("INSERT INTO containers(kind_id, name) VALUES (?, 'fx-practice')", (dev,)).lastrowid
    return fx


def run(con, sample, start, end):
    """start 分から end 分まで、1分ごとに読む(本物と同じ間隔)。"""
    for m in range(start, end + 1):
        worklog.tick(con, sample, T0 + timedelta(minutes=m))


def minutes(con, cid):
    total = 0
    for r in con.execute("SELECT * FROM work_logs WHERE container_id = ?", (cid,)):
        total += (datetime.fromisoformat(r["ended_at"]) - datetime.fromisoformat(r["started_at"])).seconds // 60
    return total


def test_key_of():
    assert worklog.key_of("VS Code", "app.py - fx-practice - Visual Studio Code") == "fx-practice"
    assert worklog.key_of("VS Code", "● app.py - fx-practice - Visual Studio Code") == "fx-practice"
    assert worklog.key_of("Word", "卒論_第2章.docx - Word") == "卒論_第2章"
    assert worklog.key_of("Chrome", "(3) 受信トレイ - Google Chrome") == "受信トレイ"


def test_first_window_is_asked_then_remembered_and_title_is_forgotten(db_path):
    fx = setup(db_path)
    with db.session(db_path) as con:
        assert worklog.tick(con, VS, T0) is None
        worklog.tick(con, VS, T0 + timedelta(minutes=1))  # 同じ窓は1回だけためる
        assert con.execute("SELECT COUNT(*) FROM notices").fetchone()[0] == 0  # すぐには聞かない。まず AI が仕分ける(Q38)
        import winsort
        winsort.run(con, runner=lambda s, p: {"items": []}, now=T0 + timedelta(minutes=2))  # AI が分からなかった → 聞く
        ns = con.execute("SELECT * FROM notices").fetchall()
        assert len(ns) == 1 and "fx-practice" in ns[0]["body"]
        worklog.answer_window(con, ns[0]["id"], container_id=fx)
        assert con.execute("SELECT COUNT(*) FROM pending_windows").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM notices").fetchone()[0] == 0
        rule = con.execute("SELECT * FROM window_rules").fetchone()
        assert (rule["app"], rule["pattern"], rule["container_id"]) == ("VS Code", "fx-practice", fx)


def test_same_container_continues_and_switch_closes(db_path):
    fx = setup(db_path)
    with db.session(db_path) as con:
        con.execute("INSERT INTO window_rules(app, pattern, container_id) VALUES ('VS Code', 'fx-practice', ?)", (fx,))
        con.execute("INSERT INTO window_rules(app, pattern, ignore) VALUES ('Chrome', 'YouTube', 1)")
        for m in range(0, 30):
            worklog.tick(con, VS, T0 + timedelta(minutes=m))
        assert con.execute("SELECT COUNT(*) FROM work_logs").fetchone()[0] == 1
        worklog.tick(con, ("Chrome", "動画 - YouTube - Google Chrome"), T0 + timedelta(minutes=30))  # 記録しない
        assert worklog.current(con) is None
        assert minutes(con, fx) == 30


def test_own_window_does_not_break_the_log(db_path):
    fx = setup(db_path)
    with db.session(db_path) as con:
        con.execute("INSERT INTO window_rules(app, pattern, container_id) VALUES ('VS Code', 'fx-practice', ?)", (fx,))
        worklog.tick(con, VS, T0)
        worklog.tick(con, ("Chrome", "段取りさん"), T0 + timedelta(minutes=1))
        assert worklog.current(con)["container_id"] == fx


def test_lock_and_sleep_stop_the_log(db_path):
    fx = setup(db_path)
    with db.session(db_path) as con:
        con.execute("INSERT INTO window_rules(app, pattern, container_id) VALUES ('VS Code', 'fx-practice', ?)", (fx,))
        run(con, VS, 0, 10)
        worklog.tick(con, None, T0 + timedelta(minutes=11))  # ロック
        assert worklog.current(con) is None
        assert minutes(con, fx) == 11
        run(con, VS, 20, 25)
        # 1時間眠っていた → 眠った時刻(最後に読んだ時刻)で止める
        worklog.tick(con, VS, T0 + timedelta(minutes=80))
        logs = con.execute("SELECT * FROM work_logs ORDER BY id").fetchall()
        assert logs[1]["ended_at"] == (T0 + timedelta(minutes=25)).isoformat(timespec="seconds")


def test_done_question_after_15_minutes_once_a_day(db_path):
    fx = setup(db_path)
    with db.session(db_path) as con:
        con.execute("INSERT INTO window_rules(app, pattern, container_id) VALUES ('VS Code', 'fx-practice', ?)", (fx,))
        con.execute("INSERT INTO tasks(container_id, name) VALUES (?, 'グラフの表示')", (fx,))
        run(con, VS, 0, 9)
        worklog.tick(con, None, T0 + timedelta(minutes=10))  # 10分では聞かない
        assert worklog.open_done_questions(con, T0.date()) == []
        run(con, VS, 11, 29)
        worklog.tick(con, None, T0 + timedelta(minutes=30))
        qs = worklog.open_done_questions(con, T0.date())
        assert qs[0]["container"] == "fx-practice" and qs[0]["tasks"][0]["name"] == "グラフの表示"
        run(con, VS, 31, 59)
        worklog.tick(con, None, T0 + timedelta(minutes=60))
        assert con.execute("SELECT COUNT(*) FROM done_questions").fetchone()[0] == 1


def test_api_logs_edit_and_answer(client):
    cid = client.post("/api/containers", json={"name": "卒論", "kind_id": 1}).get_json()["id"]
    r = client.post("/api/work-logs", json={"container_id": cid, "started_at": "2026-10-19T09:00", "ended_at": "2026-10-19T08:00"})
    assert r.status_code == 400
    lid = client.post("/api/work-logs", json={"container_id": cid, "started_at": "2026-10-19T09:00", "ended_at": "2026-10-19T10:00", "note": "第2章"}).get_json()["id"]
    client.patch(f"/api/work-logs/{lid}", json={"ended_at": "2026-10-19T10:30"})
    logs = client.get(f"/api/containers/{cid}/logs").get_json()
    assert logs[0]["ended_at"] == "2026-10-19T10:30:00" and logs[0]["edited"] == 1
    client.delete(f"/api/work-logs/{lid}")
    assert client.get(f"/api/containers/{cid}/logs").get_json() == []
    assert client.get("/api/work-logs/current").get_json() is None


def test_foreground_runs_on_this_pc():
    s = worklog.foreground()
    assert s is None or (isinstance(s[0], str) and isinstance(s[1], str))


def test_edge_title_is_trimmed():
    """Edge の名前には見えない文字が入る。プロフィールの名前と「および他 ○ ページ」も削る(2026-10-22)。"""
    z = "\u200b"
    assert worklog.key_of("Edge", f"データのやり取り - 検索 および他 2 ページ - 個人 - Microsoft{z} Edge") == "データのやり取り - 検索"
    assert worklog.key_of("Edge", f"cooking-logのしくみ - 個人 - Microsoft{z} Edge") == "cooking-logのしくみ"
    assert worklog.key_of("Edge", "11章 - Microsoft Edge") == "11章"
    assert worklog.key_of("Edge", "A - B - Microsoft Edge") == "A - B"  # プロフィールの名前でなければ削らない
