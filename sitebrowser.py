"""モッチのサイトの道具(要件 F22 1.07、規程 第6条・第11条)。

段取りさん専用のプロフィール(data/browser/)で Chrome を開き、登録したサイトだけを読む。
- 開けるのは、登録したサイトのアドレス(と、そのサイトのログイン画面)だけ。ほかへ移ろうとしたら止める
- K'sLife だけは、登録したログイン画面のときにだけ、段取りさんのプログラムが .env のパスワードで入る(モッチには見せない)
  ほかのサイトは、本人が専用の窓で手でログインし、モッチはログイン済みの窓を使うだけ
- 2段階認証や「ロボットではありません」は突破しない。ログインの失敗はくり返さない
- ボタンを押すのは、本人の確認のあと(道具箱の confirm)
Playwright の同期の道具は、作ったスレッドからしか使えないので、専用のスレッド1本で動かす。
"""
import json
import queue
import threading
from pathlib import Path
from urllib.parse import urljoin, urlparse

import db

KEY = "agent_sites"
TEXT_MAX = 8000
LOGIN_WAIT = 20_000
MFA_WORDS = ("承認", "Authenticator", "確認コード", "認証コード", "2段階", "多要素", "サインイン要求", "verify", "approve", "robot", "ロボット", "captcha")


class SiteError(Exception):
    pass


# ---------- 登録したサイト(settings に JSON で置く。data/ の DB なので GitHub には上がらない) ----------
def sites(con):
    r = con.execute("SELECT value FROM settings WHERE key = ?", (KEY,)).fetchone()
    return json.loads(r["value"]) if r else []


def save_sites(con, items):
    con.execute("INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)", (KEY, json.dumps(items, ensure_ascii=False)))


def add_site(con, name, url, login="manual", login_host=None):
    name, url = (name or "").strip(), (url or "").strip()
    if not name or not url.startswith(("https://", "http://")):
        raise SiteError("名前と、https:// から始まるアドレスを入れてください")
    if login not in ("manual", "auto"):
        raise SiteError("ログインのしかたがちがいます")
    items = sites(con)
    if any(s["name"] == name for s in items):
        raise SiteError("同じ名前のサイトがあります")
    if login == "auto" and any(s["login"] == "auto" for s in items):
        raise SiteError("パスワードで自動で入るのは K'sLife の1つだけです")
    host = urlparse(url).hostname
    items.append({"name": name, "url": url, "host": host, "login": login,
                  "login_host": (login_host or "").strip().lower() or None})
    save_sites(con, items)


def remove_site(con, name):
    save_sites(con, [s for s in sites(con) if s["name"] != name])


def allowed(site_list, url):
    """開いてよいアドレスか(登録したサイトのホストとその下、ログイン画面のホスト)。"""
    h = (urlparse(url).hostname or "").lower()
    if not h or urlparse(url).scheme not in ("https", "http"):
        return None
    for s in site_list:
        for host in filter(None, (s["host"], s.get("login_host"))):
            if h == host or h.endswith("." + host):
                return s
    return None


def credentials():
    """K'sLife の ID とパスワード(.env)。ここ以外では読まない。"""
    import gmail
    env = gmail.read_env()
    return env.get("KSLIFE_ID"), env.get("KSLIFE_PASSWORD")


