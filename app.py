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
    """1分ごとに、前に出ている窓の名前を読んで作業記録をつける(F4)。"""
    import threading
    import time

    import worklog

    def loop():
        while True:
            try:
                with db.session(db_path) as con:
                    worklog.tick(con, worklog.foreground())
            except Exception as e:  # 1回失敗しても止めない。本体の様子に残す
                try:
                    with db.session(db_path) as con:
                        con.execute(
                            "INSERT INTO job_status(job, last_error) VALUES ('作業記録', ?) "
                            "ON CONFLICT(job) DO UPDATE SET last_error = excluded.last_error", (str(e),))
                except Exception:
                    pass
            time.sleep(60)

    threading.Thread(target=loop, daemon=True, name="worklog").start()


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
    start_worklog(db_path)
    app.run(host=HOST, port=args.port, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
