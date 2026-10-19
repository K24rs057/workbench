"""通知(要件 F8、基本設計 Q5・Q24・Q28)。

1分ごとに確かめ、当てはまれば Windows の通知を1回だけ出す。
- 締切の前日(明日が締切の未完了のタスク)
- 手つかず:締切のあるタスクは、締切の3日前になっても、その入れ物に作業記録がない
            締切のないタスクは、登録から3日たっても、その入れ物に作業記録がない(「手つかずの通知」がオフの種類は出さない)
- 着手日を過ぎた:着手日の翌日になっても、着手日から後にその入れ物に作業記録がない(F16・Q28)
本体が止まっていて出せなかった前日の通知は、次に画面を開いたときにまとめて見せる。
出したかどうかは settings に "notified:種類:タスク" で残す。
"""
import json
import os
import subprocess
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

UNTOUCHED_DAYS = 3  # Claude の案(要件 F8)
SCRIPT = Path(__file__).resolve().parent / "notify.ps1"


def show(title, message):
    """Windows の通知を出す(待たない)。テストでは DANDORI_NO_TOAST=1 で止める。"""
    if os.environ.get("DANDORI_NO_TOAST"):
        return
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"title": title, "message": message}, f, ensure_ascii=False)
    subprocess.Popen(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT), "-File", path],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def _sent(con, key):
    return con.execute("SELECT 1 FROM settings WHERE key = ?", (f"notified:{key}",)).fetchone() is not None


def _mark(con, key, now):
    con.execute("INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)", (f"notified:{key}", now.isoformat(timespec="seconds")))


def _touched_since(con, cid, since):
    return con.execute("SELECT 1 FROM work_logs WHERE container_id = ? AND started_at >= ? LIMIT 1", (cid, since)).fetchone() is not None


def marks(con, today=None):
    """画面のタスクの行につける印(Q5):{task_id: '明日まで' | '着手日を過ぎた' | '手つかず'}。"""
    today = today or date.today()
    out = {}
    rows = con.execute(
        """SELECT t.*, k.notify_untouched FROM tasks t JOIN containers c ON c.id = t.container_id
           LEFT JOIN kinds k ON k.id = c.kind_id WHERE t.done = 0 AND c.ended = 0"""
    ).fetchall()
    for t in rows:
        if t["due_date"] == (today + timedelta(days=1)).isoformat():
            out[t["id"]] = "明日まで"
        elif _start_missed(con, t, today):
            out[t["id"]] = "着手日を過ぎた"
        elif _untouched(con, t, today):
            out[t["id"]] = "手つかず"
    return out


def _untouched(con, t, today):
    created = t["created_at"][:10]
    if t["due_date"]:
        due = date.fromisoformat(t["due_date"])
        if not (today <= due <= today + timedelta(days=UNTOUCHED_DAYS)):
            return False
    else:
        if t["notify_untouched"] == 0:
            return False
        if date.fromisoformat(created) + timedelta(days=UNTOUCHED_DAYS) > today:
            return False
    return not _touched_since(con, t["container_id"], created)


def _start_missed(con, t, today):
    """着手日の翌日までに、その入れ物に自動の作業記録が1つもない(F16・Q28。入れ物の単位で見る)。"""
    if not t["start_date"]:
        return False
    if date.fromisoformat(t["start_date"]) + timedelta(days=1) > today:
        return False
    return not _touched_since(con, t["container_id"], t["start_date"])


def check(con, now=None):
    """1分ごとに呼ぶ。出した通知の (題, 中身) の一覧を返す。"""
    now = now or datetime.now()
    today = now.date()
    sent = []
    rows = con.execute(
        """SELECT t.*, c.name AS c_name, k.notify_untouched FROM tasks t JOIN containers c ON c.id = t.container_id
           LEFT JOIN kinds k ON k.id = c.kind_id WHERE t.done = 0 AND c.ended = 0"""
    ).fetchall()
    for t in rows:
        label = f"{t['c_name']}:{t['name']}"
        if t["due_date"]:
            due = date.fromisoformat(t["due_date"])
            key = f"eve:{t['id']}:{t['due_date']}"
            if due == today + timedelta(days=1) and not _sent(con, key):
                msg = ("明日まで", f"{label}" + (f"(締切 {t['due_time']})" if t["due_time"] else ""))
                show(*msg); sent.append(msg); _mark(con, key, now)
            elif due <= today and not _sent(con, key) and t["created_at"][:10] < (due - timedelta(days=1)).isoformat():
                # 前日の通知を出すはずだったのに、本体が止まっていた
                con.execute("INSERT INTO pending_pc_notices(text, due_at) VALUES (?, ?)", (f"明日まで(前日の通知):{label}", (due - timedelta(days=1)).isoformat()))
                _mark(con, key, now)
        key = f"start:{t['id']}:{t['start_date']}"
        if t["start_date"] and not _sent(con, key) and _start_missed(con, t, today):
            msg = ("着手日を過ぎた", f"{label} は着手日を過ぎましたが、まだ手をつけていません")
            show(*msg); sent.append(msg); _mark(con, key, now)
        key = f"untouched:{t['id']}"
        if not _sent(con, key) and _untouched(con, t, today):
            msg = ("手つかず", f"{label} にまだ手をつけていません")
            show(*msg); sent.append(msg); _mark(con, key, now)
    con.execute(
        "INSERT INTO job_status(job, last_run_at, last_error) VALUES ('通知', ?, NULL) "
        "ON CONFLICT(job) DO UPDATE SET last_run_at = excluded.last_run_at, last_error = NULL",
        (now.isoformat(timespec="seconds"),),
    )
    return sent


def take_pending(con):
    """電源が切れていた間の通知を読み、見せたら消す。"""
    rows = [r["text"] for r in con.execute("SELECT text FROM pending_pc_notices ORDER BY due_at")]
    con.execute("DELETE FROM pending_pc_notices")
    return rows
