import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "dandori.db"


@pytest.fixture
def client(db_path):
    import app as app_module

    return app_module.create_app(db_path).test_client()
