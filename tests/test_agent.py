"""区切り6 モッチ(F22、Q31〜Q34)。claude -p は呼ばず、作り物の答えを返す。"""
import json
from datetime import datetime, timedelta

import agent
import db


def setup(db_path):
    db.init(db_path)
    with db.session(db_path) as con:
        uni = con.execute("SELECT id FROM kinds WHERE name = '大学'").fetchone()["id"]
        cid = con.execute("INSERT INTO containers(kind_id, name) VALUES (?, '卒論')", (uni,)).lastrowid
        tid = con.execute("INSERT INTO tasks(container_id, name, due_date) VALUES (?, '中間発表のスライド', '2026-10-21')", (cid,)).lastrowid
    return cid, tid


def test_reply_without_action_and_context_has_no_mail_body(db_path):
    cid, tid = setup(db_path)
    seen = {}

    def fake(system, prompt):
        seen["prompt"] = prompt
        return {"reply": "今週は卒論を進めよう", "action": None}

    with db.session(db_path) as con:
        agent.ask(con, "今日は何から?", "トップ", runner=fake)
        ms = agent.messages(con)
    data = json.loads(seen["prompt"].split("\n", 1)[1])
    assert data["data"]["open_tasks"][0]["name"] == "中間発表のスライド"
    assert "body" not in json.dumps(data)
    assert [(m["role"], m["text"]) for m in ms] == [("自分", "今日は何から?"), ("モッチ", "今週は卒論を進めよう")]


def test_action_needs_confirm_then_runs(db_path):
    cid, tid = setup(db_path)
    act = {"tool": "add_tasks", "label": "この2つを足す", "args": {"tasks": [
        {"container_id": cid, "name": "構成を決める", "due_date": "2026-10-18", "due_time": None},
        {"container_id": cid, "name": "図を作る", "due_date": None, "due_time": None}]}}
    with db.session(db_path) as con:
        mid = agent.ask(con, "スライドを分けて", "トップ", runner=lambda s, p: {"reply": "2つに分けてみたよ", "action": act})
        assert con.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1   # 確認の前は何もしない
        agent.confirm(con, mid)
        assert con.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 3
        try:
            agent.confirm(con, mid)
            raised = False
        except agent.AgentError:
            raised = True
        assert raised  # 2回は行わない


def test_cancel_and_link_change(db_path):
    cid, tid = setup(db_path)
    act = {"tool": "set_task_link", "label": "変える", "args": {"task_id": tid, "url": "https://example.ac.jp/x"}}
    with db.session(db_path) as con:
        mid = agent.ask(con, "リンクを変えて", "トップ", runner=lambda s, p: {"reply": "変えるね", "action": act})
        agent.cancel(con, mid)
        assert con.execute("SELECT open_url FROM tasks").fetchone()[0] is None
        mid = agent.ask(con, "やっぱり変えて", "トップ", runner=lambda s, p: {"reply": "変えるね", "action": act})
        agent.confirm(con, mid)
        assert con.execute("SELECT open_url FROM tasks").fetchone()[0] == "https://example.ac.jp/x"


def test_unknown_tool_or_bad_ids_are_dropped(db_path):
    setup(db_path)
    bad = [
        {"tool": "send_mail", "label": "送る", "args": {}},
        {"tool": "delete_task", "label": "消す", "args": {"task_id": 999}},
        {"tool": "set_task_link", "label": "変える", "args": {"task_id": 1, "url": "C:/Windows"}},
    ]
    with db.session(db_path) as con:
        for a in bad:
            mid = agent.ask(con, "やって", "トップ", runner=lambda s, p, a=a: {"reply": "はい", "action": a})
            row = con.execute("SELECT action, action_state FROM agent_messages WHERE id = ?", (mid,)).fetchone()
            assert row["action"] is None and row["action_state"] is None


def test_failures_and_usage_limit(db_path):
    setup(db_path)

    def broken(s, p):
        raise agent.AgentError("x")

    def limited(s, p):
        raise agent.UsageLimit("limit")

    with db.session(db_path) as con:
        agent.ask(con, "a", "トップ", runner=broken)
        agent.ask(con, "b", "トップ", runner=limited)
        texts = [m["text"] for m in agent.messages(con) if m["role"] == "モッチ"]
    assert texts == [agent.FAIL_TEXT, agent.LIMIT_TEXT]


def test_history_is_cleared_after_seven_days(db_path):
    setup(db_path)
    old = (datetime.now() - timedelta(days=8)).isoformat(timespec="seconds")
    with db.session(db_path) as con:
        con.execute("INSERT INTO agent_messages(role, text, created_at) VALUES ('自分', '古い話', ?)", (old,))
        assert agent.messages(con) == []


def test_settings_and_hint(client, db_path):
    assert client.get("/api/mochi").get_json()["settings"]["mochi_idle"] == "1"
    client.patch("/api/mochi", json={"mochi_idle": "0", "mochi_pos_wide": "{\"x\":10,\"y\":20}", "unknown": "x"})
    st = client.get("/api/mochi").get_json()
    assert st["settings"]["mochi_idle"] == "0" and "unknown" not in st["settings"]
    assert st["hint"] is None
    cid = client.post("/api/containers", json={"name": "情報工学演習", "kind_id": 1}).get_json()["id"]
    client.post("/api/tasks", json={"container_id": cid, "name": "第9回レポート", "due_date": "2000-01-01"})
    assert "第9回レポート" in client.get("/api/mochi").get_json()["hint"]
    assert client.post("/api/agent/ask", json={"text": " "}).status_code == 400
