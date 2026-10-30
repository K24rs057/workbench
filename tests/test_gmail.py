"""区切り9 自分の Gmail(F11・F20、Q20〜Q22)。Google にはつながず、作り物のメールを渡す。"""
from datetime import date, datetime, timedelta

import db
import gmail
import mails

NOW = datetime(2026, 10, 19, 9, 0)


def mail(subject, body="", sender="saiyo@abc-tech.co.jp", days_ago=1, eid=None):
    return {"source": "Gmail", "external_id": eid or f"gmail:{subject}", "subject": subject, "sender": sender,
            "received_at": NOW - timedelta(days=days_ago), "body": body}


def setup(con):
    job = con.execute("SELECT id FROM kinds WHERE name = '就活'").fetchone()["id"]
    a = con.execute("INSERT INTO containers(kind_id, name, company_domain) VALUES (?, '株式会社ABCテック', 'abc-tech.co.jp')", (job,)).lastrowid
    b = con.execute("INSERT INTO containers(kind_id, name) VALUES (?, '九州ソフト株式会社')", (job,)).lastrowid
    return a, b


def run(con, items, initial=False):
    if not initial:
        mails.set_setting(con, "gmail_read_at", (NOW - timedelta(hours=1)).isoformat())
    return gmail.refresh(con, now=NOW, reader=lambda since: items, force=True)


def test_company_by_domain_and_name_ads_skipped(db_path):
    db.init(db_path)
    with db.session(db_path) as con:
        a, b = setup(con)
        n = run(con, [
            mail("ES提出のお願い", "10月30日 23:59までにESを提出してください"),
            mail("【マイナビ】九州ソフトからのメッセージ", "説明会のご案内", sender="message@mynavi.jp"),
            mail("【マイナビ】エントリー受付中!九州ソフト", "", sender="info@mynavi.jp"),
            mail("Amazon のご注文", "", sender="shop@amazon.co.jp"),
        ])
        rows = {r["subject"]: (r["category"], r["container_id"]) for r in con.execute("SELECT * FROM messages")}
        t = con.execute("SELECT * FROM tasks").fetchone()
    assert n == 2
    assert rows["ES提出のお願い"] == ("企業", a)
    assert rows["【マイナビ】九州ソフトからのメッセージ"] == ("企業", b)  # 「株式会社」を外した名前で見分ける
    assert (t["container_id"], t["due_date"], t["due_time"]) == (a, "2026-10-30", "23:59")


def test_blocked_domain_and_sort_rule(db_path):
    db.init(db_path)
    with db.session(db_path) as con:
        a, b = setup(con)
        con.execute("INSERT INTO blocked_senders(address) VALUES ('@abc-tech.co.jp')")
        con.execute("INSERT INTO sort_rules(sender, container_id) VALUES ('hr@other.jp', ?)", (b,))
        run(con, [mail("ES"), mail("面談のお礼", sender="hr@other.jp")])
        rows = [(r["subject"], r["container_id"]) for r in con.execute("SELECT * FROM messages")]
    assert rows == [("面談のお礼", b)]


def test_baito_relay_asks_once_then_remembers(db_path):
    db.init(db_path)
    with db.session(db_path) as con:
        run(con, [mail("応募ありがとうございます", "面接日を調整します", sender="abc123@indeedemail.com", eid="g1"),
                  mail("ご連絡", "", sender="abc123@indeedemail.com", eid="g2")])
        qs = con.execute("SELECT * FROM notices WHERE kind = 'バイト先の質問'").fetchall()
        assert len(qs) == 1
        assert con.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0  # アルバイトはタスクにしない
        mails.answer_baito(con, qs[0], name="カフェ博多店")
        bid = con.execute("SELECT id FROM baito_places").fetchone()["id"]
        assert con.execute("SELECT COUNT(*) FROM messages WHERE baito_id = ?", (bid,)).fetchone()[0] == 2
        run(con, [mail("シフトについて", "", sender="abc123@indeedemail.com", eid="g3")])
        assert con.execute("SELECT baito_id FROM messages WHERE external_id = 'g3'").fetchone()[0] == bid
        assert con.execute("SELECT COUNT(*) FROM notices WHERE answered = 0").fetchone()[0] == 0
        # 中継サイトそのもののお知らせは取り込まない
        run(con, [mail("ログインしてメッセージを確認してください", "", sender="sender@townwork.net", eid="g4")])
        assert con.execute("SELECT COUNT(*) FROM messages WHERE external_id = 'g4'").fetchone()[0] == 0


