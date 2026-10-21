"""データの置き場所(data/ の SQLite)。

表の形は基本設計書 ver.1.01 の「3 テーブル定義」に合わせる。
作る順番①で使う表だけを作り、メール・カレンダー・git の表は②〜④で足す。
"""
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("DANDORI_DATA_DIR", BASE_DIR / "data"))
DB_PATH = DATA_DIR / "dandori.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS kinds (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    color TEXT NOT NULL,
    sort_first INTEGER NOT NULL DEFAULT 0,
    notify_untouched INTEGER NOT NULL DEFAULT 1,
    builtin INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS containers (
    id INTEGER PRIMARY KEY,
    kind_id INTEGER REFERENCES kinds(id),
    is_unsorted INTEGER NOT NULL DEFAULT 0,
    name TEXT NOT NULL,
    ended INTEGER NOT NULL DEFAULT 0,
    links_always_top INTEGER NOT NULL DEFAULT 0,
    auto_source TEXT,
    source_key TEXT,
    repo_path TEXT,
    repo_subdir TEXT,
    company_domain TEXT,
    own_description TEXT,
    dev_state TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY,
    container_id INTEGER NOT NULL REFERENCES containers(id),
    name TEXT NOT NULL,
    due_date TEXT,
    due_time TEXT,
    start_date TEXT,
    repeat_weekday INTEGER,
    repeat_from_task_id INTEGER,
    done INTEGER NOT NULL DEFAULT 0,
    done_at TEXT,
    auto_done_by TEXT,
    from_message_id INTEGER,
    ai_read INTEGER NOT NULL DEFAULT 0,
    ai_checked INTEGER NOT NULL DEFAULT 0,
    ai_excerpt TEXT,
    open_url TEXT,
    calendar_written INTEGER NOT NULL DEFAULT 0,
    calendar_deleted INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE TABLE IF NOT EXISTS work_logs (
    id INTEGER PRIMARY KEY,
    container_id INTEGER NOT NULL REFERENCES containers(id),
    task_id INTEGER,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    edited INTEGER NOT NULL DEFAULT 0,
    note TEXT
);
CREATE TABLE IF NOT EXISTS notices (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    body TEXT NOT NULL,
    task_id INTEGER,
    message_id INTEGER,
    container_id INTEGER,
    pending_window_id INTEGER,
    answered INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE TABLE IF NOT EXISTS done_questions (
    id INTEGER PRIMARY KEY,
    container_id INTEGER NOT NULL,
    asked_on TEXT NOT NULL,
    answered INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS window_rules (
    id INTEGER PRIMARY KEY,
    app TEXT NOT NULL,
    pattern TEXT NOT NULL,
    container_id INTEGER,
    ignore INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS pending_windows (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    first_seen TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS links (
    id INTEGER PRIMARY KEY,
    container_id INTEGER NOT NULL REFERENCES containers(id),
    name TEXT NOT NULL,
    target TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pending_pc_notices (
    id INTEGER PRIMARY KEY,
    text TEXT NOT NULL,
    due_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS claude_jobs (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    target TEXT NOT NULL,
    tries INTEGER NOT NULL DEFAULT 0,
    next_try_at TEXT,
    last_error TEXT
);
CREATE TABLE IF NOT EXISTS job_status (
    job TEXT PRIMARY KEY,
    last_run_at TEXT,
    last_error TEXT
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    external_id TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL,
    container_id INTEGER,
    baito_id INTEGER,
    subject TEXT NOT NULL,
    sender TEXT NOT NULL,
    received_at TEXT NOT NULL,
    body TEXT,
    links TEXT,
    seen INTEGER NOT NULL DEFAULT 0,
    ai_failed INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS sort_rules (
    id INTEGER PRIMARY KEY,
    sender TEXT NOT NULL,
    subject TEXT,
    container_id INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS blocked_senders (
    id INTEGER PRIMARY KEY,
    address TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE TABLE IF NOT EXISTS deleted_items (
    id INTEGER PRIMARY KEY,
    external_id TEXT NOT NULL,
    what TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS baito_places (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    domain TEXT
);
CREATE TABLE IF NOT EXISTS baito_addresses (
    id INTEGER PRIMARY KEY,
    baito_id INTEGER NOT NULL,
    address TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS held_events (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    start_at TEXT NOT NULL,
    end_at TEXT,
    reason TEXT NOT NULL,
    container_id INTEGER,
    task_id INTEGER,
    from_message_id INTEGER,
    ai_read INTEGER NOT NULL DEFAULT 0,
    ai_excerpt TEXT
);
CREATE TABLE IF NOT EXISTS event_extras (
    id INTEGER PRIMARY KEY,
    google_event_id TEXT NOT NULL UNIQUE,
    edit_allowed INTEGER NOT NULL DEFAULT 0,
    marked INTEGER NOT NULL DEFAULT 0,
    task_id INTEGER,
    container_id INTEGER,
    synced_date TEXT,
    synced_summary TEXT
);
CREATE TABLE IF NOT EXISTS commits (
    id INTEGER PRIMARY KEY,
    container_id INTEGER NOT NULL REFERENCES containers(id),
    work_log_id INTEGER,
    hash TEXT NOT NULL,
    message TEXT NOT NULL,
    committed_at TEXT NOT NULL,
    hidden INTEGER NOT NULL DEFAULT 0,
    UNIQUE(container_id, hash)
);
CREATE TABLE IF NOT EXISTS maybe_done (
    id INTEGER PRIMARY KEY,
    task_id INTEGER NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    resolved INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS agent_runs (
    id INTEGER PRIMARY KEY,
    message_id INTEGER,
    token TEXT NOT NULL,
    state TEXT NOT NULL,
    progress TEXT,
    started_at TEXT NOT NULL,
    ended_at TEXT
);
CREATE TABLE IF NOT EXISTS agent_actions (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL,
    tool TEXT NOT NULL,
    args TEXT NOT NULL,
    preview TEXT,
    undo TEXT,
    state TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_messages (
    id INTEGER PRIMARY KEY,
    role TEXT NOT NULL,
    text TEXT NOT NULL,
    screen TEXT,
    action TEXT,
    action_state TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
"""

# 初めからある3つの種類(要件 F1)。色は UI 試作に合わせる
BUILTIN_KINDS = [
    ("大学", "#17806a", 1, 1),
    ("就活", "#5b4fc4", 1, 1),
    ("開発", "#b9561f", 0, 0),
]


def connect(path=None):
    path = Path(path or DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


@contextmanager
def session(path=None):
    """1回の読み書き。最後にまとめて保存し、失敗したら元に戻す。"""
    con = connect(path)
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def init(path=None):
    """表を作り、初めの種類と「未分類」の入れ物を1回だけ入れる。"""
    with session(path) as con:
        con.executescript(SCHEMA)
        if con.execute("SELECT COUNT(*) FROM kinds").fetchone()[0] == 0:
            con.executemany(
                "INSERT INTO kinds(name, color, sort_first, notify_untouched, builtin) VALUES (?, ?, ?, ?, 1)",
                BUILTIN_KINDS,
            )
        if con.execute("SELECT COUNT(*) FROM containers WHERE is_unsorted = 1").fetchone()[0] == 0:
            con.execute("INSERT INTO containers(kind_id, is_unsorted, name) VALUES (NULL, 1, '未分類')")
