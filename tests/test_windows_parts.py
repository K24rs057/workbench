"""Windows でしか動かない部分を、Windows の部品を作り物にして確かめる。

本物の通知・窓・Outlook・タスクスケジューラは、自分の PC で確かめる。ここでは、その部品に何を渡し、
返ってきたものをどう扱うかを見る。
"""
import json
import subprocess
import sys
import types
from datetime import datetime

import pytest

import db


@pytest.fixture
def win_flags(monkeypatch):
    """Windows にだけある subprocess の印を、ほかの OS でも使えるようにする。"""
    for name in ("CREATE_NO_WINDOW", "DETACHED_PROCESS", "CREATE_NEW_PROCESS_GROUP"):
        monkeypatch.setattr(subprocess, name, 0, raising=False)


# ---------- 裏の仕事(app.run_jobs_once) ----------
def test_jobs_keep_going_when_worklog_fails(db_path, monkeypatch):
    import app
    import autodone
    import gcal
    import gitlog
    import gmail
    import mails
    import notify
    import outlook
    import worklog

    db.init(db_path)
    called = []
    def broken():
        raise OSError("窓が読めない")
    monkeypatch.setattr(worklog, "foreground", broken)
    monkeypatch.setattr(notify, "check", lambda con: called.append("通知"))
    for mod, fn in ((outlook, "refresh"), (gmail, "refresh"), (gcal, "refresh"), (gitlog, "refresh"),
                    (mails, "run_claude_jobs"), (autodone, "run_jobs"), (autodone, "run_maybe")):
        monkeypatch.setattr(mod, fn, lambda con, _n=f"{mod.__name__}.{fn}": called.append(_n))
    app.run_jobs_once(db_path)
    assert called[0] == "通知"                                    # 作業記録が失敗しても、通知は出す
    assert "gitlog.refresh" in called and "autodone.run_maybe" in called
    with db.session(db_path) as con:
        row = con.execute("SELECT last_error FROM job_status WHERE job = '作業記録'").fetchone()
        assert "窓が読めない" in row["last_error"]


# ---------- Outlook(outlook.read_inbox) ----------
class _Exch:
    PrimarySmtpAddress = "teacher@example.ac.jp"


class _Sender:
    def GetExchangeUser(self):
        return _Exch()


class _Mail:
    def __init__(self, eid, received, subject, addr="", kind="SMTP"):
        self.EntryID, self.ReceivedTime, self.Subject = eid, received, subject
        self.SenderEmailAddress, self.SenderEmailType = addr, kind
        self.Sender, self.Body = _Sender(), "本文"


class _Report:
    """配信できなかったお知らせ。差出人の項目がない。"""
    def __init__(self, received):
        self.ReceivedTime, self.EntryID, self.Subject = received, "r1", "配信不能"

    @property
    def SenderEmailAddress(self):
        raise AttributeError("SenderEmailAddress")


class _Items(list):
    def Sort(self, key, desc):
        self.sorted = (key, desc)


def _fake_outlook(monkeypatch, items):
    calls = []
    com = types.SimpleNamespace(CoInitialize=lambda: calls.append("init"), CoUninitialize=lambda: calls.append("uninit"))
    ns = types.SimpleNamespace(GetDefaultFolder=lambda n: types.SimpleNamespace(Items=items))
    client = types.SimpleNamespace(Dispatch=lambda name: types.SimpleNamespace(GetNamespace=lambda kind: ns))
    monkeypatch.setitem(sys.modules, "pythoncom", com)
    monkeypatch.setitem(sys.modules, "win32com", types.SimpleNamespace(client=client))
    monkeypatch.setitem(sys.modules, "win32com.client", client)
    return calls


