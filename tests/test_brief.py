"""モーニングブリーフとの連携(F22 1.07・モッチ-5 A)。"""
import json
from datetime import date, datetime

import db


def setup(client):
    cid = client.post("/api/containers", json={"name": "情報演習", "kind_id": 1}).get_json()["id"]
    client.post("/api/tasks", json={"container_id": cid, "name": "第3回レポート", "due_date": "2026-10-22", "due_time": "23:59"})
    client.post("/api/tasks", json={"container_id": cid, "name": "第4回レポート", "due_date": "2026-10-28"})
    client.post("/api/tasks", json={"container_id": cid, "name": "遠い課題", "due_date": "2026-11-30"})
    client.post("/api/tasks", json={"container_id": cid, "name": "遅れた課題", "due_date": "2026-10-01"})
    return cid


def test_brief_summary_and_health(client, db_path):
    setup(client)
    d = client.get("/api/brief?date=2026-10-22&since=2026-10-21T00:00:00").get_json()
    s, h = d["summary"], d["health"]
    assert [x["name"] for x in s["due_today"]] == ["第3回レポート"]
    assert [x["name"] for x in s["due_7days"]] == ["第3回レポート", "第4回レポート"]  # 7日以内だけ
    assert [x["name"] for x in s["overdue"]] == ["遅れた課題"]
    assert h["ok"] is True and h["questions_waiting"] == 0 and "calendar" in h
    with db.session(db_path) as con:  # 止まっている仕事があれば ok ではない
        con.execute("INSERT INTO job_status(job, last_run_at, last_error) VALUES ('Gmail', '2026-01-01T00:00:00', 'invalid_grant')")
    h = client.get("/api/brief").get_json()["health"]
    assert h["ok"] is False and "Gmail" in h["late"] and h["errors"][0]["job"] == "Gmail"
    assert client.get("/api/brief?date=x").status_code == 400


def test_findings_become_questions_then_tasks(client, db_path):
    cid = setup(client)
    items = [{"title": "A社 冬インターン エントリー締切", "date": "2026-10-31", "source": "28卒のうごき", "url": "https://example.com/a"},
             {"title": "日付がない", "date": "そのうち"}, {"title": "第4回レポート", "date": "2026-10-28"}]
    assert client.post("/api/brief/findings", json={"items": items}).get_json()["added"] == 1  # 日付がない・もうあるタスクは入れない
    assert client.post("/api/brief/findings", json={"items": items}).get_json()["added"] == 0  # 同じものは二度入れない
    n = [x for x in client.get("/api/notices").get_json()["notices"] if x["kind"] == "ブリーフの締切"][0]
    assert n["data"]["title"] == "A社 冬インターン エントリー締切"
    assert client.post(f"/api/notices/{n['id']}/answer", json={}).status_code == 400  # 入れ物を選ばないとタスクにしない
    client.post(f"/api/notices/{n['id']}/answer", json={"container_id": cid})
    tasks = client.get(f"/api/containers/{cid}").get_json()["tasks"]
    t = next(x for x in tasks if x["name"] == "A社 冬インターン エントリー締切")
    assert t["due_date"] == "2026-10-31" and t["open_url"] == "https://example.com/a"
    assert not [x for x in client.get("/api/notices").get_json()["notices"] if x["kind"] == "ブリーフの締切"]


def test_finding_can_be_dismissed(client, db_path):
    setup(client)
    client.post("/api/brief/findings", json={"items": [{"title": "説明会", "date": "2026-11-05"}]})
    n = [x for x in client.get("/api/notices").get_json()["notices"] if x["kind"] == "ブリーフの締切"][0]
    client.post(f"/api/notices/{n['id']}/answer", json={"none": True})
    assert client.get("/api/notices").get_json()["notices"] == []
