"""段取りさん(workbench)の本体。

    pythonw app.py            … ふだんの起動(画面は 段取りさんを開く.bat から開く)
    python app.py --port 8780 … ポートを変えて動かす

この PC の中(127.0.0.1)からだけ開ける。同じ Wi-Fi のほかの端末からは開けない(非機能 外から使えないこと)。
"""
import argparse
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


def create_app(db_path=None):
    app = Flask(__name__, static_folder=None)
    app.config["DB_PATH"] = db_path
    app.json.ensure_ascii = False
    db.init(db_path)
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
        return jsonify(ok=True, name=APP_NAME)

    return app


def main():
    parser = argparse.ArgumentParser(description=f"{APP_NAME}の本体")
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--data-dir", help="data/ のかわりに使うフォルダ(画面の確かめ用。本物のデータを汚さない)")
    args = parser.parse_args()
    db_path = Path(args.data_dir) / "dandori.db" if args.data_dir else None
    app = create_app(db_path)
    backup.run(db_path)
    import timetable
    with db.session(db_path) as con:
        timetable.refresh(con, force=True)
    app.run(host=HOST, port=args.port, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
