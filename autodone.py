"""自動で完了(要件 F18 ① ② ④、基本設計 Q12〜Q14・AI ④)。③「終わった?」は worklog.py。

① 提出を受け付けたメール(学習サイト・Forms・企業から直接のエントリー受付)
② git のコミットのメッセージの「完了:」
→ どのタスクのものかを Claude(claude -p)に、まだ終わっていないタスクの一覧から1つ選ばせ、すぐ完了にする。
   当てはまるものがなければ完了にせず、④の「終わっていそう」に回す。
④ 1日1回、Claude がメールの件名・コミット・作業時間を見て「終わっていそう」を出す。自分が [完了] を押す。
"""
import json
import re
from datetime import date, datetime, timedelta

import gcal
import mails
import tasks

KIND = "完了の合図"
TRIES = 3
PER_RUN = 5
MAX_TASKS = 80  # Claude に渡すタスクの数の上限
ENTRY_WORDS = ("エントリー完了", "エントリーを受け付けました", "ご応募ありがとう")  # Q13 ウ
NOT_ENTRY = ("受付中", "受付開始")
DONE_MARK = re.compile(r"完了\s*[:：]")

PICK_SCHEMA = {"type": "object", "properties": {"task_id": {"type": ["integer", "null"]}}, "required": ["task_id"]}
PICK_SYSTEM = ("あなたは、提出の受付メールやコミットが、どのタスクを終えた合図かを選ぶ係です。"
               "tasks の中から当てはまるものを1つだけ選び、その id を task_id に入れる。"
               "はっきり当てはまるものがなければ task_id は null。推測で選ばない。説明はしない。")
MAYBE_SCHEMA = {"type": "object", "properties": {"maybe_done": {"type": "array", "items": {"type": "object", "properties": {
    "task_id": {"type": "integer"}, "reason": {"type": "string"}}, "required": ["task_id", "reason"]}}}, "required": ["maybe_done"]}
MAYBE_SYSTEM = ("あなたは、まだ完了になっていないタスクのうち、もう終わっていそうなものを選ぶ係です。"
                "mails(届いたメールの件名)・commits(git のコミット)・work(入れ物ごとの作業時間)を見て、"
                "終わったとはっきり読み取れるタスクだけを maybe_done に入れる。reason は「○○の提出メールが届いた」のように短く1文。"
                "なければ空。説明はしない。")


def is_entry(subject):
    return any(w in subject for w in ENTRY_WORDS) and not any(w in subject for w in NOT_ENTRY)


def mail_signal(con, msg):
    """取り込んだメールが①の合図なら、その種類(auto_done_by に入れる名前)。ちがえば None。"""
    cat = msg["category"]
    if cat == "提出受付":
        return "提出受付"
    if cat == "Forms":
        return "Forms"
    if cat == "企業" and msg.get("container_id") and is_entry(msg["subject"]):
        c = con.execute("SELECT company_domain FROM containers WHERE id = ?", (msg["container_id"],)).fetchone()
        dom = c["company_domain"] if c else None
        if dom and msg["sender"].lower().endswith("@" + dom):  # 企業から直接届いたものだけ。就活サイト経由は入れない
            return "エントリー受付"
    return None


def queue(con, target):
    if not con.execute("SELECT 1 FROM claude_jobs WHERE kind = ? AND target = ?", (KIND, target)).fetchone():
        con.execute("INSERT INTO claude_jobs(kind, target, tries, next_try_at) VALUES (?, ?, 0, NULL)", (KIND, target))


def is_done_commit(message):
    return bool(DONE_MARK.search(message or ""))


def _open_tasks(con, cid=None):
    sql = ("SELECT t.id, t.name, t.due_date, c.name AS container FROM tasks t JOIN containers c ON c.id = t.container_id "
           "WHERE t.done = 0 AND c.ended = 0")
    args = ()
    if cid:
        sql += " AND t.container_id = ?"
        args = (cid,)
    sql += " ORDER BY t.due_date IS NULL, t.due_date, t.id LIMIT ?"
    return [dict(r) for r in con.execute(sql, (*args, MAX_TASKS))]


def _signal(con, target):
    """claude_jobs の target から、合図の中身。もうなければ None。"""
    kind, _, sid = target.partition(":")
    if kind == "mail":
        m = con.execute("SELECT * FROM messages WHERE id = ?", (int(sid),)).fetchone()
        if not m:
            return None
        by = mail_signal(con, dict(m))
        return {"by": by or "提出受付", "text": m["subject"], "cid": None, "source": f"メール「{m['subject']}」"}
    if kind == "commit":
        r = con.execute("SELECT * FROM commits WHERE id = ?", (int(sid),)).fetchone()
        if not r or r["hidden"]:
            return None
        return {"by": "コミット", "text": r["message"], "cid": r["container_id"], "source": f"コミット「{r['message']}」"}
    return None


