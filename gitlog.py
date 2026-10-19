"""git からの取り込み(要件 F7)と、開発の中身と進み具合(F15)。

git は読むだけ。リポジトリの中のファイルは書きかえない。
リポジトリの場所(PC の中のフォルダ名)は data/ の DB にだけ置く。
"""
import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import mails

EVERY = timedelta(minutes=10)  # 起動時と10分ごと(Claude の案)
DAYS = 30  # さかのぼって読む日数。同じコミットは番号で見分けて二度入れない
MAX = 300
DESC_LEN = 100  # README の説明はこの文字数で切る(Claude の案)
DEV_STATES = ("アイデア", "作成中", "動いている", "休止")
SEP = "\x1f"


def _git(args, cwd):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode != 0:
        raise RuntimeError((r.stderr or "git が失敗しました").strip()[:200])
    return r.stdout


def check_repo(path, subdir=None):
    """入れ物の設定で入れた場所を確かめて、そろえた形で返す。だめなら ValueError(画面に出す理由)。"""
    p = Path((path or "").strip().strip('"'))
    if not str(p) or not p.is_dir():
        raise ValueError("そのフォルダが見つかりません")
    try:
        top = _git(["rev-parse", "--show-toplevel"], p).strip()
    except (RuntimeError, OSError, subprocess.TimeoutExpired):
        raise ValueError("そのフォルダは git のリポジトリではありません")
    sub = (subdir or "").strip().strip("/\\").replace("\\", "/") or None
    if sub:
        if ".." in sub.split("/") or not (Path(top) / sub).is_dir():
            raise ValueError("リポジトリの中に、そのフォルダが見つかりません")
    return str(Path(top)), sub


def read_commits(path, subdir=None, since=None):
    """新しい順の [{hash, committed_at, message}]。subdir があれば、そのフォルダを変えたコミットだけ。"""
    since = since or datetime.now() - timedelta(days=DAYS)
    args = ["log", f"--since={since.isoformat(timespec='seconds')}", f"-n{MAX}", "--date=format-local:%Y-%m-%dT%H:%M:%S",
            f"--format=%H{SEP}%cd{SEP}%s"]
    if subdir:
        args += ["--", subdir]
    out = []
    for line in _git(args, path).splitlines():
        parts = line.split(SEP)
        if len(parts) == 3:
            out.append({"hash": parts[0], "committed_at": parts[1], "message": parts[2]})
    return out


def _attach(con, cid, at):
    """コミットの時刻に、同じ入れ物の記録が動いていれば、その記録の番号(F7)。"""
    r = con.execute("SELECT id FROM work_logs WHERE container_id = ? AND started_at <= ? AND (ended_at IS NULL OR ended_at >= ?) "
                    "ORDER BY started_at DESC LIMIT 1", (cid, at, at)).fetchone()
    return r["id"] if r else None


def ingest(con, cid, commits):
    """新しいコミットだけ入れる。消したもの(hidden)も行は残るので、戻ってこない。入れた番号のリストを返す。"""
    new = []
    for c in reversed(commits):  # 古い順に入れる
        if con.execute("SELECT 1 FROM commits WHERE container_id = ? AND hash = ?", (cid, c["hash"])).fetchone():
            continue
        new.append(con.execute("INSERT INTO commits(container_id, work_log_id, hash, message, committed_at) VALUES (?, ?, ?, ?, ?)",
                               (cid, _attach(con, cid, c["committed_at"]), c["hash"], c["message"], c["committed_at"])).lastrowid)
    return new


def refresh(con, now=None, reader=None, force=False):
    """リポジトリを登録した入れ物を、10分ごとに読む。入れたコミットの数を返す。"""
    now = now or datetime.now()
    reader = reader or read_commits
    last = mails.setting(con, "git_read_at")
    if not force and last and now - datetime.fromisoformat(last) < EVERY:
        return 0
    rows = con.execute("SELECT id, name, repo_path, repo_subdir FROM containers WHERE repo_path IS NOT NULL AND ended = 0").fetchall()
    n, failed = 0, []
    for r in rows:
        try:
            got = reader(r["repo_path"], r["repo_subdir"], now - timedelta(days=DAYS))
        except Exception:  # リポジトリが見つからないなど。推測で埋めない
            failed.append(r["name"])
            continue
        n += len(ingest(con, r["id"], got))
    if failed:
        mails.set_setting(con, "git_error", "「" + "」「".join(failed) + "」のリポジトリを読めませんでした(設定でリポジトリの場所を直せます)")
    else:
        con.execute("DELETE FROM settings WHERE key = 'git_error'")
    mails.set_setting(con, "git_read_at", now.isoformat(timespec="seconds"))
    if rows:  # 1つも登録していなければ、本体の様子に出さない
        con.execute("INSERT INTO job_status(job, last_run_at, last_error) VALUES ('git の取り込み', ?, ?) "
                    "ON CONFLICT(job) DO UPDATE SET last_run_at = excluded.last_run_at, last_error = excluded.last_error",
                    (now.isoformat(timespec="seconds"), ("読めなかった: " + "、".join(failed)) if failed else None))
    return n


# ---------- 開発の中身と進み具合(F15) ----------
def _app_dir(c):
    return Path(c["repo_path"]) / c["repo_subdir"] if c["repo_subdir"] else Path(c["repo_path"])


def readme_summary(folder):
    """README の一番上の見出しのすぐ下の段落(空行まで)。100文字を超えたら切って「…」。なければ None。"""
    for name in ("README.md", "readme.md", "README.markdown", "README.txt", "README"):
        p = Path(folder) / name
        if p.is_file():
            break
    else:
        return None
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    i = next((k for k, l in enumerate(lines) if l.startswith("#")), None)
    if i is None:
        return None
    para = []
    for l in lines[i + 1:]:
        s = l.strip()
        if not s:
            if para:
                break
            continue
        if s.startswith("#"):  # 段落の前に次の見出しが来た = 段落がない
            break
        para.append(s)
    if not para:
        return None
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", " ".join(para))  # リンクは文字だけ
    text = re.sub(r"[*_`]", "", text)
    return text if len(text) <= DESC_LEN else text[:DESC_LEN] + "…"


def spec_stage(folder):
    """docs/spec-excel-status.md の表から、いまの工程。なければ None。"""
    p = Path(folder) / "docs" / "spec-excel-status.md"
    if not p.is_file():
        return None
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    rows = []
    for l in text.splitlines():
        cells = [x.strip() for x in l.strip().strip("|").split("|")]
        if len(cells) >= 3 and cells[0].isdigit():
            rows.append((cells[0], cells[1], cells[2]))
    if not rows:
        return None
    for no, name, st in rows:
        if st == "進行中":
            return f"工程{no} {name}(進行中)"
    done = [r for r in rows if r[2] in ("完了", "飛ばした")]
    if len(done) == len(rows):
        return "全部の工程が完了"
    if done:
        no, name, _ = done[-1]
        return f"工程{no} {name}まで完了"
    return f"工程{rows[0][0]} {rows[0][1]}(未着手)"


def dev_info(c):
    """入れ物の中のいちばん上に出す、説明と工程(S5-1)。リポジトリを登録していなければ None。"""
    if not c["repo_path"]:
        return None
    folder = _app_dir(c)
    readme = readme_summary(folder)
    stage = spec_stage(folder)
    return {
        "description": c["own_description"] or readme,  # 自分で書いた説明があれば、そちらを優先する
        "readme": readme,
        "stage": stage,
        "state": None if stage else (c["dev_state"] or None),  # spec-excel の工程がないときだけ、自分で選んだ状態
        "has_spec": stage is not None,
    }
