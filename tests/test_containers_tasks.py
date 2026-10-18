"""区切り2 入れ物とタスク(F1・F2・F6)。"""
from datetime import date


def kind_id(client, name):
    return next(k["id"] for k in client.get("/api/kinds").get_json() if k["name"] == name)


def make(client, name, kind="大学"):
    res = client.post("/api/containers", json={"name": name, "kind_id": kind_id(client, kind)})
    assert res.status_code == 201
    return res.get_json()["id"]


def add_task(client, cid, **kw):
    res = client.post("/api/tasks", json={"container_id": cid, **kw})
    assert res.status_code == 201, res.get_json()
    return res.get_json()["id"]


# ---------- 種類 ----------
def test_kinds_rules(client):
    res = client.post("/api/kinds", json={"name": "アルバイト", "color": "#77746e"})
    assert res.status_code == 400 and "灰色" in res.get_json()["error"]
    kid = client.post("/api/kinds", json={"name": "アルバイト", "color": "#aa3366"}).get_json()["id"]
    new = next(k for k in client.get("/api/kinds").get_json() if k["id"] == kid)
    assert (new["sort_first"], new["notify_untouched"]) == (0, 1)  # Q2
    assert client.delete(f"/api/kinds/{kind_id(client, '大学')}").status_code == 400  # 初めの3つは消せない
    make(client, "さくら食堂", "アルバイト")
    assert "中に" in client.delete(f"/api/kinds/{kid}").get_json()["error"]


# ---------- 入れ物 ----------
def test_container_end_restore_delete(client):
    cid = make(client, "情報工学演習")
    add_task(client, cid, name="第10回課題")
    assert "終了にする" in client.delete(f"/api/containers/{cid}").get_json()["error"]
    client.patch(f"/api/containers/{cid}", json={"ended": True})
    ov = client.get("/api/containers").get_json()
    assert [e["name"] for e in ov["ended"]] == ["情報工学演習"]
    assert all(i["name"] != "情報工学演習" for k in ov["kinds"] for i in k["items"])
    client.patch(f"/api/containers/{cid}", json={"ended": False})
    empty = make(client, "空っぽ")
    assert client.delete(f"/api/containers/{empty}").status_code == 200


def test_overview_order_and_columns(client):
    a = make(client, "データベース")
    b = make(client, "英語")
    c = make(client, "卒論")
    add_task(client, a, name="小テスト", due_date="2099-10-17")
    add_task(client, c, name="スライド", due_date="2099-10-11", due_time="9:00")
    add_task(client, c, name="第2章", due_date="2099-10-30")
    uni = next(k for k in client.get("/api/containers").get_json()["kinds"] if k["name"] == "大学")
    names = [i["name"] for i in uni["items"]]
    assert names == ["卒論", "データベース", "英語"]  # 締切の近い順、締切なしは最後
    sotsu = uni["items"][0]
    assert sotsu["next"]["name"] == "スライド" and sotsu["next"]["due_time"] == "09:00"
    assert sotsu["left"] == 2 and uni["items"][2]["next"] is None
    assert uni["items"][2]["progress"] is None  # タスクなし


def test_overdue_flag(client):
    cid = make(client, "情報工学演習")
    add_task(client, cid, name="第9回レポート", due_date="2000-01-01")
    item = next(i for k in client.get("/api/containers").get_json()["kinds"] for i in k["items"] if i["id"] == cid)
    assert item["next"]["overdue"] is True


# ---------- タスク ----------
def test_task_validation(client):
    cid = make(client, "卒論")
    assert client.post("/api/tasks", json={"container_id": cid, "name": " "}).status_code == 400
    r = client.post("/api/tasks", json={"container_id": cid, "name": "a", "due_time": "23:59"})
    assert "日付" in r.get_json()["error"]


def test_progress_and_done_toggle(client):
    cid = make(client, "情報工学演習")
    t1 = add_task(client, cid, name="第9回")
    add_task(client, cid, name="第10回")
    client.patch(f"/api/tasks/{t1}", json={"done": True})
    detail = client.get(f"/api/containers/{cid}").get_json()
    assert detail["progress"] == 50
    assert [t["name"] for t in detail["tasks"]] == ["第10回", "第9回"]  # 完了は下
    client.patch(f"/api/tasks/{t1}", json={"done": False})
    assert client.get(f"/api/containers/{cid}").get_json()["progress"] == 0


def test_weekly_repeat_makes_next_and_undo_removes_it(client):
    cid = make(client, "情報工学演習")
    t = add_task(client, cid, name="毎週の課題", due_date="2026-10-20", due_time="09:00", repeat_weekday=1)
    client.patch(f"/api/tasks/{t}", json={"done": True})
    names = [(x["name"], x["due_date"], x["done"]) for x in client.get(f"/api/containers/{cid}").get_json()["tasks"]]
    assert ("毎週の課題", "2026-10-27", False) in names
    client.patch(f"/api/tasks/{t}", json={"done": False})
    assert len(client.get(f"/api/containers/{cid}").get_json()["tasks"]) == 1


def test_open_target_uses_own_url_then_container_link(client, db_path):
    import db
    cid = make(client, "情報工学演習")
    t = add_task(client, cid, name="第10回課題")
    assert client.get(f"/api/containers/{cid}").get_json()["tasks"][0]["open_target"] is None
    with db.session(db_path) as con:
        con.execute("INSERT INTO links(container_id, name, target) VALUES (?, '学習サイト', 'https://example.ac.jp/course')", (cid,))
    task = client.get(f"/api/containers/{cid}").get_json()["tasks"][0]
    assert (task["open_target"], task["open_label"]) == ("https://example.ac.jp/course", "学習サイト")
    client.patch(f"/api/tasks/{t}", json={"open_url": "https://example.ac.jp/assign/10"})
    task = client.get(f"/api/containers/{cid}").get_json()["tasks"][0]
    assert task["open_target"] == "https://example.ac.jp/assign/10"


def test_unsorted_sorting(client):
    ov = client.get("/api/containers").get_json()
    t = add_task(client, ov["unsorted_id"], name="奨学金の書類")
    assert client.get("/api/containers").get_json()["unsorted"] == 1
    cid = make(client, "奨学金")
    client.patch(f"/api/tasks/{t}", json={"container_id": cid})
    assert client.get("/api/containers").get_json()["unsorted"] == 0
    assert client.get("/api/unsorted").get_json()["tasks"] == []


def test_week_hours(client, db_path):
    import db
    cid = make(client, "fx-practice", "開発")
    monday = date.today().toordinal() - date.today().weekday()
    d = date.fromordinal(monday).isoformat()
    with db.session(db_path) as con:
        con.execute("INSERT INTO work_logs(container_id, started_at, ended_at) VALUES (?, ?, ?)", (cid, f"{d}T09:00:00", f"{d}T10:30:00"))
        con.execute("INSERT INTO work_logs(container_id, started_at, ended_at) VALUES (?, '2000-01-01T09:00:00', '2000-01-01T10:00:00')", (cid,))
    item = client.get(f"/api/containers/{cid}").get_json()
    assert item["week_label"] == "1時間30分"
    assert item["total_label"] == "2時間30分"