def test_baito_subject_words_only(db_path):
    """件名の言葉を持つバイト先は、件名にその言葉があるときだけ拾う。宣伝は同じアドレスから届いても拾わない(1.13)。"""
    db.init(db_path)
    with db.session(db_path) as con:
        e = con.execute("INSERT INTO baito_places(name, domain, subject_has) VALUES ('派遣の会社', 'haken.example.jp', '作業内容/派遣の会社')").lastrowid
        con.execute("INSERT INTO baito_addresses(baito_id, address) VALUES (?, 'kurume@haken.example.jp')", (e,))
        k = con.execute("INSERT INTO baito_places(name, domain) VALUES ('カフェ', 'cafe.example.jp')").lastrowid
        run(con, [mail("0001 山田 様 2026年11月06日(金) 作業内容/派遣の会社", sender="fukuoka@haken.example.jp", eid="w1"),
                  mail("【注目】時給UP店舗も続出!", sender="fukuoka@haken.example.jp", eid="w2"),
                  mail("明日の単発バイト急募です!", sender="kurume@haken.example.jp", eid="w3"),
                  mail("2026年11月07日(土) 作業内容/派遣の会社", sender="kurume@haken.example.jp", eid="w4"),
                  mail("来週のシフト", sender="tencho@cafe.example.jp", eid="w5")])
        rows = {r["external_id"]: r["baito_id"] for r in con.execute("SELECT * FROM messages")}
    assert rows == {"w1": e, "w4": e, "w5": k}  # 言葉のないバイト先は今までどおり全部


def test_interview_decided_becomes_held_event(db_path):
    db.init(db_path)
    with db.session(db_path) as con:
        a, _ = setup(con)
        run(con, [mail("一次面接のご案内", "一次面接を10月23日(金)14:00から行います")])
        assert con.execute("SELECT kind FROM claude_jobs").fetchone()[0] == "面接の読み取り"
        mails.run_claude_jobs(con, runner=lambda s, p: {"type": "決定", "title": "一次面接",
                                                        "dates": [{"date": "2026-10-23", "start": "14:00", "end": "15:00"}]},
                              now=NOW, today=NOW.date())
        h = con.execute("SELECT * FROM held_events").fetchone()
    assert (h["title"], h["start_at"], h["end_at"], h["container_id"], h["ai_read"]) == \
        ("一次面接:株式会社ABCテック", "2026-10-23T14:00", "2026-10-23T15:00", a, 1)


def test_interview_candidates_then_pick_and_delete(db_path):
    db.init(db_path)
    with db.session(db_path) as con:
        setup(con)
        run(con, [mail("面接日程のご相談", "10月26日、10月27日、10月28日のいずれかで面接はいかがでしょうか")])
        mails.run_claude_jobs(con, runner=lambda s, p: {"type": "候補", "title": "面接", "dates": [
            {"date": "2026-10-26", "start": "10:00", "end": None}, {"date": "2026-10-27", "start": "13:00", "end": None},
            {"date": "2026-10-01", "start": None, "end": None}]}, now=NOW, today=NOW.date())
        assert con.execute("SELECT COUNT(*) FROM held_events").fetchone()[0] == 0
        n = con.execute("SELECT * FROM notices WHERE kind = '候補日'").fetchone()
        import json
        assert len(json.loads(n["body"])["dates"]) == 2  # 過ぎた日は出さない
        mails.answer_candidate(con, n, 1)
        h = con.execute("SELECT * FROM held_events").fetchone()
        assert h["start_at"] == "2026-10-27T13:00"
        mails.delete_held(con, h["id"])
        assert con.execute("SELECT COUNT(*) FROM deleted_items WHERE what = '予定'").fetchone()[0] == 1


