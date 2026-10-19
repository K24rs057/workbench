"""モッチとのやりとり(基本設計 A34〜A37、S6-7・S7)。"""
from flask import jsonify

import agent
from api import body, bp, con
from containers import UserError


@bp.get("/agent/messages")
def agent_messages():
    with con() as c:
        return jsonify(agent.messages(c))


@bp.post("/agent/ask")
def agent_ask():
    b = body()
    with con() as c:
        try:
            agent.ask(c, b.get("text"), b.get("screen"))
        except agent.AgentError as e:
            raise UserError(str(e))
        return jsonify(agent.messages(c))


@bp.delete("/agent/messages")
def agent_clear():
    with con() as c:
        agent.clear(c)
        return jsonify([])


@bp.post("/agent/actions/<int:mid>/<what>")
def agent_action(mid, what):
    with con() as c:
        try:
            if what == "confirm":
                agent.confirm(c, mid)
            elif what == "cancel":
                agent.cancel(c, mid)
            else:
                raise UserError("その操作はありません")
        except agent.AgentError as e:
            raise UserError(str(e))
        return jsonify(agent.messages(c))


@bp.get("/mochi")
def mochi_get():
    with con() as c:
        return jsonify(settings=agent.get_settings(c), hint=agent.hint(c))


@bp.patch("/mochi")
def mochi_set():
    with con() as c:
        agent.set_settings(c, body())
        return jsonify(settings=agent.get_settings(c))
