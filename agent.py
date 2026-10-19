"""モッチ(要件 F22、基本設計 Q31〜Q34・AI ⑧)。

話しかけられたら、段取りさんのデータの要約と会話の続きを claude -p に渡して答えを作る。
claude -p には道具を1つも渡さない(--tools "")。操作が要るときは「やりたい操作」を JSON で返させ、
画面の確認ボタンが押されたときだけ、本体がその操作をする(Q34)。
メールの本文・大学のアドレスの形・鍵は渡さない。
"""
import json
import subprocess
import tempfile
from datetime import date, datetime, timedelta

import containers
import tasks
import timetable

KEEP = timedelta(days=7)        # 最後に話してから7日で消す(Q32)
HISTORY = 12                    # 渡す会話の数
TIMEOUT = 120
FAIL_TEXT = "うまく答えられなかった。もう一度話しかけてね"
LIMIT_TEXT = "使用量の上限に来ちゃったみたい。少し時間をおいてから、また話しかけてね"

SYSTEM = """あなたは、予定とタスクの管理アプリ「段取りさん」の中にいるキャラクター「モッチ」です。
まるいおもちのような、のんびりした性格で、やさしい話し言葉(「〜だよ」「〜してね」)で、短く答えます。
- 答えは、渡されたデータ(タスク・作業時間・時間割)だけをもとにする。知らないことは知らないと言う
- 使い方を聞かれたら、画面の名前(トップ・予定・連絡・授業・会社・開発・設定)を使って説明する
- タスクを足す・直す・消す、タスクを押したときに開くページを変える、が必要なときだけ action を返す。
  勝手に実行されることはなく、本人が確認のボタンを押したときだけ実行される。label には「この3つを足す」のように、ボタンに出す短い文を入れる
- メールを送る、ログインする、設定を変える、ファイルをさわることはできない。頼まれたら、できないと答える
- 日付は YYYY-MM-DD、時刻は HH:MM。container_id と task_id は、渡されたデータにある番号だけを使う
- 必ず指定の JSON の形で答える"""

TOOLS = {
    "add_tasks": "タスクを足す。args: {\"tasks\": [{\"container_id\": 番号, \"name\": 名前, \"due_date\": 日付かnull, \"due_time\": 時刻かnull, \"start_date\": 着手日かnull}]}",
    "update_task": "タスクを直す。args: {\"task_id\": 番号, \"name\"?, \"due_date\"?, \"due_time\"?, \"start_date\"?, \"done\"?, \"container_id\"?}",
    "delete_task": "タスクを消す。args: {\"task_id\": 番号}",
    "set_task_link": "タスクを押したときに開くページを変える。args: {\"task_id\": 番号, \"url\": URL}",
}

SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {"type": "string"},
        "action": {
            "anyOf": [
                {"type": "null"},
                {"type": "object", "properties": {
                    "tool": {"type": "string", "enum": list(TOOLS)},
                    "args": {"type": "object"},
                    "label": {"type": "string"},
                }, "required": ["tool", "args", "label"]},
            ]
        },
    },
    "required": ["reply", "action"],
}


class AgentError(Exception):
    pass


class UsageLimit(AgentError):
    pass


# ---------- claude -p ----------
def call_claude(system, prompt, schema=SCHEMA):
    """claude -p を道具なしで1回呼び、決まった形の答え(dict)を返す。"""
    cmd = ["claude", "-p", "--output-format", "json", "--tools", "", "--strict-mcp-config", "--no-session-persistence",
           "--system-prompt", system, "--json-schema", json.dumps(schema, ensure_ascii=False)]
    try:
        r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8", timeout=TIMEOUT,
                           cwd=tempfile.gettempdir(), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired) as e:
        raise AgentError(str(e))
    out = (r.stdout or "") + (r.stderr or "")
    try:
        data = json.loads(r.stdout)
    except ValueError:
        if "limit" in out.lower():
            raise UsageLimit(out[:200])
        raise AgentError(out[:200])
    if data.get("is_error"):
        text = str(data.get("result", ""))
        if "limit" in text.lower():
            raise UsageLimit(text[:200])
        raise AgentError(text[:200])
    result = data.get("structured_output")
    if not isinstance(result, dict):
        try:
            result = json.loads(data.get("result", ""))
        except ValueError:
            raise AgentError("答えの形がちがいます")
    return result


