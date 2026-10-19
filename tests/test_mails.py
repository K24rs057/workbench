"""区切り7 大学の Outlook(F9、Q6・Q11・Q13)。Outlook は読まず、作り物のメールを渡す。"""
from datetime import date, datetime, timedelta

import agent
import db
import mails
import outlook
import timetable

NOW = datetime(2026, 10, 19, 9, 0)
UNI = "example-u.ac.jp"


def setup(db_path):
    db.init(db_path)
    with db.session(db_path) as con:
        timetable.refresh(con, force=True)   # 設計演習・情報演習・デザイン(テスト用の時間割)
        mails.set_setting(con, "university_domain", UNI)


def mail(subject, body="", sender=f"teacher@ip.{UNI}", days_ago=1, eid=None):
    return {"source": "Outlook", "external_id": eid or f"outlook:{subject}", "subject": subject, "sender": sender,
            "received_at": NOW - timedelta(days=days_ago), "body": body}


def run(con, items, initial_last=None):
    if initial_last:
        mails.set_setting(con, "outlook_read_at", initial_last.isoformat())
    return outlook.refresh(con, now=NOW, reader=lambda since: items, force=True)


def test_find_deadlines():
    r = NOW
    assert mails.find_deadlines("第3回レポートは10月23日(金)23:59までに提出してください", r)[0][:2] == (date(2026, 10, 23), "23:59")
    assert mails.find_deadlines("提出期限:2027/1/10 17時", r)[0][:2] == (date(2027, 1, 10), "17:00")
    assert mails.find_deadlines("【本日締切12:00】申込", r)[0][:2] == (date(2026, 10, 19), "12:00")
    assert mails.find_deadlines("1月8日まで提出", datetime(2026, 12, 20))[0][0] == date(2027, 1, 8)  # 年をまたぐ
    assert mails.find_deadlines("10月23日に開催します", r) == []


def test_classify_and_skip_outside(db_path):
    setup(db_path)
    with db.session(db_path) as con:
        n = run(con, [
            mail("教員連絡:情報演習(10/21 3限)について"),
            mail("学内連絡:【奨学金】在籍報告の書類について"),
            mail("学内連絡:留学祭のお知らせ"),
            mail("広告メール", sender="news@shop.example.com"),
            mail("自分の応答: 情報演習 第3回", sender="no-reply@forms.mail.microsoft"),
        ], initial_last=NOW - timedelta(hours=1))
        rows = {r["subject"]: (r["category"], r["container_id"]) for r in con.execute("SELECT * FROM messages")}
        cls = con.execute("SELECT id FROM containers WHERE source_key = '情報演習'").fetchone()["id"]
        sch = con.execute("SELECT id FROM containers WHERE auto_source = '奨学金'").fetchone()["id"]
    assert n == 4 and "広告メール" not in rows
    assert rows["教員連絡:情報演習(10/21 3限)について"] == ("授業", cls)
    assert rows["学内連絡:【奨学金】在籍報告の書類について"] == ("奨学金", sch)
    assert rows["学内連絡:留学祭のお知らせ"] == ("その他", None)
    assert rows["自分の応答: 情報演習 第3回"][0] == "Forms"


def test_deadline_becomes_task_with_container_or_unsorted(db_path):
    setup(db_path)
    with db.session(db_path) as con:
        run(con, [mail("教員連絡:情報演習 第3回レポート", "第3回レポートは10月23日 23:59までに提出"),
                  mail("学内連絡:【本日締切17:00】説明会の申込", "申込は本日締切です", days_ago=0)],
            initial_last=NOW - timedelta(hours=1))
        ts = {t["name"]: (t["due_date"], t["due_time"], t["container_id"], t["from_message_id"]) for t in con.execute("SELECT * FROM tasks")}
        uid = con.execute("SELECT id FROM containers WHERE is_unsorted = 1").fetchone()["id"]
    assert ts["情報演習 第3回レポート"][:2] == ("2026-10-23", "23:59")
    assert ts["説明会の申込"][2] == uid  # その他 → 未分類


def test_first_read_skips_past_deadlines_and_marks_seen(db_path):
    setup(db_path)
    with db.session(db_path) as con:
        run(con, [mail("教員連絡:デザイン 課題", "10月10日までに提出", days_ago=20), mail("教員連絡:デザイン 次の課題", "10月30日までに提出", days_ago=2)])
        names = [t["name"] for t in con.execute("SELECT name FROM tasks")]
        assert names == ["デザイン 次の課題"]
        assert con.execute("SELECT COUNT(*) FROM messages WHERE seen = 0").fetchone()[0] == 0  # 初めの分は「新しい」にしない


def test_no_domain_setting_is_error(db_path):
    db.init(db_path)
    with db.session(db_path) as con:
        assert outlook.refresh(con, now=NOW, reader=lambda s: [mail("x")], force=True) == 0
        assert "設定されていません" in mails.setting(con, "outlook_error")


def test_reader_failure_does_not_guess(db_path):
    setup(db_path)

    def broken(since):
        raise RuntimeError("sign-in expired")

    with db.session(db_path) as con:
        outlook.refresh(con, now=NOW, reader=broken, force=True)
        assert mails.setting(con, "outlook_error") == "大学のメールを読めませんでした"
        assert con.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0