def test_read_inbox_skips_items_that_are_not_mail(monkeypatch):
    import outlook
    items = _Items([
        _Mail("m3", datetime(2026, 10, 19, 12, 0), "第10回課題", "office@example.ac.jp"),
        _Report(datetime(2026, 10, 19, 11, 0)),                         # これがあっても全体は止まらない
        _Mail("m2", datetime(2026, 10, 19, 10, 0), "休講", "/o=EX/cn=teacher", kind="EX"),
        _Mail("m1", datetime(2026, 10, 1, 9, 0), "古いメール", "office@example.ac.jp"),   # since より前で読み終わる
    ])
    calls = _fake_outlook(monkeypatch, items)
    got = outlook.read_inbox(datetime(2026, 10, 10))
    assert [(m["external_id"], m["sender"]) for m in got] == [
        ("outlook:m3", "office@example.ac.jp"),
        ("outlook:m2", "teacher@example.ac.jp"),                        # 学内(Exchange)の差出人はアドレスに直す
    ]
    assert items.sorted == ("[ReceivedTime]", True) and calls == ["init", "uninit"]


# ---------- Windows の通知(notify.show) ----------
def test_show_passes_text_by_utf8_file(monkeypatch, win_flags):
    import notify
    monkeypatch.delenv("DANDORI_NO_TOAST", raising=False)
    got = {}
    monkeypatch.setattr(notify.subprocess, "Popen", lambda cmd, **kw: got.update(cmd=cmd, kw=kw))
    notify.show("明日まで", "情報工学演習:第10回課題(締切 23:59)")
    cmd = got["cmd"]
    assert cmd[0] == "powershell" and str(notify.SCRIPT) in cmd and cmd[-2] == "-File"
    path = cmd[-1]
    with open(path, encoding="utf-8") as f:
        assert json.load(f) == {"title": "明日まで", "message": "情報工学演習:第10回課題(締切 23:59)"}
    import os
    os.unlink(path)


def test_show_is_silent_in_tests(monkeypatch):
    import notify
    monkeypatch.setenv("DANDORI_NO_TOAST", "1")
    monkeypatch.setattr(notify.subprocess, "Popen", lambda *a, **k: pytest.fail("通知を出してしまった"))
    notify.show("x", "y")


# ---------- 画面を開く(open_app)・見回り(keepalive) ----------
def test_stop_old_server_only_when_code_changed(monkeypatch, win_flags):
    import open_app
    killed = []
    monkeypatch.setattr(open_app.subprocess, "run", lambda cmd, **kw: killed.append(cmd))
    monkeypatch.setattr(open_app, "code_version", lambda: "200")
    monkeypatch.setattr(open_app, "health", lambda: {"version": "200", "pid": 42})
    open_app.stop_old_server()
    assert killed == []                                                  # 同じコードなら止めない
    state = {"up": True}
    monkeypatch.setattr(open_app, "health", lambda: {"version": "100", "pid": 42} if state["up"] else None)
    monkeypatch.setattr(open_app, "is_running", lambda: False)
    open_app.stop_old_server()
    assert killed == [["taskkill", "/PID", "42", "/F"]]


def test_pid_on_port_reads_netstat(monkeypatch, win_flags):
    import open_app
    out = f"""
  プロトコル  ローカル アドレス  外部アドレス  状態  PID
  TCP  0.0.0.0:135  0.0.0.0:0  LISTENING  1100
  TCP  {open_app.HOST}:{open_app.PORT}  0.0.0.0:0  LISTENING  5321
"""
    monkeypatch.setattr(open_app.subprocess, "run", lambda cmd, **kw: types.SimpleNamespace(stdout=out))
    assert open_app.pid_on_port() == 5321


