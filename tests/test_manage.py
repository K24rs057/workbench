"""管理用の命令(manage.py、基本設計 A33)。"""
import json

import pytest

import db
import manage


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "dandori.db")
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    return tmp_path


def test_term_end_and_end_container(data, capsys):
    assert manage.main(["term-end", "2027-07-31"]) == 0
    with db.session() as con:
        assert con.execute("SELECT value FROM settings WHERE key = 'term_end'").fetchone()[0] == "2027-07-31"
        kid = con.execute("SELECT id FROM kinds WHERE name = '大学'").fetchone()[0]
        con.execute("INSERT INTO containers(kind_id, name) VALUES (?, '工業デザイン')", (kid,))
    assert manage.main(["end-container", "工業デザイン"]) == 0
    assert manage.main(["end-container", "ない授業"]) == 1
    with db.session() as con:
        assert con.execute("SELECT ended FROM containers WHERE name = '工業デザイン'").fetchone()[0] == 1


def test_errors_are_short_messages(data, tmp_path, capsys):
    assert manage.main(["term-end", "7/31"]) == 1
    assert "2027-07-31 の形" in capsys.readouterr().err
    assert manage.main(["google-key", str(tmp_path / "ない.json")]) == 1
    assert "できませんでした" in capsys.readouterr().err
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"other": {}}), encoding="utf-8")
    assert manage.main(["google-key", str(bad)]) == 1
    assert "デスクトップ アプリ" in capsys.readouterr().err
