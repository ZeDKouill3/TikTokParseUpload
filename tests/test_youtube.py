"""Tests de clipper.youtube, des comptes YouTube et du pilotage commun (TASK-883c, SPEC-5e50 R1, R5, R8).

Aucun test ne touche YouTube, le reseau ni un vrai navigateur : fausses pages, faux Playwright.
"""

from __future__ import annotations

import json
import random
import re
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from clipper import accounts, browser, youtube
from clipper.config import Config
from clipper.web import create_app

ROOT = Path(__file__).resolve().parent.parent
SELECTORS = ROOT / "clipper" / "assets" / "youtube_selectors.toml"
NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)
UC = "UCabcdefghijklmnopqrstuv"
STUDIO = "https://studio.youtube.com"
CHANNEL_URL = f"{STUDIO}/channel/{UC}/videos/short"
LOGIN_URL = "https://accounts.google.com/v3/signin/identifier?service=youtube"


def _sel() -> dict:
    return youtube.load_selectors()


def make_config(tmp_path) -> Config:
    return Config(mode="review", workspace_dir=tmp_path / "workspace", output_dir=tmp_path / "output")


# ---------------------------------------------------------------- fausse page YouTube Studio


class FakeElement:
    def __init__(self, page, text="", on_click=None, visible=True):
        self.page, self.text, self.on_click, self.visible = page, text, on_click, visible
        self.children: dict[str, "FakeElement"] = {}

    def click(self, **kwargs):
        self.page.calls.append(("click", self.text))
        if self.on_click is not None:
            self.on_click()

    def inner_text(self):
        return self.text

    def is_visible(self):
        return self.visible

    def query_selector(self, selector):
        return self.children.get(selector)


class FakeStudio:
    """YouTube Studio simule : ``redirect`` = adresse reelle apres goto ; ``nav_text`` = texte de la navigation ;
    ``dialogs`` = fenetres surgissantes (texte, libelle du bouton)."""

    def __init__(self, *, redirect=CHANNEL_URL, nav_text="Votre chaîne Ma Chaîne\nTableau de bord\nContenu",
                 dialogs=(), screenshot_error=None):
        self.url = "about:blank"
        self.redirect, self.nav_text, self.screenshot_error = redirect, nav_text, screenshot_error
        self.calls: list[tuple] = []
        self.dialogs: list[FakeElement] = []
        self.closed: list[str] = []
        for text, label in dialogs:
            self.add_dialog(text, label)

    def add_dialog(self, text, label):
        dialog = FakeElement(self, text=text)
        button_sel = _sel()["modal"]["button"].format(label=label)
        dialog.children[button_sel] = FakeElement(self, text=label, on_click=lambda: self.close(dialog, label))
        self.dialogs.append(dialog)

    def close(self, dialog, label):
        self.dialogs.remove(dialog)
        self.closed.append(label)

    def goto(self, url, **kwargs):
        self.calls.append(("goto", url))
        self.url = self.redirect

    def query_selector_all(self, selector):
        if selector == _sel()["modal"]["container"]:
            return list(self.dialogs)
        if selector == _sel()["selectors"]["navigation"] and self.nav_text is not None:
            return [FakeElement(self, text=self.nav_text)]
        return []

    def query_selector(self, selector):
        found = self.query_selector_all(selector)
        return found[0] if found else None

    def wait_for_timeout(self, ms):
        self.calls.append(("poll", ms))

    def screenshot(self, path=None, **kwargs):
        if self.screenshot_error:
            raise RuntimeError(self.screenshot_error)
        Path(path).write_bytes(b"\x89PNG fake")


class FakeContext:
    def __init__(self, page):
        self.page, self.pages = page, [page]

    def new_page(self):
        return self.page


def verify(tmp_path, monkeypatch, page, **settings):
    monkeypatch.chdir(tmp_path)
    opened = []
    sleeps = []

    @contextmanager
    def opener(account, *, headless):
        opened.append((account, headless))
        yield FakeContext(page)

    config = Config(mode="review", workspace_dir=tmp_path / "w", output_dir=tmp_path / "o",
                    _sections={"youtube": settings})
    result = youtube.verify_login("ma_chaine", config=config, now=NOW, opener=opener, sleep=sleeps.append,
                                  rng=random.Random(1))
    return result, opened, sleeps