def test_start_server_and_alert(monkeypatch, tmp_path, win_flags):
    import open_app
    monkeypatch.setattr(open_app, "BASE_DIR", tmp_path)
    monkeypatch.setattr(open_app.time, "sleep", lambda s: None)
    started = []
    monkeypatch.setattr(open_app.subprocess, "Popen", lambda cmd, **kw: started.append(cmd))
    monkeypatch.setattr(open_app, "is_running", lambda: bool(started))
    assert open_app.start_server() is True and started[0][-1].endswith("app.py")

    # 動かせなかったら、小窓で知らせて画面は開かない
    alerts, opened = [], []
    monkeypatch.setattr(open_app, "stop_old_server", lambda: None)
    monkeypatch.setattr(open_app, "is_running", lambda: False)
    monkeypatch.setattr(open_app, "start_server", lambda: False)
    monkeypatch.setattr(open_app, "alert", alerts.append)
    monkeypatch.setattr(open_app, "open_window", lambda: opened.append(1))
    open_app.main()
    assert alerts and "run_log.txt" in alerts[0] and opened == []


def test_open_window_prefers_chrome_app_window(monkeypatch, tmp_path):
    import open_app
    chrome = tmp_path / "chrome.exe"
    chrome.write_text("")
    got = []
    monkeypatch.setattr(open_app, "CHROME_PATHS", [str(tmp_path / "ない.exe"), str(chrome)])
    monkeypatch.setattr(open_app.subprocess, "Popen", lambda cmd, **kw: got.append(cmd))
    monkeypatch.setattr(open_app.webbrowser, "open", lambda url: got.append(["browser", url]))
    open_app.open_window()
    assert got[0][0] == str(chrome) and got[0][1] == f"--app={open_app.URL}"
    got.clear()
    monkeypatch.setattr(open_app, "CHROME_PATHS", [str(tmp_path / "ない.exe")])
    open_app.open_window()
    assert got == [["browser", open_app.URL]]                            # Chrome がなければ既定のブラウザ


def test_keepalive_starts_only_when_stopped(monkeypatch):
    import keepalive
    import open_app
    started = []
    monkeypatch.setattr(open_app, "stop_old_server", lambda: None)
    monkeypatch.setattr(open_app, "start_server", lambda: started.append(1))
    monkeypatch.setattr(open_app, "is_running", lambda: True)
    keepalive.main()
    assert started == []
    monkeypatch.setattr(open_app, "is_running", lambda: False)
    keepalive.main()
    assert started == [1]


# ---------- 自動起動の登録(autostart) ----------
def test_autostart_install_and_remove(monkeypatch, tmp_path):
    import autostart
    runs = []
    registered = {"on": False}
    def fake_run(args):
        runs.append(args)
        if args[0] == "/Create":
            registered["on"] = True
        if args[0] == "/Delete":
            registered["on"] = False
        ok = args[0] != "/Query" or registered["on"]
        return subprocess.CompletedProcess(args, 0 if ok else 1, "", "")
    monkeypatch.setattr(autostart, "_run", fake_run)
    monkeypatch.setattr(autostart, "STARTUP", tmp_path / "段取りさん.bat")
    st = autostart.install()
    assert st == {autostart.LOGIN: True, autostart.TASK: True}
    create = runs[0]
    assert create[:5] == ["/Create", "/F", "/TN", autostart.TASK, "/TR"] and "keepalive.py" in create[5]
    assert create[6:] == ["/SC", "MINUTE", "/MO", "5", "/RL", "LIMITED"]   # 5分ごと・ふだんの権限
    bat = (tmp_path / "段取りさん.bat").read_bytes().decode("cp932")      # cmd が読める形で書く
    assert "keepalive.py" in bat and str(autostart.BASE_DIR) in bat
    assert autostart.remove() == {autostart.LOGIN: False, autostart.TASK: False}


def test_autostart_install_failure(monkeypatch, tmp_path):
    import autostart
    monkeypatch.setattr(autostart, "_run", lambda args: subprocess.CompletedProcess(args, 1, "", "アクセスが拒否されました"))
    monkeypatch.setattr(autostart, "STARTUP", tmp_path / "段取りさん.bat")
    with pytest.raises(RuntimeError, match="アクセスが拒否されました"):
        autostart.install()
    assert not (tmp_path / "段取りさん.bat").exists()
