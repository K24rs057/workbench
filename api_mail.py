"""連絡の画面(基本設計 S3、API A6・A22〜A25)。"""
import json

from flask import jsonify, request

import containers
import mails
from api import body, bp, con
from containers import UserError

HIDDEN = ("Forms", "提出受付")  # 自動で完了の合図。一覧には出さない


def _row(c, m):
    cname = None
    if m["container_id"]:
        r = c.execute("SELECT name FROM containers WHERE id = ?", (m["container_id"],)).fetchone()
        cname = r["name"] if r else None
    return {"id": m["id"], "source": m["source"], "category": m["category"], "container_id": m["container_id"], "container": cname,
            "subject": m["subject"], "sender": m["sender"], "received_at": m["received_at"], "seen": bool(m["seen"]),
            "ai_failed": bool(m["ai_failed"])}


@bp.get("/messages/summary")
def messages_summary():
    """連絡の3つの欄の件数。開いたら全部「見た」にする(メールの既読にはさわらない)。"""
    with con() as c:
        new = c.execute(f"SELECT COUNT(*) FROM messages WHERE seen = 0 AND category NOT IN {HIDDEN}").fetchone()[0]
        if request.args.get("open"):
            c.execute("UPDATE messages SET seen = 1 WHERE seen = 0")
        asks = c.execute("SELECT COUNT(*) FROM notices WHERE answered = 0").fetchone()[0]
        err = mails.setting(c, "outlook_error")
        return jsonify(new=new, asks=asks, error=err)


@bp.get("/messages")
def messages_list():
    with con() as c:
        rows = c.execute(f"SELECT * FROM messages WHERE category NOT IN {HIDDEN} ORDER BY received_at DESC LIMIT 300").fetchall()
        main = [_row(c, m) for m in rows if m["category"] != "その他"]
        other = [_row(c, m) for m in rows if m["category"] == "その他"]
        return jsonify(main=main, other=other)


@bp.get("/messages/<int:mid>")
def messages_get(mid):
    with con() as c:
        m = c.execute("SELECT * FROM messages WHERE id = ?", (mid,)).fetchone()
        if not m:
            raise UserError("その連絡はありません")
        ts = [dict(t) for t in c.execute("SELECT id, name, due_date, due_time, done FROM tasks WHERE from_message_id = ?", (mid,))]
        hs = [dict(h) for h in c.execute("SELECT id, title, start_at FROM held_events WHERE from_message_id = ?", (mid,))]
        blocked = c.execute("SELECT 1 FROM blocked_senders WHERE address = ?", (m["sender"],)).fetchone() is not None
        return jsonify(**_row(c, m), body=m["body"], body_gone=m["body"] is None, links=json.loads(m["links"] or "[]"),
                       tasks=ts, held=hs, blocked=blocked)


@bp.patch("/messages/<int:mid>")
def messages_resort(mid):
    """振り分けを直す。次から同じ差出人のメールは直したほうに入れる(F9・F11)。このメールから入ったタスクも移す。"""
    b = body()
    with con() as c:
        m = c.execute("SELECT * FROM messages WHERE id = ?", (mid,)).fetchone()
        if not m:
            raise UserError("その連絡はありません")
        cid = b.get("container_id")
        if cid:
            containers.get_row(c, cid)
            c.execute("UPDATE messages SET container_id = ?, category = CASE WHEN category = 'その他' THEN '授業' ELSE category END WHERE id = ?", (cid, mid))
            c.execute("DELETE FROM sort_rules WHERE sender = ?", (m["sender"],))
            c.execute("INSERT INTO sort_rules(sender, subject, container_id) VALUES (?, NULL, ?)", (m["sender"], cid))
            c.execute("UPDATE tasks SET container_id = ? WHERE from_message_id = ?", (cid, mid))
        else:
            c.execute("UPDATE messages SET container_id = NULL, category = 'その他' WHERE id = ?", (mid,))
            c.execute("DELETE FROM sort_rules WHERE sender = ?", (m["sender"],))
            c.execute("UPDATE tasks SET container_id = ? WHERE from_message_id = ?", (containers.unsorted_id(c), mid))
        return jsonify(ok=True)


@bp.get("/blocked-senders")
def blocked_list():
    with con() as c:
        return jsonify([dict(r) for r in c.execute("SELECT * FROM blocked_senders ORDER BY created_at DESC")])


@bp.post("/blocked-senders")
def blocked_add():
    addr = (body().get("address") or "").strip().lower()
    if "@" not in addr:
        raise UserError("差出人のアドレスがありません")
    with con() as c:
        c.execute("INSERT OR IGNORE INTO blocked_senders(address) VALUES (?)", (addr,))
        return jsonify(ok=True)


@bp.delete("/blocked-senders/<int:bid>")
def blocked_delete(bid):
    with con() as c:
        c.execute("DELETE FROM blocked_senders WHERE id = ?", (bid,))
        return jsonify(ok=True)


@bp.post("/tasks/<int:tid>/ai-checked")
def task_ai_checked(tid):
    with con() as c:
        c.execute("UPDATE tasks SET ai_checked = 1 WHERE id = ?", (tid,))
        return jsonify(ok=True)


@bp.get("/tasks/<int:tid>/ai")
def task_ai(tid):
    """「AI」の札の小窓(S1-13):もとのメールの件名と、Claude が読み取った部分。"""
    with con() as c:
        t = c.execute("SELECT * FROM tasks WHERE id = ?", (tid,)).fetchone()
        if not t:
            raise UserError("そのタスクはありません")
        m = c.execute("SELECT subject FROM messages WHERE id = ?", (t["from_message_id"],)).fetchone() if t["from_message_id"] else None
        return jsonify(subject=m["subject"] if m else None, excerpt=t["ai_excerpt"], message_id=t["from_message_id"])


@bp.get("/settings/mail")
def mail_settings():
    with con() as c:
        return jsonify(university_domain=mails.setting(c, "university_domain") or "")


@bp.patch("/settings/mail")
def mail_settings_set():
    d = (body().get("university_domain") or "").strip().lower().lstrip("@")
    if d and "." not in d:
        raise UserError("「example.ac.jp」のように、@ から後ろを入れてください")
    with con() as c:
        mails.set_setting(c, "university_domain", d)
        return jsonify(ok=True)
