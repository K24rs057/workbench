"""区切り15 シフト表の写真(F14)。Claude と Google にはつながず、作り物を使う。"""
import io
from datetime import date
from pathlib import Path

import pytest

import agent
import db
import gcal
import shift
from tests.test_gcal import FakeCal, timed


@pytest.fixture
def fake(monkeypatch):
    cal = FakeCal([timed("x", "2026-10-24", "18:00", "19:00", "サークル")])
    monkeypatch.setattr(gcal, "_api", lambda: cal)
    import gmail
    monkeypatch.setattr(gmail, "calendar_allowed", lambda env=None: True)
    return cal


def test_needs_name_first(db_path):
    db.init(db_path)
    with db.session(db_path) as con:
        with pytest.raises(shift.ShiftError, match="自分の名前"):
            shift.read_photo(con, b"x", "a.jpg", runner=lambda *a: {"shifts": []})


def test_photo_is_removed_and_only_name_is_sent(db_path):
    db.init(db_path)
    seen = {}

    def run(folder, filename, who, today):
        p = Path(folder) / filename
        seen.update(folder=folder, exists=p.exists(), files=sorted(x.name for x in Path(folder).iterdir()), who=who)
        return {"shifts": [{"date": "2026-10-23", "start": "17:00", "end": "22:00"}, {"date": "x", "start": "1", "end": "2"},
                           {"date": "2026-10-22", "start": "9:00", "end": "13:00"}]}
    with db.session(db_path) as con:
        shift.set_name(con, " 山田 ")
        got = shift.read_photo(con, b"\x89PNG...", "IMG_0001.PNG", runner=run, today=date(2026, 10, 20))
    assert seen["exists"] and seen["files"] == ["shift.png"] and seen["who"] == "山田"  # 写真1枚だけのフォルダ
    assert not Path(seen["folder"]).exists()  # 読み終えたら消す
    assert got == [{"date": "2026-10-22", "start": "09:00", "end": "13:00"}, {"date": "2026-10-23", "start": "17:00", "end": "22:00"}]


def test_failure_message(db_path):
    db.init(db_path)
    with db.session(db_path) as con:
        shift.set_name(con, "山田")
        def bad(*a):
            raise agent.AgentError("x")
        with pytest.raises(shift.ShiftError, match="読み取れませんでした"):
            shift.read_photo(con, b"x", "a.jpg", runner=bad)
        with pytest.raises(shift.ShiftError, match="写真"):
            shift.read_photo(con, b"x", "a.pdf", runner=bad)


def test_title_by_number_of_places(db_path):
    db.init(db_path)
    with db.session(db_path) as con:
        assert shift.title(con) == "バイト"
        a = con.execute("INSERT INTO baito_places(name) VALUES ('○○カフェ')").lastrowid
        assert shift.title(con) == "バイト(○○カフェ)"
        b = con.execute("INSERT INTO baito_places(name) VALUES ('△△書店')").lastrowid
        with pytest.raises(shift.ShiftError):
            shift.title(con)
        assert shift.title(con, b) == "バイト(△△書店)"


def test_photo_api_and_commit(client, db_path, fake, monkeypatch):
    client.patch("/api/settings/mail", json={"shift_name": "山田"})
    assert client.get("/api/settings/mail").get_json()["shift_name"] == "山田"
    monkeypatch.setattr(shift, "_run_claude", lambda *a: {"shifts": [{"date": "2026-10-24", "start": "17:00", "end": "22:00"},
                                                                      {"date": "2026-10-25", "start": "10:00", "end": "15:00"}]})
    r = client.post("/api/shift-photo", data={"photo": (io.BytesIO(b"jpgdata"), "s.jpg")}, content_type="multipart/form-data")
    got = r.get_json()["shifts"]
    assert len(got) == 2
    res = client.post("/api/shift-photo/commit", json={"shifts": got}).get_json()
    assert res["summary"] == "バイト"
    assert [s["date"] for s in res["written"]] == ["2026-10-25"]
    assert "重なる予定" in res["skipped"][0]["reason"]  # 10/24 はサークルと重なる
    ev = [e for e in fake.events.values() if e["summary"] == "バイト"][0]
    assert ev["extendedProperties"]["private"]["dandori"] == "shift"
    # もう一度書いても、二重にはしない
    res2 = client.post("/api/shift-photo/commit", json={"shifts": [got[1]]}).get_json()
    assert res2["written"] == [] and res2["skipped"][0]["reason"] == "もう入っています"


def test_commit_rejects_bad_rows(client, db_path, fake):
    r = client.post("/api/shift-photo/commit", json={"shifts": [{"date": "2026-10-26", "start": "22:00", "end": "05:00"}]}).get_json()
    assert r["written"] == [] and "終わり" in r["skipped"][0]["reason"]
    assert client.post("/api/shift-photo/commit", json={"shifts": []}).status_code == 400


def test_name_setting_does_not_touch_domain(client, db_path):
    client.patch("/api/settings/mail", json={"university_domain": "example.ac.jp"})
    client.patch("/api/settings/mail", json={"shift_name": "山田"})
    assert client.get("/api/settings/mail").get_json()["university_domain"] == "example.ac.jp"
