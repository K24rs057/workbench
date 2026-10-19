"""区切り5 通知と自動起動(F8、Q5・Q19・Q28)。Windows の通知は出さない。"""
from datetime import date, datetime, timedelta

import pytest

import db
import notify
import status

NOW = datetime(2026, 10, 19, 9, 0)


@pytest.fixture(autouse=True)
def no_toast(monkeypatch):
    shown = []
    monkeypatch.setattr(notify, "show", lambda t, m: shown.append((t, m)))
    return shown


def setup(db_path):
    db.init(db_path)
    with db.session(db_path) as con:
        uni = con.execute("SELECT id FROM kinds WHERE name = '大学'").fetchone()["id"]
        dev = con.execute("SELECT id FROM kinds WHERE name = '開発'").fetchone()["id"]
        a = con.execute("INSERT INTO containers(kind_id, name) VALUES (?, '情報工学演習')", (uni,)).lastrowid
        fx = con.execute("INSERT INTO containers(kind_id, name) VALUES (?, 'fx-practice')", (dev,)).lastrowid
    return a, fx


def add(con, cid, name, due=None, created="2026-10-10 00:00:00"):
    return con.execute("INSERT INTO tasks(container_id, name, due_date, created_at) VALUES (?, ?, ?, ?)", (cid, name, due, created)).lastrowid


def test_eve_notice_once(db_path, no_toast):
    a, _ = setup(db_path)
    with db.session(db_path) as con:
        add(con, a, "第10回課題", "2026-10-20")
        notify.check(con, NOW)
        notify.check(con, NOW + timedelta(minutes=1))
    assert [t for t, _ in no_toast].count("明日まで") == 1


def test_untouched_with_due_and_without_due(db_path, no_toast):
    a, fx = setup(db_path)
    with db.session(db_path) as con:
        add(con, a, "レポート", "2026-10-22")                 # 締切の3日前、記録なし → 出す
        add(con, a, "まだ先", "2026-11-30")                   # 先なので出さない
        add(con, a, "締切なし", None)                         # 大学は手つかずの通知オン → 出す
        add(con, fx, "開発の締切なし", None)                  # 開発はオフ → 出さない
        notify.check(con, NOW)
    names = [m for t, m in no_toast if t == "手つかず"]
    assert len(names) == 2 and any("レポート" in m for m in names) and any("締切なし" in m for m in names)


def test_work_log_counts_as_touched(db_path, no_toast):
    a, _ = setup(db_path)
    with db.session(db_path) as con:
        add(con, a, "レポート", "2026-10-22")
        con.execute("INSERT INTO work_logs(container_id, started_at, ended_at) VALUES (?, '2026-10-15T10:00:00', '2026-10-15T11:00:00')", (a,))
        notify.check(con, NOW)
    assert not [t for t, _ in no_toast if t == "手つかず"]


def test_missed_eve_notice_is_shown_on_next_open(db_path, no_toast):
    a, _ = setup(db_path)
    with db.session(db_path) as con:
        add(con, a, "止まっていた間の締切", "2026-10-19")      # 前日(10/18)は本体が止まっていた
        notify.check(con, NOW)
        assert not [t for t, _ in no_toast if t == "明日まで"]
        assert notify.take_pending(con) == ["明日まで(前日の通知):情報工学演習:止まっていた間の締切"]
        assert notify.take_pending(con) == []                 # 見せたら消える


def test_marks_for_screen(db_path):
    a, _ = setup(db_path)
    with db.session(db_path) as con:
        t1 = add(con, a, "明日の", "2026-10-20")
        t2 = add(con, a, "3日後の", "2026-10-22")
        assert notify.marks(con, NOW.date()) == {t1: "明日まで", t2: "手つかず"}


def test_status_late_jobs(db_path):
    db.init(db_path)
    with db.session(db_path) as con:
        assert status.late_jobs(con, NOW) == []               # 一度も動いていないものは数えない
        con.execute("INSERT INTO job_status(job, last_run_at) VALUES ('作業記録', '2026-10-19T08:50:00')")
        assert [j["job"] for j in status.late_jobs(con, NOW)] == ["作業記録"]


def test_status_api(client):
    res = client.get("/api/status").get_json()
    assert {j["job"] for j in res["jobs"]} == {"作業記録", "通知", "時間割の読み込み", "Outlook"}
    assert set(res["autostart"]) == {"ログイン時(スタートアップ)", "段取りさん(見回り)"}
