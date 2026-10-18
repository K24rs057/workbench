"""画面とのやりとり(基本設計 4 API一覧)。区切りごとに足していく。"""
from flask import Blueprint, current_app, jsonify, request

import containers
import db
import tasks
from containers import UserError

bp = Blueprint("api", __name__, url_prefix="/api")


def con():
    return db.session(current_app.config.get("DB_PATH"))


def body():
    return request.get_json(silent=True) or {}


@bp.errorhandler(UserError)
def user_error(e):
    return jsonify(error=str(e)), 400


# ---------- 種類(A30 の一部) ----------
@bp.get("/kinds")
def kinds_list():
    with con() as c:
        return jsonify(containers.list_kinds(c))


@bp.post("/kinds")
def kinds_add():
    b = body()
    with con() as c:
        return jsonify(id=containers.add_kind(c, b.get("name"), b.get("color"))), 201


@bp.patch("/kinds/<int:kid>")
def kinds_update(kid):
    with con() as c:
        containers.update_kind(c, kid, **body())
        return jsonify(ok=True)


@bp.delete("/kinds/<int:kid>")
def kinds_delete(kid):
    with con() as c:
        containers.delete_kind(c, kid)
        return jsonify(ok=True)


# ---------- 入れ物(A12〜A14) ----------
@bp.get("/containers")
def containers_overview():
    with con() as c:
        return jsonify(containers.overview(c))


@bp.post("/containers")
def containers_add():
    b = body()
    with con() as c:
        return jsonify(id=containers.add_container(c, b.get("name"), b.get("kind_id"))), 201


@bp.get("/containers/<int:cid>")
def containers_get(cid):
    with con() as c:
        row = containers.get_row(c, cid)
        kind = c.execute("SELECT * FROM kinds WHERE id = ?", (row["kind_id"],)).fetchone() if row["kind_id"] else None
        return jsonify(
            **containers.summary(c, row),
            kind=dict(kind) if kind else None,
            tasks=tasks.list_for(c, cid),
            deletable=not any(
                c.execute(f"SELECT 1 FROM {t} WHERE container_id = ? LIMIT 1", (cid,)).fetchone()
                for t in ("tasks", "work_logs", "links")
            ),
        )


@bp.patch("/containers/<int:cid>")
def containers_update(cid):
    with con() as c:
        containers.update_container(c, cid, **body())
        return jsonify(ok=True)


@bp.delete("/containers/<int:cid>")
def containers_delete(cid):
    with con() as c:
        containers.delete_container(c, cid)
        return jsonify(ok=True)


# ---------- タスク(A3〜A5) ----------
@bp.post("/tasks")
def tasks_add():
    with con() as c:
        return jsonify(id=tasks.add(c, body())), 201


@bp.patch("/tasks/<int:tid>")
def tasks_update(tid):
    with con() as c:
        tasks.update(c, tid, body())
        return jsonify(tasks.to_json(c, tasks.get(c, tid)))


@bp.delete("/tasks/<int:tid>")
def tasks_delete(tid):
    with con() as c:
        tasks.delete(c, tid)
        return jsonify(ok=True)


@bp.get("/unsorted")
def unsorted_list():
    """未分類の仕分けの一覧(S4-2a)。"""
    with con() as c:
        uid = containers.unsorted_id(c)
        rows = c.execute("SELECT * FROM tasks WHERE container_id = ? AND done = 0 ORDER BY created_at", (uid,)).fetchall()
        opts = c.execute(
            "SELECT c.id, c.name, k.name AS kind FROM containers c JOIN kinds k ON k.id = c.kind_id WHERE c.ended = 0 ORDER BY k.id, c.name"
        ).fetchall()
        return jsonify(tasks=[tasks.to_json(c, t) for t in rows], options=[dict(o) for o in opts])
