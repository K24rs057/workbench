"""連絡の画面(基本設計 S3、API A6・A22〜A25)。"""
import json

from flask import jsonify, request

import autodone
import containers
import gmail
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
        new += autodone.unseen(c)  # 自動で完了のお知らせも青い点に数える(Q14)
        if request.args.get("open"):
            c.execute("UPDATE messages SET seen = 1 WHERE seen = 0")
            autodone.mark_seen(c)
        asks = c.execute("SELECT COUNT(*) FROM notices WHERE answered = 0").fetchone()[0]
        auto = len(autodone.archive(c, limit=99))
        err = " / ".join(e for e in (mails.setting(c, "outlook_error"), mails.setting(c, "gmail_error")) if e) or None
        return jsonify(new=new, asks=asks, auto=auto, error=err)


# ---------- モーニングブリーフとの連携(F22 1.07・モッチ-5 A) ----------
@bp.get("/brief")
def brief_get():
    """ブリーフの夜の PC の回が読む:対象日の段取りと、段取りさんの様子。"""
    import brief
    from datetime import date, datetime
    day = request.args.get("date")
    since = request.args.get("since")
    try:
        d = date.fromisoformat(day) if day else None
        s = datetime.fromisoformat(since) if since else None
    except ValueError:
        raise UserError("日付の形がちがいます")
    with con() as c:
        return jsonify(summary=brief.summary(c, d), health=brief.health(c, s))


@bp.post("/brief/findings")
def brief_findings():
    """ブリーフが見つけた締切を「確認してほしいこと」に入れる。"""
    import brief
    items = body().get("items") or []
    if not isinstance(items, list):
        raise UserError("items は一覧で送ってください")
    with con() as c:
        return jsonify(added=brief.add_findings(c, items))


# ---------- 自動で完了(F18、S3-5・S1-4a、A28) ----------
@bp.get("/auto-done")
def auto_done_list():
    with con() as c:
        rows = autodone.archive(c, limit=50, before=request.args.get("before"))
        return jsonify(items=rows[:50], more=len(rows) > 50)


@bp.post("/auto-done/<int:tid>/undo")
def auto_done_undo(tid):
    with con() as c:
        if not autodone.undo(c, tid):
            raise UserError("このタスクは、自動で完了にしたものではありません")
        return jsonify(ok=True)


@bp.get("/maybe-done")
def maybe_done_list():
    with con() as c:
        return jsonify(autodone.maybe_list(c))


@bp.post("/maybe-done/<int:mid>")
def maybe_done_answer(mid):
    with con() as c:
        autodone.answer_maybe(c, mid, bool(body().get("done")))
        return jsonify(ok=True)


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
        import shift
        return jsonify(university_domain=mails.setting(c, "university_domain") or "", shift_name=shift.name(c),
                       google={"state": gmail.state(), "calendar": gmail.calendar_allowed()}, gmail_error=mails.setting(c, "gmail_error"))


@bp.patch("/settings/mail")
def mail_settings_set():
    b = body()
    with con() as c:
        if "shift_name" in b:  # シフト表での自分の名前(F14)。PC の中にだけ置く
            import shift
            shift.set_name(c, b["shift_name"])
        if "university_domain" in b:
            d = (b.get("university_domain") or "").strip().lower().lstrip("@")
            if d and "." not in d:
                raise UserError("「example.ac.jp」のように、@ から後ろを入れてください")
            mails.set_setting(c, "university_domain", d)
        return jsonify(ok=True)


@bp.delete("/held-events/<int:hid>")
def held_delete(hid):
    with con() as c:
        mails.delete_held(c, hid)
        return jsonify(ok=True)


# ---------- バイト先(F20・Q21、S6-2) ----------
def _baito_fields(b):
    out = {}
    if "name" in b:
        nm = (b.get("name") or "").strip()
        if not nm:
            raise UserError("バイト先の名前を入れてください")
        out["name"] = nm
    if "domain" in b:
        d = (b.get("domain") or "").strip().lower().lstrip("@") or None
        if d and "." not in d:
            raise UserError("「example.co.jp」のように、@ から後ろを入れてください")
        out["domain"] = d
    return out


@bp.get("/baito")
def baito_list():
    with con() as c:
        out = []
        for b in c.execute("SELECT * FROM baito_places ORDER BY name"):
            adds = [a["address"] for a in c.execute("SELECT address FROM baito_addresses WHERE baito_id = ?", (b["id"],))]
            out.append({**dict(b), "addresses": adds})
        return jsonify(out)


@bp.post("/baito")
def baito_add():
    f = _baito_fields({"name": "", "domain": None, **body()})
    with con() as c:
        bid = c.execute("INSERT INTO baito_places(name, domain) VALUES (?, ?)", (f["name"], f["domain"])).lastrowid
        return jsonify(id=bid)


@bp.patch("/baito/<int:bid>")
def baito_update(bid):
    f = _baito_fields(body())
    with con() as c:
        for k, v in f.items():
            c.execute(f"UPDATE baito_places SET {k} = ? WHERE id = ?", (v, bid))
        return jsonify(ok=True)


@bp.delete("/baito/<int:bid>")
def baito_delete(bid):
    """消すと、覚えた中継アドレスも忘れる。取り込んだメールは残し、バイト先の名前だけ外す。"""
    with con() as c:
        c.execute("DELETE FROM baito_addresses WHERE baito_id = ?", (bid,))
        c.execute("UPDATE messages SET baito_id = NULL WHERE baito_id = ?", (bid,))
        c.execute("DELETE FROM baito_places WHERE id = ?", (bid,))
        return jsonify(ok=True)
