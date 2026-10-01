"""TASK-e522 : clipper.browser (SPEC-9225 R1, R8) et commande « clipper browser login ».

Playwright n'est jamais lance pour de vrai : un faux Playwright (objets
simules) remplace ``sync_playwright``. Aucun reseau, aucun navigateur.
"""

from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path

import pytest

from clipper import browser, __main__ as cli

ROOT = Path(__file__).resolve().parent.parent

NO_CHROME = (
    "BrowserType.launch_persistent_context: Chromium distribution 'chrome' is not found at "
    '/opt/google/chrome/chrome\nRun "playwright install chrome"'
)


class FakePage:
    def __init__(self):
        self.calls: list[tuple] = []

    def goto(self, url, **kwargs):
        self.calls.append(("goto", url))

    def __getattr__(self, name):  # fill/type/press... : enregistre, pour prouver qu'on n'y touche pas
        def call(*args, **kwargs):
            self.calls.append((name, args))

        return call


class FakeContext:
    def __init__(self, cookies=None):
        self.page = FakePage()
        self.pages = [self.page]
        self._cookies = cookies or []
        self.events: list[tuple] = []
        self.closed = False

    def cookies(self):
        return list(self._cookies)

    def wait_for_event(self, name, timeout=None):
        self.events.append((name, timeout))

    def close(self):
        self.closed = True


class FakeChromium:
    def __init__(self, context, error=None):
        self.context, self.error, self.launches = context, error, []

    def launch_persistent_context(self, user_data_dir, **kwargs):
        self.launches.append((str(user_data_dir), kwargs))
        if self.error:
            raise RuntimeError(self.error)
        Path(user_data_dir).mkdir(parents=True, exist_ok=True)
        (Path(user_data_dir) / "Local State").write_text("{}", encoding="utf-8")
        return self.context


class FakePlaywright:
    def __init__(self, chromium):
        self.chromium, self.stopped = chromium, False

    def stop(self):
        self.stopped = True


class FakeManager:
    def __init__(self, playwright):
        self.playwright = playwright

    def start(self):
        return self.playwright


def fake_playwright(monkeypatch, context=None, error=None):
    context = context or FakeContext()
    chromium = FakeChromium(context, error)
    pw = FakePlaywright(chromium)
    browser.use_playwright(lambda: FakeManager(pw))
    monkeypatch.setattr(browser, "_active", {})
    return context, chromium, pw


@pytest.fixture(autouse=True)
def _reset_override():
    yield
    browser.use_playwright(None)


@pytest.fixture
def cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


# ------------------------------------------------------------------ chemin du profil


def test_profile_dir_is_under_state_browser(cwd):
    assert browser.profile_dir("ab12cd") == Path("state/browser/ab12cd")


@pytest.mark.parametrize("bad", ["", "..", "../x", "a/b", "a\\b", ".hidden", "a b", "x" * 65, "/abs", "a\x00b", "é"])
def test_account_id_rejects_traversal_and_odd_ids(bad):
    with pytest.raises(browser.BrowserError, match="identifiant de compte invalide"):
        browser.profile_dir(bad)


def test_account_id_must_be_a_string():
    with pytest.raises(browser.BrowserError, match="identifiant de compte invalide"):
        browser.profile_dir(None)


def test_gitignore_covers_state_browser():
    out = subprocess.run(
        ["git", "check-ignore", "-q", "state/browser/ab12cd/cookies.txt"],
        cwd=ROOT, capture_output=True,
    )
    assert out.returncode == 0, "state/browser/ doit etre ignore par git"


def test_profile_status_absent_then_present(cwd):
    assert browser.profile_status("ab12cd") == {"present": False, "modified_at": None}
    d = browser.profile_dir("ab12cd")
    d.mkdir(parents=True)
    assert browser.profile_status("ab12cd")["present"] is False  # dossier vide = pas de profil
    (d / "Local State").write_text("{}", encoding="utf-8")
    status = browser.profile_status("ab12cd")
    assert status["present"] is True
    assert status["modified_at"].endswith("+00:00")


# ------------------------------------------------------------------ ouverture / connexion


def test_login_opens_visible_persistent_chrome_on_login_page_and_waits_for_close(cwd, monkeypatch):
    context, chromium, pw = fake_playwright(monkeypatch)

    browser.login("ab12cd")

    (user_dir, kwargs), = chromium.launches
    assert user_dir.replace("\\", "/").endswith("state/browser/ab12cd")
    assert kwargs["channel"] == "chrome"
    assert kwargs["headless"] is False
    assert context.page.calls == [("goto", "https://www.tiktok.com/login")]
    assert context.events == [("close", 0)]  # attend la fermeture de la fenetre, sans delai
    assert pw.stopped is True


def test_login_accepts_another_url(cwd, monkeypatch):
    context, _chromium, _pw = fake_playwright(monkeypatch)

    browser.login("ab12cd", "https://accounts.google.com/ServiceLogin?service=youtube")

    assert context.page.calls == [("goto", "https://accounts.google.com/ServiceLogin?service=youtube")]


