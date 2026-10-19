"""自分の Gmail を読む(要件 F11・F20、基本設計 Q20〜Q22)。

Google の公式の連携(API)で、読むだけ(gmail.readonly)。送信・返信・削除・ラベル・既読には一切さわらない。
合鍵(クライアントの ID と秘密の文字)と通行証(リフレッシュトークン)は .env にだけ置き、GitHub には上げない。
取り込むのは、企業(登録したアドレス・企業の名前)とアルバイト(中継アドレス・登録したバイト先)のメールだけ。
"""
import base64
import html
import os
import re
from datetime import datetime, timedelta
from pathlib import Path

import mails

ROOT = Path(__file__).resolve().parent
ENV_PATH = ROOT / ".env"
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
FIRST_DAYS = 30
EVERY = timedelta(minutes=10)
MAX_PER_RUN = 200
GAP = 0.15                 # 1通ごとの間(秒)。Google の1秒あたりの上限より十分ゆっくり読む

# 応募サイトの中継アドレス(バイト先ごとに @ の前がちがう。Q21)
RELAY_DOMAINS = ("indeedemail.com", "r-sender.jp")
# 就活サイト。ここから届く宣伝の形の件名は取り込まない(Q20。初めに止めておく分。Claude の案で、アドレスではなく件名の形で止める)
JOB_SITES = ("rikunabi.com", "mynavi.jp", "rikeinavi.com", "gakujo.ne.jp")
AD_WORDS = ("受付中", "受付開始", "締切間近", "まもなく締切", "おすすめ", "オススメ", "新着", "特集", "ピックアップ", "あなたに", "人気")


# ---------- 合鍵と通行証(.env) ----------
def read_env(path=None):
    path = Path(path or ENV_PATH)
    out = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    return out


def write_env(values, path=None):
    """.env のキーを書きかえる(ほかの行はそのまま)。"""
    path = Path(path or ENV_PATH)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    left = dict(values)
    out = []
    for line in lines:
        k = line.split("=", 1)[0].strip() if "=" in line else None
        if k in left:
            v = left.pop(k)
            if v is not None:
                out.append(f"{k}={v}")
        else:
            out.append(line)
    out += [f"{k}={v}" for k, v in left.items() if v is not None]
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def client_config(env=None):
    env = env if env is not None else read_env()
    cid, secret = env.get("GOOGLE_CLIENT_ID"), env.get("GOOGLE_CLIENT_SECRET")
    if not cid or not secret:
        return None
    return {"installed": {"client_id": cid, "client_secret": secret,
                          "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": "https://oauth2.googleapis.com/token",
                          "redirect_uris": ["http://127.0.0.1"]}}


def credentials(env=None):
    """通行証から、読むための資格を作る。合鍵か通行証がなければ None。"""
    env = env if env is not None else read_env()
    cfg = client_config(env)
    token = env.get("GOOGLE_REFRESH_TOKEN")
    if not cfg or not token:
        return None
    from google.oauth2.credentials import Credentials
    c = cfg["installed"]
    return Credentials(None, refresh_token=token, token_uri=c["token_uri"], client_id=c["client_id"],
                       client_secret=c["client_secret"], scopes=SCOPES)


def state(env=None):
    """設定の「Google」に出す状態:合鍵なし / 未許可 / 許可済み。"""
    env = env if env is not None else read_env()
    if not client_config(env):
        return "合鍵なし"
    return "許可済み" if env.get("GOOGLE_REFRESH_TOKEN") else "未許可"


def import_client_json(json_path, env_path=None):
    """Google Cloud で保存した合鍵のファイルから、ID と秘密の文字だけを .env に移す(中身は画面に出さない)。"""
    import json
    d = json.loads(Path(json_path).read_text(encoding="utf-8"))
    c = d.get("installed") or d.get("web")
    if not c or not c.get("client_id") or not c.get("client_secret"):
        raise ValueError("「デスクトップ アプリ」の合鍵のファイルではないようです")
    write_env({"GOOGLE_CLIENT_ID": c["client_id"], "GOOGLE_CLIENT_SECRET": c["client_secret"]}, env_path)


# ---------- 許可の画面(A31 /auth/google) ----------
_flows = {}


