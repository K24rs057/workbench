"""大学の Outlook を読む(要件 F9)。

PC の Outlook アプリ(クラシック版)を COM で、読み取りだけで読む。送信・返信・削除・移動・既読化には一切さわらない。
Outlook が閉じていれば、COM が裏で立ち上げる。読めなかったら推測で埋めず、お知らせに出す。
"""
from datetime import datetime, timedelta

import mails

FIRST_DAYS = 30            # 初めて読むときの期間(Claude の案)
EVERY = timedelta(minutes=10)
INBOX = 6


def read_inbox(since):
    """受信トレイの、since より新しいメールを新しい順に返す(読むだけ)。"""
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    try:
        ns = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
        items = ns.GetDefaultFolder(INBOX).Items
        items.Sort("[ReceivedTime]", True)
        out = []
        for m in items:
            try:
                received = m.ReceivedTime.replace(tzinfo=None)
            except Exception:
                continue
            if received < since:
                break
            try:  # 配信できなかったお知らせ(差出人がない)など、メールの形でないものは飛ばす
                addr = m.SenderEmailAddress or ""
                if m.SenderEmailType == "EX":
                    try:
                        addr = m.Sender.GetExchangeUser().PrimarySmtpAddress or addr
                    except Exception:
                        pass
                out.append({"source": "Outlook", "external_id": "outlook:" + m.EntryID, "subject": m.Subject or "",
                            "sender": addr, "received_at": received, "body": m.Body or ""})
            except Exception:
                continue
        return out
    finally:
        pythoncom.CoUninitialize()


def classify(con, msg):
    """大学のメール・Forms の応答・学習サイトの提出受付だけを残す。ほかは None(取り込まない)。"""
    dom = mails.domain_of(msg["sender"])
    if dom.startswith("forms.") and dom.endswith("microsoft") and msg["subject"].startswith("自分の応答"):
        return {**msg, "category": "Forms"}  # 大学の外からでも、合図としてだけ取り込む(Q13 イ)
    if not mails.is_university(con, msg["sender"]):
        return None
    cat, cid = mails.classify_university(con, msg)
    if "への提出を送信しました" in msg["subject"]:
        cat = "提出受付"  # 自動で完了の合図(Q13 ア、作る順番④で使う)
    return {**msg, "category": cat, "container_id": cid}


def refresh(con, now=None, reader=read_inbox, force=False):
    """10分ごとに読む。取り込んだ数を返す。"""
    now = now or datetime.now()
    last = mails.setting(con, "outlook_read_at")
    if not force and last and now - datetime.fromisoformat(last) < EVERY:
        return 0
    if not mails.setting(con, "university_domain"):
        mails.set_setting(con, "outlook_error", "大学のアドレスの形が設定されていません(設定の「メールと連絡」)")
        return 0
    initial = last is None
    since = now - timedelta(days=FIRST_DAYS) if initial else datetime.fromisoformat(last) - timedelta(minutes=30)
    try:
        items = reader(since)
    except Exception as e:  # サインイン切れ・Outlook が入っていないなど
        mails.set_setting(con, "outlook_error", "大学のメールを読めませんでした")
        con.execute("INSERT INTO job_status(job, last_error) VALUES ('Outlook', ?) ON CONFLICT(job) DO UPDATE SET last_error = excluded.last_error", (str(e)[:200],))
        return 0
    con.execute("DELETE FROM settings WHERE key = 'outlook_error'")
    n = 0
    for msg in reversed(items):  # 古い順に入れる
        m = classify(con, msg)
        if m and mails.ingest(con, m, initial=initial):
            n += 1
    mails.set_setting(con, "outlook_read_at", now.isoformat(timespec="seconds"))
    con.execute("INSERT INTO job_status(job, last_run_at, last_error) VALUES ('Outlook', ?, NULL) ON CONFLICT(job) DO UPDATE SET last_run_at = excluded.last_run_at, last_error = NULL",
                (now.isoformat(timespec="seconds"),))
    mails.purge_bodies(con, now)
    return n
