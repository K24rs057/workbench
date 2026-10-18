"""段取りさんの画面を開く(段取りさんを開く.bat から呼ぶ)。

本体が動いていなければ裏で動かし、Chrome の専用の窓(アドレス欄やタブのない窓)で開く。
Chrome が見つからないときだけ、既定のブラウザで開く。
"""
import os
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

from app import HOST, PORT

BASE_DIR = Path(__file__).resolve().parent
URL = f"http://{HOST}:{PORT}/"
CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
]


def is_running():
    try:
        with urllib.request.urlopen(URL + "api/health", timeout=1) as res:
            return res.status == 200
    except OSError:
        return False


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


def main():
    if not is_running():
        start_server()
    open_window()


if __name__ == "__main__":
    main()
