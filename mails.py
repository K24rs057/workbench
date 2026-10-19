"""取り込んだ連絡(要件 F9・F11・F20、基本設計 Q6・Q13・Q20〜Q22)。Outlook と Gmail で共通の部分。

メールは読むだけ。ここでは、読んだメールを仕分けて、締切をタスクに、休講・補講を預かった予定にする。
締切は、まず決まった書き方を探し、見つからないが「締切」などの言葉があるものだけ Claude に読ませる。
本文は90日で消す(構想設計)。大学のアドレスの形は data/ の設定(settings.university_domain)にだけ置く。
"""
import json
import re
from datetime import date, datetime, timedelta

import containers

BODY_DAYS = 90
DEADLINE_WORDS = ("締切", "〆切", "締め切り", "期限", "提出")
INTERVIEW_WORDS = ("面接", "面談")
CLAUDE_PER_RUN = 5          # 1回の取り込みで Claude に読ませる数の上限(使用量を一度に使わない)
TRIES = 3                   # 3回失敗したら「読み取れなかった」(Q6)
URL_RE = re.compile(r"https?://[^\s<>\"'()()「」]+")
DATE_RE = re.compile(r"(?:(\d{4})\s*[年/])?\s*(\d{1,2})\s*[月/]\s*(\d{1,2})\s*日?(?:\s*[((][月火水木金土日][))])?")
TIME_RE = re.compile(r"(\d{1,2})\s*[::]\s*(\d{2})|(\d{1,2})\s*時")
PREFIX_RE = re.compile(r"^(学内連絡|教員連絡|Re|RE|Fw|FW|Fwd)\s*[::]\s*")


# ---------- 小さな道具 ----------
def setting(con, key, default=None):
    r = con.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return r["value"] if r else default


