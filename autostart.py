"""自動で動き出す仕組み(構想設計「自動で動き出す仕組み」、要件 F8)。

- ログインしたとき:スタートアップのフォルダに「段取りさん.bat」を置く
  (タスクスケジューラの「ログオン時」は管理者の権限が要り、ふだんの権限では登録できないため)
- 止まったとき:タスクスケジューラの「段取りさん(見回り)」が5分ごとに見て、止まっていたら動かし直す
どちらも keepalive.py を呼ぶ。keepalive.py は画面を開かない。
"""
import os
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
TASK = "段取りさん(見回り)"
STARTUP = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "段取りさん.bat"
LOGIN = "ログイン時(スタートアップ)"


def _pythonw():
    p = Path(sys.executable).with_name("pythonw.exe")
    return str(p if p.exists() else sys.executable)


def _run(args):
    return subprocess.run(["schtasks", *args], capture_output=True, text=True, encoding="cp932", errors="replace",
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def install():
    command = f'"{_pythonw()}" "{BASE_DIR / "keepalive.py"}"'
    r = _run(["/Create", "/F", "/TN", TASK, "/TR", command, "/SC", "MINUTE", "/MO", "5", "/RL", "LIMITED"])
    if r.returncode != 0:
        raise RuntimeError(f"{TASK} を登録できませんでした:{r.stderr.strip() or r.stdout.strip()}")
    # .bat は cmd が cp932 で読むので、その形で書く(フォルダの名前に日本語があるため)
    STARTUP.write_text(f'@echo off\r\ncd /d "{BASE_DIR}"\r\nstart "" "{_pythonw()}" keepalive.py\r\n', encoding="cp932")
    return status()


def remove():
    _run(["/Delete", "/F", "/TN", TASK])
    if STARTUP.exists():
        STARTUP.unlink()
    return status()


def status():
    """{名前: 登録されているか}。タスクは schtasks の確認の命令で本当に確かめる。"""
    return {LOGIN: STARTUP.exists(), TASK: _run(["/Query", "/TN", TASK]).returncode == 0}
