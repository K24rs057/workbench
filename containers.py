"""種類と入れ物(要件 F1)、進み具合(F6)、一覧画面の中身(基本設計 S4)。

画面では「入れ物」とは呼ばず、「授業・会社・開発」や名前で呼ぶ(基本設計 Q30 の前の UI 試作の決定)。
"""
from datetime import date, datetime, timedelta

GRAY = "#77746e"  # 未分類だけの色


class UserError(ValueError):
    """画面にそのまま出せる理由つきの失敗。"""


# ---------- 種類 ----------
def list_kinds(con):
    rows = con.execute("SELECT * FROM kinds ORDER BY id").fetchall()
    out = []
    for r in rows:
        n = con.execute("SELECT COUNT(*) FROM containers WHERE kind_id = ?", (r["id"],)).fetchone()[0]
        out.append({**dict(r), "containers": n})
    return out


def add_kind(con, name, color):
    name = (name or "").strip()
    if not name:
        raise UserError("種類の名前を入れてください")
    if (color or "").lower() == GRAY:
        raise UserError("灰色は未分類だけの色なので選べません")
    cur = con.execute(
        "INSERT INTO kinds(name, color, sort_first, notify_untouched, builtin) VALUES (?, ?, 0, 1, 0)",
        (name, color or "#0a64d6"),
    )  # 新しい種類の初めの値:先に並べる=オフ、手つかずの通知=オン(Q2)
    return cur.lastrowid


def update_kind(con, kind_id, **fields):
    allowed = {"name", "color", "sort_first", "notify_untouched"}
    if fields.get("color", "").lower() == GRAY:
        raise UserError("灰色は未分類だけの色なので選べません")
    if "name" in fields and not str(fields["name"]).strip():
        raise UserError("種類の名前を入れてください")
    for k, v in fields.items():
        if k in allowed:
            con.execute(f"UPDATE kinds SET {k} = ? WHERE id = ?", (v, kind_id))


def delete_kind(con, kind_id):
    k = con.execute("SELECT * FROM kinds WHERE id = ?", (kind_id,)).fetchone()
    if not k:
        raise UserError("その種類はありません")
    if k["builtin"]:
        raise UserError("初めからある3つの種類は消せません(名前と色は変えられます)")
    if con.execute("SELECT COUNT(*) FROM containers WHERE kind_id = ?", (kind_id,)).fetchone()[0]:
        raise UserError("中に授業・会社・開発がある種類は消せません。先にほかの種類へ移してください")
    con.execute("DELETE FROM kinds WHERE id = ?", (kind_id,))


# ---------- 入れ物 ----------
def unsorted_id(con):
    return con.execute("SELECT id FROM containers WHERE is_unsorted = 1").fetchone()[0]


def add_container(con, name, kind_id):
    name = (name or "").strip()
    if not name:
        raise UserError("名前を入れてください")
    if not con.execute("SELECT 1 FROM kinds WHERE id = ?", (kind_id,)).fetchone():
        raise UserError("種類を選んでください")
    return con.execute("INSERT INTO containers(kind_id, name) VALUES (?, ?)", (kind_id, name)).lastrowid


def update_container(con, cid, **fields):
    c = get_row(con, cid)
    if c["is_unsorted"]:
        raise UserError("未分類は名前や種類を変えられません")
    if "name" in fields:
        if not str(fields["name"]).strip():
            raise UserError("名前を入れてください")
        con.execute("UPDATE containers SET name = ? WHERE id = ?", (fields["name"].strip(), cid))
    if "kind_id" in fields:
        if not con.execute("SELECT 1 FROM kinds WHERE id = ?", (fields["kind_id"],)).fetchone():
            raise UserError("その種類はありません")
        con.execute("UPDATE containers SET kind_id = ? WHERE id = ?", (fields["kind_id"], cid))
    if "ended" in fields:
        con.execute("UPDATE containers SET ended = ? WHERE id = ?", (1 if fields["ended"] else 0, cid))
    if "links_always_top" in fields:
        con.execute("UPDATE containers SET links_always_top = ? WHERE id = ?", (1 if fields["links_always_top"] else 0, cid))


def delete_container(con, cid):
    c = get_row(con, cid)
    if c["is_unsorted"]:
        raise UserError("未分類は消せません")
    used = sum(
        con.execute(f"SELECT COUNT(*) FROM {t} WHERE container_id = ?", (cid,)).fetchone()[0]
        for t in ("tasks", "work_logs", "links")
    )
    if used:
        raise UserError("中身(タスク・作業記録・リンク)があるので消せません。かわりに「終了にする」を使ってください")
    con.execute("DELETE FROM containers WHERE id = ?", (cid,))