def set_setting(con, key, value):
    con.execute("INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))


def domain_of(address):
    return (address or "").rsplit("@", 1)[-1].lower().strip(">")


def is_university(con, address):
    dom = (setting(con, "university_domain") or "").lower().lstrip("@")
    d = domain_of(address)
    return bool(dom) and (d == dom or d.endswith("." + dom))


def clean_subject(subject):
    s = PREFIX_RE.sub("", (subject or "").strip())
    s = re.sub(r"^(※?再送)\s*", "", s)
    s = re.sub(r"^(受付中[!!]?)\s*", "", s)
    s = re.sub(r"^【[^】]{0,12}】\s*", "", s)
    return s[:40] or "(件名なし)"


def _year_for(month, day, received):
    """年が書いていないとき、受け取った日に近い年にする(年をまたぐ締切のため)。"""
    for y in (received.year, received.year + 1):
        try:
            d = date(y, month, day)
        except ValueError:
            return None
        if d >= received.date() - timedelta(days=60):
            # 次の年にずらすのは、年明けすぐの日付だけ。半年より先になるなら、終わった日付とみなす
            return d if d - received.date() <= timedelta(days=200) else None
    return None


def find_deadlines(text, received):
    """締切の言葉と日付が同じ行にあるものを探す。[(日付, 時刻か None, その行)]。"""
    out = []
    for line in re.split(r"[\r\n]+", text or ""):
        if not any(w in line for w in DEADLINE_WORDS) and "まで" not in line:
            continue
        if "本日" in line and any(w in line for w in DEADLINE_WORDS):
            d = received.date()
        else:
            m = DATE_RE.search(line)
            if not m:
                continue
            y, mo, dd = m.group(1), int(m.group(2)), int(m.group(3))
            if not (1 <= mo <= 12 and 1 <= dd <= 31):
                continue
            try:
                d = date(int(y), mo, dd) if y else _year_for(mo, dd, received)
            except ValueError:
                d = None
            if not d:
                continue
        t = TIME_RE.search(line)
        tm = None
        if t:
            h, mi = (int(t.group(1)), int(t.group(2))) if t.group(1) else (int(t.group(3)), 0)
            if 0 <= h <= 24 and 0 <= mi < 60:
                tm = f"{min(h, 23):02d}:{mi if h < 24 else 59:02d}"
        out.append((d, tm, line.strip()[:120]))
        break  # 1通から1つ(いちばん上に書いてある締切)
    return out


def has_deadline_words(text):
    return any(w in (text or "") for w in DEADLINE_WORDS)


def has_interview(text):
    """「面接」「面談」があり、日付が書いてあるメール(AI ②に毎回渡す)。"""
    return any(w in (text or "") for w in INTERVIEW_WORDS) and DATE_RE.search(text or "") is not None


# ---------- 仕分け ----------
def _auto_container(con, source, name):
    r = con.execute("SELECT id FROM containers WHERE auto_source = ? AND source_key = ?", (source, name)).fetchone()
    if r:
        return r["id"]
    uni = con.execute("SELECT id FROM kinds WHERE builtin = 1 ORDER BY id LIMIT 1").fetchone()["id"]
    return con.execute("INSERT INTO containers(kind_id, name, auto_source, source_key) VALUES (?, ?, ?, ?)", (uni, name, source, name)).lastrowid


def classify_university(con, msg):
    """(分類, 入れ物)。選び直しの覚え → 授業の名前 → 奨学金 → 試合のチケット → その他。"""
    for r in con.execute("SELECT * FROM sort_rules WHERE sender = ?", (msg["sender"].lower(),)):
        if not r["subject"] or r["subject"] in msg["subject"]:
            return "授業", r["container_id"]
    subj, head = msg["subject"], (msg.get("body") or "")[:600]
    # 「学内連絡」は大学全体への一斉配信。科目名と同じ言葉(「インターンシップ」など)が入っていても、授業のメールではない
    broadcast = subj.startswith("学内連絡")
    best = None
    rows = [] if broadcast else  con.execute("SELECT c.id, c.name, c.source_key FROM containers c JOIN kinds k ON k.id = c.kind_id WHERE c.ended = 0 AND c.auto_source = '時間割'").fetchall()
    for c in rows:
        for nm in {c["name"], c["source_key"]} - {None}:
            if nm and (nm in subj or nm in head) and (best is None or len(nm) > best[1]):
                best = (c["id"], len(nm))
    if best:
        return "授業", best[0]
    if "奨学金" in subj:
        return "奨学金", _auto_container(con, "奨学金", "奨学金")
    if "チケット" in subj and ("試合" in subj or "観戦" in subj):
        return "試合のチケット", _auto_container(con, "試合のチケット", "試合のチケット")
    return "その他", None


# ---------- 取り込む ----------
def ingest(con, msg, initial=False, today=None):
    """1通を取り込む。新しく入れたら連絡の番号、もう入っていた・取り込まないものは None。
    msg: {source, external_id, subject, sender, received_at(datetime), body, category?, container_id?, baito_id?}"""
    if con.execute("SELECT 1 FROM messages WHERE external_id = ?", (msg["external_id"],)).fetchone():
        return None
    if con.execute("SELECT 1 FROM blocked_senders WHERE address = ?", (msg["sender"].lower(),)).fetchone():
        return None
    today = today or date.today()
    received = msg["received_at"]
    body = msg.get("body") or ""
    links = URL_RE.findall(body)[:20]
    mid = con.execute(
        "INSERT INTO messages(source, external_id, category, container_id, baito_id, subject, sender, received_at, body, links, seen) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (msg["source"], msg["external_id"], msg["category"], msg.get("container_id"), msg.get("baito_id"), msg["subject"],
         msg["sender"].lower(), received.isoformat(timespec="seconds"), body, json.dumps(links, ensure_ascii=False), 1 if initial else 0),
    ).lastrowid
    if msg["category"] in ("Forms", "提出受付"):
        return mid  # 自動で完了の合図(作る順番④)。タスクは作らない
    if msg["category"] == "その他" and msg["subject"].startswith("学内連絡"):
        return mid  # 一斉配信は一覧に残すだけ。参加したいものは本人が足す(要件 F9、2026-10-19 決定)
    text = msg["subject"] + "\n" + body
    if msg["category"] == "アルバイト":
        if not msg.get("baito_id"):
            _ask_baito(con, msg, mid)
    else:  # アルバイトは入れ物を作らないので、締切のタスクにはしない(F20)
        found = find_deadlines(text, received)
        if found:
            d, tm, _ = found[0]
            _add_task(con, msg, mid, d, tm, today, initial, ai=False, excerpt=None)
        elif has_deadline_words(text):
            con.execute("INSERT INTO claude_jobs(kind, target, tries, next_try_at) VALUES ('締切の読み取り', ?, 0, NULL)", (str(mid),))
    if has_interview(text):  # 決まった書き方で見つかっても、候補日か決定かは毎回 Claude に判断させる(AI ②)
        con.execute("INSERT INTO claude_jobs(kind, target, tries, next_try_at) VALUES ('面接の読み取り', ?, 0, NULL)", (str(mid),))
    _hold_class_change(con, msg, mid, received)
    return mid


