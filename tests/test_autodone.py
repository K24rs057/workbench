"""区切り14 自動で完了(F18 ① ② ④)。Claude の答えは作り物。"""
from datetime import datetime

import pytest

import agent
import autodone
import db
import mails
import tasks

NOW = datetime(2026, 10, 20, 9, 0)


def setup(db_path):
    db.init(db_path)
    with db.session(db_path) as con:
        cls = con.execute("INSERT INTO containers(kind_id, name) VALUES (1, '情報演習')").lastrowid
        dev = con.execute("INSERT INTO containers(kind_id, name) VALUES (3, 'fx-practice')").lastrowid
        co = con.execute("INSERT INTO containers(kind_id, name, company_domain) VALUES (2, 'A社', 'a-sha.co.jp')").lastrowid
        t1 = tasks.add(con, {"container_id": cls, "name": "第3回レポート", "due_date": "2026-10-23"})
        t2 = tasks.add(con, {"container_id": dev, "name": "ログイン画面", "repeat_weekday": None})
        t3 = tasks.add(con, {"container_id": co, "name": "ES 提出", "due_date": "2026-10-25"})
    return {"cls": cls, "dev": dev, "co": co, "t1": t1, "t2": t2, "t3": t3}


def mail(con, n, subject, category, sender="noreply@moodle.example.ac.jp", container_id=None, initial=False):
    return mails.ingest(con, {"source": "Outlook", "external_id": f"x{n}", "subject": subject, "sender": sender,
                              "received_at": NOW, "body": "", "category": category, "container_id": container_id}, initial=initial)


def picker(answer):
    calls = []

    def run(system, prompt):
        calls.append(prompt)
        if isinstance(answer, Exception):
            raise answer
        return answer(prompt) if callable(answer) else answer
    run.calls = calls
    return run


def test_submission_mail_completes_task(db_path):
    ids = setup(db_path)
    with db.session(db_path) as con:
        mail(con, 1, "あなたは課題「第3回レポート」への提出を送信しました。", "提出受付")
        run = picker({"task_id": ids["t1"]})
        assert autodone.run_jobs(con, runner=run, now=NOW) == 1
        assert "第3回レポート" in run.calls[0]
        t = tasks.get(con, ids["t1"])
        assert t["done"] == 1 and t["auto_done_by"] == "提出受付"
        n = con.execute("SELECT * FROM notices WHERE kind = '自動で完了'").fetchone()
        assert "「第3回レポート」(情報演習)を自動で完了にしました" in n["body"]
        assert mails.setting(con, "calendar_dirty") == "1"  # カレンダーの「済」
        assert autodone.unseen(con) == 1


def test_initial_read_does_not_complete(db_path):
    setup(db_path)
    with db.session(db_path) as con:
        mail(con, 1, "あなたは課題「第3回レポート」への提出を送信しました。", "提出受付", initial=True)
        assert con.execute("SELECT COUNT(*) FROM claude_jobs").fetchone()[0] == 0


def test_no_match_is_not_completed(db_path):
    ids = setup(db_path)
    with db.session(db_path) as con:
        mail(con, 1, "自分の応答: 授業アンケート", "Forms", sender="noreply@forms.office.com")
        autodone.run_jobs(con, runner=picker({"task_id": None}), now=NOW)
        autodone.run_jobs(con, runner=picker({"task_id": 99999}), now=NOW)  # 一覧にない番号は捨てる
        assert con.execute("SELECT COUNT(*) FROM tasks WHERE done = 1").fetchone()[0] == 0
        assert "授業アンケート" in mails.setting(con, "maybe_hint")  # 次の「終わっていそう」の材料に回す


def test_entry_mail_only_from_company_itself(db_path):
    ids = setup(db_path)
    with db.session(db_path) as con:
        mail(con, 1, "【A社】エントリーを受け付けました", "企業", sender="saiyo@a-sha.co.jp", container_id=ids["co"])
        mail(con, 2, "【A社】エントリー完了のお知らせ", "企業", sender="info@job-site.example.jp", container_id=ids["co"])
        mail(con, 3, "【A社】エントリー受付中!", "企業", sender="saiyo@a-sha.co.jp", container_id=ids["co"])
        assert [j["target"] for j in con.execute("SELECT target FROM claude_jobs WHERE kind = '完了の合図'")] == ["mail:" + str(
            con.execute("SELECT id FROM messages WHERE external_id = 'x1'").fetchone()[0])]


def test_commit_done_mark_only_after_first_read(db_path):
    ids = setup(db_path)
    import gitlog
    commits = [{"hash": "h1", "committed_at": "2026-10-19T10:00:00", "message": "完了: 古い画面"}]
    with db.session(db_path) as con:
        con.execute("UPDATE containers SET repo_path = 'x' WHERE id = ?", (ids["dev"],))
        gitlog.refresh(con, now=NOW, reader=lambda *a: commits, force=True)
        assert con.execute("SELECT COUNT(*) FROM claude_jobs").fetchone()[0] == 0  # 初めて読んだ過去の分は合図にしない
        commits.insert(0, {"hash": "h2", "committed_at": "2026-10-20T08:00:00", "message": "完了：ログイン画面"})
        commits.insert(0, {"hash": "h3", "committed_at": "2026-10-20T08:30:00", "message": "色を直した"})
        gitlog.refresh(con, now=NOW, reader=lambda *a: commits, force=True)
        run = picker({"task_id": ids["t2"]})
        autodone.run_jobs(con, runner=run, now=NOW)
        assert len(run.calls) == 1
        assert "第3回レポート" not in run.calls[0]  # そのリポジトリの入れ物のタスクだけ渡す
        assert tasks.get(con, ids["t2"])["auto_done_by"] == "コミット"