# ---------------------------------------------------------------- reglages et reperes


def test_youtube_defaults_follow_r5():
    d = youtube.CONFIG_DEFAULTS
    assert (d["max_posts_per_day"], d["min_gap_minutes"]) == (3, 120)
    assert d["min_action_delay_s"] <= d["max_action_delay_s"]


def test_youtube_section_resolves_through_clipper_config():
    config = Config(mode="review", workspace_dir=Path("w"), output_dir=Path("o"), _sections={"youtube": {"max_posts_per_day": 2}})
    assert config.section("youtube")["max_posts_per_day"] == 2
    assert youtube.get_settings(config)["max_posts_per_day"] == 2


@pytest.mark.parametrize("key,value", [("max_posts_per_day", 0), ("min_gap_minutes", -1), ("action_timeout_s", 0),
                                       ("max_action_delay_s", True)])
def test_an_invalid_youtube_setting_is_an_explicit_error(key, value):
    config = Config(mode="review", workspace_dir=Path("w"), output_dir=Path("o"), _sections={"youtube": {key: value}})
    with pytest.raises(youtube.YouTubeError, match=key):
        youtube.get_settings(config)


def test_min_delay_above_max_delay_is_an_explicit_error():
    config = Config(mode="review", workspace_dir=Path("w"), output_dir=Path("o"),
                    _sections={"youtube": {"min_action_delay_s": 5, "max_action_delay_s": 1}})
    with pytest.raises(youtube.YouTubeError, match="min_action_delay_s"):
        youtube.get_settings(config)


def test_the_selectors_file_is_loaded_and_holds_the_surveyed_landmarks():
    data = _sel()
    assert data["urls"]["studio"] == STUDIO
    assert re.search(data["expect"]["channel_url_pattern"], CHANNEL_URL).group(1) == UC
    assert "accounts.google.com" in data["expect"]["login_url_markers"]
    assert data["labels"]["channel_prefix"] == "Votre chaîne"
    assert data["popups"] == {"Bienvenue dans YouTube Studio": "Continuer"}


def test_the_surveyed_landmarks_are_marked_verified_on_2026_10_03():
    text = SELECTORS.read_text(encoding="utf-8")
    assert text.count("vérifié 2026-10-03") >= 4
    assert "NON VÉRIFIÉ" in text  # un repere ecrit sans releve reel ne se fait pas passer pour verifie (R4)


@pytest.mark.parametrize("table,key", [("urls", "studio"), ("expect", "channel_url_pattern"),
                                       ("expect", "login_url_markers"), ("labels", "channel_prefix"),
                                       ("selectors", "navigation"), ("modal", "container"), ("modal", "button")])
def test_a_missing_selector_is_an_explicit_error_naming_the_key(tmp_path, table, key):
    text = SELECTORS.read_text(encoding="utf-8")
    broken = re.sub(rf"(?m)^{key} = ", f"{key}_absent = ", text, count=1)
    assert broken != text
    bad = tmp_path / "s.toml"
    bad.write_text(broken, encoding="utf-8")
    with pytest.raises(youtube.YouTubeError, match=rf"\[{table}\] {key}"):
        youtube.load_selectors(bad)


def test_a_missing_popups_table_is_an_explicit_error(tmp_path):
    text = SELECTORS.read_text(encoding="utf-8").replace("[popups]", "[popups_absent]")
    bad = tmp_path / "s.toml"
    bad.write_text(text, encoding="utf-8")
    with pytest.raises(youtube.YouTubeError, match=r"\[popups\]"):
        youtube.load_selectors(bad)


def test_a_missing_selectors_file_is_an_explicit_error(tmp_path):
    with pytest.raises(youtube.YouTubeError, match="introuvable"):
        youtube.load_selectors(tmp_path / "absent.toml")