def _ask_baito(con, msg, mid):
    """初めての中継アドレスは「どのバイト先?」と聞く(Q21)。同じアドレスで聞いている途中なら、もう聞かない。"""
    sender = msg["sender"].lower()
    if con.execute("SELECT 1 FROM notices n JOIN messages m ON m.id = n.message_id WHERE n.kind = 'バイト先の質問' AND n.answered = 0 AND m.sender = ?",
                   (sender,)).fetchone():
        return
    con.execute("INSERT INTO notices(kind, body, message_id) VALUES ('バイト先の質問', ?, ?)",
                (f"「{clean_subject(msg['subject'])}」は、どのバイト先からのメールですか?", mid))


def _add_task(con, msg, mid, d, tm, today, initial, ai, excerpt, title=None):
    if initial and d < today:
        return None  # 初めて読むときは、もう過ぎた締切はタスクにしない(期限切れが一気に増えるのを防ぐ)
    if con.execute("SELECT 1 FROM deleted_items WHERE external_id = ? AND what = 'タスク'", (msg["external_id"],)).fetchone():
        return None
    cid = msg.get("container_id") or containers.unsorted_id(con)
    name = (title or clean_subject(msg["subject"]))[:60]
    key = re.sub(r"^(※?再送|受付中!?|受付中!?)\s*", "", name)
    if con.execute("SELECT 1 FROM tasks WHERE due_date = ? AND (name = ? OR name LIKE ?)", (d.isoformat(), name, f"%{key[-20:]}")).fetchone():
        return None  # 同じ知らせの再送など、同じ日の同じ締切は1つにする
    return con.execute(
        "INSERT INTO tasks(container_id, name, due_date, due_time, from_message_id, ai_read, ai_excerpt) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (cid, name, d.isoformat(), tm, mid, 1 if ai else 0, excerpt),
    ).lastrowid


def _hold_class_change(con, msg, mid, received):
    """休講・補講は、予定として預かる(Google カレンダーは作る順番③)。"""
    text = msg["subject"] + "\n" + (msg.get("body") or "")
    for word in ("休講", "補講"):
        if word not in text:
            continue
        for line in re.split(r"[\r\n]+", text):
            if word in line:
                m = DATE_RE.search(line)
                if m:
                    mo, dd = int(m.group(2)), int(m.group(3))
                    d = _year_for(mo, dd, received) if 1 <= mo <= 12 and 1 <= dd <= 31 else None
                    if d:
                        con.execute(
                            "INSERT INTO held_events(title, start_at, reason, container_id, from_message_id) VALUES (?, ?, 'カレンダーがまだつながっていない', ?, ?)",
                            (f"{word}:{clean_subject(msg['subject'])}", d.isoformat(), msg.get("container_id"), mid),
                        )
                        return
        return


# ---------- Claude に読ませる(AI ①・②) ----------
DEADLINE_SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {"type": "object", "properties": {
        "date": {"type": "string"}, "time": {"type": ["string", "null"]}, "title": {"type": "string"}},
        "required": ["date", "time", "title"]}}},
    "required": ["items"],
}
DEADLINE_SYSTEM = ("あなたはメールから提出・申込の締切だけを読み取る係です。締切がなければ items は空。"
                   "date は YYYY-MM-DD、time は HH:MM か null。title は「第10回課題」のように短く。説明はしない。")


INTERVIEW_SCHEMA = {
    "type": "object",
    "properties": {"type": {"type": "string", "enum": ["決定", "候補", "不明"]},
                   "title": {"type": "string"},
                   "dates": {"type": "array", "items": {"type": "object", "properties": {
                       "date": {"type": "string"}, "start": {"type": ["string", "null"]}, "end": {"type": ["string", "null"]}},
                       "required": ["date", "start", "end"]}}},
    "required": ["type", "title", "dates"],
}
INTERVIEW_SYSTEM = ("あなたはメールから面接・面談の日時を読み取る係です。相手が日時を決めて伝えているなら type は「決定」、"
                    "いくつかの候補日から選ばせているなら「候補」、どちらかわからなければ「不明」。dates に日時を全部入れる。"
                    "date は YYYY-MM-DD、start と end は HH:MM か null。title は「一次面接」のように短く。説明はしない。")
