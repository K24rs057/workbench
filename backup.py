"""毎日の予備(基本設計 Q17)。

その日最初に起動したときに data/backup/ に日付つきでコピーし、7日分だけ残す。
SQLite の backup 機能を使うので、書き込み中でも壊れない。
"""
import sqlite3
from datetime import date
from pathlib import Path

import db

KEEP_DAYS = 7


def backup_dir(db_path=None):
    return Path(db_path or db.DB_PATH).parent / "backup"


def run(db_path=None, today=None):
    """今日の予備がなければ作る。作ったときはそのファイルの場所を返す。"""
    db_path = Path(db_path or db.DB_PATH)
    if not db_path.exists():
        return None
    today = today or date.today()
    folder = backup_dir(db_path)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"dandori-{today:%Y-%m-%d}.db"
    made = None
    if not target.exists():
        src = sqlite3.connect(db_path)
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        made = target
    for old in sorted(folder.glob("dandori-*.db"))[:-KEEP_DAYS]:
        old.unlink()
    return made
