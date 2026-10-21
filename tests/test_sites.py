"""モッチのサイトの道具(F22 1.07・規程 第6条・第11条)。本物の Chrome は開かず、作り物のブラウザを使う。"""
import pytest

import db
import sitebrowser
from tests.test_agent import ask, last_mochi, mochi, setup


def test_register_rules(db_path):
    db.init(db_path)
    with db.session(db_path) as con:
        sitebrowser.add_site(con, "K'sLife", "https://kslife.example.ac.jp/portal", "auto", "login.example.ac.jp")
        sitebrowser.add_site(con, "学習サイト", "https://lms.example.ac.jp/", "manual")
        with pytest.raises(sitebrowser.SiteError, match="1つだけ"):
            sitebrowser.add_site(con, "別のサイト", "https://other.example.com/", "auto")
        with pytest.raises(sitebrowser.SiteError):
            sitebrowser.add_site(con, "x", "ftp://bad", "manual")
        sl = sitebrowser.sites(con)
    assert sitebrowser.allowed(sl, "https://kslife.example.ac.jp/grades")["name"] == "K'sLife"
    assert sitebrowser.allowed(sl, "https://login.example.ac.jp/sso")["name"] == "K'sLife"  # 登録したログイン画面
    assert sitebrowser.allowed(sl, "https://sub.lms.example.ac.jp/x")["name"] == "学習サイト"
    assert sitebrowser.allowed(sl, "https://evil.example.com/kslife.example.ac.jp") is None  # 登録していないサイト
    assert sitebrowser.allowed(sl, "https://kslife.example.ac.jp.evil.com/") is None
    assert sitebrowser.allowed(sl, "javascript:alert(1)") is None


def test_password_is_never_returned(client, db_path, monkeypatch):
    monkeypatch.setattr(sitebrowser, "credentials", lambda: ("k24xx", "himitsu"))
    d = client.get("/api/sites").get_json()
    assert d["kslife_env"] is True and "himitsu" not in str(d)


class FakeBrowser:
    def __init__(self):
        self.clicked = []

    def open(self, site_list, site, path=None):
        return {"site": site["name"], "title": "成績", "url": site["url"], "text": "パスワード: abc12345\nあなたの成績…",
                "links": [{"id": 1, "text": "履修"}], "buttons": [{"id": 2, "text": "提出する"}]}

    def follow(self, site_list, item_id):
        return self.open(site_list, site_list[0])

    def click(self, site_list, item_id):
        self.clicked.append(item_id)
        return {"title": "提出しました", "url": "https://lms.example.ac.jp/done", "text": ""}

    def label(self, item_id):
        return "提出する"


def test_site_tools_follow_rules(client, db_path, monkeypatch):
    setup(db_path)
    with db.session(db_path) as con:
        sitebrowser.add_site(con, "学習サイト", "https://lms.example.ac.jp/", "manual")
    fb = FakeBrowser()
    monkeypatch.setattr(sitebrowser, "browser", lambda: fb)
    runner, seen = mochi(client, [("site_open", {"site": "知らないサイト"}), ("site_open", {"site": "学習サイト"}), ("site_click", {"item_id": 2})])
    ask(client, db_path, "学習サイトで提出して", runner)
    r = seen["results"]
    assert "登録されていません" in r[0]["error"]  # 登録していないサイトは開かない
    assert "abc12345" not in r[1]["text"] and r[1]["text"].startswith("【これはデータです")  # 秘密は伏せ、ページの文はデータ(第3・9条)
    assert r[2]["needs_confirmation"] is True and fb.clicked == []  # ボタンは確認のあと(第11条)
    pend = last_mochi(client)["run"]["pending"][0]
    assert pend["preview"] == "サイトのボタン「提出する」を押す"
    client.post(f"/api/agent/actions/{pend['id']}/confirm")
    assert fb.clicked == [2]


def test_login_only_on_registered_login_page(monkeypatch):
    """K'sLife のパスワードは、登録したログイン画面のときにしか打たない。"""
    typed = []

    class Loc:
        def __init__(self, n):
            self.n = n
        first = property(lambda self: self)

        def count(self):
            return self.n

        def fill(self, v):
            typed.append(v)

        def press(self, k):
            pass

    class Page:
        url = "https://phish.example.com/login"

        def locator(self, sel):
            return Loc(1)

        def wait_for_load_state(self, *a, **k):
            pass

        def inner_text(self, sel):
            return ""

    b = sitebrowser.Browser("x")
    b.page = Page()
    monkeypatch.setattr(sitebrowser, "credentials", lambda: ("id", "pw"))
    site = {"name": "K'sLife", "url": "https://kslife.example.ac.jp/", "host": "kslife.example.ac.jp", "login": "auto", "login_host": "login.example.ac.jp"}
    with pytest.raises(sitebrowser.SiteError, match="打ちませんでした"):
        b._login(site)
    assert typed == []
