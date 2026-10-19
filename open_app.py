"""段取りさんの画面を開く(段取りさんを開く.bat から呼ぶ)。

本体が動いていなければ裏で動かし、Chrome の専用の窓(アドレス欄やタブのない窓)で開く。
Chrome が見つからないときだけ、既定のブラウザで開く。
"""
import json
import os
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

from app import HOST, PORT, code_version

BASE_DIR = Path(__file__).resolve().parent
URL = f"http://{HOST}:{PORT}/"
CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
]


def health():
    try:
        with urllib.request.urlopen(URL + "api/health", timeout=1) as res:
            return json.load(res) if res.status == 200 else None
    except (OSError, ValueError):
        return None


def is_running():
    return health() is not None


def stop_old_server():
    """コードが新しくなっていたら、前から動いている古い本体を止める(.bat を押せば新しいコードで開く)。"""
    h = health()
    if not h or h.get("version") == code_version():
        return
    pid = h.get("pid") or pid_on_port()  # 版の情報を返さない、とても古い本体はポートから探す
    if not pid:
        return
    subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    for _ in range(20):
        if not is_running():
            return
        time.sleep(0.25)


def pid_on_port():
    out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW).stdout
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[1] == f"{HOST}:{PORT}" and parts[3] == "LISTENING":
            return int(parts[4])
    return None


def start_server():
    """本体を裏で動かす。窓は出さない。"""
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    exe = str(pythonw if pythonw.exists() else sys.executable)
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    log = open(BASE_DIR / "run_log.txt", "a", encoding="utf-8")
    subprocess.Popen([exe, str(BASE_DIR / "app.py")], cwd=BASE_DIR, stdout=log, stderr=log, creationflags=flags)
    for _ in range(40):
        if is_running():
            return True
        time.sleep(0.25)
    return False


def open_window():
    for path in CHROME_PATHS:
        if os.path.exists(path):
            try:
                subprocess.Popen([path, f"--app={URL}", "--window-size=1200,820"])
                return
            except OSError:
                break
    webbrowser.open(URL)


def alert(text):
    """pythonw では画面に何も出ないので、困ったときだけ Windows の小窓で知らせる。"""
    import ctypes

    ctypes.windll.user32.MessageBoxW(None, text, "段取りさん", 0x30)


def main():
    try:
        stop_old_server()
        if not is_running() and not start_server():
            alert("段取りさんの本体を動かせませんでした。\nrun_log.txt に理由が残っています。")
            return
        open_window()
    except Exception:
        import traceback

        with open(BASE_DIR / "run_log.txt", "a", encoding="utf-8") as f:
            traceback.print_exc(file=f)
        alert("段取りさんを開けませんでした。\nrun_log.txt に理由が残っています。")


if __name__ == "__main__":
    main()
