"""1行入力(要件 F17、基本設計 Q3・Q4・Q10・S1-6・S5-3a・API A2・AI ⑤)。

打った1行から、締切(日付・時刻)・入れ物・タスク名を読んで、その場でタスクにする。
- トグルがオフ(初め):本体が決まった書き方で読む(Q10)
- トグルがオン:claude -p に読ませる。失敗したら決まった書き方で読み直す(AI ⑤・Claude の案)
読めなかった所は、入れ物なら未分類、締切なら締切なしで入る(エラー時の動き)。
"""
import json
import re
from datetime import date, timedelta

import containers
import tasks
from containers import UserError

WEEK = "月火水木金土日"  # date.weekday() の順
AI_KEY = "quick_ai"       # トグルの状態(settings)
PAST_OK = 30              # 年のない日付が今日よりこれ以上前なら、来年の日付とみなす(Claude の案)

DAY_WORDS = {"今日": 0, "きょう": 0, "明日": 1, "あした": 1, "あす": 1, "明後日": 2, "あさって": 2}
WD_RE = re.compile(rf"^(来週|再来週)?の?([{WEEK}])(?:曜日?)?(?:まで)?$")
MD_RE = re.compile(r"^(?:(\d{4})[/-])?(\d{1,2})[/月](\d{1,2})日?(?:まで)?$")
D_RE = re.compile(r"^(\d{1,2})日(?:まで)?$")
AFTER_RE = re.compile(r"^(\d{1,2})日後(?:まで)?$")
HM_RE = re.compile(r"^(\d{1,2}):(\d{2})(?:まで)?$")
H_RE = re.compile(r"^(\d{1,2})時(半|(\d{1,2})分)?(?:まで)?$")
SEP_RE = re.compile(r"[\s　]+")

SYSTEM = """あなたは、タスク管理アプリに打たれた1行から、タスク名・締切・入れ物を読み取る係です。
- date は締切の日付(YYYY-MM-DD)。「金」「月末」「再来週の頭」など、どんな書き方でも今日の日付をもとに読む。書いていなければ null
- 曜日だけのときは、今日以降で一番近いその曜日(今日がその曜日なら今日)
- time は締切の時刻(HH:MM)。書いていなければ null
- container_id は、渡された入れ物の一覧のうち、名前の一部が書かれているものの番号。なければ null。一覧にない番号は使わない
- title は、締切と入れ物の名前を除いたタスクの名前。短く、打たれた言葉をそのまま使う
- 必ず指定の JSON の形で答える"""

SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "date": {"type": ["string", "null"]},
        "time": {"type": ["string", "null"]},
        "container_id": {"type": ["integer", "null"]},
    },
    "required": ["title", "date", "time", "container_id"],
}


# ---------- 決まった書き方 ----------
def _md(month, day, today, year=None):
    try:
        d = date(year or today.year, month, day)
    except ValueError:
        return None
    if not year and d < today - timedelta(days=PAST_OK):
        try:
            d = date(today.year + 1, month, day)
        except ValueError:
            return None
    return d


def read_date(word, today):
    """1語を締切の日付として読む。読めなければ None。"""
    if word in DAY_WORDS:
        return today + timedelta(days=DAY_WORDS[word])
    m = WD_RE.match(word)
    if m:
        # 「金」は、今週の範囲に関係なく今日以降で一番近い金曜(今日が金曜なら今日。Q4)
        d = today + timedelta(days=(WEEK.index(m.group(2)) - today.weekday()) % 7)
        return d + timedelta(days={None: 0, "来週": 7, "再来週": 14}[m.group(1)])
    m = MD_RE.match(word)
    if m:
        return _md(int(m.group(2)), int(m.group(3)), today, int(m.group(1)) if m.group(1) else None)
    m = AFTER_RE.match(word)
    if m:
        return today + timedelta(days=int(m.group(1)))
    m = D_RE.match(word)
    if m:
        # 「25日」は、今月の25日。もう過ぎていれば来月の25日
        dd = int(m.group(1))
        for k in range(3):
            y, mo = divmod(today.month - 1 + k, 12)
            try:
                d = date(today.year + y, mo + 1, dd)
            except ValueError:
                continue
            if d >= today:
                return d
    return None


def read_time(word):
    m = HM_RE.match(word)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
    else:
        m = H_RE.match(word)
        if not m:
            return None
        h = int(m.group(1))
        mi = 30 if m.group(2) == "半" else int(m.group(3) or 0)
    if h > 24 or mi > 59 or (h == 24 and mi):
        return None
    if h == 24:
        h, mi = 23, 59
    return f"{h:02d}:{mi:02d}"


def _choices(con):
    """読み取りに使う入れ物(終了していないもの。未分類は除く)。"""
    return [dict(r) for r in con.execute(
        "SELECT id, name FROM containers WHERE ended = 0 AND is_unsorted = 0 ORDER BY id")]