JOBS = {"締切の読み取り": (DEADLINE_SYSTEM, DEADLINE_SCHEMA), "面接の読み取り": (INTERVIEW_SYSTEM, INTERVIEW_SCHEMA)}
HM_RE = re.compile(r"^\d{1,2}:\d{2}$")


def _hm(v):
    return v if isinstance(v, str) and HM_RE.match(v) else None


def run_claude_jobs(con, runner=None, now=None, today=None):
    """たまっている締切・面接日の読み取りを、上限まで進める。上限に当たったら止めて、回数には数えない(エラー1)。"""
    import agent
    schemas = {sysp: sch for sysp, sch in JOBS.values()}
    runner = runner or (lambda s, p: agent.call_claude(s, p, schemas[s]))
    now = now or datetime.now()
    today = today or date.today()
    marks = ",".join("?" * len(JOBS))
    jobs = con.execute(f"SELECT * FROM claude_jobs WHERE kind IN ({marks}) AND (next_try_at IS NULL OR next_try_at <= ?) ORDER BY id LIMIT ?",
                       (*JOBS, now.isoformat(timespec="seconds"), CLAUDE_PER_RUN)).fetchall()
    done = 0
    for j in jobs:
        m = con.execute("SELECT * FROM messages WHERE id = ?", (int(j["target"]),)).fetchone()
        if not m:
            con.execute("DELETE FROM claude_jobs WHERE id = ?", (j["id"],))
            continue
        prompt = json.dumps({"received": m["received_at"][:10], "subject": m["subject"], "body": (m["body"] or "")[:4000]}, ensure_ascii=False)
        try:
            res = runner(JOBS[j["kind"]][0], prompt)
        except agent.UsageLimit:
            set_setting(con, "claude_limited_at", now.isoformat(timespec="seconds"))
            break
        except agent.AgentError as e:
            tries = j["tries"] + 1
            if tries >= TRIES:
                con.execute("UPDATE messages SET ai_failed = 1 WHERE id = ?", (m["id"],))
                con.execute("DELETE FROM claude_jobs WHERE id = ?", (j["id"],))
            else:
                con.execute("UPDATE claude_jobs SET tries = ?, next_try_at = ?, last_error = ? WHERE id = ?",
                            (tries, (now + timedelta(minutes=10)).isoformat(timespec="seconds"), str(e)[:200], j["id"]))
            continue
        if j["kind"] == "面接の読み取り":
            _interview_result(con, m, res or {}, today)
        else:
            msg = dict(m) | {"received_at": datetime.fromisoformat(m["received_at"])}
            for it in (res.get("items") or [])[:1]:
                try:
                    d = date.fromisoformat(it["date"])
                except (ValueError, TypeError, KeyError):
                    continue
                tm = _hm(it.get("time"))
                _add_task(con, msg, m["id"], d, tm, today, initial=False, ai=True,
                          excerpt=f"{it.get('title', '')}:{it['date']} {tm or ''}".strip(), title=it.get("title") or None)
        con.execute("DELETE FROM claude_jobs WHERE id = ?", (j["id"],))
        done += 1
    return done


def interview_title(con, m, title):
    """予定の名前。「一次面接:○○株式会社」のように、相手の名前をつける。"""
    who = None
    if m["container_id"]:
        r = con.execute("SELECT name FROM containers WHERE id = ?", (m["container_id"],)).fetchone()
        who = r["name"] if r else None
    if not who and m["baito_id"]:
        r = con.execute("SELECT name FROM baito_places WHERE id = ?", (m["baito_id"],)).fetchone()
        who = r["name"] if r else None
    t = (title or "面接").strip()[:20]
    return f"{t}:{who}" if who else t


def hold_interview(con, m, d, start, end, title, ai_excerpt):
    """面接の日時を預かった予定にする(Google カレンダーは作る順番③)。同じメールの同じ日時は1つ。"""
    start_at = f"{d}T{start}" if start else d
    if con.execute("SELECT 1 FROM deleted_items WHERE external_id = ? AND what = '予定'", (m["external_id"],)).fetchone():
        return None
    if con.execute("SELECT 1 FROM held_events WHERE from_message_id = ? AND start_at = ?", (m["id"], start_at)).fetchone():
        return None
    end_at = f"{d}T{end}" if start and end else None
    return con.execute(
        "INSERT INTO held_events(title, start_at, end_at, reason, container_id, from_message_id, ai_read, ai_excerpt) "
        "VALUES (?, ?, ?, 'カレンダーがまだつながっていない', ?, ?, 1, ?)",
        (interview_title(con, m, title), start_at, end_at, m["container_id"], m["id"], ai_excerpt)).lastrowid