def auth_url(redirect_uri):
    from google_auth_oauthlib.flow import Flow
    cfg = client_config()
    if not cfg:
        raise ValueError("Google の合鍵がまだありません")
    flow = Flow.from_client_config(cfg, scopes=SCOPES, redirect_uri=redirect_uri)
    url, st = flow.authorization_url(access_type="offline", prompt="consent")
    _flows.clear()
    _flows[st] = flow
    return url


def finish_auth(state_value, full_url):
    flow = _flows.pop(state_value, None)
    if not flow:
        raise ValueError("許可の画面の期限が切れました。もう一度 [Google と連携する] を押してください")
    os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")  # 戻り先がこの PC の中(http://127.0.0.1)のため
    flow.fetch_token(authorization_response=full_url)
    token = flow.credentials.refresh_token
    if not token:
        raise ValueError("Google から通行証が届きませんでした。もう一度許可してください")
    write_env({"GOOGLE_REFRESH_TOKEN": token})


# ---------- 読む ----------
def _header(headers, name):
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _decode(data):
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", "replace")


def _body(payload):
    """本文の文字だけ。text/plain がなければ HTML からタグを外す。"""
    plain, htm = [], []

    def walk(p):
        mt = p.get("mimeType", "")
        data = (p.get("body") or {}).get("data")
        if data and mt == "text/plain":
            plain.append(_decode(data))
        elif data and mt == "text/html":
            htm.append(_decode(data))
        for c in p.get("parts") or []:
            walk(c)

    walk(payload)
    if plain:
        return "\n".join(plain)
    if htm:
        t = re.sub(r"(?is)<(script|style).*?</\1>", "", "\n".join(htm))
        t = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>", "\n", t)
        t = re.sub(r"<[^>]+>", "", t)
        return html.unescape(re.sub(r"\n\s*\n+", "\n", t))
    return ""


def _address(from_header):
    m = re.search(r"<([^>]+)>", from_header or "")
    return (m.group(1) if m else (from_header or "")).strip().lower()


def _get(svc, mid, tries=4):
    """1通を読む。Google の回数の上限(1秒あたり)に当たらないよう間をあけ、当たったら少し待ってやり直す。"""
    import time
    from googleapiclient.errors import HttpError
    for i in range(tries):
        time.sleep(GAP)
        try:
            return svc.users().messages().get(userId="me", id=mid, format="full").execute()
        except HttpError as e:
            limited = e.resp.status == 429 or (e.resp.status == 403 and ("uota" in str(e) or "ateLimit" in str(e)))
            if not limited or i == tries - 1:
                raise
            time.sleep(2 ** (i + 1))


def read_inbox(since, creds=None):
    """since より新しい受信メールを新しい順に返す(読むだけ)。"""
    from googleapiclient.discovery import build
    creds = creds or credentials()
    if not creds:
        raise PermissionError("Google の許可がまだありません")
    svc = build("gmail", "v1", credentials=creds, cache_discovery=False)
    q = f"after:{int(since.timestamp())} -in:sent -in:chats -in:drafts"
    ids, page = [], None
    while len(ids) < MAX_PER_RUN:
        r = svc.users().messages().list(userId="me", q=q, maxResults=100, pageToken=page).execute()
        ids += [m["id"] for m in r.get("messages", [])]
        page = r.get("nextPageToken")
        if not page:
            break
    out = []
    for mid in ids[:MAX_PER_RUN]:
        m = _get(svc, mid)
        hs = m.get("payload", {}).get("headers", [])
        out.append({"source": "Gmail", "external_id": "gmail:" + mid, "subject": _header(hs, "Subject"),
                    "sender": _address(_header(hs, "From")), "received_at": datetime.fromtimestamp(int(m["internalDate"]) / 1000),
                    "body": _body(m.get("payload", {}))})
    return out


# ---------- 仕分け ----------
def _is_ad(msg):
    dom = mails.domain_of(msg["sender"])
    on_site = any(dom == s or dom.endswith("." + s) for s in JOB_SITES)
    return on_site and any(w in msg["subject"] for w in AD_WORDS)


