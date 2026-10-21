"""初めて見た窓の仕分け(要件 F4 1.08、基本設計 Q38・AI ⑨)。Claude は作り物を渡す。"""
import json
from datetime import datetime, timedelta

import agent
import db
import winsort
import worklog

T0 = datetime(2026, 10, 21, 9, 0)


def setup(db_path):
    db.init(db_path)
    with db.session(db_path) as con:
        dev = con.execute("SELECT id FROM kinds WHERE name = '開発'").fetchone()["id"]
        uni = con.execute("SELECT id FROM kinds WHERE name = '大学'").fetchone()["id"]
        wb = con.execute("INSERT INTO containers(kind_id, name) VALUES (?, 'workbench')", (dev,)).lastrowid
        cls = con.execute("INSERT INTO containers(kind_id, name) VALUES (?, '情報科学演習Ⅱ')", (uni,)).lastrowid
        for i, w in enumerate([("VS Code", "app.py - workbench - Visual Studio Code"), ("Chrome", "Instagram - Google Chrome"),
                               ("Claude", "何でも屋"), ("Edge", "11章 - 個人 - Microsoft Edge")]):
            worklog.tick(con, w, T0 + timedelta(minutes=i))
    return wb, cls


def pending(con):
    return {p["title"].split("|", 1)[1]: p["id"] for p in con.execute("SELECT * FROM pending_windows")}


def test_ai_sorts_and_only_unknown_is_asked(db_path):
    wb, cls = setup(db_path)
    seen = {}

    def fake(system, prompt):
        data = json.loads(prompt)
        seen["prompt"] = data
        key = {w["name"]: w["key"] for w in data["windows"]}
        return {"items": [{"key": key["workbench"], "result": "container", "container_id": wb},
                          {"key": key["Instagram"], "result": "ignore"},
                          {"key": key["何でも屋"], "result": "unknown"},
                          {"key": key["11章"], "result": "container", "container_id": 9999}]}  # 一覧にない番号

    with db.session(db_path) as con:
        assert con.execute("SELECT COUNT(*) FROM notices").fetchone()[0] == 0  # すぐには聞かない
        assert winsort.run(con, runner=fake, now=T0 + timedelta(minutes=5)) == 2
        # Claude に渡すのは、アプリ名と短くした文字と入れ物の一覧だけ
        assert set(seen["prompt"]) == {"windows", "containers"}
        assert {w["name"] for w in seen["prompt"]["windows"]} == {"workbench", "Instagram", "何でも屋", "11章"}
        rules = {r["pattern"]: dict(r) for r in con.execute("SELECT * FROM window_rules")}
        assert rules["workbench"]["container_id"] == wb and rules["workbench"]["by_ai"] == 1 and rules["workbench"]["ai_seen"] == 0
        assert rules["Instagram"]["ignore"] == 1
        asked = sorted(n["body"] for n in con.execute("SELECT * FROM notices WHERE kind = 'window'"))
        assert len(asked) == 2 and "何でも屋" in asked[1] + asked[0] and any("11章" in a for a in asked)  # 分からない・番号ちがいは聞く
        assert set(pending(con)) == {"何でも屋", "11章"}  # 決まった窓の名前は消す
        # 次からは決まりで記録する
        worklog.tick(con, ("VS Code", "x.py - workbench - Visual Studio Code"), T0 + timedelta(minutes=6))
        assert worklog.current(con)["container_id"] == wb
        # 聞いたものは、もう Claude に渡さない
        assert winsort.run(con, runner=lambda s, p: 1 / 0, now=T0 + timedelta(minutes=20)) == 0


def test_claude_fails_then_asks_and_limit_waits(db_path):
    setup(db_path)
    with db.session(db_path) as con:
        def broken(s, p):
            raise agent.AgentError("形がちがう")
        assert winsort.run(con, runner=broken, now=T0 + timedelta(minutes=5)) == 0
        assert con.execute("SELECT COUNT(*) FROM notices WHERE kind = 'window'").fetchone()[0] == 4  # 推測で埋めずに聞く
    db.init(db_path)
    with db.session(db_path) as con:
        con.execute("DELETE FROM notices"); con.execute("UPDATE pending_windows SET ai_tried = 0")

        def limited(s, p):
            raise agent.UsageLimit("limit")
        assert winsort.run(con, runner=limited, now=T0 + timedelta(minutes=30)) == 0
        assert con.execute("SELECT COUNT(*) FROM notices").fetchone()[0] == 0  # 上限のときは聞かずに、あとでもう一度
        assert winsort.run(con, runner=lambda s, p: {"items": []}, now=T0 + timedelta(minutes=31)) == 0  # 間を数えない
        assert con.execute("SELECT COUNT(*) FROM notices").fetchone()[0] == 4