def _interview_result(con, m, res, today):
    dates = []
    for it in res.get("dates") or []:
        try:
            d = date.fromisoformat(it["date"])
        except (ValueError, TypeError, KeyError):
            continue
        if d >= today:  # 過ぎた日は入れない
            dates.append({"date": d.isoformat(), "start": _hm(it.get("start")), "end": _hm(it.get("end"))})
    if not dates:
        return
    title = res.get("title") or "面接"
    if res.get("type") == "決定":
        for x in dates[:3]:
            hold_interview(con, m, x["date"], x["start"], x["end"], title, f"決まった日時:{x['date']} {x['start'] or ''}".strip())
        return
    # 候補日・判断できなかったときは、ボタンで選んでもらう(Q22)
    body = json.dumps({"text": f"「{clean_subject(m['subject'])}」に面接の候補日があります。決まった日を押してください",
                       "title": title, "dates": dates[:10]}, ensure_ascii=False)
    con.execute("INSERT INTO notices(kind, body, message_id, container_id) VALUES ('候補日', ?, ?, ?)", (body, m["id"], m["container_id"]))


# ---------- 「確認してほしいこと」への答え(A27) ----------
def answer_baito(con, n, baito_id=None, name=None):
    """「どのバイト先?」の答え。中継アドレス(@ の前も全部)を覚え、同じアドレスのメールに名前をつける(Q21)。"""
    m = con.execute("SELECT * FROM messages WHERE id = ?", (n["message_id"],)).fetchone()
    if baito_id:
        if not con.execute("SELECT 1 FROM baito_places WHERE id = ?", (baito_id,)).fetchone():
            raise containers.UserError("そのバイト先はありません")
    else:
        name = (name or "").strip()
        if not name:
            raise containers.UserError("バイト先を選ぶか、名前を入れてください")
        baito_id = con.execute("INSERT INTO baito_places(name) VALUES (?)", (name,)).lastrowid
    if m:
        if not con.execute("SELECT 1 FROM baito_addresses WHERE address = ?", (m["sender"],)).fetchone():
            con.execute("INSERT INTO baito_addresses(baito_id, address) VALUES (?, ?)", (baito_id, m["sender"]))
        con.execute("UPDATE messages SET baito_id = ? WHERE sender = ? AND category = 'アルバイト'", (baito_id, m["sender"]))
        con.execute("UPDATE notices SET answered = 1 WHERE kind = 'バイト先の質問' AND message_id IN (SELECT id FROM messages WHERE sender = ?)", (m["sender"],))
    con.execute("UPDATE notices SET answered = 1 WHERE id = ?", (n["id"],))


def answer_candidate(con, n, index=None, none=False):
    """候補日のボタン。押した日を預かった予定にする(Q22)。"""
    if not none:
        data = json.loads(n["body"])
        try:
            x = data["dates"][int(index)]
        except (TypeError, ValueError, IndexError, KeyError):
            raise containers.UserError("その候補日はありません")
        m = con.execute("SELECT * FROM messages WHERE id = ?", (n["message_id"],)).fetchone()
        if m:
            hold_interview(con, m, x["date"], x["start"], x["end"], data.get("title"), f"候補日から選んだ日:{x['date']} {x['start'] or ''}".strip())
    con.execute("UPDATE notices SET answered = 1 WHERE id = ?", (n["id"],))


def delete_held(con, hid):
    """預かった予定を消す。メールから入ったものは、次に読んでも戻さない。"""
    h = con.execute("SELECT * FROM held_events WHERE id = ?", (hid,)).fetchone()
    if not h:
        raise containers.UserError("その予定はありません")
    if h["from_message_id"]:
        m = con.execute("SELECT external_id FROM messages WHERE id = ?", (h["from_message_id"],)).fetchone()
        if m:
            con.execute("INSERT INTO deleted_items(external_id, what) VALUES (?, '予定')", (m["external_id"],))
    con.execute("DELETE FROM held_events WHERE id = ?", (hid,))


def purge_bodies(con, now=None):
    now = now or datetime.now()
    con.execute("UPDATE messages SET body = NULL WHERE body IS NOT NULL AND received_at < ?",
                ((now - timedelta(days=BODY_DAYS)).isoformat(timespec="seconds"),))
