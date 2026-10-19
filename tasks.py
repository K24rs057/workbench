"""タスク(要件 F2)。

締切は日付が必須で時刻は任意。毎週の繰り返しは、1つ完了すると次の週の分を出す。
着手日(F16)はつけてもつけなくてもよい。着手日になると、トップの「今日」に上がる。
タスクの名前を押したときに開くページは、自分で入れたもの → 入れ物のリンクの順に使う(基本設計 Q33)。
メールのリンクは作る順番②でここに足す。
"""
import re
from datetime import date, datetime, timedelta

from containers import UserError, get_row

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")


def _clean(fields, creating):
    out = {}
    if "name" in fields or creating:
        name = (fields.get("name") or "").strip()
        if not name:
            raise UserError("タスクの名前を入れてください")
        out["name"] = name
    if "due_date" in fields:
        d = fields["due_date"] or None
        if d and not DATE_RE.match(d):
            raise UserError("締切の日付の形がちがいます")
        out["due_date"] = d
    if "due_time" in fields:
        t = fields["due_time"] or None
        if t and not TIME_RE.match(t):
            raise UserError("締切の時刻は 23:59 のように入れてください")
        if t:
            h, m = t.split(":")
            t = f"{int(h):02d}:{m}"
        out["due_time"] = t
    if "start_date" in fields:
        d = fields["start_date"] or None
        if d and not DATE_RE.match(d):
            raise UserError("着手日の日付の形がちがいます")
        out["start_date"] = d
    if "repeat_weekday" in fields:
        w = fields["repeat_weekday"]
        out["repeat_weekday"] = None if w in (None, "") else int(w)
    if "open_url" in fields:
        out["open_url"] = (fields["open_url"] or "").strip() or None
    if "container_id" in fields:
        out["container_id"] = int(fields["container_id"])
    return out


def _check_due(row):
    if row.get("due_time") and not row.get("due_date"):
        raise UserError("時刻をつけるときは、締切の日付も入れてください")
    if row.get("repeat_weekday") is not None and not row.get("due_date"):
        raise UserError("毎週の繰り返しには、最初の締切の日付が要ります")
    if row.get("start_date") and row.get("due_date") and row["start_date"] > row["due_date"]:
        raise UserError("着手日は、締切の日より前にしてください")


def add(con, fields):
    row = _clean(fields, creating=True)
    if "container_id" not in row:
        raise UserError("どの授業・会社・開発のタスクかを選んでください")
    get_row(con, row["container_id"])
    _check_due(row)
    cols = ", ".join(row)
    q = ", ".join("?" * len(row))
    return con.execute(f"INSERT INTO tasks({cols}) VALUES ({q})", tuple(row.values())).lastrowid


def get(con, tid):
    t = con.execute("SELECT * FROM tasks WHERE id = ?", (tid,)).fetchone()
    if not t:
        raise UserError("そのタスクはありません")
    return t


def update(con, tid, fields):
    t = dict(get(con, tid))
    row = _clean(fields, creating=False)
    if "container_id" in row:
        get_row(con, row["container_id"])
    merged = {**t, **row}
    _check_due(merged)
    for k, v in row.items():
        con.execute(f"UPDATE tasks SET {k} = ? WHERE id = ?", (v, tid))
    if "done" in fields:
        set_done(con, tid, bool(fields["done"]))


def set_done(con, tid, done, now=None):
    """完了にする/外す。繰り返しなら次の週の分を出し、外したら(まだ手つかずの)次の回を消す。"""
    t = get(con, tid)
    if bool(t["done"]) == done:
        return None
    now = now or datetime.now()
    nxt_id = None
    if done:
        con.execute("UPDATE tasks SET done = 1, done_at = ? WHERE id = ?", (now.isoformat(timespec="seconds"), tid))
        if t["repeat_weekday"] is not None and t["due_date"]:
            nd = (date.fromisoformat(t["due_date"]) + timedelta(days=7)).isoformat()
            # 着手日があれば、次の回も同じだけ前にずらしてつける
            ns = (date.fromisoformat(t["start_date"]) + timedelta(days=7)).isoformat() if t["start_date"] else None
            nxt_id = con.execute(
                "INSERT INTO tasks(container_id, name, due_date, due_time, start_date, repeat_weekday, repeat_from_task_id, open_url) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (t["container_id"], t["name"], nd, t["due_time"], ns, t["repeat_weekday"], tid, t["open_url"]),
            ).lastrowid
    else:
        con.execute("UPDATE tasks SET done = 0, done_at = NULL, auto_done_by = NULL WHERE id = ?", (tid,))
        con.execute("DELETE FROM tasks WHERE repeat_from_task_id = ? AND done = 0", (tid,))
    return nxt_id


def delete(con, tid):
    t = get(con, tid)
    if t["from_message_id"]:  # メールから自動で入ったものは、次に読んでも戻さない(F9)
        m = con.execute("SELECT external_id FROM messages WHERE id = ?", (t["from_message_id"],)).fetchone()
        if m:
            con.execute("INSERT INTO deleted_items(external_id, what) VALUES (?, 'タスク')", (m["external_id"],))
    con.execute("UPDATE tasks SET repeat_from_task_id = NULL WHERE repeat_from_task_id = ?", (tid,))
    con.execute("DELETE FROM tasks WHERE id = ?", (tid,))


def open_target(con, t):
    """名前を押したときに開く先と、その行き先の短い名前。なければ (None, None)。"""
    if t["open_url"]:
        return t["open_url"], _label(t["open_url"])
    link = con.execute("SELECT name, target FROM links WHERE container_id = ? ORDER BY id LIMIT 1", (t["container_id"],)).fetchone()
    if link:
        return link["target"], link["name"]
    return None, None


def _label(url):
    m = re.match(r"https?://([^/]+)", url)
    return m.group(1) if m else "開く"


def to_json(con, t):
    target, label = open_target(con, t)
    return {
        "id": t["id"], "container_id": t["container_id"], "name": t["name"],
        "due_date": t["due_date"], "due_time": t["due_time"], "start_date": t["start_date"], "repeat_weekday": t["repeat_weekday"],
        "done": bool(t["done"]), "open_url": t["open_url"], "open_target": target, "open_label": label,
        "ai": bool(t["ai_read"] and not t["ai_checked"]), "created_at": t["created_at"],
        "from_mail": bool(t["from_message_id"]),
    }


def list_for(con, cid):
    """入れ物の中のタスク(S5-3):未完了を締切順に、完了したものはその下に。"""
    rows = con.execute("SELECT * FROM tasks WHERE container_id = ?", (cid,)).fetchall()
    def key(t):
        return (t["done"], t["due_date"] is None, t["due_date"] or "", t["due_time"] or "99:99", t["created_at"])
    return [to_json(con, t) for t in sorted(rows, key=key)]