# ---------- 渡すもの ----------
def context(con, screen, today=None):
    today = today or date.today()
    timetable.refresh(con)
    rows = con.execute(
        """SELECT t.id, t.name, t.due_date, t.due_time, t.start_date, t.container_id, c.name AS container FROM tasks t
           JOIN containers c ON c.id = t.container_id WHERE t.done = 0 AND c.ended = 0
           ORDER BY t.due_date IS NULL, t.due_date, t.due_time LIMIT 80"""
    ).fetchall()
    ov = containers.overview(con, today)
    week = [{"name": i["name"], "this_week": i["week_label"], "left": i["left"]} for k in ov["kinds"] for i in k["items"]]
    cons = [{"id": i["id"], "name": i["name"], "kind": k["name"]} for k in ov["kinds"] for i in k["items"]]
    cons.append({"id": ov["unsorted_id"], "name": "未分類", "kind": "なし"})
    return {
        "today": f"{today.isoformat()}({'月火水木金土日'[today.weekday()]})",
        "screen": screen,
        "containers": cons,
        "open_tasks": [dict(r) for r in rows],
        "work_time": week,
        "classes_today": [c["name"] + " " + c["start"] for c in timetable.classes_on(con, today)],
        "classes_tomorrow": [c["name"] + " " + c["start"] for c in timetable.classes_on(con, today + timedelta(days=1))],
        "questions_waiting": con.execute("SELECT COUNT(*) FROM notices WHERE answered = 0").fetchone()[0],
    }


def prune(con, now=None):
    now = now or datetime.now()
    last = con.execute("SELECT MAX(created_at) FROM agent_messages").fetchone()[0]
    if last and now - datetime.fromisoformat(last) > KEEP:
        con.execute("DELETE FROM agent_messages")


def messages(con):
    prune(con)
    return [dict(r) | {"action": json.loads(r["action"]) if r["action"] else None}
            for r in con.execute("SELECT * FROM agent_messages ORDER BY id")]


def _add(con, role, text, screen=None, action=None, state=None):
    return con.execute(
        "INSERT INTO agent_messages(role, text, screen, action, action_state, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (role, text, screen, json.dumps(action, ensure_ascii=False) if action else None, state,
         datetime.now().isoformat(timespec="seconds")),
    ).lastrowid


def _valid(con, action):
    """渡していない道具・ない番号・形の崩れた操作は捨てる(エラー「モッチの操作が…」)。"""
    if not isinstance(action, dict) or action.get("tool") not in TOOLS or not isinstance(action.get("args"), dict):
        return None
    a, tool = action["args"], action["tool"]
    task_ok = lambda tid: isinstance(tid, int) and con.execute("SELECT 1 FROM tasks WHERE id = ?", (tid,)).fetchone()
    cont_ok = lambda cid: isinstance(cid, int) and con.execute("SELECT 1 FROM containers WHERE id = ?", (cid,)).fetchone()
    if tool == "add_tasks":
        ts = a.get("tasks")
        if not isinstance(ts, list) or not ts or not all(isinstance(t, dict) and t.get("name") and cont_ok(t.get("container_id")) for t in ts):
            return None
    elif tool in ("update_task", "delete_task", "set_task_link"):
        if not task_ok(a.get("task_id")):
            return None
        if tool == "set_task_link" and not str(a.get("url", "")).startswith(("http://", "https://")):
            return None
        if tool == "update_task" and "container_id" in a and not cont_ok(a["container_id"]):
            return None
    return {"tool": tool, "args": a, "label": str(action.get("label") or "これをする")[:40]}


