"""段取りさん(workbench)の本体。

    pythonw app.py            … ふだんの起動(画面は 段取りさんを開く.bat から開く)
    python app.py --port 8780 … ポートを変えて動かす

この PC の中(127.0.0.1)からだけ開ける。同じ Wi-Fi のほかの端末からは開けない(非機能 外から使えないこと)。
"""
import argparse
import os
from pathlib import Path

from flask import Flask, jsonify, redirect, request, send_from_directory

import api
import backup
import db

BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "web"
HOST = "127.0.0.1"
PORT = 8780
APP_NAME = "段取りさん"


def code_version():
    """コードの新しさ。.py と web/ のいちばん新しい更新時刻。開く .bat が、古い本体を動かし直すのに使う。"""
    files = list(BASE_DIR.glob("*.py")) + list(WEB_DIR.glob("*"))
    return str(int(max(f.stat().st_mtime for f in files)))


CODE_VERSION = code_version()


def create_app(db_path=None):
    app = Flask(__name__, static_folder=None)
    app.config["DB_PATH"] = db_path
    app.json.ensure_ascii = False
    db.init(db_path)
    import api_worklog  # noqa: F401  作業記録の API を bp に足す
    import api_agent  # noqa: F401  モッチの API を bp に足す
    import api_mail  # noqa: F401  連絡の API を bp に足す
    import api_sched  # noqa: F401  予定の画面の API を bp に足す
    app.register_blueprint(api.bp)

    @app.get("/")
    def index():
        return send_from_directory(WEB_DIR, "index.html")

    @app.get("/web/<path:name>")
    def web_file(name):
        return send_from_directory(WEB_DIR, name)

    @app.get("/assets/<path:name>")
    def asset_file(name):
        return send_from_directory(BASE_DIR / "assets", name)

    @app.get("/api/health")
    def health():
        return jsonify(ok=True, name=APP_NAME, version=CODE_VERSION, pid=os.getpid())

    @app.get("/auth/google")
    def google_auth():
        """Google の許可の画面へ(A31)。戻り先はこの PC の中だけ。"""
        import gmail
        try:
            return redirect(gmail.auth_url(request.host_url + "auth/google/callback"))
        except ValueError as e:
            return _auth_page(str(e))

    @app.get("/auth/google/callback")
    def google_callback():
        import gmail
        if request.args.get("error"):
            return _auth_page("許可をやめました。設定の「Google」から、いつでも許可し直せます")
        try:
            gmail.finish_auth(request.args.get("state"), request.url)
        except Exception as e:  # 期限切れ・通行証が届かないなど
            return _auth_page(f"許可できませんでした:{e}")
        return redirect("/#set")

    return app


def _auth_page(text):
    from markupsafe import escape
    return (f'<!doctype html><meta charset="utf-8"><title>段取りさん</title><body style="font-family:sans-serif;padding:40px">'
            f'<p>{escape(text)}</p><p><a href="/#set">段取りさんに戻る</a></p></body>')


def start_worklog(db_path):
    """1分ごとに、作業記録をつけ(F4)、通知を確かめ(F8)、10分ごとに大学のメールを読む(F9)。"""
    import threading
    import time

    def loop():
        while True:
            run_jobs_once(db_path)
            time.sleep(60)

    threading.Thread(target=loop, daemon=True, name="worklog").start()


def run_jobs_once(db_path):
    """裏の仕事を1回分。どれかが失敗しても、ほかは続ける(本体の様子に残す)。"""
    import autodone
    import gcal
    import gitlog
    import gmail
    import mails
    import notify
    import outlook
    import worklog

    try:
        with db.session(db_path) as con:
            worklog.tick(con, worklog.foreground())
    except Exception as e:  # 1回失敗しても止めない。本体の様子に残す
        _log_error(db_path, "作業記録", e)
    try:  # 作業記録が失敗しても、通知は出す
        with db.session(db_path) as con:
            notify.check(con)
    except Exception as e:
        _log_error(db_path, "通知", e)
    try:  # メールは10分ごと(outlook.refresh の中で間を数える)
        with db.session(db_path) as con:
            outlook.refresh(con)
        with db.session(db_path) as con:
            mails.run_claude_jobs(con)
    except Exception as e:
        _log_error(db_path, "Outlook", e)
    try:  # Gmail も10分ごと。許可がまだなら何もしない(F11・F20)
        with db.session(db_path) as con:
            gmail.refresh(con)
        with db.session(db_path) as con:
            mails.run_claude_jobs(con)
    except Exception as e:
        _log_error(db_path, "Gmail", e)
    try:  # カレンダーは10分ごと。タスクが変わったときは次の1分で直す(F12・F13)
        with db.session(db_path) as con:
            gcal.refresh(con)
    except Exception as e:
        _log_error(db_path, "Google カレンダー", e)
    try:  # git は起動時と10分ごと。読むだけ(F7)
        with db.session(db_path) as con:
            gitlog.refresh(con)
    except Exception as e:
        _log_error(db_path, "git の取り込み", e)
    try:  # 自動で完了の合図を見分ける。「終わっていそう」は1日1回(F18)
        with db.session(db_path) as con:
            autodone.run_jobs(con)
        with db.session(db_path) as con:
            autodone.run_maybe(con)
    except Exception as e:
        _log_error(db_path, "Claude", e)


def _log_error(db_path, job, e):
    try:
        with db.session(db_path) as con:
            con.execute("INSERT INTO job_status(job, last_error) VALUES (?, ?) ON CONFLICT(job) DO UPDATE SET last_error = excluded.last_error", (job, str(e)[:200]))
    except Exception:
        pass


def already_running(port):
    """同じポートで本体がもう動いていたら、2つ目は動かさない(Windows では同じポートに2つ待ち受けられてしまうため)。"""
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://{HOST}:{port}/api/health", timeout=1) as res:
            return res.status == 200
    except OSError:
        return False


def main():
    parser = argparse.ArgumentParser(description=f"{APP_NAME}の本体")
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--data-dir", help="data/ のかわりに使うフォルダ(画面の確かめ用。本物のデータを汚さない)")
    parser.add_argument("--no-jobs", action="store_true", help="作業記録と通知を動かさない(画面の確かめ用。窓の名前を読まず、通知も出さない)")
    args = parser.parse_args()
    if already_running(args.port):
        print(f"{APP_NAME}の本体は、もう動いています(ポート {args.port})")
        return
    db_path = Path(args.data_dir) / "dandori.db" if args.data_dir else None
    app = create_app(db_path)
    backup.run(db_path)
    import timetable
    with db.session(db_path) as con:
        timetable.refresh(con, force=True)
    if not args.no_jobs:
        start_worklog(db_path)
    app.run(host=HOST, port=args.port, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
