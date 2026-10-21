"""あとの区切り 1行入力(F17)と着手日(F16)。"""
from datetime import date, datetime, timedelta

import pytest

import agent
import db
import notify
import quick
import top
from test_containers_tasks import add_task, make

FRI = date(2026, 10, 23)   # 金曜
WED = date(2026, 10, 21)   # 水曜


# ---------- 決まった書き方(Q10) ----------
@pytest.mark.parametrize("word,today,want", [
    ("金", WED, "2026-10-23"),
    ("金", FRI, "2026-10-23"),          # 今日が金曜なら今日(Q4)
    ("金曜", WED, "2026-10-23"),
    ("来週金", WED, "2026-10-30"),
    ("今日", WED, "2026-10-21"),
    ("明日", WED, "2026-10-22"),
    ("あさって", WED, "2026-10-23"),
    ("3日後", WED, "2026-10-24"),
    ("10/25", WED, "2026-10-25"),
    ("10月25日", WED, "2026-10-25"),
    ("25日", WED, "2026-10-25"),
    ("20日", WED, "2026-11-20"),        # 今月の20日はもう過ぎた → 来月
    ("1/10", WED, "2027-01-10"),        # 年明けの日付は来年
    ("10/15", WED, "2026-10-15"),       # 少し前の日付はそのまま(期限切れとして入る)
])
def test_read_date(word, today, want):
    assert quick.read_date(word, today).isoformat() == want


@pytest.mark.parametrize("word,want", [("23:59", "23:59"), ("9:05", "09:05"), ("17時", "17:00"), ("17時半", "17:30"),
                                       ("24時", "23:59"), ("25:00", None), ("レポート", None)])
def test_read_time(word, want):
    assert quick.read_time(word) == want


def test_parse_rules():
    choices = [{"id": 1, "name": "卒論"}, {"id": 2, "name": "情報工学演習"}, {"id": 3, "name": "株式会社さくら 商事"}]
    assert quick.parse_rules("金 レポート 卒論", choices, WED) == {"title": "レポート", "date": "2026-10-23", "time": None, "container_id": 1}
    assert quick.parse_rules("情報 第10回課題 10/25 23:59", choices, WED)["container_id"] == 2  # 名前の一部
    got = quick.parse_rules("株式会社さくら 商事 ES 明日 17時", choices, WED)  # 空白を含む名前
    assert (got["container_id"], got["title"], got["date"], got["time"]) == (3, "ES", "2026-10-22", "17:00")
    # 語の中に名前があるときは、入れ物を決めて、タスク名はそのまま残す
    got = quick.parse_rules("金 卒論の資料を読む", choices, WED)
    assert (got["container_id"], got["title"]) == (1, "卒論の資料を読む")
    assert quick.parse_rules("株式会社さくら 商事の説明会", choices, WED)["container_id"] == 3  # 名前の一部「株式会社さくら」
    assert quick.parse_rules("本を読む", choices, WED) == {"title": "本を読む", "date": None, "time": None, "container_id": None}
    assert quick.parse_rules("金", choices, WED)["title"] == "金"   # 名前が残らないときは打った文字をそのまま
    assert quick.parse_rules("23:59 提出", choices, WED)["date"] == "2026-10-21"  # 時刻だけなら今日


# ---------- API(A2) ----------
def test_quick_input_api(client):
    cid = make(client, "卒論", "開発")
    r = client.post("/api/quick-input", json={"text": "明日 レポート 卒論"})
    assert r.status_code == 201
    j = r.get_json()
    assert (j["task"]["name"], j["task"]["container_id"], j["how"], j["unsorted"]) == ("レポート", cid, "rules", False)
    assert j["task"]["due_date"] == (date.today() + timedelta(days=1)).isoformat()

    # 入れ物が読めなければ未分類と印、締切が読めなければ締切なし
    j = client.post("/api/quick-input", json={"text": "なにかやる"}).get_json()
    assert j["unsorted"] and j["task"]["due_date"] is None
    assert any(t["name"] == "なにかやる" for t in client.get("/api/unsorted").get_json()["tasks"])

    # 入れ物の中の欄(S5-3a)は、その入れ物に決まっている
    other = make(client, "情報工学演習")
    j = client.post("/api/quick-input", json={"text": "金 卒論の資料を読む", "container_id": other}).get_json()
    assert j["task"]["container_id"] == other and j["task"]["name"] == "卒論の資料を読む"

    assert client.post("/api/quick-input", json={"text": "  "}).status_code == 400


def test_quick_ai_toggle(client):
    assert client.get("/api/top").get_json()["quick_ai"] is False   # 初めはオフ
    assert client.patch("/api/quick-input", json={"ai": True}).get_json() == {"ai": True}
    assert client.get("/api/top").get_json()["quick_ai"] is True


def test_quick_ai_reads_and_falls_back(db_path):
    db.init(db_path)
    with db.session(db_path) as con:
        import containers
        kid = con.execute("SELECT id FROM kinds WHERE name = '開発'").fetchone()[0]
        cid = containers.add_container(con, "卒論", kid)

        seen = {}
        def good(system, prompt):
            seen["prompt"] = prompt
            return {"title": "中間発表のスライド", "date": "2026-10-31", "time": "9:00", "container_id": cid}
        j = quick.add(con, "月末の朝に卒論の中間発表のスライド", use_ai=True, today=WED, runner=good)
        assert (j["how"], j["task"]["due_date"], j["task"]["due_time"], j["task"]["container_id"]) == ("ai", "2026-10-31", "09:00", cid)
        assert "卒論" in seen["prompt"] and "2026-10-21" in seen["prompt"]

        # 一覧にない番号・形の崩れた日付は捨てる
        j = quick.add(con, "なにか", use_ai=True, today=WED, runner=lambda s, p: {"title": "なにか", "date": "来週", "time": None, "container_id": 999})
        assert j["unsorted"] and j["task"]["due_date"] is None

        # 失敗したら決まった書き方で読み直す(AI ⑤)
        def broken(system, prompt):
            raise agent.AgentError("x")
        j = quick.add(con, "金 レポート 卒論", use_ai=True, today=WED, runner=broken)
        assert (j["how"], j["task"]["due_date"], j["task"]["container_id"]) == ("fallback", "2026-10-23", cid)

        def limited(system, prompt):
            raise agent.UsageLimit("limit")
        assert quick.add(con, "金 レポート", use_ai=True, today=WED, runner=limited)["how"] == "limit"