def _match_container(word, choices):
    """1語が入れ物の名前の一部(2文字以上)なら、その入れ物。いくつも当たるときは名前の短いもの。"""
    if len(word) < 2:
        return None
    hits = [c for c in choices if word.lower() in c["name"].lower() or c["name"].lower() == word.lower()]
    return min(hits, key=lambda c: (len(c["name"]), c["id"])) if hits else None


def _inside_word(word, choices):
    """1語の中に入れ物の名前(2文字以上)がそのまま入っていれば、その入れ物。いくつも当たるときは名前の長いもの。"""
    hits = [c for c in choices if len(c["name"]) >= 2 and c["name"].lower() in word.lower()]
    return max(hits, key=lambda c: (len(c["name"]), -c["id"])) if hits else None


def parse_rules(text, choices, today, fixed_container=False):
    """決まった書き方で読む。{"title", "date", "time", "container_id"} を返す。"""
    text = text.strip()
    rest = text
    cid = None
    if not fixed_container:
        # 空白を含む名前は1語ずつに分かれてしまうので、先に名前そのもの(前後が空白か端)を長い順に探す
        for c in sorted((c for c in choices if SEP_RE.search(c["name"])), key=lambda c: -len(c["name"])):
            m = re.search(rf"(?:^|(?<=[\s\u3000])){re.escape(c['name'])}(?=$|[\s\u3000])", rest, re.IGNORECASE)
            if m:
                rest = rest[:m.start()] + " " + rest[m.end():]
                cid = c["id"]
                break
    d = tm = None
    title = []
    for w in SEP_RE.split(rest.strip()):
        if not w:
            continue
        if d is None and (got := read_date(w, today)):
            d = got
            continue
        if tm is None and (got := read_time(w)):
            tm = got
            continue
        if cid is None and not fixed_container and (c := _match_container(w, choices)):
            cid = c["id"]
            continue
        if cid is None and not fixed_container and (c := _inside_word(w, choices)):
            cid = c["id"]  # 「卒論の資料を読む」:入れ物は卒論に。語はタスク名に残す
        title.append(w)
    name = " ".join(title) or text
    if tm and not d:
        d = today  # 時刻だけなら今日のその時刻(Claude の案)
    return {"title": name, "date": d.isoformat() if d else None, "time": tm, "container_id": cid}


# ---------- Claude ----------
def parse_ai(text, choices, today, runner=None):
    import agent
    runner = runner or (lambda s, p: agent.call_claude(s, p, SCHEMA))
    prompt = json.dumps({"today": today.isoformat(), "weekday": WEEK[today.weekday()] + "曜",
                         "text": text, "containers": choices}, ensure_ascii=False)
    res = runner(SYSTEM, prompt) or {}
    out = {"title": (res.get("title") or "").strip() or text.strip(), "date": None, "time": None, "container_id": None}
    if isinstance(res.get("date"), str) and tasks.DATE_RE.match(res["date"]):
        try:
            out["date"] = date.fromisoformat(res["date"]).isoformat()
        except ValueError:
            pass
    if isinstance(res.get("time"), str) and out["date"]:
        out["time"] = read_time(res["time"])
    if res.get("container_id") in {c["id"] for c in choices}:  # 一覧にない番号は捨てる
        out["container_id"] = res["container_id"]
    return out


# ---------- タスクにする ----------
def ai_on(con):
    r = con.execute("SELECT value FROM settings WHERE key = ?", (AI_KEY,)).fetchone()
    return bool(r and r["value"] == "1")


def set_ai(con, on):
    con.execute("INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (AI_KEY, "1" if on else "0"))


def add(con, text, use_ai=False, container_id=None, today=None, runner=None):
    """1行からタスクを作る。作ったタスクと、どう読んだかを返す。"""
    text = (text or "").strip()
    if not text:
        raise UserError("タスクを1行で打ってください(例:「金 レポート 卒論」)")
    today = today or date.today()
    fixed = container_id is not None
    if fixed:
        containers.get_row(con, int(container_id))
    choices = _choices(con)
    how = "rules"
    got = None
    if use_ai:
        import agent
        try:
            got = parse_ai(text, choices, today, runner)
            how = "ai"
        except agent.UsageLimit:
            how = "limit"
        except agent.AgentError:
            how = "fallback"
    if got is None:
        got = parse_rules(text, choices, today, fixed_container=fixed)
    cid = int(container_id) if fixed else (got["container_id"] or containers.unsorted_id(con))
    tid = tasks.add(con, {"container_id": cid, "name": got["title"], "due_date": got["date"], "due_time": got["time"]})
    t = tasks.get(con, tid)
    cname = con.execute("SELECT name, is_unsorted FROM containers WHERE id = ?", (cid,)).fetchone()
    return {"task": tasks.to_json(con, t), "how": how, "container": cname["name"], "unsorted": bool(cname["is_unsorted"])}
