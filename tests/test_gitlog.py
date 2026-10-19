"""区切り13 git からの取り込み(F7)と開発の中身(F15)。テスト用のリポジトリを tmp に作って読む。"""
import subprocess
from datetime import datetime

import pytest

import db
import gitlog


def git(cwd, *args, env=None):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, env=env)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    (r / "products" / "app-a").mkdir(parents=True)
    (r / "products" / "app-b").mkdir(parents=True)
    git(r, "init", "-q")
    git(r, "config", "user.email", "t@example.com")
    git(r, "config", "user.name", "t")
    git(r, "config", "commit.gpgsign", "false")
    return r


def commit(r, path, text, msg, when):
    p = r / path
    p.write_text(text, encoding="utf-8")
    git(r, "add", "-A")
    import os
    env = {**os.environ, "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when}
    git(r, "commit", "-q", "-m", msg, env=env)


def setup(db_path):
    db.init(db_path)
    with db.session(db_path) as con:
        a = con.execute("INSERT INTO containers(kind_id, name) VALUES (3, 'app-a')").lastrowid
        b = con.execute("INSERT INTO containers(kind_id, name) VALUES (3, 'app-b')").lastrowid
    return a, b


def test_read_split_by_folder_and_no_double(db_path, repo):
    now = datetime.now()
    day = now.strftime("%Y-%m-%dT")
    commit(repo, "products/app-a/x.txt", "1", "a: ログイン画面", day + "09:10:00")
    commit(repo, "products/app-b/y.txt", "1", "b: 初めの形", day + "09:20:00")
    commit(repo, "products/app-a/x.txt", "2", "a: 直した", day + "10:05:00")
    a, b = setup(db_path)
    with db.session(db_path) as con:
        con.execute("INSERT INTO work_logs(container_id, started_at, ended_at) VALUES (?, ?, ?)", (a, day + "10:00:00", day + "10:30:00"))
        con.execute("UPDATE containers SET repo_path = ?, repo_subdir = 'products/app-a' WHERE id = ?", (str(repo), a))
        con.execute("UPDATE containers SET repo_path = ?, repo_subdir = 'products/app-b' WHERE id = ?", (str(repo), b))
        assert gitlog.refresh(con, now=now, force=True) == 3
        rows = con.execute("SELECT message, work_log_id FROM commits WHERE container_id = ? ORDER BY committed_at", (a,)).fetchall()
        assert [r["message"] for r in rows] == ["a: ログイン画面", "a: 直した"]
        assert rows[0]["work_log_id"] is None and rows[1]["work_log_id"] is not None  # 記録の間なら、くっつける
        assert gitlog.refresh(con, now=now, force=True) == 0  # 同じコミットは二度入れない
        # 消したものは戻ってこない
        con.execute("UPDATE commits SET hidden = 1 WHERE container_id = ?", (b,))
        gitlog.refresh(con, now=now, force=True)
        assert con.execute("SELECT COUNT(*) FROM commits WHERE container_id = ? AND hidden = 0", (b,)).fetchone()[0] == 0
        assert con.execute("SELECT last_run_at FROM job_status WHERE job = 'git の取り込み'").fetchone()[0]


def test_missing_repo_shows_error(db_path, tmp_path):
    a, _ = setup(db_path)
    with db.session(db_path) as con:
        con.execute("UPDATE containers SET repo_path = ? WHERE id = ?", (str(tmp_path / "nothing"), a))
        gitlog.refresh(con, force=True)
        assert "「app-a」のリポジトリを読めませんでした" in con.execute("SELECT value FROM settings WHERE key = 'git_error'").fetchone()[0]
        import top
        assert any("app-a" in n["text"] for n in top.build(con)["notices"])


def test_settings_check_repo(client, repo):
    cid = client.post("/api/containers", json={"name": "lab", "kind_id": 3}).get_json()["id"]
    r = client.patch(f"/api/containers/{cid}", json={"repo_path": str(repo / "nothing")})
    assert r.status_code == 400 and "見つかりません" in r.get_json()["error"]
    r = client.patch(f"/api/containers/{cid}", json={"repo_path": str(repo), "repo_subdir": "products/zzz"})
    assert "リポジトリの中に" in r.get_json()["error"]
    assert client.patch(f"/api/containers/{cid}", json={"repo_path": str(repo), "repo_subdir": "products\\app-a\\"}).status_code == 200
    c = client.get(f"/api/containers/{cid}").get_json()
    assert c["repo_subdir"] == "products/app-a" and c["dev"] is not None
    # 空にすると登録をやめる
    client.patch(f"/api/containers/{cid}", json={"repo_path": ""})
    assert client.get(f"/api/containers/{cid}").get_json()["dev"] is None


def test_readme_and_stage(tmp_path):
    (tmp_path / "README.md").write_text("# fx-practice\n\n[FX](http://x) の**練習**をする小さなアプリ。\n2行目。\n\n## 使い方\n", encoding="utf-8")
    assert gitlog.readme_summary(tmp_path) == "FX の練習をする小さなアプリ。 2行目。"
    (tmp_path / "README.md").write_text("# a\n\n" + "あ" * 120 + "\n", encoding="utf-8")
    assert gitlog.readme_summary(tmp_path) == "あ" * 100 + "…"
    (tmp_path / "README.md").write_text("# a\n## b\n", encoding="utf-8")
    assert gitlog.readme_summary(tmp_path) is None
    assert gitlog.spec_stage(tmp_path) is None
    (tmp_path / "docs").mkdir()
    st = tmp_path / "docs" / "spec-excel-status.md"
    st.write_text("| No | 工程 | 状態 |\n|---|---|---|\n| 1 | 要件定義 | 完了 |\n| 2 | 構想設計 | 進行中 |\n| 3 | 基本設計 | 未着手 |\n", encoding="utf-8")
    assert gitlog.spec_stage(tmp_path) == "工程2 構想設計(進行中)"
    st.write_text("| No | 工程 | 状態 |\n|---|---|---|\n| 1 | 要件定義 | 完了 |\n| 2 | 構想設計 | 未着手 |\n", encoding="utf-8")
    assert gitlog.spec_stage(tmp_path) == "工程1 要件定義まで完了"


def test_own_description_wins_and_state(client, repo):
    (repo / "README.md").write_text("# r\n\nREADME の説明\n", encoding="utf-8")
    cid = client.post("/api/containers", json={"name": "r", "kind_id": 3}).get_json()["id"]
    client.patch(f"/api/containers/{cid}", json={"repo_path": str(repo)})
    assert client.get(f"/api/containers/{cid}").get_json()["dev"]["description"] == "README の説明"
    client.patch(f"/api/containers/{cid}", json={"own_description": "自分の一言", "dev_state": "作成中"})
    d = client.get(f"/api/containers/{cid}").get_json()["dev"]
    assert d["description"] == "自分の一言" and d["state"] == "作成中"
    assert client.patch(f"/api/containers/{cid}", json={"dev_state": "完成"}).status_code == 400


def test_commit_delete_and_log_delete(client, db_path, repo):
    now = datetime.now()
    commit(repo, "a.txt", "1", "最初", now.strftime("%Y-%m-%dT%H:%M:%S"))
    cid = client.post("/api/containers", json={"name": "r", "kind_id": 3}).get_json()["id"]
    client.patch(f"/api/containers/{cid}", json={"repo_path": str(repo)})
    with db.session(db_path) as con:
        gitlog.refresh(con, force=True)
    got = client.get(f"/api/containers/{cid}/commits").get_json()
    assert [m["message"] for m in got] == ["最初"]
    client.delete(f"/api/commits/{got[0]['id']}")
    assert client.get(f"/api/containers/{cid}/commits").get_json() == []
    assert client.get(f"/api/containers/{cid}").get_json()["deletable"] is False  # 消したコミットも中身として数える
