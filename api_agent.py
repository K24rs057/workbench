"""モッチとのやりとり(基本設計 A34〜A40、S6-7・S7)。"""
from flask import current_app, jsonify, request

import agent
from api import body, bp, con
from containers import UserError

BRIEF_URL = "https://claude.ai/artifact/Hx6bK1QtFiQmazq8S5XisU"  # モーニングブリーフ(朝のあいさつの最後にリンクを付ける)


def _path():
    return current_app.config.get("DB_PATH")


@bp.get("/agent/messages")
def agent_messages():
    with con() as c:
        return jsonify(agent.messages(c))


@bp.post("/agent/ask")
def agent_ask():
    """頼みを受け取って動かし始める。答えは /agent/messages を読み直して待つ(動いている間は手が積み上がる)。"""
    b = body()
    try:
        agent.ask(_path(), b.get("text"), b.get("screen"), request.host_url.rstrip("/"),
                  app=current_app._get_current_object())
    except agent.AgentError as e:
        raise UserError(str(e))
    with con() as c:
        return jsonify(agent.messages(c))


@bp.post("/agent/tool")
def agent_tool():
    """モッチの道具箱(agent_tools.py)からだけ呼ばれる。その頼みの合言葉がないものは断る。"""
    import agent_toolbox
    b = body()
    try:
        run_id = int(b.get("run"))
    except (TypeError, ValueError):
        return jsonify(error="頼みの番号がありません"), 403
    with con() as c:
        ok = agent.check_token(c, run_id, b.get("token"))
    if not ok:
        return jsonify(error="この頼みはもう終わっているか、合言葉がちがいます"), 403
    return jsonify(agent_toolbox.run_tool(run_id, b.get("tool"), b.get("args")))


@bp.delete("/agent/messages")
def agent_clear():
    with con() as c:
        agent.clear(c)
        return jsonify([])


@bp.post("/agent/actions/<int:aid>/<what>")
def agent_action(aid, what):
    """確認のカードの [する] [やめる](S7-5)。"""
    try:
        if what == "confirm":
            agent.confirm(_path(), aid)
        elif what == "cancel":
            agent.cancel(_path(), aid)
        else:
            raise UserError("その操作はありません")
    except agent.AgentError as e:
        raise UserError(str(e))
    with con() as c:
        return jsonify(agent.messages(c))


@bp.post("/agent/runs/<int:rid>/undo")
def agent_undo(rid):
    """その頼みでモッチがしたことを、まとめて元に戻す(S7-6・A39)。"""
    agent.undo(_path(), rid)
    with con() as c:
        return jsonify(agent.messages(c))


@bp.post("/agent/greeting")
def agent_greeting():
    """その日最初に吹き出しを開いたときの朝のあいさつ(S7-7)。もう話していれば何もしない。"""
    with con() as c:
        agent.greeting(c, brief_url=BRIEF_URL)
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