def test_claude_reads_when_rule_fails_and_retries(db_path):
    setup(db_path)
    with db.session(db_path) as con:
        run(con, [mail("教員連絡:設計演習 中間レポート", "中間レポートの提出は来週の授業の前日です")], initial_last=NOW - timedelta(hours=1))
        assert con.execute("SELECT COUNT(*) FROM claude_jobs").fetchone()[0] == 1

        def broken(s, p):
            raise agent.AgentError("x")

        for i in range(2):
            mails.run_claude_jobs(con, runner=broken, now=NOW + timedelta(minutes=11 * (i + 1)), today=NOW.date())
        mails.run_claude_jobs(con, runner=lambda s, p: {"items": [{"date": "2026-10-26", "time": None, "title": "中間レポート"}]},
                              now=NOW + timedelta(minutes=40), today=NOW.date())
        t = con.execute("SELECT * FROM tasks").fetchone()
        assert (t["name"], t["due_date"], t["ai_read"]) == ("中間レポート", "2026-10-26", 1)
        assert con.execute("SELECT COUNT(*) FROM claude_jobs").fetchone()[0] == 0


def test_claude_three_failures_marks_message(db_path):
    setup(db_path)
    with db.session(db_path) as con:
        run(con, [mail("教員連絡:設計演習 課題", "提出は追って連絡します")], initial_last=NOW - timedelta(hours=1))

        def broken(s, p):
            raise agent.AgentError("x")

        for i in range(3):
            mails.run_claude_jobs(con, runner=broken, now=NOW + timedelta(minutes=11 * (i + 1)))
        assert con.execute("SELECT ai_failed FROM messages").fetchone()[0] == 1


def test_usage_limit_does_not_count(db_path):
    setup(db_path)
    with db.session(db_path) as con:
        run(con, [mail("教員連絡:設計演習 課題", "提出は追って連絡します")], initial_last=NOW - timedelta(hours=1))

        def limited(s, p):
            raise agent.UsageLimit("limit")

        mails.run_claude_jobs(con, runner=limited, now=NOW + timedelta(minutes=11))
        assert con.execute("SELECT tries FROM claude_jobs").fetchone()[0] == 0


def test_class_change_is_held(db_path):
    setup(db_path)
    with db.session(db_path) as con:
        run(con, [mail("教員連絡:情報演習 補講のお知らせ", "10月24日(土)3限に補講を行います")], initial_last=NOW - timedelta(hours=1))
        h = con.execute("SELECT * FROM held_events").fetchone()
    assert h["start_at"] == "2026-10-24" and h["title"].startswith("補講")


def test_same_mail_once_and_body_purge(db_path):
    setup(db_path)
    with db.session(db_path) as con:
        old = mail("教員連絡:デザイン お知らせ", "本文", days_ago=100)
        mails.ingest(con, {**old, "category": "授業"})
        assert mails.ingest(con, {**old, "category": "授業"}) is None
        mails.purge_bodies(con, NOW)
        assert con.execute("SELECT body FROM messages").fetchone()[0] is None


def test_mail_screen_api(client, db_path):
    with db.session(db_path) as con:
        mails.set_setting(con, "university_domain", UNI)
        timetable.refresh(con, force=True)
        run(con, [mail("学内連絡:説明会", "10月30日までに申込"), mail("教員連絡:デザイン 連絡", "本文です")], initial_last=NOW - timedelta(hours=1))
    s = client.get("/api/messages/summary").get_json()
    assert s["new"] == 2
    client.get("/api/messages/summary?open=1")
    assert client.get("/api/messages/summary").get_json()["new"] == 0
    lst = client.get("/api/messages").get_json()
    assert len(lst["main"]) == 1 and len(lst["other"]) == 1
    other = lst["other"][0]
    detail = client.get(f"/api/messages/{other['id']}").get_json()
    assert detail["tasks"][0]["name"] == "説明会"
    cid = client.post("/api/containers", json={"name": "キャリア", "kind_id": 2}).get_json()["id"]
    client.patch(f"/api/messages/{other['id']}", json={"container_id": cid})
    assert client.get(f"/api/messages/{other['id']}").get_json()["container"] == "キャリア"
    with db.session(db_path) as con:
        assert con.execute("SELECT container_id FROM tasks").fetchone()[0] == cid
        assert con.execute("SELECT COUNT(*) FROM sort_rules").fetchone()[0] == 1
    # 自動で入ったタスクを消すと、記録が残る
    tid = detail["tasks"][0]["id"]
    client.delete(f"/api/tasks/{tid}")
    with db.session(db_path) as con:
        assert con.execute("SELECT COUNT(*) FROM deleted_items").fetchone()[0] == 1
    client.post("/api/blocked-senders", json={"address": other["sender"]})
    assert client.get("/api/blocked-senders").get_json()[0]["address"] == other["sender"]
    assert client.patch("/api/settings/mail", json={"university_domain": "abc"}).status_code == 400
