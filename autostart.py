"""自動で動き出す仕組み(構想設計「自動で動き出す仕組み」、要件 F8)。

タスクスケジューラに2つ登録する。
- 段取りさん(ログイン時):ログインしたら本体を動かす
- 段取りさん(見回り):5分ごとに、本体が止まっていたら動かし直す
どちらも keepalive.py を呼ぶ。keepalive.py は画面を開かない。
"""
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
TASKS = {"段取りさん(ログイン時)": ["/SC", "ONLOGON"], "段取りさん(見回り)": ["/SC", "MINUTE", "/MO", "5"]}


def _pythonw():
    p = Path(sys.executable).with_name("pythonw.exe")
    return str(p if p.exists() else sys.executable)


def _run(args):
    return subprocess.run(["schtasks", *args], capture_output=True, text=True, encoding="cp932", errors="replace",
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def install():
    command = f'"{_pythonw()}" "{BASE_DIR / "keepalive.py"}"'
    for name, sched in TASKS.items():
        r = _run(["/Create", "/F", "/TN", name, "/TR", command, *sched, "/RL", "LIMITED"])
        if r.returncode != 0:
            raise RuntimeError(f"{name} を登録できませんでした:{r.stderr.strip() or r.stdout.strip()}")
    return status()


def remove():
    for name in TASKS:
        _run(["/Delete", "/F", "/TN", name])
    return status()


def status():
    """{タスク名: 登録されているか}。schtasks の確認の命令で本当に確かめる。"""
    return {name: _run(["/Query", "/TN", name]).returncode == 0 for name in TASKS}
