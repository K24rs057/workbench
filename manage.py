"""管理用の小さな命令(基本設計 A33)。学期の入れ替えのとき、Claude Code が使う。画面からは呼ばない。

    python manage.py term-end 2027-07-31        … 学期の終わりの日を入れる(Q7)
    python manage.py end-container "工業デザイン" … 終わった授業を終了にする
    python manage.py read-timetable             … 時間割をすぐ読み直す
    python manage.py install-autostart          … ログインしたら動き出す・止まったら動かし直す(タスクスケジューラ)
    python manage.py remove-autostart           … 上の登録を外す
    python manage.py google-key <ファイル>        … Google Cloud で保存した合鍵のファイルから、ID と秘密の文字を .env に移す(中身は出さない)
"""
import argparse
import sys
from datetime import date

import db
import timetable


def main(argv=None):
    p = argparse.ArgumentParser(description="段取りさんの管理用の命令")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("term-end"); s.add_argument("day")
    s = sub.add_parser("end-container"); s.add_argument("name")
    sub.add_parser("read-timetable")
    sub.add_parser("install-autostart")
    sub.add_parser("remove-autostart")
    s = sub.add_parser("google-key"); s.add_argument("path")
    a = p.parse_args(argv)
    try:
        return _run(a)
    except (ValueError, OSError, RuntimeError) as e:  # ファイルがない・日付の形がちがう・登録できないなど
        print(f"できませんでした:{e}", file=sys.stderr)
        return 1


def _run(a):
    if a.cmd == "google-key":
        import gmail
        gmail.import_client_json(a.path)
        print("Google の合鍵を .env に入れました。段取りさんの設定の「Google」から許可してください")
        return 0
    if a.cmd in ("install-autostart", "remove-autostart"):
        import autostart
        st = autostart.install() if a.cmd == "install-autostart" else autostart.remove()
        for name, ok in st.items():
            print(f"{name}:{'登録されています' if ok else '登録されていません'}")
        return 0
    db.init()
    with db.session() as con:
        if a.cmd == "term-end":
            try:
                date.fromisoformat(a.day)
            except ValueError:
                raise ValueError(f"日付は 2027-07-31 の形で入れてください({a.day})")
            con.execute("INSERT INTO settings(key, value) VALUES ('term_end', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (a.day,))
            print(f"学期の終わりの日を {a.day} にしました")
        elif a.cmd == "end-container":
            n = con.execute("UPDATE containers SET ended = 1 WHERE name = ? AND is_unsorted = 0", (a.name,)).rowcount
            print(f"「{a.name}」を終了にしました" if n else f"「{a.name}」は見つかりませんでした")
            return 0 if n else 1
        elif a.cmd == "read-timetable":
            timetable.refresh(con, force=True)
            print(timetable.error(con) or "時間割を読みました")
    return 0


if __name__ == "__main__":
    sys.exit(main())