def complete(con, tid, by, source, now=None):
    """自動で完了にして、連絡の「確認してほしいこと」にお知らせを1件入れる(Q14)。"""
    t = con.execute("SELECT t.*, c.name AS container FROM tasks t JOIN containers c ON c.id = t.container_id WHERE t.id = ?", (tid,)).fetchone()
    if not t or t["done"]:
        return False
    tasks.set_done(con, tid, True, now=now)
    con.execute("UPDATE tasks SET auto_done_by = ? WHERE id = ?", (by, tid))
    con.execute("INSERT INTO notices(kind, body, task_id) VALUES ('自動で完了', ?, ?)",
                (f"「{t['name']}」({t['container']})を自動で完了にしました。もとになったもの: {source}", tid))
    gcal.mark_dirty(con)  # カレンダーの締切に「済」をつける
    return True


def _to_maybe(con, tid, reason):
    if not con.execute("SELECT 1 FROM maybe_done WHERE task_id = ? AND resolved = 0", (tid,)).fetchone():
        con.execute("INSERT INTO maybe_done(task_id, reason) VALUES (?, ?)", (tid, reason[:200]))


def run_jobs(con, runner=None, now=None):
    """たまった①②の合図を、上限まで Claude に見分けさせる。"""
    import agent
    runner = runner or (lambda s, p: agent.call_claude(s, p, PICK_SCHEMA))
    now = now or datetime.now()
    jobs = con.execute("SELECT * FROM claude_jobs WHERE kind = ? AND (next_try_at IS NULL OR next_try_at <= ?) ORDER BY id LIMIT ?",
                       (KIND, now.isoformat(timespec="seconds"), PER_RUN)).fetchall()
    n = 0
    for j in jobs:
        sig = _signal(con, j["target"])
        cands = _open_tasks(con, sig["cid"]) if sig else []
        if not sig or not cands:
            con.execute("DELETE FROM claude_jobs WHERE id = ?", (j["id"],))
            continue
        prompt = json.dumps({"signal": sig["text"], "kind": sig["by"], "tasks": cands}, ensure_ascii=False)
        try:
            res = runner(PICK_SYSTEM, prompt) or {}
        except agent.UsageLimit:
            mails.set_setting(con, "claude_limited_at", now.isoformat(timespec="seconds"))
            break
        except agent.AgentError as e:
            tries = j["tries"] + 1
            if tries >= TRIES:  # 3回続けて失敗 → 2段目④に出す(Q6)
                mails.set_setting(con, "autodone_error", f"Claude が完了の合図({sig['source']})を読み取れませんでした")
                con.execute("DELETE FROM claude_jobs WHERE id = ?", (j["id"],))
            else:
                con.execute("UPDATE claude_jobs SET tries = ?, next_try_at = ?, last_error = ? WHERE id = ?",
                            (tries, (now + timedelta(minutes=10)).isoformat(timespec="seconds"), str(e)[:200], j["id"]))
            continue
        tid = res.get("task_id")
        ids = {c["id"] for c in cands}
        if isinstance(tid, int) and tid in ids:
            complete(con, tid, sig["by"], sig["source"], now=now)
        else:  # 当てはまるものがない → 完了にせず、次の「終わっていそう」で見る材料に残す
            mails.set_setting(con, "maybe_hint", (mails.setting(con, "maybe_hint") or "")[-1500:] + "\n" + sig["source"])
        con.execute("DELETE FROM claude_jobs WHERE id = ?", (j["id"],))
        n += 1
    return n


