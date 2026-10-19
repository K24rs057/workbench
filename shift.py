"""シフト表の写真の読み取り(要件 F14、基本設計 AI ⑥・S2-2・S2-2a、API A20・A21)。

写真は「予定」の画面に落とす。Claude(claude -p)には、写真1枚だけを置いた空のフォルダで「ファイルを読む」道具だけを渡す。
写真・読み取った結果・ほかのスタッフの名前は残さない(読み終えたらフォルダごと消す)。
シフト表での自分の名前は data/ の DB(settings)にだけ置く。
"""
import json
import shutil
import subprocess
import tempfile
from datetime import date
from pathlib import Path

import gcal
import mails

KEY = "shift_name"
EXTS = {".jpg": ".jpg", ".jpeg": ".jpg", ".png": ".png", ".webp": ".webp", ".heic": ".heic", ".gif": ".gif"}
MAX_BYTES = 15 * 1024 * 1024
TIMEOUT = 180
SCHEMA = {"type": "object", "properties": {"shifts": {"type": "array", "items": {"type": "object", "properties": {
    "date": {"type": "string"}, "start": {"type": "string"}, "end": {"type": "string"}}, "required": ["date", "start", "end"]}}},
    "required": ["shifts"]}
SYSTEM = ("あなたはアルバイトのシフト表の写真から、1人の人のシフトだけを読み取る係です。"
          "写真のファイルを Read で読み、name の人の行(または列)だけを見る。ほかの人の名前やシフトは答えに入れない。"
          "date は YYYY-MM-DD(年が書いていなければ today に近い年)、start と end は HH:MM。休みの日は入れない。"
          "読み取れなければ shifts は空。説明はしない。")


class ShiftError(Exception):
    pass


def name(con):
    return mails.setting(con, KEY) or ""


def set_name(con, value):
    v = (value or "").strip()
    if v:
        mails.set_setting(con, KEY, v[:40])
    else:
        con.execute("DELETE FROM settings WHERE key = ?", (KEY,))


def _run_claude(folder, filename, who, today):
    """写真を置いたフォルダで claude -p を動かす。渡す道具は Read だけ。"""
    import agent
    prompt = json.dumps({"photo": filename, "name": who, "today": today.isoformat()}, ensure_ascii=False)
    cmd = ["claude", "-p", "--output-format", "json", "--tools", "Read", "--allowedTools", "Read", "--strict-mcp-config",
           "--no-session-persistence", "--system-prompt", SYSTEM, "--json-schema", json.dumps(SCHEMA, ensure_ascii=False)]
    try:
        r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8", timeout=TIMEOUT, cwd=folder,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired) as e:
        raise agent.AgentError(str(e))
    out = (r.stdout or "") + (r.stderr or "")
    try:
        data = json.loads(r.stdout)
    except ValueError:
        raise (agent.UsageLimit if "limit" in out.lower() else agent.AgentError)(out[:200])
    if data.get("is_error"):
        text = str(data.get("result", ""))
        raise (agent.UsageLimit if "limit" in text.lower() else agent.AgentError)(text[:200])
    res = data.get("structured_output")
    if not isinstance(res, dict):
        try:
            res = json.loads(data.get("result", ""))
        except ValueError:
            raise agent.AgentError("答えの形がちがいます")
    return res


def read_photo(con, data, filename, runner=None, today=None):
    """写真のバイト列から、自分のシフト [{date, start, end}] を返す。写真はその場で消す。"""
    import agent
    who = name(con)
    if not who:
        raise ShiftError("先に、設定の「メールと連絡」で「シフト表での自分の名前」を入れてください")
    ext = EXTS.get(Path(filename or "").suffix.lower())
    if not ext:
        raise ShiftError("写真(JPG・PNG など)を落としてください")
    if not data or len(data) > MAX_BYTES:
        raise ShiftError("写真が大きすぎるか、空です")
    today = today or date.today()
    folder = tempfile.mkdtemp(prefix="dandori-shift-")
    try:
        p = Path(folder) / ("shift" + ext)
        p.write_bytes(data)
        try:
            res = (runner or _run_claude)(folder, p.name, who, today)
        except agent.UsageLimit:
            raise ShiftError("Claude の使用量の上限に当たっています。しばらくしてから、もう一度落としてください")
        except agent.AgentError:
            raise ShiftError("読み取れませんでした。もう一度落とすか、自分で入れてください")
    finally:
        shutil.rmtree(folder, ignore_errors=True)  # 写真は残さない
    return clean(res.get("shifts") or [])


def clean(rows):
    out = []
    for r in rows[:62]:
        try:
            d = date.fromisoformat(str(r.get("date")))
        except ValueError:
            continue
        s, e = r.get("start"), r.get("end")
        if not (isinstance(s, str) and gcal.HM_RE.match(s) and isinstance(e, str) and gcal.HM_RE.match(e)):
            continue
        out.append({"date": d.isoformat(), "start": _pad(s), "end": _pad(e)})
    return sorted(out, key=lambda x: (x["date"], x["start"]))


def _pad(hm):
    h, m = hm.split(":")
    return f"{int(h):02d}:{m}"


def title(con, baito_id=None):
    """予定の名前。バイト先が1つならそれ、2つ以上なら選んだもの、0なら「バイト」だけ(2026-10-20 決定 C)。"""
    places = con.execute("SELECT id, name FROM baito_places ORDER BY id").fetchall()
    if not places:
        return "バイト"
    if len(places) == 1:
        return f"バイト({places[0]['name']})"
    pick = next((p for p in places if p["id"] == baito_id), None)
    if not pick:
        raise ShiftError("どのバイト先のシフトかを選んでください")
    return f"バイト({pick['name']})"


def commit(con, api, items, shifts, summary):
    """[書き込む]。F13 と同じ決まりで、重なる予定があれば書かず、同じ予定がもうあれば書かない。
    返すもの: {"written": [...], "skipped": [{date, start, end, reason}]}"""
    written, skipped = [], []
    for s in clean(shifts):
        if s["end"] <= s["start"]:
            skipped.append({**s, "reason": "終わりの時刻が始まりより前です"})
            continue
        hit = gcal.overlaps(items, s["date"], s["start"], s["end"])
        if any(h["name"] == summary and h["start"] == s["start"] for h in hit):
            skipped.append({**s, "reason": "もう入っています"})
            continue
        if hit:
            skipped.append({**s, "reason": f"重なる予定があります({hit[0]['name']})"})
            continue
        ev = api.insert(gcal._timed_body(s["date"], s["start"], s["end"], summary, {"dandori": "shift"}))
        gcal.remember(ev)
        items = items + [gcal.normalize(ev)]
        written.append(s)
    return {"written": written, "skipped": skipped}