# ---------- 着手日(F16) ----------
def test_start_date_rules(client):
    cid = make(client, "卒論", "開発")
    tid = add_task(client, cid, name="原稿", due_date="2026-12-01", start_date="2026-11-01")
    assert client.patch(f"/api/tasks/{tid}", json={"start_date": "2026-12-05"}).status_code == 400   # 締切より後はだめ
    assert client.patch(f"/api/tasks/{tid}", json={"start_date": "11/01"}).status_code == 400
    j = client.patch(f"/api/tasks/{tid}", json={"start_date": ""}).get_json()
    assert j["start_date"] is None


def test_started_tasks_rise_to_today(client, db_path):
    cid = make(client, "卒論", "開発")
    t0 = date.today()
    started = add_task(client, cid, name="原稿を書きはじめる", due_date=(t0 + timedelta(days=20)).isoformat(), start_date=t0.isoformat())
    nodue = add_task(client, cid, name="参考文献を集める", start_date=(t0 - timedelta(days=1)).isoformat())
    later = add_task(client, cid, name="まだ先", due_date=(t0 + timedelta(days=3)).isoformat(), start_date=(t0 + timedelta(days=2)).isoformat())
    due_today = add_task(client, cid, name="今日まで", due_date=t0.isoformat(), start_date=t0.isoformat())
    j = client.get("/api/top").get_json()
    assert [t["id"] for t in j["started"]] == [started, nodue]
    assert [t["id"] for t in j["today_tasks"]] == [due_today]       # 今日が締切なら、ふつうの「今日」のまま
    assert [t["id"] for t in j["week"]] == [later]                   # 着手日の前は隠さない
    assert nodue not in [t["id"] for t in j["nodue"]]                # 上がったものは二重に出さない


def test_start_missed_mark_and_notice(db_path, monkeypatch):
    monkeypatch.setenv("DANDORI_NO_TOAST", "1")
    db.init(db_path)
    with db.session(db_path) as con:
        import containers
        import tasks
        kid = con.execute("SELECT id FROM kinds WHERE name = '開発'").fetchone()[0]
        cid = containers.add_container(con, "卒論", kid)
        tid = tasks.add(con, {"container_id": cid, "name": "原稿", "start_date": "2026-10-20"})
        con.execute("UPDATE tasks SET created_at = '2026-10-19 10:00:00' WHERE id = ?", (tid,))
        assert notify.marks(con, date(2026, 10, 20)).get(tid) is None           # 着手日の当日はまだ
        assert notify.marks(con, date(2026, 10, 21)).get(tid) == "着手日を過ぎた"
        sent = notify.check(con, datetime(2026, 10, 21, 9, 0))
        assert ("着手日を過ぎた", "卒論:原稿 は着手日を過ぎましたが、まだ手をつけていません") in sent
        assert not [m for m in notify.check(con, datetime(2026, 10, 21, 9, 1)) if m[0] == "着手日を過ぎた"]  # 1回だけ
        # 着手日から後に、その入れ物の記録があれば出さない(入れ物の単位。Q28)
        con.execute("INSERT INTO work_logs(container_id, started_at, ended_at) VALUES (?, '2026-10-20 13:00:00', '2026-10-20 14:00:00')", (cid,))
        assert notify.marks(con, date(2026, 10, 21)).get(tid) != "着手日を過ぎた"


def test_repeat_carries_start_date(db_path):
    db.init(db_path)
    with db.session(db_path) as con:
        import containers
        import tasks
        kid = con.execute("SELECT id FROM kinds WHERE name = '大学'").fetchone()[0]
        cid = containers.add_container(con, "情報工学演習", kid)
        tid = tasks.add(con, {"container_id": cid, "name": "課題", "due_date": "2026-10-27", "start_date": "2026-10-24", "repeat_weekday": 1})
        nxt = tasks.set_done(con, tid, True)
        n = tasks.get(con, nxt)
        assert (n["due_date"], n["start_date"]) == ("2026-11-03", "2026-10-31")


def test_mochi_can_set_start_date(client, db_path):
    import tasks
    cid = client.post("/api/containers", json={"name": "卒論", "kind_id": 3}).get_json()["id"]
    tid = client.post("/api/tasks", json={"container_id": cid, "name": "原稿", "due_date": "2026-11-30"}).get_json()["id"]

    def runner(system, prompt, env):
        client.post("/api/agent/tool", json={"run": env["DANDORI_RUN"], "token": env["DANDORI_TOKEN"], "tool": "task_update",
                                             "args": {"task_id": tid, "start_date": "2026-11-01"}})
        return "着手日をつけたよ"
    agent.ask(db_path, "原稿は11/1から始める", "トップ", "http://localhost", runner=runner, wait=True, app=client.application)
    with db.session(db_path) as con:
        assert tasks.get(con, tid)["start_date"] == "2026-11-01"
