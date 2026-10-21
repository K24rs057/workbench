"""作業記録と「確認してほしいこと」のやりとり(基本設計 A7〜A10・A26・A27、S6-4)。"""
import json
from datetime import datetime

from flask import jsonify

import containers
import mails
import tasks
import worklog
from api import body, bp, con
from containers import UserError


@bp.get("/work-logs/current")
def work_current():
    with con() as c:
        log = worklog.current(c)
        if not log:
            return jsonify(None)
        name = c.execute("SELECT name FROM containers WHERE id = ?", (log["container_id"],)).fetchone()["name"]
        return jsonify(container_id=log["container_id"], name=name, elapsed=worklog.elapsed_label(log))


@bp.get("/containers/<int:cid>/logs")
def work_list(cid):
    with con() as c:
        containers.get_row(c, cid)
        rows = c.execute("SELECT * FROM work_logs WHERE container_id = ? ORDER BY started_at DESC LIMIT 200", (cid,)).fetchall()
        return jsonify([dict(r) for r in rows])


def _log_fields(b, creating):
    out = {}
    for k in ("started_at", "ended_at"):
        if k in b or (creating and k == "started_at"):
            v = (b.get(k) or "").strip()
            if not v:
                if k == "started_at":
                    raise UserError("始まりの時刻を入れてください")
                out[k] = None
                continue
            try:
                out[k] = datetime.fromisoformat(v).isoformat(timespec="seconds")
            except ValueError:
                raise UserError("時刻の形がちがいます")
    if "note" in b:
        out["note"] = (b.get("note") or "").strip() or None
    return out


@bp.post("/work-logs")
def work_add():
    b = body()
    f = _log_fields(b, True)
    if not f.get("ended_at"):
        raise UserError("あとから足す記録には、終わりの時刻も入れてください")
    if f["ended_at"] <= f["started_at"]:
        raise UserError("終わりは始まりより後にしてください")
    with con() as c:
        containers.get_row(c, b.get("container_id"))
        new_id = c.execute(
            "INSERT INTO work_logs(container_id, started_at, ended_at, edited, note) VALUES (?, ?, ?, 1, ?)",
            (b["container_id"], f["started_at"], f["ended_at"], f.get("note")),
        ).lastrowid
        return jsonify(id=new_id), 201


@bp.patch("/work-logs/<int:lid>")
def work_update(lid):
    f = _log_fields(body(), False)
    with con() as c:
        row = c.execute("SELECT * FROM work_logs WHERE id = ?", (lid,)).fetchone()
        if not row:
            raise UserError("その記録はありません")
        s, e = f.get("started_at", row["started_at"]), f.get("ended_at", row["ended_at"])
        if e and e <= s:
            raise UserError("終わりは始まりより後にしてください")
        for k, v in f.items():
            c.execute(f"UPDATE work_logs SET {k} = ?, edited = 1 WHERE id = ?", (v, lid))
        return jsonify(ok=True)


@bp.delete("/work-logs/<int:lid>")
def work_delete(lid):
    with con() as c:
        c.execute("UPDATE commits SET work_log_id = NULL WHERE work_log_id = ?", (lid,))  # くっついていたコミットは点に戻す
        c.execute("DELETE FROM work_logs WHERE id = ?", (lid,))
        return jsonify(ok=True)


@bp.get("/containers/<int:cid>/commits")
def commits_list(cid):
    """git から入ったコミット(F7)。記録の画面で、作業記録と日付ごとに混ぜて出す。"""
    with con() as c:
        containers.get_row(c, cid)
        rows = c.execute("SELECT id, work_log_id, hash, message, committed_at FROM commits WHERE container_id = ? AND hidden = 0 "
                         "ORDER BY committed_at DESC LIMIT 300", (cid,)).fetchall()
        return jsonify([dict(r) for r in rows])


@bp.delete("/commits/<int:mid>")
def commits_delete(mid):
    """消したコミットは、次の取り込みで戻さない(S5-4)。"""
    with con() as c:
        c.execute("UPDATE commits SET hidden = 1 WHERE id = ?", (mid,))
        return jsonify(ok=True)


@bp.post("/done-questions/<int:qid>")
def done_answer(qid):
    b = body()
    with con() as c:
        if b.get("task_id"):
            tasks.set_done(c, int(b["task_id"]), True)
        c.execute("UPDATE done_questions SET answered = 1 WHERE id = ?", (qid,))
        return jsonify(ok=True)