def test_the_channel_url_pattern_must_capture_the_channel_id(tmp_path):
    text = SELECTORS.read_text(encoding="utf-8")
    broken = re.sub(r"(?m)^channel_url_pattern = .*$", "channel_url_pattern = 'studio\\.youtube\\.com/channel/'", text)
    bad = tmp_path / "s.toml"
    bad.write_text(broken, encoding="utf-8")
    with pytest.raises(youtube.YouTubeError, match="channel_url_pattern"):
        youtube.load_selectors(bad)


# ---------------------------------------------------------------- verification « pret a publier » (R1)


def test_a_connected_studio_gives_ready_with_the_channel_name_and_id(tmp_path, monkeypatch):
    page = FakeStudio()
    result, opened, sleeps = verify(tmp_path, monkeypatch, page)

    assert result["ready"] is True
    assert result["channel"] == {"name": "Ma Chaîne", "id": UC}
    assert result["reason"] is None
    assert ("goto", STUDIO) in page.calls
    assert opened == [("ma_chaine", False)]  # visible : jamais de navigateur cache (ADR-58c0)


def test_the_channel_name_is_read_after_the_label_in_the_navigation(tmp_path, monkeypatch):
    page = FakeStudio(nav_text="Menu\nVotre chaîne   Les Aventures de Léa \nContenu")
    result, _, _ = verify(tmp_path, monkeypatch, page)
    assert result["channel"]["name"] == "Les Aventures de Léa"


def test_the_google_login_page_is_not_ready_with_a_reason(tmp_path, monkeypatch):
    page = FakeStudio(redirect=LOGIN_URL, nav_text=None)
    result, _, _ = verify(tmp_path, monkeypatch, page)

    assert result["ready"] is False
    assert result["channel"] is None
    assert "connexion Google" in result["reason"] and "Se connecter" in result["reason"]


def test_a_google_verification_page_is_not_ready_too(tmp_path, monkeypatch):
    page = FakeStudio(redirect="https://accounts.google.com/v3/signin/challenge/pwd", nav_text=None)
    result, _, _ = verify(tmp_path, monkeypatch, page)
    assert result["ready"] is False and "connexion Google" in result["reason"]


def test_an_unexpected_page_is_not_ready_with_the_address_and_a_capture(tmp_path, monkeypatch):
    page = FakeStudio(redirect="https://www.youtube.com/", nav_text=None)
    result, _, _ = verify(tmp_path, monkeypatch, page, action_timeout_s=2, poll_interval_s=1)

    assert result["ready"] is False
    assert "https://www.youtube.com/" in result["reason"]
    assert result["capture"] and Path(result["capture"]).is_file()
    assert Path(result["capture"]).parent == browser.profile_dir("ma_chaine") / "captures"
    assert [c for c in page.calls if c[0] == "poll"]  # attente bornee de l'adresse de chaine


def test_a_channel_page_without_the_channel_label_is_not_ready(tmp_path, monkeypatch):
    page = FakeStudio(nav_text="Tableau de bord\nContenu")
    result, _, _ = verify(tmp_path, monkeypatch, page)
    assert result["ready"] is False and "Votre chaîne" in result["reason"]


def test_an_empty_channel_name_is_not_ready(tmp_path, monkeypatch):
    page = FakeStudio(nav_text="Votre chaîne   \nContenu")
    result, _, _ = verify(tmp_path, monkeypatch, page)
    assert result["ready"] is False and "nom" in result["reason"]


def test_the_welcome_dialog_is_closed_with_continue_when_present(tmp_path, monkeypatch):
    page = FakeStudio(dialogs=[("Bienvenue dans YouTube Studio Gérez votre chaîne", "Continuer")])
    result, _, _ = verify(tmp_path, monkeypatch, page)

    assert page.closed == ["Continuer"]
    assert result["ready"] is True


def test_no_welcome_dialog_means_no_click(tmp_path, monkeypatch):
    page = FakeStudio()
    verify(tmp_path, monkeypatch, page)
    assert not [c for c in page.calls if c[0] == "click"]