def test_unknown_type_is_treated_as_candidates(db_path):
    db.init(db_path)
    with db.session(db_path) as con:
        setup(con)
        run(con, [mail("面談について", "11月2日に面談")])
        mails.run_claude_jobs(con, runner=lambda s, p: {"type": "不明", "title": "面談", "dates": [{"date": "2026-11-02", "start": None, "end": None}]},
                              now=NOW, today=NOW.date())
        assert con.execute("SELECT COUNT(*) FROM notices WHERE kind = '候補日'").fetchone()[0] == 1


def test_read_failure_sets_error(db_path):
    db.init(db_path)

    def broken(since):
        raise RuntimeError("invalid_grant: Token has been expired or revoked.")

    with db.session(db_path) as con:
        gmail.refresh(con, now=NOW, reader=broken, force=True)
        assert "許可が切れています" in mails.setting(con, "gmail_error")


def test_not_connected_does_nothing(db_path, tmp_path, monkeypatch):
    monkeypatch.setattr(gmail, "ENV_PATH", tmp_path / ".env")
    db.init(db_path)
    with db.session(db_path) as con:
        assert gmail.refresh(con, now=NOW, force=True) == 0
        assert gmail.state() == "合鍵なし"


def test_env_key_import_keeps_other_lines(tmp_path):
    env = tmp_path / ".env"
    env.write_text("OTHER=1\n", encoding="utf-8")
    key = tmp_path / "client.json"
    key.write_text('{"installed": {"client_id": "id-x", "client_secret": "sec-y"}}', encoding="utf-8")
    gmail.import_client_json(key, env)
    gmail.write_env({"GOOGLE_REFRESH_TOKEN": "tok"}, env)
    e = gmail.read_env(env)
    assert e == {"OTHER": "1", "GOOGLE_CLIENT_ID": "id-x", "GOOGLE_CLIENT_SECRET": "sec-y", "GOOGLE_REFRESH_TOKEN": "tok"}
    assert gmail.state(e) == "許可済み"


def test_body_from_html_part():
    import base64
    data = base64.urlsafe_b64encode("<p>面接は<b>10月23日</b></p><style>x{}</style>".encode()).decode().rstrip("=")
    assert "面接は10月23日" in gmail._body({"mimeType": "multipart/alternative", "parts": [{"mimeType": "text/html", "body": {"data": data}}]})
    assert gmail._address('"採用担当" <Saiyo@ABC.jp>') == "saiyo@abc.jp"


def test_far_future_year_is_not_guessed():
    # 10月に届いた「7/13」は、来年の7月ではなく過ぎた日とみなす
    assert mails.find_deadlines("申込締切 7月13日", datetime(2026, 10, 1)) == []
    assert mails.find_deadlines("1月8日まで提出", datetime(2026, 12, 20))[0][0] == date(2027, 1, 8)


def test_baito_and_company_api(client):
    bid = client.post("/api/baito", json={"name": "カフェ", "domain": "@cafe.example.jp"}).get_json()["id"]
    assert client.get("/api/baito").get_json()[0]["domain"] == "cafe.example.jp"
    assert client.patch(f"/api/baito/{bid}", json={"domain": "abc"}).status_code == 400
    client.delete(f"/api/baito/{bid}")
    assert client.get("/api/baito").get_json() == []
    cid = client.post("/api/containers", json={"name": "ABC", "kind_id": 2}).get_json()["id"]
    client.patch(f"/api/containers/{cid}", json={"company_domain": "@ABC.co.jp"})
    assert client.get(f"/api/containers/{cid}").get_json()["company_domain"] == "abc.co.jp"
    s = client.get("/api/settings/mail").get_json()
    assert s["google"]["state"] in ("合鍵なし", "未許可", "許可済み")