@pytest.mark.parametrize("bad", ["file:///etc/passwd", "javascript:alert(1)", "tiktok.com", ""])
def test_login_refuses_non_http_urls(cwd, monkeypatch, bad):
    fake_playwright(monkeypatch)
    with pytest.raises(browser.BrowserError, match="URL invalide"):
        browser.login("ab12cd", bad)


def test_login_never_types_anything(cwd, monkeypatch):
    context, _c, _p = fake_playwright(monkeypatch)

    browser.login("ab12cd")

    assert [c[0] for c in context.page.calls] == ["goto"]
    source = (ROOT / "clipper" / "browser.py").read_text(encoding="utf-8")
    for forbidden in (".fill(", ".type(", ".press(", ".press_sequentially(", ".keyboard"):
        assert forbidden not in source


def test_missing_chrome_is_an_explicit_french_error_with_install_command(cwd, monkeypatch):
    fake_playwright(monkeypatch, error=NO_CHROME)

    with pytest.raises(browser.BrowserError) as err:
        browser.login("ab12cd")

    message = str(err.value)
    assert "Chrome" in message and "playwright install chrome" in message


def test_missing_playwright_is_an_explicit_error_with_install_command(cwd, monkeypatch):
    monkeypatch.setitem(sys.modules, "playwright", None)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", None)
    browser.use_playwright(None)

    with pytest.raises(browser.BrowserError) as err:
        browser.login("ab12cd")

    assert "playwright" in str(err.value) and "uv pip install" in str(err.value)


def test_other_launch_error_is_reported_not_swallowed(cwd, monkeypatch):
    fake_playwright(monkeypatch, error="profil verrouille par un autre processus")

    with pytest.raises(browser.BrowserError, match="profil verrouille"):
        browser.login("ab12cd")


def test_start_login_returns_once_window_is_open_and_refuses_a_second_one(cwd, monkeypatch):
    release = threading.Event()
    context, _c, pw = fake_playwright(monkeypatch)
    context.wait_for_event = lambda name, timeout=None: release.wait(5)

    browser.start_login("ab12cd")
    with pytest.raises(browser.BrowserError, match="deja ouverte|déjà ouverte"):
        browser.start_login("ab12cd")
    release.set()
    for _ in range(100):
        if "ab12cd" not in browser._active:
            break
        threading.Event().wait(0.02)
    assert "ab12cd" not in browser._active
    assert pw.stopped is True


def test_start_login_surfaces_launch_error(cwd, monkeypatch):
    fake_playwright(monkeypatch, error=NO_CHROME)

    with pytest.raises(browser.BrowserError, match="playwright install chrome"):
        browser.start_login("ab12cd")
    assert "ab12cd" not in browser._active


# ------------------------------------------------------------------ export des cookies (R8)

COOKIES = [
    {"name": "SID", "value": "abc", "domain": ".youtube.com", "path": "/", "expires": 1893456000.7,
     "httpOnly": True, "secure": True},
    {"name": "PREF", "value": "x=1", "domain": "www.youtube.com", "path": "/watch", "expires": -1,
     "httpOnly": False, "secure": False},
    {"name": "G", "value": "g", "domain": ".google.com", "path": "/", "expires": 1893456000,
     "httpOnly": False, "secure": True},
    {"name": "tt", "value": "tiktok", "domain": ".tiktok.com", "path": "/", "expires": 1893456000,
     "httpOnly": True, "secure": True},
]


def test_format_netscape_lines():
    text = browser.format_netscape(COOKIES[:2])
    lines = text.splitlines()
    assert lines[0] == "# Netscape HTTP Cookie File"
    assert "#HttpOnly_.youtube.com\tTRUE\t/\tTRUE\t1893456000\tSID\tabc" in lines
    assert "www.youtube.com\tFALSE\t/watch\tFALSE\t0\tPREF\tx=1" in lines  # session : expires 0
    assert text.endswith("\n")


def test_format_netscape_rejects_tab_or_newline_in_a_value():
    bad = [{"name": "a", "value": "x\ty", "domain": ".youtube.com", "path": "/", "expires": 0}]
    with pytest.raises(browser.BrowserError, match="cookie"):
        browser.format_netscape(bad)


def test_export_cookies_writes_netscape_file_with_youtube_google_cookies_only(cwd, monkeypatch):
    context, chromium, pw = fake_playwright(monkeypatch, context=FakeContext(COOKIES))
    browser.profile_dir("yt01").mkdir(parents=True)
    (browser.profile_dir("yt01") / "Local State").write_text("{}", encoding="utf-8")

    path = browser.export_cookies("yt01")

    assert path == Path("state/browser/yt01/cookies.txt")
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# Netscape HTTP Cookie File\n")
    assert "SID" in text and "PREF" in text and "\tG\t" in text
    assert "tiktok" not in text  # les cookies TikTok ne servent pas a yt-dlp : ils ne sortent pas du profil
    assert chromium.launches[0][1]["channel"] == "chrome"
    assert context.closed and pw.stopped
    assert list(path.parent.glob("*.tmp")) == []


