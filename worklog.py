"""全自動の作業記録(要件 F4・F5、基本設計 Q23〜Q25・Q29)。

1分ごとに、前に出ているアプリの窓の名前だけを読む(画面の中身は見ない)。
覚えた決まり(window_rules)で入れ物を決め、同じ入れ物が続くあいだを1つの記録にする。
初めて見た窓は「確認してほしいこと」で聞き、答えたら窓の名前そのものは消す。
"""
import ctypes
import re
from ctypes import wintypes
from datetime import date, datetime, timedelta

GAP = timedelta(minutes=3)        # これより間があいたら、眠っていたとみなす
DONE_ASK_AFTER = timedelta(minutes=15)  # 「終わったタスクはある?」を聞く長さ(要件 F18 ③)
SELF_TITLE = "段取りさん"

APP_NAMES = {
    "code.exe": "VS Code", "chrome.exe": "Chrome", "msedge.exe": "Edge", "winword.exe": "Word",
    "excel.exe": "Excel", "powerpnt.exe": "PowerPoint", "explorer.exe": "エクスプローラー",
    "windowsterminal.exe": "ターミナル", "pycharm64.exe": "PyCharm", "idea64.exe": "IntelliJ", "notepad.exe": "メモ帳",
    "claude.exe": "Claude",
}
SUFFIXES = [" - Visual Studio Code", " - Google Chrome", " - Microsoft Edge", " - Word", " - Excel", " - PowerPoint", " - メモ帳"]
SKIP_TITLES = {"", "タスク スイッチング", "Program Manager", "スタート", "検索", "通知センター"}


# ---------- 窓を読む(Windows) ----------
def foreground():
    """(アプリ名, 窓の名前) を返す。ロック中など読めないとき(Windows 以外も)は None。"""
    if not hasattr(ctypes, "windll"):
        return None
    user32 = ctypes.windll.user32
    if not _desktop_is_input():
        return None
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return _app_name(pid.value), buf.value


def _desktop_is_input():
    """ロック画面のときは、ふだんの机(Default)に入力が来ていない。"""
    user32 = ctypes.windll.user32
    h = user32.OpenInputDesktop(0, False, 0x0100)  # DESKTOP_SWITCHDESKTOP
    if not h:
        return False
    user32.CloseDesktop(h)
    return True


def _app_name(pid):
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return "不明"
    try:
        size = wintypes.DWORD(260)
        buf = ctypes.create_unicode_buffer(260)
        if not k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return "不明"
        exe = buf.value.rsplit("\\", 1)[-1]
        return APP_NAMES.get(exe.lower(), exe.rsplit(".", 1)[0])
    finally:
        k32.CloseHandle(h)


# ---------- 決まり ----------
def key_of(app, title):
    """窓の名前から、覚える文字(決まりの候補)を取り出す。"""
    t = title
    for s in SUFFIXES:
        if t.endswith(s):
            t = t[: -len(s)]
    t = re.sub(r"^\(\d+\)\s*", "", t).strip()  # 「(3) 受信トレイ」の件数
    if app == "VS Code":
        parts = [p.strip() for p in t.split(" - ")]
        t = parts[-1] if len(parts) > 1 else parts[0]   # 開いているフォルダ
    elif app in ("Word", "Excel", "PowerPoint"):
        t = re.sub(r"\.(docx?|xlsx?|pptx?)$", "", t)    # ファイル名
    return t.strip(" ●*")


def match(con, app, title):
    """('container', id) / ('ignore', None) / ('unknown', 覚える文字) / ('skip', None)"""
    if title.strip() in SKIP_TITLES or SELF_TITLE in title:
        return ("skip", None)
    best = None
    low = title.lower()
    for r in con.execute("SELECT * FROM window_rules WHERE app = ?", (app,)):
        if r["pattern"].lower() in low and (best is None or len(r["pattern"]) > len(best["pattern"])):
            best = r
    if best is None:
        k = key_of(app, title)
        return ("unknown", k) if k else ("skip", None)
    return ("ignore", None) if best["ignore"] else ("container", best["container_id"])


# ---------- 1分ごと ----------
def _setting(con, key):
    r = con.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return r["value"] if r else None