def get_row(con, cid):
    c = con.execute("SELECT * FROM containers WHERE id = ?", (cid,)).fetchone()
    if not c:
        raise UserError("その授業・会社・開発はありません")
    return c


# ---------- 数える ----------
def progress(done, total):
    """完了 ÷ 全部。0件なら None(画面では「タスクなし」)。"""
    return None if total == 0 else round(done * 100 / total)


def week_start(today=None):
    today = today or date.today()
    return today - timedelta(days=today.weekday())  # 月曜はじまり(Claude の案)


def minutes_between(con, cid, since=None, now=None):
    now = now or datetime.now()
    sql = "SELECT started_at, ended_at FROM work_logs WHERE container_id = ?"
    total = 0
    for r in con.execute(sql, (cid,)):
        s = datetime.fromisoformat(r["started_at"])
        e = datetime.fromisoformat(r["ended_at"]) if r["ended_at"] else now
        if since:
            s = max(s, since)
        if e > s:
            total += (e - s).total_seconds() / 60
    return int(total)


def hours_label(minutes):
    h, m = divmod(minutes, 60)
    return f"{h}時間" if m == 0 else f"{h}時間{m}分"


def _due_key(t):
    return (t["due_date"], t["due_time"] or "99:99")


def summary(con, c, today=None):
    """一覧と中の画面で使う、1つの入れ物のまとめ。"""
    today = today or date.today()
    tasks = con.execute("SELECT * FROM tasks WHERE container_id = ?", (c["id"],)).fetchall()
    open_tasks = [t for t in tasks if not t["done"]]
    dated = sorted((t for t in open_tasks if t["due_date"]), key=_due_key)
    nxt = None
    if dated:
        t = dated[0]
        nxt = {"id": t["id"], "name": t["name"], "due_date": t["due_date"], "due_time": t["due_time"],
               "overdue": t["due_date"] < today.isoformat()}
    since = datetime.combine(week_start(today), datetime.min.time())
    week = minutes_between(con, c["id"], since)
    total = minutes_between(con, c["id"])
    done = len(tasks) - len(open_tasks)
    return {
        "id": c["id"], "name": c["name"], "kind_id": c["kind_id"], "is_unsorted": bool(c["is_unsorted"]),
        "ended": bool(c["ended"]), "links_always_top": bool(c["links_always_top"]),
        "next": nxt, "left": len(open_tasks), "done": done, "total": len(tasks),
        "progress": progress(done, len(tasks)),
        "week_minutes": week, "week_label": hours_label(week),
        "total_minutes": total, "total_label": hours_label(total),
    }


def overview(con, today=None):
    """「授業・会社・開発」の画面(S4)。種類ごとに、締切の近い順 → 締切なしは名前順。"""
    today = today or date.today()
    kinds = list_kinds(con)
    rows = con.execute("SELECT * FROM containers WHERE is_unsorted = 0").fetchall()
    out = []
    for k in kinds:
        items = [summary(con, c, today) for c in rows if c["kind_id"] == k["id"] and not c["ended"]]
        with_due = sorted((i for i in items if i["next"]), key=lambda i: (i["next"]["due_date"], i["next"]["due_time"] or "99:99"))
        no_due = sorted((i for i in items if not i["next"]), key=lambda i: i["name"])
        kind_done = sum(i["done"] for i in items)
        kind_total = sum(i["total"] for i in items)
        out.append({**k, "items": with_due + no_due, "progress": progress(kind_done, kind_total)})
    ended = [summary(con, c, today) for c in rows if c["ended"]]
    uid = unsorted_id(con)
    unsorted_left = con.execute("SELECT COUNT(*) FROM tasks WHERE container_id = ? AND done = 0", (uid,)).fetchone()[0]
    return {"kinds": out, "ended": sorted(ended, key=lambda i: i["name"]), "unsorted": unsorted_left, "unsorted_id": uid}


def overall(con):
    """全体の進み具合。終了していない入れ物のタスクと未分類を数える(F6)。"""
    r = con.execute(
        "SELECT COUNT(*) AS total, COALESCE(SUM(t.done), 0) AS done FROM tasks t JOIN containers c ON c.id = t.container_id WHERE c.ended = 0"
    ).fetchone()
    return progress(r["done"], r["total"])