def test_an_unknown_dialog_is_not_ready_and_never_clicked(tmp_path, monkeypatch):
    page = FakeStudio(dialogs=[("Une fenêtre jamais vue", "OK")])
    result, _, _ = verify(tmp_path, monkeypatch, page)

    assert result["ready"] is False and "Une fenêtre jamais vue" in result["reason"]
    assert page.closed == []


def test_a_known_dialog_without_its_button_is_not_ready(tmp_path, monkeypatch):
    page = FakeStudio()
    dialog = FakeElement(page, text="Bienvenue dans YouTube Studio")
    page.dialogs.append(dialog)
    result, _, _ = verify(tmp_path, monkeypatch, page)
    assert result["ready"] is False and "Continuer" in result["reason"]


def test_the_verification_pauses_like_a_human(tmp_path, monkeypatch):
    page = FakeStudio(dialogs=[("Bienvenue dans YouTube Studio", "Continuer")])
    _, _, sleeps = verify(tmp_path, monkeypatch, page, min_action_delay_s=0.2, max_action_delay_s=0.4)
    assert sleeps and all(0.2 <= s <= 0.4 for s in sleeps)


def test_a_failed_capture_is_said_in_the_reason_never_swallowed(tmp_path, monkeypatch):
    page = FakeStudio(redirect="https://www.youtube.com/", nav_text=None, screenshot_error="boom")
    result, _, _ = verify(tmp_path, monkeypatch, page, action_timeout_s=1, poll_interval_s=1)
    assert result["capture"] is None and "capture d'écran impossible" in result["reason"]