def test_failures_retry_then_show(db_path):
    setup(db_path)
    with db.session(db_path) as con:
        mail(con, 1, "あなたは課題「第3回レポート」への提出を送信しました。", "提出受付")
        for i in range(3):
            con.execute("UPDATE claude_jobs SET next_try_at = NULL")
            autodone.run_jobs(con, runner=picker(agent.AgentError("x")), now=NOW)
        assert "読み取れませんでした" in mails.setting(con, "autodone_error")
        assert con.execute("SELECT COUNT(*) FROM claude_jobs").fetchone()[0] == 0


def test_usage_limit_does_not_count(db_path):
    setup(db_path)
    with db.session(db_path) as con:
        mail(con, 1, "あなたは課題「第3回レポート」への提出を送信しました。", "提出受付")
        autodone.run_jobs(con, runner=picker(agent.UsageLimit("limit")), now=NOW)
        assert con.execute("SELECT tries FROM claude_jobs").fetchone()[0] == 0


def test_undo_from_archive_and_repeat(client, db_path):
    ids = setup(db_path)
    with db.session(db_path) as con:
        rid = tasks.add(con, {"container_id": ids["cls"], "name": "毎週の小テスト", "due_date": "2026-10-21", "repeat_weekday": 2})
        autodone.complete(con, rid, "提出受付", "メール「x」", now=NOW)
        assert con.execute("SELECT COUNT(*) FROM tasks WHERE repeat_from_task_id = ?", (rid,)).fetchone()[0] == 1
    s = client.get("/api/messages/summary").get_json()
    assert s["new"] == 1 and s["auto"] == 1  # 青い点と欄の件数
    client.get("/api/messages/summary?open=1")
    assert client.get("/api/messages/summary").get_json()["new"] == 0
    items = client.get("/api/auto-done").get_json()["items"]
    assert items[0]["name"] == "毎週の小テスト" and "メール「x」" in items[0]["body"]
    assert client.post(f"/api/auto-done/{rid}/undo").status_code == 200
    with db.session(db_path) as con:
        t = tasks.get(con, rid)
        assert t["done"] == 0 and t["auto_done_by"] is None
        assert con.execute("SELECT COUNT(*) FROM tasks WHERE repeat_from_task_id = ?", (rid,)).fetchone()[0] == 0  # 手つかずの次の回は消す
    assert client.get("/api/auto-done").get_json()["items"] == []
    assert client.post(f"/api/auto-done/{ids['t1']}/undo").status_code == 400


def test_notice_ok_button(client, db_path):
    ids = setup(db_path)
    with db.session(db_path) as con:
        autodone.complete(con, ids["t1"], "Forms", "メール「自分の応答: 第3回」", now=NOW)
        nid = con.execute("SELECT id FROM notices WHERE kind = '自動で完了'").fetchone()[0]
    client.post(f"/api/notices/{nid}/answer", json={})
    assert client.get("/api/notices").get_json()["notices"] == []
    assert len(client.get("/api/auto-done").get_json()["items"]) == 1  # 欄には残る


def test_maybe_done_daily(client, db_path):
    ids = setup(db_path)
    with db.session(db_path) as con:
        mail(con, 1, "第3回レポートの提出がありました(教員より)", "授業")
        run = picker(lambda p: {"maybe_done": [{"task_id": ids["t1"], "reason": "提出のお知らせが届いた"}, {"task_id": 4242, "reason": "x"}]})
        assert autodone.run_maybe(con, runner=run, now=NOW) == 1
        assert autodone.run_maybe(con, runner=run, now=NOW) == 0  # 1日1回
        import top
        assert any(n["kind"] == "maybe" for n in top.build(con)["notices"])
    lst = client.get("/api/maybe-done").get_json()
    assert lst[0]["name"] == "第3回レポート"
    client.post(f"/api/maybe-done/{lst[0]['id']}", json={"done": False})  # ちがう
    assert client.get("/api/maybe-done").get_json() == []
    with db.session(db_path) as con:
        assert tasks.get(con, ids["t1"])["done"] == 0
        # 次の日も、「ちがう」を押したものは7日間は渡さない
        run2 = picker({"maybe_done": []})
        mail(con, 2, "別のお知らせ", "授業")
        autodone.run_maybe(con, runner=run2, now=datetime(2026, 10, 21, 9, 0))
        import json
        assert "第3回レポート" not in [t["name"] for t in json.loads(run2.calls[0])["tasks"]]


def test_maybe_done_yes_completes(client, db_path):
    ids = setup(db_path)
    with db.session(db_path) as con:
        con.execute("INSERT INTO maybe_done(task_id, reason) VALUES (?, 'r')", (ids["t3"],))
    mid = client.get("/api/maybe-done").get_json()[0]["id"]
    client.post(f"/api/maybe-done/{mid}", json={"done": True})
    with db.session(db_path) as con:
        t = tasks.get(con, ids["t3"])
        assert t["done"] == 1 and t["auto_done_by"] is None  # 自分で押したので「自動」ではない


def test_maybe_failure_waits_next_day(db_path):
    setup(db_path)
    with db.session(db_path) as con:
        mail(con, 1, "お知らせ", "授業")
        assert autodone.run_maybe(con, runner=picker(agent.AgentError("x")), now=NOW) == 0
        assert autodone.run_maybe(con, runner=picker({"maybe_done": []}), now=NOW) == 0
        assert mails.setting(con, "maybe_done_on") == "2026-10-20"