def test_export_cookies_without_profile_is_an_explicit_error(cwd, monkeypatch):
    fake_playwright(monkeypatch)

    with pytest.raises(browser.BrowserError, match="clipper browser login yt01"):
        browser.export_cookies("yt01")


def test_export_cookies_without_youtube_cookie_is_an_explicit_error(cwd, monkeypatch):
    fake_playwright(monkeypatch, context=FakeContext([COOKIES[3]]))
    browser.profile_dir("yt01").mkdir(parents=True)
    (browser.profile_dir("yt01") / "Local State").write_text("{}", encoding="utf-8")

    with pytest.raises(browser.BrowserError, match="aucun cookie"):
        browser.export_cookies("yt01")


def test_export_cookies_refused_while_login_window_is_open(cwd, monkeypatch):
    fake_playwright(monkeypatch)
    browser.profile_dir("yt01").mkdir(parents=True)
    (browser.profile_dir("yt01") / "Local State").write_text("{}", encoding="utf-8")
    browser._active["yt01"] = object()

    with pytest.raises(browser.BrowserError, match="fenêtre de connexion"):
        browser.export_cookies("yt01")


# ------------------------------------------------------------------ CLI


def test_parser_browser_login_defaults_and_url():
    parser = cli.build_parser()

    args = parser.parse_args(["browser", "login", "ab12cd"])
    assert (args.command, args.browser_command, args.account, args.url) == ("browser", "login", "ab12cd", None)

    args = parser.parse_args(["browser", "login", "ab12cd", "--url", "https://www.youtube.com"])
    assert args.url == "https://www.youtube.com"


def test_parser_browser_requires_subcommand(capsys):
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["browser"])


def _config_file(tmp_path, accounts_json='{"accounts": [{"id": "ab12cd", "label": "Compte"}]}'):
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "accounts.json").write_text(accounts_json, encoding="utf-8")
    cfg = tmp_path / "config.toml"
    cfg.write_text('mode = "review"\n', encoding="utf-8")
    return cfg


def test_main_browser_login_calls_browser_login(cwd, monkeypatch):
    cfg = _config_file(cwd)
    calls = []
    monkeypatch.setattr(browser, "login", lambda account, url=None, **kw: calls.append((account, url)))

    code = cli.main(["--config", str(cfg), "browser", "login", "ab12cd", "--url", "https://www.youtube.com"])

    assert code == 0
    assert calls == [("ab12cd", "https://www.youtube.com")]


def test_main_browser_login_unknown_account_is_an_error(cwd, monkeypatch, capsys):
    cfg = _config_file(cwd)
    monkeypatch.setattr(browser, "login", lambda *a, **k: pytest.fail("ne doit pas s'ouvrir"))

    code = cli.main(["--config", str(cfg), "browser", "login", "zz99"])

    assert code == 1
    assert "compte inconnu" in capsys.readouterr().err


def test_main_browser_login_reports_browser_error(cwd, monkeypatch, capsys):
    cfg = _config_file(cwd)

    def boom(*a, **k):
        raise browser.BrowserError("Chrome introuvable : playwright install chrome")

    monkeypatch.setattr(browser, "login", boom)

    code = cli.main(["--config", str(cfg), "browser", "login", "ab12cd"])

    assert code == 1
    assert "playwright install chrome" in capsys.readouterr().err


# ------------------------------------------------------------------ installation et documentation


def test_playwright_is_a_project_dependency():
    import tomllib

    deps = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["dependencies"]
    assert "playwright" in deps


def test_setup_script_checks_playwright_and_chrome_with_a_clear_message():
    script = (ROOT / "tools" / "setup.ps1").read_text(encoding="utf-8")

    assert "import playwright.sync_api" in script
    assert "chrome.exe" in script and "Google Chrome introuvable" in script
    assert "playwright install chrome" in script


def test_readme_documents_tiktok_publishing_and_youtube_cookies():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    tiktok = readme.split("## Publier sur TikTok", 1)[1].split("\n## ", 1)[0]
    cookies = readme.split("## Cookies YouTube", 1)[1].split("\n## ", 1)[0]

    assert "tiktok_account" in tiktok and "browser login" in tiktok
    assert "à la main" in tiktok and "jamais" in tiktok          # connexion manuelle, aucun identifiant saisi
    assert "Risques" in tiktok and "captcha" in tiktok.lower() and "arrêt" in tiktok
    assert "cookies_profile" in cookies and "cookies_from_browser" in cookies


def test_browser_section_resolves_through_clipper_config(tmp_path):
    from clipper.config import load_config

    (tmp_path / "config.toml").write_text('[browser]\nlogin_url = "https://exemple.invalid/login"\n', encoding="utf-8")

    section = load_config(tmp_path / "config.toml").section("browser")

    assert section["login_url"] == "https://exemple.invalid/login"
    assert section["cookie_domains"] == ["youtube.com", "google.com"]
