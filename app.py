"""段取りさん(workbench)の本体。

    pythonw app.py            … ふだんの起動(画面は 段取りさんを開く.bat から開く)
    python app.py --port 8780 … ポートを変えて動かす

この PC の中(127.0.0.1)からだけ開ける。同じ Wi-Fi のほかの端末からは開けない(非機能 外から使えないこと)。
"""
import argparse
import os
from pathlib import Path

from flask import Flask, jsonify, send_from_directory

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

    return app


def start_worklog(db_path):
    """1分ごとに、作業記録をつけ(F4)、通知を確かめ(F8)、10分ごとに大学のメールを読む(F9)。"""
    import threading
    import time

    import mails
    import notify
    import outlook
    import worklog

    def loop():
        while True:
            try:
                with db.session(db_path) as con:
                    worklog.tick(con, worklog.foreground())
                with db.session(db_path) as con:
                    notify.check(con)
            except Exception as e:  # 1回失敗しても止めない。本体の様子に残す
                _log_error(db_path, "作業記録", e)
            try:  # メールは10分ごと(outlook.refresh の中で間を数える)
                with db.session(db_path) as con:
                    outlook.refresh(con)
                with db.session(db_path) as con:
                    mails.run_claude_jobs(con)
            except Exception as e:
                _log_error(db_path, "Outlook", e)
            time.sleep(60)

    threading.Thread(target=loop, daemon=True, name="worklog").start()


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