def test_runs_every_five_minutes(db_path):
    setup(db_path)
    calls = []
    with db.session(db_path) as con:
        winsort.run(con, runner=lambda s, p: calls.append(1) or {"items": []}, now=T0 + timedelta(minutes=5))
        worklog.tick(con, ("Word", "卒論.docx - Word"), T0 + timedelta(minutes=6))
        winsort.run(con, runner=lambda s, p: calls.append(1) or {"items": []}, now=T0 + timedelta(minutes=8))
        assert len(calls) == 1
        winsort.run(con, runner=lambda s, p: calls.append(1) or {"items": []}, now=T0 + timedelta(minutes=10))
        assert len(calls) == 2


def test_old_questions_are_sorted_once(db_path):
    """前からたまっていた質問も、1回まとめて仕分ける。"""
    wb, _ = setup(db_path)
    with db.session(db_path) as con:
        for p in con.execute("SELECT * FROM pending_windows").fetchall():  # 前の作りで、もう聞いてある
            app, key = p["title"].split("|", 1)
            con.execute("INSERT INTO notices(kind, body, pending_window_id) VALUES ('window', ?, ?)", (f"{app} で開いている「{key}」は?", p["id"]))
        key = pending(con)["workbench"]
        winsort.run(con, runner=lambda s, p: {"items": [{"key": key, "result": "container", "container_id": wb}]}, now=T0 + timedelta(minutes=5))
        assert con.execute("SELECT COUNT(*) FROM notices WHERE kind = 'window'").fetchone()[0] == 3  # 決まった1件の質問は消える


def test_api_shows_ai_notice_and_can_fix(client, db_path):
    wb, cls = setup(db_path)
    with db.session(db_path) as con:
        key = pending(con)["11章"]
        ig = pending(con)["Instagram"]
        winsort.run(con, runner=lambda s, p: {"items": [{"key": key, "result": "container", "container_id": wb}, {"key": ig, "result": "ignore"}]}, now=T0 + timedelta(minutes=5))
    d = client.get("/api/notices").get_json()
    assert {a["pattern"] for a in d["ai"]} == {"11章", "Instagram"}
    assert client.get("/api/messages/summary").get_json()["asks"] == 2 + 1  # 聞いている2件と、AI のお知らせ1行
    rid = next(a["id"] for a in d["ai"] if a["pattern"] == "11章")
    assert client.patch(f"/api/window-rules/{rid}", json={"container_id": cls}).status_code == 200  # 選び直す
    assert client.patch(f"/api/window-rules/{rid}", json={"container_id": 9999}).status_code == 400
    client.post("/api/window-rules/ai-seen")
    assert client.get("/api/notices").get_json()["ai"] == []
    rules = {r["pattern"]: r for r in client.get("/api/window-rules").get_json()}
    assert rules["11章"]["container_id"] == cls and rules["11章"]["by_ai"] == 0  # 直したら本人が決めたもの
    assert rules["Instagram"]["by_ai"] == 1
    client.patch(f"/api/window-rules/{rules['Instagram']['id']}", json={"ignore": True})


def test_old_db_gets_new_columns(tmp_path):
    """前からある DB にも、起動時に足りない列だけ足す。前の決まりはお知らせに出さない。"""
    import sqlite3
    p = tmp_path / "old.db"
    con = sqlite3.connect(p)
    con.executescript("CREATE TABLE window_rules (id INTEGER PRIMARY KEY, app TEXT NOT NULL, pattern TEXT NOT NULL, container_id INTEGER, ignore INTEGER NOT NULL DEFAULT 0);"
                      "CREATE TABLE pending_windows (id INTEGER PRIMARY KEY, title TEXT NOT NULL, first_seen TEXT NOT NULL);"
                      "INSERT INTO window_rules(app, pattern, ignore) VALUES ('Chrome', 'YouTube', 1);")
    con.commit(); con.close()
    db.init(p)
    with db.session(p) as c:
        r = c.execute("SELECT * FROM window_rules").fetchone()
        assert r["by_ai"] == 0 and r["ai_seen"] == 1
        assert "ai_tried" in {x[1] for x in c.execute("PRAGMA table_info(pending_windows)")}
