"""区切り1 土台:本体・データ・予備・画面の枠。"""
from datetime import date, timedelta

import backup
import db


def test_init_makes_builtin_kinds_and_unsorted(db_path):
    db.init(db_path)
    db.init(db_path)  # 2回動かしても増えない
    with db.session(db_path) as con:
        kinds = [r["name"] for r in con.execute("SELECT name FROM kinds WHERE builtin = 1 ORDER BY id")]
        unsorted = con.execute("SELECT COUNT(*) FROM containers WHERE is_unsorted = 1").fetchone()[0]
    assert kinds == ["大学", "就活", "開発"]
    assert unsorted == 1


def test_builtin_kind_settings(db_path):
    """先に並べる:大学・就活がオン、手つかずの通知:開発だけオフ(要件 F1)。"""
    db.init(db_path)
    with db.session(db_path) as con:
        rows = {r["name"]: (r["sort_first"], r["notify_untouched"]) for r in con.execute("SELECT * FROM kinds")}
    assert rows == {"大学": (1, 1), "就活": (1, 1), "開発": (0, 0)}


def test_no_show_on_top_column(db_path):
    """「トップに出す」はなくした(基本設計 Q30)。"""
    db.init(db_path)
    with db.session(db_path) as con:
        cols = [r["name"] for r in con.execute("PRAGMA table_info(containers)")]
    assert "show_on_top" not in cols
    assert "links_always_top" in cols


def test_backup_once_a_day_and_keeps_seven(db_path):
    db.init(db_path)
    start = date(2026, 10, 1)
    for i in range(10):
        backup.run(db_path, today=start + timedelta(days=i))
    assert backup.run(db_path, today=start + timedelta(days=9)) is None  # 同じ日は作らない
    files = sorted(p.name for p in backup.backup_dir(db_path).glob("dandori-*.db"))
    assert len(files) == 7
    assert files[0] == "dandori-2026-10-04.db"
    assert files[-1] == "dandori-2026-10-10.db"


def test_health_and_index(client):
    res = client.get("/api/health")
    assert res.get_json() == {"ok": True, "name": "段取りさん"}
    page = client.get("/")
    assert page.status_code == 200
    assert "段取りさん" in page.get_data(as_text=True)
    assert client.get("/web/app.js").status_code == 200
    assert client.get("/assets/character/dandori-normal.png").status_code == 200


def test_listens_only_on_localhost():
    import app as app_module

    assert app_module.HOST == "127.0.0.1"
