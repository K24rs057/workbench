import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


SAMPLE_TIMETABLE = """# 時間割(テスト用)
1限 09:00-10:40 / 2限 11:00-12:40 / 3限 13:40-15:20 / 4限 15:40-17:20

## 月曜
- 1限・2限: 設計演習([102]) / 先生A / 教室1

## 水曜
- 3限: 情報演習([115]) / 先生B / 教室2
- 2限: デザイン([101]) / 先生C / 教室3

## 金曜・土曜
- 授業なし(5限・6限も全曜日で空き)
"""


@pytest.fixture(autouse=True)
def sample_timetable(tmp_path, monkeypatch):
    p = tmp_path / "timetable.md"
    p.write_text(SAMPLE_TIMETABLE, encoding="utf-8")
    monkeypatch.setenv("DANDORI_TIMETABLE", str(p))
    return p


@pytest.fixture(autouse=True)
def no_real_google(tmp_path, monkeypatch):
    """本物の .env(Google の合鍵と通行証)を読まない。テストから本物の Gmail・カレンダーにつながないため。"""
    import gcal
    import gmail
    monkeypatch.setattr(gmail, "ENV_PATH", tmp_path / ".env")
    gcal._cache.update(at=None, items=[], error=None)


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "dandori.db"


@pytest.fixture
def client(db_path):
    import app as app_module

    return app_module.create_app(db_path).test_client()