# ---------- ④ 終わっていそう(AI ④) ----------
def run_maybe(con, runner=None, now=None):
    """1日1回、その日最初に動いたとき。失敗したら次の日にやり直す(Q6)。出した件数を返す。"""
    import agent
    runner = runner or (lambda s, p: agent.call_claude(s, p, MAYBE_SCHEMA))
    now = now or datetime.now()
    today = now.date().isoformat()
    if mails.setting(con, "maybe_done_on") == today:
        return 0
    last = mails.setting(con, "maybe_done_at")
    since = datetime.fromisoformat(last) if last else now - timedelta(days=1)
    s = since.isoformat(timespec="seconds")
    cands = [t for t in _open_tasks(con)
             if not con.execute("SELECT 1 FROM maybe_done WHERE task_id = ? AND (resolved = 0 OR created_at >= ?)",
                                (t["id"], (now - timedelta(days=7)).isoformat(timespec="seconds"))).fetchone()]  # 「ちがう」を押したものは7日聞かない
    mails_ = [r["subject"] for r in con.execute("SELECT subject FROM messages WHERE received_at >= ? ORDER BY received_at LIMIT 60", (s,))]
    commits = [f"{r['name']}: {r['message']}" for r in con.execute(
        "SELECT c.name, m.message FROM commits m JOIN containers c ON c.id = m.container_id WHERE m.committed_at >= ? AND m.hidden = 0 LIMIT 60", (s,))]
    hints = [x for x in (mails.setting(con, "maybe_hint") or "").splitlines() if x]
    work = []
    for r in con.execute("SELECT c.name, l.started_at, l.ended_at FROM work_logs l JOIN containers c ON c.id = l.container_id WHERE l.started_at >= ?", (s,)):
        e = datetime.fromisoformat(r["ended_at"]) if r["ended_at"] else now
        work.append((r["name"], (e - datetime.fromisoformat(r["started_at"])).total_seconds() / 60))
    totals = {}
    for name, m in work:
        totals[name] = totals.get(name, 0) + m
    mails.set_setting(con, "maybe_done_on", today)  # 失敗しても、その日はもう聞かない
    if not cands or not (mails_ or commits or hints or totals):
        mails.set_setting(con, "maybe_done_at", now.isoformat(timespec="seconds"))
        return 0
    prompt = json.dumps({"tasks": cands, "mails": mails_, "commits": commits + hints,
                         "work": [{"container": k, "minutes": int(v)} for k, v in totals.items()]}, ensure_ascii=False)
    try:
        res = runner(MAYBE_SYSTEM, prompt) or {}
    except agent.AgentError:
        return 0
    ids = {t["id"] for t in cands}
    n = 0
    for it in (res.get("maybe_done") or [])[:10]:
        tid = it.get("task_id")
        if isinstance(tid, int) and tid in ids:
            _to_maybe(con, tid, str(it.get("reason") or "終わっていそう"))
            n += 1
    mails.set_setting(con, "maybe_done_at", now.isoformat(timespec="seconds"))
    con.execute("DELETE FROM settings WHERE key = 'maybe_hint'")
    return n


def maybe_list(con):
    return [dict(r) for r in con.execute(
        "SELECT m.id, m.task_id, m.reason, t.name, c.name AS container FROM maybe_done m JOIN tasks t ON t.id = m.task_id "
        "JOIN containers c ON c.id = t.container_id WHERE m.resolved = 0 AND t.done = 0 ORDER BY m.id")]


def answer_maybe(con, mid, done):
    m = con.execute("SELECT * FROM maybe_done WHERE id = ?", (mid,)).fetchone()
    if not m:
        return
    if done:
        tasks.set_done(con, m["task_id"], True)
        gcal.mark_dirty(con)
    con.execute("UPDATE maybe_done SET resolved = 1 WHERE id = ?", (mid,))


# ---------- 自動で完了の欄(S3-5、A28) ----------
def archive(con, limit=50, before=None):
    sql = ("SELECT t.id, t.name, t.done_at, t.auto_done_by, c.name AS container, "
           "(SELECT body FROM notices n WHERE n.kind = '自動で完了' AND n.task_id = t.id ORDER BY n.id DESC LIMIT 1) AS body "
           "FROM tasks t JOIN containers c ON c.id = t.container_id WHERE t.done = 1 AND t.auto_done_by IS NOT NULL")
    args = []
    if before:
        sql += " AND t.done_at < ?"
        args.append(before)
    sql += " ORDER BY t.done_at DESC LIMIT ?"
    return [dict(r) for r in con.execute(sql, (*args, limit + 1))]


def undo(con, tid):
    """[戻す]:未完了に戻し、カレンダーの「済」を消す。まだ手つかずの次の回は消す(Q14)。"""
    t = tasks.get(con, tid)
    if not t["auto_done_by"]:
        return False
    tasks.set_done(con, tid, False)
    con.execute("UPDATE notices SET answered = 1 WHERE kind = '自動で完了' AND task_id = ?", (tid,))
    gcal.mark_dirty(con)
    return True


def unseen(con):
    """連絡のボタンの青い点に数える、まだ見ていない「自動で完了」のお知らせ。"""
    seen = int(mails.setting(con, "auto_done_seen_id") or 0)
    return con.execute("SELECT COUNT(*) FROM notices WHERE kind = '自動で完了' AND id > ?", (seen,)).fetchone()[0]


def mark_seen(con):
    r = con.execute("SELECT MAX(id) FROM notices WHERE kind = '自動で完了'").fetchone()[0]
    if r:
        mails.set_setting(con, "auto_done_seen_id", str(r))
