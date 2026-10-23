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


# ---------- モッチが開けるサイト(設定の「サイト」。規程 第6条・第11条) ----------
@bp.get("/sites")
def sites_list():
    import sitebrowser
    with con() as c:
        uid, pw = sitebrowser.credentials()
        import kslife
        return jsonify(sites=sitebrowser.sites(c), kslife_env=bool(uid and pw), kslife_last=kslife.last(c))  # パスワードそのものは返さない


@bp.post("/sites")
def sites_add():
    import sitebrowser
    b = body()
    with con() as c:
        try:
            sitebrowser.add_site(c, b.get("name"), b.get("url"), b.get("login") or "manual", b.get("login_host"))
        except sitebrowser.SiteError as e:
            raise UserError(str(e))
        return jsonify(sites=sitebrowser.sites(c))


@bp.patch("/sites/<path:name>")
def sites_update(name):
    """K'sLife の課題のページ(F23・S6-8)。"""
    import kslife
    import sitebrowser
    b = body()
    with con() as c:
        try:
            kslife.set_tasks_url(c, name, b.get("tasks_url"))
        except sitebrowser.SiteError as e:
            raise UserError(str(e))
        return jsonify(sites=sitebrowser.sites(c))


@bp.delete("/sites/<path:name>")
def sites_remove(name):
    import sitebrowser
    with con() as c:
        sitebrowser.remove_site(c, name)
        return jsonify(sites=sitebrowser.sites(c))


@bp.post("/sites/window")
def sites_window():
    """[専用の窓で開く]。本人が手でログインするため。"""
    import sitebrowser
    name = body().get("name")
    with con() as c:
        site = next((s for s in sitebrowser.sites(c) if s["name"] == name), None)
    if not site:
        raise UserError("そのサイトは登録されていません")
    try:
        sitebrowser.browser().show_window(site)
    except sitebrowser.SiteError as e:
        raise UserError(str(e))
    return jsonify(ok=True)


# ---------- モッチが探せるフォルダ(設定の「フォルダ」。規程第12条・S6-9) ----------
@bp.get("/folders")
def folders_list():
    import localfiles
    with con() as c:
        return jsonify(folders=localfiles.folders(c))


@bp.post("/folders/pick")
def folders_pick():
    """[フォルダを選んで足す…]。Windows の「フォルダーの選択」の窓を出し、選んだフォルダを足す。"""
    import localfiles
    path = localfiles.pick_folder()
    with con() as c:
        if not path:
            return jsonify(folders=localfiles.folders(c), added=None)
        try:
            localfiles.add_folder(c, path)
        except localfiles.LocalFileError as e:
            raise UserError(str(e))
        return jsonify(folders=localfiles.folders(c), added=path)


@bp.post("/folders/remove")
def folders_remove():
    import localfiles
    with con() as c:
        return jsonify(folders=localfiles.remove_folder(c, body().get("path")))


# ---------- モッチの答えの中のファイルの札(S7-2 1.11・A47・A48) ----------
@bp.post("/files/open")
def files_open():
    """札を本人が押したとき。登録したフォルダの中だけ。本人の操作なので確認のカードは出さない。"""
    import localfiles
    with con() as c:
        try:
            p = localfiles.open_link(c, body().get("path"))
        except localfiles.LocalFileError as e:
            raise UserError(str(e))
    return jsonify(opened=p.name)


@bp.post("/files/reveal")
def files_reveal():
    import localfiles
    with con() as c:
        try:
            p = localfiles.reveal(c, body().get("path"))
        except localfiles.LocalFileError as e:
            raise UserError(str(e))
    return jsonify(shown=p.name)


@bp.get("/mochi")
def mochi_get():
    with con() as c:
        return jsonify(settings=agent.get_settings(c), hint=agent.hint(c))


@bp.patch("/mochi")
def mochi_set():
    with con() as c:
        agent.set_settings(c, body())
        return jsonify(settings=agent.get_settings(c))