def classify(con, msg):
    """企業かアルバイトなら {…, category, container_id, baito_id}。どちらでもなければ None(取り込まない)。"""
    sender = msg["sender"].lower()
    dom = mails.domain_of(sender)
    if con.execute("SELECT 1 FROM blocked_senders WHERE address = ? OR address = ?", (sender, "@" + dom)).fetchone():
        return None
    if _is_ad(msg):
        return None
    for r in con.execute("SELECT * FROM sort_rules WHERE sender = ?", (sender,)):
        if not r["subject"] or r["subject"] in msg["subject"]:
            return {**msg, "category": "企業", "container_id": r["container_id"]}
    # アルバイト:覚えた中継アドレス → 登録したバイト先の @ から後ろ → 初めての中継アドレス(どのバイト先? と聞く)
    r = con.execute("SELECT baito_id FROM baito_addresses WHERE address = ?", (sender,)).fetchone()
    if r:
        return {**msg, "category": "アルバイト", "baito_id": r["baito_id"]}
    r = con.execute("SELECT id FROM baito_places WHERE domain IS NOT NULL AND domain != '' AND ? IN (domain, ltrim(domain, '@'))", (dom,)).fetchone()
    if r:
        return {**msg, "category": "アルバイト", "baito_id": r["id"]}
    if any(dom == d or dom.endswith("." + d) for d in RELAY_DOMAINS):
        return {**msg, "category": "アルバイト", "baito_id": None}
    # 企業:登録したアドレスの @ から後ろ → 件名・本文の企業の名前(就活サイト経由のもの)
    rows = con.execute("SELECT c.id, c.name, c.company_domain FROM containers c JOIN kinds k ON k.id = c.kind_id "
                       "WHERE c.ended = 0 AND c.is_unsorted = 0 AND k.name = '就活'").fetchall()
    for c in rows:
        cd = (c["company_domain"] or "").lower().lstrip("@")
        if cd and (dom == cd or dom.endswith("." + cd)):
            return {**msg, "category": "企業", "container_id": c["id"]}
    head = msg["subject"] + "\n" + (msg.get("body") or "")[:1500]
    best = None
    for c in rows:
        nm = _core_name(c["name"])
        if len(nm) >= 2 and nm in head and (best is None or len(nm) > best[1]):
            best = (c["id"], len(nm))
    if best:
        return {**msg, "category": "企業", "container_id": best[0]}
    return None


def _core_name(name):
    """「株式会社〇〇」の「株式会社」などを外した名前(メールでは省かれることが多いため)。"""
    return re.sub(r"(株式会社|有限会社|合同会社|\(株\)|(株)|\s)", "", name or "")


def refresh(con, now=None, reader=None, force=False):
    """10分ごとに読む。取り込んだ数を返す。許可がまだなら何もしない。"""
    now = now or datetime.now()
    if reader is None:
        if state() != "許可済み":
            return 0
        reader = read_inbox
    last = mails.setting(con, "gmail_read_at")
    if not force and last and now - datetime.fromisoformat(last) < EVERY:
        return 0
    initial = last is None
    since = now - timedelta(days=FIRST_DAYS) if initial else datetime.fromisoformat(last) - timedelta(minutes=30)
    try:
        items = reader(since)
    except Exception as e:  # 許可切れ・つながらないなど。推測で埋めない
        expired = "invalid_grant" in str(e) or isinstance(e, PermissionError)
        mails.set_setting(con, "gmail_error", "Gmail を読めませんでした" + ("(Google の許可が切れています。設定の「Google」から許可し直してください)" if expired else ""))
        con.execute("INSERT INTO job_status(job, last_error) VALUES ('Gmail', ?) ON CONFLICT(job) DO UPDATE SET last_error = excluded.last_error", (str(e)[:200],))
        return 0
    con.execute("DELETE FROM settings WHERE key = 'gmail_error'")
    n = 0
    for msg in reversed(items):  # 古い順に入れる
        m = classify(con, msg)
        if m and mails.ingest(con, m, initial=initial):
            n += 1
    mails.set_setting(con, "gmail_read_at", now.isoformat(timespec="seconds"))
    con.execute("INSERT INTO job_status(job, last_run_at, last_error) VALUES ('Gmail', ?, NULL) ON CONFLICT(job) DO UPDATE SET last_run_at = excluded.last_run_at, last_error = NULL",
                (now.isoformat(timespec="seconds"),))
    return n