def ask(con, text, screen, runner=call_claude):
    text = (text or "").strip()
    if not text:
        raise AgentError("話しかける言葉を入れてください")
    prune(con)
    history = [{"role": r["role"], "text": r["text"]} for r in
               con.execute("SELECT role, text FROM agent_messages ORDER BY id DESC LIMIT ?", (HISTORY,))][::-1]
    _add(con, "自分", text, screen)
    prompt = json.dumps({"data": context(con, screen), "conversation": history, "message": text}, ensure_ascii=False)
    prompt = "次の JSON の message に、data と conversation をふまえて答えてください。\n" + prompt
    try:
        result = runner(SYSTEM + "\n\n使える操作:\n" + "\n".join(f"- {k}: {v}" for k, v in TOOLS.items()), prompt)
        reply = str(result.get("reply") or "").replace("\\n", "\n").strip() or FAIL_TEXT  # 「\n」が文字のまま来ることがある
        action = _valid(con, result.get("action"))
    except UsageLimit:
        reply, action = LIMIT_TEXT, None
    except AgentError:
        reply, action = FAIL_TEXT, None
    return _add(con, "モッチ", reply, screen, action, "待ち" if action else None)


def confirm(con, mid):
    m = con.execute("SELECT * FROM agent_messages WHERE id = ?", (mid,)).fetchone()
    if not m or m["action_state"] != "待ち":
        raise AgentError("その操作はもう終わっています")
    a = json.loads(m["action"])
    args, tool = a["args"], a["tool"]
    if tool == "add_tasks":
        for t in args["tasks"]:
            tasks.add(con, {"container_id": t["container_id"], "name": t["name"],
                            "due_date": t.get("due_date") or None, "due_time": t.get("due_time") or None,
                            "start_date": t.get("start_date") or None})
        done = f"タスクを{len(args['tasks'])}つ足したよ"
    elif tool == "update_task":
        fields = {k: v for k, v in args.items() if k in ("name", "due_date", "due_time", "start_date", "done", "container_id")}
        tasks.update(con, args["task_id"], fields)
        done = "直したよ"
    elif tool == "delete_task":
        tasks.delete(con, args["task_id"])
        done = "消したよ"
    else:
        tasks.update(con, args["task_id"], {"open_url": args["url"]})
        done = "開くページを変えたよ"
    con.execute("UPDATE agent_messages SET action_state = 'した' WHERE id = ?", (mid,))
    _add(con, "モッチ", done)


def cancel(con, mid):
    con.execute("UPDATE agent_messages SET action_state = 'やめた' WHERE id = ? AND action_state = '待ち'", (mid,))
    _add(con, "モッチ", "やめたよ。何も変えていないよ")


def clear(con):
    con.execute("DELETE FROM agent_messages")


# ---------- モッチの設定(S6-7・Q31) ----------
DEFAULTS = {"mochi_bubble": "1", "mochi_idle": "1", "mochi_pos_wide": "", "mochi_pos_narrow": ""}


def get_settings(con):
    out = dict(DEFAULTS)
    for r in con.execute("SELECT key, value FROM settings WHERE key LIKE 'mochi_%'"):
        out[r["key"]] = r["value"]
    return out


def set_settings(con, values):
    for k, v in values.items():
        if k in DEFAULTS:
            con.execute("INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)", (k, str(v)))


def hint(con, today=None):
    """遅れている締切があるときだけ、ひとことを返す(S7-4)。"""
    today = (today or date.today()).isoformat()
    r = con.execute(
        "SELECT t.name FROM tasks t JOIN containers c ON c.id = t.container_id WHERE t.done = 0 AND c.ended = 0 AND t.due_date < ? ORDER BY t.due_date LIMIT 1",
        (today,),
    ).fetchone()
    return f"「{r['name']}」が遅れてるよ。今日のうちに出しちゃう?" if r else None