def test_an_invalid_account_id_is_refused_before_any_browser(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(browser.BrowserError, match="identifiant de compte invalide"):
        youtube.verify_login("../x", opener=lambda *a, **k: pytest.fail("navigateur ouvert"))


def test_the_default_opener_is_the_shared_browser_context_with_paris_time(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    page = FakeStudio()
    context = FakeBrowserContext(page)
    chromium = install_fake_playwright(monkeypatch, context)

    result = youtube.verify_login("ma_chaine", now=NOW, sleep=lambda s: None, rng=random.Random(1))

    assert result["ready"] is True
    (_, kwargs), = chromium.launches
    assert kwargs["timezone_id"] == "Europe/Paris" and kwargs["headless"] is False and context.closed


# ---------------------------------------------------------------- navigateur : heure de Paris et verrou (R8, R5)


class FakeBrowserContext(FakeContext):
    def __init__(self, page=None, on_close=None):
        super().__init__(page or FakeStudio())
        self.closed, self._on_close = False, on_close

    def close(self):
        self.closed = True
        if self._on_close:
            self._on_close()


class FakeChromium:
    def __init__(self, contexts):
        self.contexts, self.launches = list(contexts), []

    def launch_persistent_context(self, user_data_dir, **kwargs):
        self.launches.append((str(user_data_dir), kwargs))
        Path(user_data_dir).mkdir(parents=True, exist_ok=True)
        return self.contexts.pop(0) if len(self.contexts) > 1 else self.contexts[0]


class FakePlaywright:
    def __init__(self, chromium):
        self.chromium = chromium

    def stop(self):
        pass


class FakeManager:
    def __init__(self, chromium):
        self.chromium = chromium

    def start(self):
        return FakePlaywright(self.chromium)


def install_fake_playwright(monkeypatch, *contexts):
    chromium = FakeChromium(contexts)
    browser.use_playwright(lambda: FakeManager(chromium))
    monkeypatch.setattr(browser, "_active", {})
    return chromium


@pytest.fixture(autouse=True)
def _reset_browser():
    yield
    browser.use_playwright(None)


def test_every_driven_context_is_launched_with_the_paris_timezone(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    chromium = install_fake_playwright(monkeypatch, FakeBrowserContext())

    with browser._open_context("ma_chaine", headless=False):
        pass

    (_, kwargs), = chromium.launches
    assert kwargs["timezone_id"] == "Europe/Paris"
    assert browser.TIMEZONE == "Europe/Paris"


def test_two_accounts_are_never_driven_at_the_same_time_whatever_their_service(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    install_fake_playwright(monkeypatch, FakeBrowserContext(), FakeBrowserContext())
    monkeypatch.setitem(browser.CONFIG_DEFAULTS, "pilot_wait_s", 0.1)

    with browser._open_context("compte_tiktok", headless=False):
        with pytest.raises(browser.BrowserError, match="compte_tiktok"):
            with browser._open_context("compte_youtube", headless=False):
                pytest.fail("deux comptes pilotes en meme temps")


def test_the_second_account_waits_for_the_first_then_goes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    install_fake_playwright(monkeypatch, FakeBrowserContext(), FakeBrowserContext())
    monkeypatch.setitem(browser.CONFIG_DEFAULTS, "pilot_wait_s", 10)
    order: list[str] = []
    inside = threading.Event()
    release = threading.Event()

    def first():
        with browser._open_context("compte_tiktok", headless=False):
            order.append("tiktok-in")
            inside.set()
            release.wait(5)
            order.append("tiktok-out")

    def second():
        with browser._open_context("compte_youtube", headless=False):
            order.append("youtube-in")

    t1 = threading.Thread(target=first)
    t1.start()
    assert inside.wait(5)
    t2 = threading.Thread(target=second)
    t2.start()
    t2.join(0.3)
    assert t2.is_alive() and order == ["tiktok-in"]  # le second attend : jamais en meme temps
    release.set()
    t1.join(5)
    t2.join(5)
    assert order == ["tiktok-in", "tiktok-out", "youtube-in"]


def test_the_lock_is_released_when_the_launch_fails(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    chromium = install_fake_playwright(monkeypatch, FakeBrowserContext())
    monkeypatch.setitem(browser.CONFIG_DEFAULTS, "pilot_wait_s", 0.1)

    def boom(*a, **k):
        raise RuntimeError("Chromium distribution 'chrome' is not found")

    real = chromium.launch_persistent_context
    chromium.launch_persistent_context = boom
    with pytest.raises(browser.BrowserError, match="Chrome est introuvable"):
        with browser._open_context("compte_tiktok", headless=False):
            pass
    chromium.launch_persistent_context = real
    with browser._open_context("compte_youtube", headless=False):  # ne bloque pas
        pass


def test_the_pilot_wait_is_a_browser_setting():
    assert browser.CONFIG_DEFAULTS["pilot_wait_s"] > 0


def test_youtube_login_opens_a_normal_chrome_on_studio_never_playwright(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    launched = []

    class Proc:
        def wait(self):
            return 0

    monkeypatch.setattr(browser, "_popen", lambda cmd, **kw: launched.append(cmd) or Proc())
    monkeypatch.setattr(browser, "find_chrome", lambda config=None: Path("chrome"))
    browser.use_playwright(lambda: pytest.fail("Playwright lance pour la connexion"))

    browser.login("ma_chaine", youtube.studio_url())

    (cmd,) = launched
    assert cmd[-1] == STUDIO
    assert any(a.startswith("--user-data-dir=") and a.endswith("ma_chaine") for a in cmd)


# ---------------------------------------------------------------- comptes : service et migration (R1)


def _write_accounts(tmp_path, accounts_list):
    (tmp_path / "state").mkdir(exist_ok=True)
    (tmp_path / "state" / "accounts.json").write_text(json.dumps({"accounts": accounts_list}), encoding="utf-8")


def test_existing_accounts_without_a_service_become_tiktok_on_read(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_accounts(tmp_path, [{"id": "ab12cd", "label": "Ancien compte", "platform": "TikTok", "username": "",
                                "notes": "", "has_password": False}])

    listed = accounts.list_accounts(make_config(tmp_path))

    assert [a["service"] for a in listed] == ["tiktok"]


def test_the_migration_is_written_on_the_next_save_without_user_action(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_accounts(tmp_path, [{"id": "ab12cd", "label": "Ancien compte", "platform": "", "username": "",
                                "notes": "", "has_password": False}])
    config = make_config(tmp_path)

    accounts.update_account(config, "ab12cd", {"notes": "x"})

    saved = json.loads((tmp_path / "state" / "accounts.json").read_text(encoding="utf-8"))
    assert saved["accounts"][0]["service"] == "tiktok"


def test_an_account_is_added_with_a_service_defaulting_to_tiktok(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = make_config(tmp_path)

    tiktok = accounts.add_account(config, {"label": "Compte A"})
    yt = accounts.add_account(config, {"label": "ma_chaine", "service": "youtube"})

    assert tiktok["service"] == "tiktok" and yt["service"] == "youtube"
    assert [a["service"] for a in accounts.list_accounts(config)] == ["tiktok", "youtube"]


@pytest.mark.parametrize("bad", ["twitch", "", 3, None])
def test_an_unknown_service_is_an_explicit_error(tmp_path, monkeypatch, bad):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(accounts.AccountsError, match="service"):
        accounts.add_account(make_config(tmp_path), {"label": "x", "service": bad})


def test_the_service_of_an_account_cannot_change(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = make_config(tmp_path)
    created = accounts.add_account(config, {"label": "ma_chaine", "service": "youtube"})

    with pytest.raises(accounts.AccountsError, match="service"):
        accounts.update_account(config, created["id"], {"service": "tiktok"})
    assert accounts.update_account(config, created["id"], {"service": "youtube", "notes": "ok"})["notes"] == "ok"


def test_a_youtube_account_is_not_ready_until_its_channel_is_verified(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = make_config(tmp_path)
    created = accounts.add_account(config, {"label": "ma_chaine", "service": "youtube"})

    assert accounts.ready_blocked_reason(created) and "YouTube" in accounts.ready_blocked_reason(created)
    done = accounts.record_login(config, created["id"], {
        "state": "connected", "channel": {"name": "Ma Chaîne", "id": UC}})

    assert done["ready_to_publish"] is True and done["auto_checked"] is True
    assert done["channel"] == {"name": "Ma Chaîne", "id": UC}
    assert accounts.ready_blocked_reason(done) is None


def test_a_google_login_page_unchecks_the_account_with_the_reason(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = make_config(tmp_path)
    created = accounts.add_account(config, {"label": "ma_chaine", "service": "youtube"})
    accounts.record_login(config, created["id"], {"state": "connected", "channel": {"name": "Ma Chaîne", "id": UC}})

    out = accounts.record_login(config, created["id"], {"state": "never", "reason": "page de connexion Google affichée"})

    assert out["ready_to_publish"] is False and out["auto_unchecked"] is True
    assert "YouTube" in out["ready_note"]
    assert accounts.ready_blocked_reason(out)


def test_a_connected_observation_without_a_channel_is_refused_for_youtube(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = make_config(tmp_path)
    created = accounts.add_account(config, {"label": "ma_chaine", "service": "youtube"})
    with pytest.raises(accounts.AccountsError, match="chaîne"):
        accounts.record_login(config, created["id"], {"state": "connected"})


# ---------------------------------------------------------------- API web (R1)


def local_client(tmp_path) -> TestClient:
    return TestClient(create_app(config=make_config(tmp_path)), base_url="http://127.0.0.1:8000",
                      client=("127.0.0.1", 50000))


def test_a_youtube_account_is_added_through_the_web_api_and_listed_with_its_service(tmp_path, isolated_cwd):
    c = local_client(tmp_path)

    created = c.post("/api/accounts", json={"label": "ma_chaine", "service": "youtube"})
    assert created.status_code == 201 and created.json()["service"] == "youtube"
    c.post("/api/accounts", json={"label": "Compte TikTok"})

    listed = c.get("/api/accounts").json()
    assert {a["label"]: a["service"] for a in listed} == {"ma_chaine": "youtube", "Compte TikTok": "tiktok"}


def test_the_web_api_refuses_an_unknown_service(tmp_path, isolated_cwd):
    resp = local_client(tmp_path).post("/api/accounts", json={"label": "x", "service": "twitch"})
    assert resp.status_code == 422 and "service" in resp.json()["detail"]


def test_listing_a_youtube_account_never_reads_tiktok_cookies(tmp_path, isolated_cwd, monkeypatch):
    c = local_client(tmp_path)
    c.post("/api/accounts", json={"label": "ma_chaine", "service": "youtube"})
    monkeypatch.setattr(browser, "login_state", lambda *a, **k: pytest.fail("cookies TikTok lus pour un compte YouTube"))

    listed = c.get("/api/accounts").json()

    assert listed[0]["service"] == "youtube" and listed[0]["ready_to_publish"] is False
    assert "YouTube" in listed[0]["ready_blocked_reason"]


def test_youtube_login_opens_studio_by_default_and_verifies_the_channel_on_close(tmp_path, isolated_cwd, monkeypatch):
    c = local_client(tmp_path)
    account = c.post("/api/accounts", json={"label": "ma_chaine", "service": "youtube"}).json()
    seen = {}

    def fake_start_login(account_id, url=None, *, config=None, on_close=None):
        seen.update(account=account_id, url=url)
        on_close()  # l'utilisateur ferme la fenetre

    monkeypatch.setattr(browser, "start_login", fake_start_login)
    monkeypatch.setattr(youtube, "verify_login", lambda account_id, **kw: {
        "ready": True, "reason": None, "channel": {"name": "Ma Chaîne", "id": UC}, "capture": None})

    resp = c.post(f"/api/accounts/{account['id']}/browser/login", json={})

    assert resp.status_code == 202
    assert seen == {"account": account["id"], "url": STUDIO}
    listed = c.get("/api/accounts").json()[0]
    assert listed["ready_to_publish"] is True and listed["channel"] == {"name": "Ma Chaîne", "id": UC}


def test_the_verify_route_records_a_not_ready_youtube_account_with_the_reason(tmp_path, isolated_cwd, monkeypatch):
    c = local_client(tmp_path)
    account = c.post("/api/accounts", json={"label": "ma_chaine", "service": "youtube"}).json()
    monkeypatch.setattr(youtube, "verify_login", lambda account_id, **kw: {
        "ready": False, "reason": "page de connexion Google affichée : connecte-toi", "channel": None, "capture": None})

    resp = c.post(f"/api/accounts/{account['id']}/verify", json={})

    assert resp.status_code == 200
    body = resp.json()
    assert body["ready_to_publish"] is False and "connexion" in body["ready_blocked_reason"]


def test_the_verify_route_reports_a_browser_error_without_fallback(tmp_path, isolated_cwd, monkeypatch):
    c = local_client(tmp_path)
    account = c.post("/api/accounts", json={"label": "ma_chaine", "service": "youtube"}).json()

    def boom(account_id, **kw):
        raise browser.BrowserError("Chrome est introuvable : installe Google Chrome")

    monkeypatch.setattr(youtube, "verify_login", boom)

    resp = c.post(f"/api/accounts/{account['id']}/verify", json={})

    assert resp.status_code == 409 and "Chrome est introuvable" in resp.json()["detail"]
    assert c.get("/api/accounts").json()[0]["ready_to_publish"] is False


def test_the_verify_route_refuses_a_tiktok_account_and_an_unknown_account(tmp_path, isolated_cwd):
    c = local_client(tmp_path)
    account = c.post("/api/accounts", json={"label": "Compte TikTok"}).json()
    assert c.post(f"/api/accounts/{account['id']}/verify", json={}).status_code == 409
    assert c.post("/api/accounts/inconnu/verify", json={}).status_code == 404


# ---------------------------------------------------------------- ecran Comptes


STATIC = ROOT / "clipper" / "web" / "static"


def test_the_accounts_screen_offers_the_service_choice_and_shows_it_on_each_account():
    js = (STATIC / "screens" / "accounts.js").read_text(encoding="utf-8")
    assert 'name="service"' in js and "YouTube" in js
    assert "a.service" in js
    assert "/verify" in js