@bp.get("/notices")
def notices_list():
    with con() as c:
        rows = c.execute("SELECT * FROM notices WHERE answered = 0 ORDER BY id DESC").fetchall()
        opts = c.execute(
            "SELECT c.id, c.name, k.name AS kind FROM containers c JOIN kinds k ON k.id = c.kind_id WHERE c.ended = 0 ORDER BY k.id, c.name"
        ).fetchall()
        out = []
        for r in rows:
            item = dict(r)
            if r["kind"] == "window":
                pw = c.execute("SELECT title FROM pending_windows WHERE id = ?", (r["pending_window_id"],)).fetchone()
                item["pattern"] = pw["title"].split("|", 1)[1] if pw else ""
            elif r["kind"] in ("候補日", "ブリーフの締切"):
                item["data"] = json.loads(r["body"])
            elif r["kind"] == "バイト先の質問":
                m = c.execute("SELECT sender FROM messages WHERE id = ?", (r["message_id"],)).fetchone()
                item["sender"] = m["sender"] if m else ""
            out.append(item)
        baito = [dict(b) for b in c.execute("SELECT id, name FROM baito_places ORDER BY name")]
        import winsort
        return jsonify(notices=out, options=[dict(o) for o in opts], baito=baito, ai=winsort.unseen(c))


@bp.post("/notices/<int:nid>/answer")
def notices_answer(nid):
    b = body()
    with con() as c:
        n = c.execute("SELECT * FROM notices WHERE id = ?", (nid,)).fetchone()
        if not n:
            raise UserError("その質問はもうありません")
        if n["kind"] == "バイト先の質問":
            mails.answer_baito(c, n, b.get("baito_id"), b.get("name"))
        elif n["kind"] == "候補日":
            mails.answer_candidate(c, n, b.get("index"), bool(b.get("none")))
        elif n["kind"] == "自動で完了":  # お知らせなので [わかった] で消すだけ。タスクは「自動で完了」の欄に残る
            c.execute("UPDATE notices SET answered = 1 WHERE id = ?", (nid,))
        elif n["kind"] == "ブリーフの締切":  # ブリーフが見つけた締切:入れ物を選んでタスクにする/いらない
            import brief
            try:
                brief.answer_finding(c, n, b.get("container_id"), bool(b.get("none")))
            except ValueError as e:
                raise UserError(str(e))
        else:
            try:
                worklog.answer_window(c, nid, b.get("container_id"), bool(b.get("ignore")), b.get("pattern"))
            except ValueError as e:
                raise UserError(str(e))
        return jsonify(ok=True)


@bp.get("/window-rules")
def rules_list():
    with con() as c:
        rows = c.execute(
            "SELECT r.*, c.name AS container FROM window_rules r LEFT JOIN containers c ON c.id = r.container_id ORDER BY r.app, r.pattern"
        ).fetchall()
        return jsonify([dict(r) for r in rows])


@bp.patch("/window-rules/<int:rid>")
def rules_update(rid):
    b = body()
    with con() as c:
        if "pattern" in b:
            if not (b["pattern"] or "").strip():
                raise UserError("覚える文字を入れてください")
            c.execute("UPDATE window_rules SET pattern = ? WHERE id = ?", (b["pattern"].strip(), rid))
        if b.get("ignore"):  # 選び直し(AI が仕分けた一覧・Q38)。直したら、もう Claude が決めたものではない
            c.execute("UPDATE window_rules SET ignore = 1, container_id = NULL, by_ai = 0 WHERE id = ?", (rid,))
        elif "container_id" in b:
            if not c.execute("SELECT 1 FROM containers WHERE id = ? AND ended = 0", (b["container_id"],)).fetchone():
                raise UserError("その授業・会社・開発はありません")
            c.execute("UPDATE window_rules SET ignore = 0, container_id = ?, by_ai = 0 WHERE id = ?", (int(b["container_id"]), rid))
        return jsonify(ok=True)


@bp.post("/window-rules/ai-seen")
def rules_ai_seen():
    """AI が仕分けた窓のお知らせを見た(Q38)。"""
    with con() as c:
        c.execute("UPDATE window_rules SET ai_seen = 1 WHERE by_ai = 1 AND ai_seen = 0")
        return jsonify(ok=True)


@bp.delete("/window-rules/<int:rid>")
def rules_delete(rid):
    with con() as c:
        c.execute("DELETE FROM window_rules WHERE id = ?", (rid,))
        return jsonify(ok=True)


@bp.get("/status")
def status_view():
    import autostart
    import status
    with con() as c:
        return jsonify(jobs=status.jobs(c), autostart=autostart.status())