# ---------- 専用の Chrome(専用のスレッドで動かす) ----------
class Browser:
    def __init__(self, profile_dir):
        self.profile_dir = Path(profile_dir)
        self.q = queue.Queue()
        self.thread = None
        self.ctx = None
        self.page = None
        self.items = []  # いまのページのリンクとボタン

    def _loop(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            self.pw = pw
            while True:
                fn, box = self.q.get()
                try:
                    box["ok"] = fn()
                except Exception as e:  # 1つの失敗でスレッドを止めない
                    box["err"] = e
                box["done"].set()

    def run(self, fn, timeout=90):
        if not self.thread or not self.thread.is_alive():
            self.thread = threading.Thread(target=self._loop, daemon=True)
            self.thread.start()
        box = {"done": threading.Event()}
        self.q.put((fn, box))
        if not box["done"].wait(timeout):
            raise SiteError("サイトが答えませんでした")
        if "err" in box:
            e = box["err"]
            raise e if isinstance(e, SiteError) else SiteError(f"サイトを開けませんでした({str(e)[:120]})")
        return box["ok"]

    def _ensure(self):
        if self.ctx is None or not self.ctx.pages:
            self.profile_dir.mkdir(parents=True, exist_ok=True)
            self.ctx = self.pw.chromium.launch_persistent_context(str(self.profile_dir), channel="chrome", headless=False,
                                                                   viewport={"width": 1100, "height": 800})
            self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        if self.page is None or self.page.is_closed():
            self.page = self.ctx.new_page()
        return self.page

    # --- 読む ---
    def snapshot(self, site_list):
        p = self.page
        url = p.url
        site = allowed(site_list, url)
        if not site:
            raise SiteError("登録していないサイトに移ったので、読むのをやめました")
        text = p.inner_text("body")[:TEXT_MAX]
        links = p.eval_on_selector_all("a[href]", "els => els.slice(0, 200).map(e => [e.innerText.trim().slice(0, 60), e.getAttribute('href')])")
        buttons = p.eval_on_selector_all("button, input[type=submit], input[type=button], [role=button]",
                                         "els => els.slice(0, 80).map(e => (e.innerText || e.value || e.getAttribute('aria-label') || '').trim().slice(0, 60))")
        self.items = []
        out_links, out_buttons = [], []
        for label, href in links:
            full = urljoin(url, href or "")
            if label and allowed(site_list, full):  # 登録していないサイトへのリンクは出さない
                self.items.append(("link", full, label))
                out_links.append({"id": len(self.items), "text": label})
        for i, label in enumerate(buttons):
            if label:
                self.items.append(("button", i, label))
                out_buttons.append({"id": len(self.items), "text": label})
        return {"site": site["name"], "title": p.title(), "url": url, "text": text, "links": out_links[:120], "buttons": out_buttons[:60]}

    def open(self, site_list, site, path=None):
        def job():
            p = self._ensure()
            target = urljoin(site["url"], path) if path else site["url"]
            if not allowed(site_list, target):
                raise SiteError("登録していないアドレスは開けません")
            p.goto(target, wait_until="domcontentloaded", timeout=30_000)
            self._settle()
            if self._on_login(site):
                if site["login"] != "auto":
                    raise SiteError(f"{site['name']} のログインが切れているよ。設定の「サイト」の [専用の窓で開く] から、ログインしてね")
                self._login(site)
                p.goto(target, wait_until="domcontentloaded", timeout=30_000)
                self._settle()
            if not allowed(site_list, p.url):
                raise SiteError("登録していないサイトに移ったので、読むのをやめました")
            return self.snapshot(site_list)
        return self.run(job)

    def follow(self, site_list, item_id):
        def job():
            kind, val, _ = self._item(item_id)
            if kind != "link":
                raise SiteError("それはリンクではありません")
            if not allowed(site_list, val):
                raise SiteError("登録していないアドレスは開けません")
            self.page.goto(val, wait_until="domcontentloaded", timeout=30_000)
            self._settle()
            return self.snapshot(site_list)
        return self.run(job)

    def click(self, site_list, item_id):
        def job():
            kind, val, _ = self._item(item_id)
            if kind != "button":
                raise SiteError("それはボタンではありません")
            self.page.locator("button, input[type=submit], input[type=button], [role=button]").nth(val).click(timeout=15_000)
            self._settle()
            return self.snapshot(site_list)
        return self.run(job)

    def show_window(self, site):
        """設定の [専用の窓で開く]。本人が手でログインするため。"""
        def job():
            p = self._ensure()
            p.goto(site["url"], wait_until="domcontentloaded", timeout=30_000)
            p.bring_to_front()
            return True
        return self.run(job)

    def label(self, item_id):
        return self._item(item_id)[2]

    def _item(self, item_id):
        try:
            return self.items[int(item_id) - 1]
        except (ValueError, IndexError, TypeError):
            raise SiteError("その番号のリンク・ボタンはありません。もう一度ページを読んでね")

    def _settle(self):
        try:
            self.page.wait_for_load_state("networkidle", timeout=8_000)
        except Exception:
            pass

    # --- ログイン ---
    def _on_login(self, site):
        p = self.page
        host = (urlparse(p.url).hostname or "").lower()
        on_login_host = site.get("login_host") and (host == site["login_host"] or host.endswith("." + site["login_host"]))
        return bool(on_login_host or p.locator("input[type=password]").count())

    def _login(self, site):
        """K'sLife だけ。登録したログイン画面でだけ、パスワードを打つ。失敗はくり返さない。"""
        p = self.page
        host = (urlparse(p.url).hostname or "").lower()
        ok_hosts = [h for h in (site.get("login_host"), site["host"]) if h]
        if not any(host == h or host.endswith("." + h) for h in ok_hosts):
            raise SiteError("登録したログイン画面ではないので、パスワードは打ちませんでした")
        uid, pw = credentials()
        if not uid or not pw:
            raise SiteError("K'sLife の ID とパスワードが .env にありません(KSLIFE_ID・KSLIFE_PASSWORD)")
        user = p.locator("input[type=email], input[type=text], input[name*=user i], input[name*=id i]").first
        if user.count():
            user.fill(uid)
            if not p.locator("input[type=password]").count():  # ID だけ先に送る画面
                user.press("Enter")
                self._settle()
        pwbox = p.locator("input[type=password]").first
        if not pwbox.count():
            raise SiteError("ログイン画面の形がわからなかったので、入れませんでした")
        pwbox.fill(pw)
        pwbox.press("Enter")
        try:
            p.wait_for_load_state("networkidle", timeout=LOGIN_WAIT)
        except Exception:
            pass
        body = p.inner_text("body")
        if any(w.lower() in body.lower() for w in MFA_WORDS):
            raise SiteError("2段階認証が出たよ。スマホで承認してから、もう一度頼んでね(専用の窓に出ています)")
        if p.locator("input[type=password]").count():
            raise SiteError("K'sLife に入れなかったよ。.env の ID とパスワードを確かめてね(くり返し試さないで止めたよ)")


_BROWSER = None


def browser():
    global _BROWSER
    if _BROWSER is None:
        _BROWSER = Browser(db.DATA_DIR / "browser")
    return _BROWSER