def _set(con, key, value):
    con.execute("INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))


def current(con):
    return con.execute("SELECT * FROM work_logs WHERE ended_at IS NULL ORDER BY id DESC LIMIT 1").fetchone()


def _close(con, at):
    log = current(con)
    if not log:
        return
    started = datetime.fromisoformat(log["started_at"])
    if at <= started:
        con.execute("DELETE FROM work_logs WHERE id = ?", (log["id"],))  # 一瞬だけの記録は残さない
        return
    con.execute("UPDATE work_logs SET ended_at = ? WHERE id = ?", (at.isoformat(timespec="seconds"), log["id"]))
    if at - started >= DONE_ASK_AFTER:
        _maybe_ask_done(con, log["container_id"], at.date())


def _maybe_ask_done(con, cid, day):
    """入れ物の記録が15分以上続いて終わったら、1日1回「○○で終わったタスクはある?」(Q24)。"""
    if not con.execute("SELECT 1 FROM tasks WHERE container_id = ? AND done = 0", (cid,)).fetchone():
        return
    if con.execute("SELECT 1 FROM done_questions WHERE container_id = ? AND asked_on = ?", (cid, day.isoformat())).fetchone():
        return
    con.execute("INSERT INTO done_questions(container_id, asked_on) VALUES (?, ?)", (cid, day.isoformat()))


def _ask_window(con, app, key, now):
    title = f"{app}|{key}"
    if con.execute("SELECT 1 FROM pending_windows WHERE title = ?", (title,)).fetchone():
        return
    pid = con.execute("INSERT INTO pending_windows(title, first_seen) VALUES (?, ?)", (title, now.isoformat(timespec="seconds"))).lastrowid
    con.execute("INSERT INTO notices(kind, body, pending_window_id) VALUES ('window', ?, ?)", (f"{app} で開いている「{key}」は、どの授業・会社・開発の作業ですか?", pid))


def tick(con, sample, now=None):
    """sample は foreground() の結果。眠っていた・ロック中は記録しない。"""
    now = now or datetime.now()
    last = _setting(con, "worklog_last_tick")
    if last and now - datetime.fromisoformat(last) > GAP:
        _close(con, datetime.fromisoformat(last))  # 眠っていた時刻で止める
    _set(con, "worklog_last_tick", now.isoformat(timespec="seconds"))
    con.execute("INSERT INTO job_status(job, last_run_at) VALUES ('作業記録', ?) ON CONFLICT(job) DO UPDATE SET last_run_at = excluded.last_run_at, last_error = NULL", (now.isoformat(timespec="seconds"),))
    if sample is None:
        _close(con, now)
        return None
    app, title = sample
    kind, value = match(con, app, title)
    if kind == "skip":
        return None  # 段取りさん自身や空の窓のときは、今の記録をそのまま続ける
    if kind == "container":
        log = current(con)
        if log and log["container_id"] == value:
            return value
        _close(con, now)
        con.execute("INSERT INTO work_logs(container_id, started_at) VALUES (?, ?)", (value, now.isoformat(timespec="seconds")))
        return value
    _close(con, now)
    if kind == "unknown":
        _ask_window(con, app, value, now)
    return None


# ---------- 答える ----------
def answer_window(con, notice_id, container_id=None, ignore=False, pattern=None):
    n = con.execute("SELECT * FROM notices WHERE id = ? AND kind = 'window'", (notice_id,)).fetchone()
    if not n:
        raise ValueError("その質問はもうありません")
    pw = con.execute("SELECT * FROM pending_windows WHERE id = ?", (n["pending_window_id"],)).fetchone()
    app, key = pw["title"].split("|", 1) if pw else ("不明", "")
    pattern = (pattern or key).strip()
    if not pattern:
        raise ValueError("覚える文字を入れてください")
    if not ignore and not container_id:
        raise ValueError("どれの作業かを選んでください")
    con.execute("INSERT INTO window_rules(app, pattern, container_id, ignore) VALUES (?, ?, ?, ?)",
                (app, pattern, None if ignore else int(container_id), 1 if ignore else 0))
    # 窓の名前は個人的な文字が入ることがあるので、答えたら消す(Q23)
    con.execute("DELETE FROM pending_windows WHERE id = ?", (n["pending_window_id"],))
    con.execute("DELETE FROM notices WHERE id = ?", (notice_id,))


def open_done_questions(con, today=None):
    today = (today or date.today()).isoformat()
    out = []
    for q in con.execute("SELECT q.*, c.name FROM done_questions q JOIN containers c ON c.id = q.container_id WHERE q.answered = 0 AND q.asked_on = ?", (today,)):
        ts = con.execute("SELECT id, name FROM tasks WHERE container_id = ? AND done = 0 ORDER BY due_date IS NULL, due_date, created_at LIMIT 6", (q["container_id"],)).fetchall()
        if ts:
            out.append({"id": q["id"], "container": q["name"], "tasks": [dict(t) for t in ts]})
    return out


def elapsed_label(log, now=None):
    now = now or datetime.now()
    m = int((now - datetime.fromisoformat(log["started_at"])).total_seconds() // 60)
    return f"{m // 60}:{m % 60:02d}"
