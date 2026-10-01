"""TASK-0b78 : clipper.tiktok (SPEC-9225 R3-R6, R9, ADR-1a58).

Playwright n'est jamais lance : une fausse page (objets simules) rejoue les cas
succes, captcha, verification, connexion expiree, element absent, page
inattendue. Aucun navigateur, aucun reseau, aucun TikTok.
"""

from __future__ import annotations

import ast
import json
import random
import tomllib
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from clipper import browser, tiktok
from clipper.config import Config

ROOT = Path(__file__).resolve().parent.parent
SELECTORS = ROOT / "clipper" / "assets" / "tiktok_selectors.toml"
NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
LINK = "https://www.tiktok.com/@ma_chaine/video/7300000000000000001"


def _sel() -> dict:
    return tiktok.load_selectors()


# ---------------------------------------------------------------- fausse page


class FakeElement:
    def __init__(self, page, selector, href=None):
        self.page, self.selector, self.href = page, selector, href

    def click(self, **kwargs):
        self.page.calls.append(("click", self.selector))
        if self.page.fail_click:
            raise RuntimeError("Target page, context or browser has been closed")
        for added in self.page.after_click.get(self.selector, ()):
            self.page.present.add(added)

    def fill(self, text, **kwargs):
        self.page.calls.append(("fill", self.selector, text))

    def get_attribute(self, name):
        return self.href if name == "href" else None


class FakePage:
    """``present`` : selecteurs actuellement affiches ; ``redirect`` : adresse
    reelle apres goto ; ``after_click`` : selecteur clique -> selecteurs qui apparaissent."""

    def __init__(self, present, *, redirect=None, link=LINK, screenshot_error=None):
        self.present = set(present)
        self.redirect, self.link, self.screenshot_error = redirect, link, screenshot_error
        self.after_click: dict[str, list[str]] = {}
        self.fail_click = False
        self.url = "about:blank"
        self.calls: list[tuple] = []

    def goto(self, url, **kwargs):
        self.calls.append(("goto", url))
        self.url = self.redirect or url

    def query_selector(self, selector):
        return FakeElement(self, selector, href=self.link) if selector in self.present else None

    def wait_for_selector(self, selector, timeout=None, state=None):
        self.calls.append(("wait", selector))
        if selector not in self.present:
            raise TimeoutError(f"Timeout {timeout}ms exceeded waiting for {selector}")
        return FakeElement(self, selector, href=self.link)

    def set_input_files(self, selector, path, **kwargs):
        self.calls.append(("upload", selector, str(path)))

    def screenshot(self, path=None, **kwargs):
        if self.screenshot_error:
            raise RuntimeError(self.screenshot_error)
        Path(path).write_bytes(b"\x89PNG fake")

    def clicks(self):
        return [c[1] for c in self.calls if c[0] == "click"]

    def fills(self):
        return [c for c in self.calls if c[0] == "fill"]


class FakeContext:
    def __init__(self, page):
        self.page, self.pages = page, [page]

    def new_page(self):
        return self.page


def _happy_present(selectors=None) -> set[str]:
    return set((selectors or _sel())["selectors"].values())


class Env:
    """Une publication complete contre une fausse page."""

    def __init__(self, tmp_path, monkeypatch, *, remove=(), detect=None, page_kwargs=None, settings=None):
        monkeypatch.chdir(tmp_path)
        present = _happy_present()
        for name in remove:
            present.discard(_sel()["selectors"][name])
        for kind in (detect or ()):
            present.add(_sel()["detect"][kind][0])
        self.page = FakePage(present, **(page_kwargs or {}))
        self.opened: list[tuple] = []
        self.sleeps: list[float] = []
        self.ticks = 0
        self.mp4 = tmp_path / "output" / "aaaaaaaaaaa" / "01.mp4"
        self.mp4.parent.mkdir(parents=True, exist_ok=True)
        self.mp4.write_bytes(b"mp4")
        self.config = Config(mode="review", workspace_dir=tmp_path / "w", output_dir=tmp_path / "output",
                             _sections={"tiktok": settings or {}})
        self.clip = {"video_path": self.mp4, "caption": "Ma legende", "hashtags": ["#un", "#deux"]}

    @contextmanager
    def opener(self, account, *, headless):
        self.opened.append((account, headless))
        yield FakeContext(self.page)

    def publish(self, mode="immediate", schedule_at=None, **kwargs):
        return tiktok.publish(
            self.clip, "ma_chaine", mode=mode, schedule_at=schedule_at, config=self.config, now=NOW,
            opener=self.opener, sleep=self.sleeps.append, rng=random.Random(1),
            on_tick=lambda: setattr(self, "ticks", self.ticks + 1), **kwargs)


@pytest.fixture
def env(tmp_path, monkeypatch):
    return Env(tmp_path, monkeypatch)


# ---------------------------------------------------------------- (1) interface, backend, defauts


def test_tiktok_defaults_are_the_new_account_values_of_the_cadence_study():
    d = tiktok.CONFIG_DEFAULTS
    assert d["backend"] == "browser"
    assert (d["max_posts_per_day"], d["min_gap_minutes"]) == (1, 480)
    assert (d["min_action_delay_s"], d["max_action_delay_s"]) == (3, 12)
    assert d["schedule_max_days"] == 10


def test_tiktok_section_is_a_valid_config_table(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('mode = "review"\n[tiktok]\nmax_posts_per_day = 3\n', encoding="utf-8")
    from clipper.config import load_config

    assert load_config(cfg).section("tiktok")["max_posts_per_day"] == 3


def test_api_backend_is_an_explicit_not_yet_available_error(env):
    env.config = Config(mode="review", workspace_dir=Path("w"), output_dir=Path("o"),
                        _sections={"tiktok": {"backend": "api"}})
    with pytest.raises(tiktok.TikTokError, match="pas encore disponible"):
        env.publish()
    with pytest.raises(tiktok.TikTokError, match="pas encore disponible"):
        tiktok.fetch_stats("ma_chaine", config=env.config)
    assert env.opened == []


def test_unknown_backend_is_refused(env):
    env.config = Config(mode="review", workspace_dir=Path("w"), output_dir=Path("o"),
                        _sections={"tiktok": {"backend": "magie"}})
    with pytest.raises(tiktok.TikTokError, match="backend"):
        env.publish()


def test_browser_fetch_stats_is_explicitly_not_implemented(env):
    with pytest.raises(tiktok.TikTokError, match="statistiques"):
        tiktok.fetch_stats("ma_chaine", config=env.config)


# ---------------------------------------------------------------- (2) publication


def test_immediate_publish_uploads_mp4_with_caption_and_hashtags_and_returns_the_post(env):
    result = env.publish()

    sel = _sel()["selectors"]
    assert env.opened == [("ma_chaine", False)]  # navigateur visible (ADR-1a58)
    assert env.page.calls[0] == ("goto", _sel()["urls"]["upload"])
    assert ("upload", sel["file_input"], str(env.mp4)) in env.page.calls
    assert env.page.fills() == [("fill", sel["caption_editor"], "Ma legende #un #deux")]
    assert env.page.clicks() == [sel["visibility_dropdown"], sel["visibility_public"], sel["post_button"]]
    assert result == {"post_url": LINK, "post_id": "7300000000000000001", "state": "published",
                      "publish_at": NOW.isoformat(), "note": None}


def test_private_visibility_selects_the_private_option(tmp_path, monkeypatch):
    env = Env(tmp_path, monkeypatch, settings={"visibility": "private"})
    env.publish()
    sel = _sel()["selectors"]
    assert env.page.clicks() == [sel["visibility_dropdown"], sel["visibility_private"], sel["post_button"]]


def test_scheduled_publish_fills_the_date_and_clicks_schedule(env):
    when = NOW + timedelta(days=2)
    result = env.publish("scheduled", when)

    sel = _sel()["selectors"]
    local = when.astimezone()
    assert env.page.clicks() == [sel["visibility_dropdown"], sel["visibility_public"],
                                 sel["schedule_toggle"], sel["schedule_button"]]
    assert ("fill", sel["schedule_date_input"], local.strftime("%Y-%m-%d")) in env.page.fills()
    assert ("fill", sel["schedule_time_input"], local.strftime("%H:%M")) in env.page.fills()
    assert result["state"] == "scheduled_on_tiktok"
    assert result["publish_at"] == when.isoformat()


def test_scheduled_beyond_schedule_max_days_is_refused_before_opening_the_browser(env):
    with pytest.raises(tiktok.TikTokError, match="10 jours"):
        env.publish("scheduled", NOW + timedelta(days=10, minutes=1))
    assert env.opened == []


def test_scheduled_without_a_date_or_too_close_is_refused(env):
    with pytest.raises(tiktok.TikTokError, match="date"):
        env.publish("scheduled", None)
    with pytest.raises(tiktok.TikTokError, match="minutes"):
        env.publish("scheduled", NOW + timedelta(minutes=5))
    assert env.opened == []


def test_unknown_mode_missing_mp4_and_empty_account_are_refused(env):
    with pytest.raises(tiktok.TikTokError, match="mode"):
        env.publish("demain")
    env.mp4.unlink()
    with pytest.raises(tiktok.TikTokError, match="mp4"):
        env.publish()
    with pytest.raises(tiktok.TikTokError, match="compte"):
        tiktok.publish(env.clip, "", mode="immediate", config=env.config, opener=env.opener)


def test_missing_post_link_is_recorded_with_a_note_not_invented(tmp_path, monkeypatch):
    env = Env(tmp_path, monkeypatch, remove=("post_link",))
    result = env.publish()
    assert result["post_url"] is None and result["post_id"] is None
    assert "lien" in result["note"]
    assert result["state"] == "published"


def test_clip_payload_reads_mp4_caption_and_hashtags_from_the_sidecar(tmp_path):
    clip = tiktok.clip_payload({"video_id": "aaaaaaaaaaa", "clip_id": "01", "caption": "c", "hashtags": ["#a"]}, tmp_path)
    assert clip == {"video_path": tmp_path / "aaaaaaaaaaa" / "01.mp4", "caption": "c", "hashtags": ["#a"]}
    with pytest.raises(tiktok.TikTokError, match="caption"):
        tiktok.clip_payload({"video_id": "a", "clip_id": "1", "hashtags": []}, tmp_path)


# ---------------------------------------------------------------- (4) R4 arret sur


@pytest.mark.parametrize("case, kwargs, code, words", [
    ("captcha", {"detect": ["captcha"]}, "captcha", "captcha"),
    ("verification", {"detect": ["verification"]}, "verification", "vérification"),
    ("login_marker", {"page_kwargs": {"redirect": "https://www.tiktok.com/login?redirect=x"}}, "login", "connexion expirée"),
    ("login_form", {"detect": ["login"]}, "login", "connexion expirée"),
    ("missing_element", {"remove": ["caption_editor"]}, "element_missing", "caption_editor"),
    ("unexpected_page", {"page_kwargs": {"redirect": "https://www.tiktok.com/error"}}, "unexpected_page", "page inattendue"),
])
def test_r4_stops_immediately_with_a_screenshot_and_never_acts_blindly(tmp_path, monkeypatch, case, kwargs, code, words):
    env = Env(tmp_path, monkeypatch, **kwargs)

    with pytest.raises(tiktok.TikTokStop) as stop:
        env.publish()

    assert stop.value.code == code
    assert words in str(stop.value)
    capture = stop.value.capture
    assert capture is not None and capture.is_file()
    assert capture.parent == Path("state/browser/ma_chaine/captures")
    sel = _sel()
    assert sel["selectors"]["post_button"] not in env.page.clicks()  # jamais de publication apres l'arret
    for solved in sel["detect"]["captcha"] + sel["detect"]["verification"]:
        assert solved not in env.page.clicks()  # un captcha n'est jamais clique ni resolu


def test_r4_captcha_appearing_mid_flow_stops_before_the_post_click(tmp_path, monkeypatch):
    env = Env(tmp_path, monkeypatch)
    sel = _sel()
    env.page.after_click[sel["selectors"]["visibility_dropdown"]] = [sel["detect"]["captcha"][0]]
    env.config = Config(mode="review", workspace_dir=Path("w"), output_dir=Path("o"),
                        _sections={"tiktok": {"visibility": "private"}})

    with pytest.raises(tiktok.TikTokStop) as stop:
        env.publish()

    assert stop.value.code == "captcha"
    assert sel["selectors"]["post_button"] not in env.page.clicks()


def test_r4_an_unexpected_page_error_is_a_stop_not_a_crash(env):
    env.page.fail_click = True
    with pytest.raises(tiktok.TikTokStop) as stop:
        env.publish()
    assert stop.value.code == "unexpected_page"
    assert "closed" in str(stop.value)


def test_r4_a_failed_screenshot_is_stated_in_the_reason(tmp_path, monkeypatch):
    env = Env(tmp_path, monkeypatch, detect=["captcha"], page_kwargs={"screenshot_error": "disque plein"})
    with pytest.raises(tiktok.TikTokStop) as stop:
        env.publish()
    assert stop.value.capture is None
    assert "capture d'écran impossible" in str(stop.value) and "disque plein" in str(stop.value)


def test_only_the_caption_and_schedule_fields_are_ever_filled_never_credentials(tmp_path, monkeypatch):
    for kwargs in ({"detect": ["login"]}, {"detect": ["captcha"]}, {}):
        env = Env(tmp_path, monkeypatch, **kwargs)
        try:
            env.publish()
        except tiktok.TikTokStop:
            pass
        sel = _sel()["selectors"]
        allowed = {sel["caption_editor"], sel["schedule_date_input"], sel["schedule_time_input"]}
        assert {f[1] for f in env.page.fills()} <= allowed


def test_a_missing_chrome_is_a_browser_error_not_a_stop(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    mp4 = tmp_path / "v.mp4"
    mp4.write_bytes(b"x")

    class NoChrome:
        def start(self):
            return self

        chromium = type("C", (), {"launch_persistent_context": staticmethod(
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("Chromium distribution 'chrome' is not found")))})()

        def stop(self):
            pass

    class Manager:
        def start(self):
            return NoChrome()

    browser.use_playwright(lambda: Manager())
    try:
        with pytest.raises(browser.BrowserError, match="Chrome"):
            tiktok.publish({"video_path": mp4, "caption": "c", "hashtags": []}, "ma_chaine",
                           mode="immediate", sleep=lambda s: None, now=NOW)
    finally:
        browser.use_playwright(None)


# ---------------------------------------------------------------- (6) delais


def test_action_delays_are_random_bounded_and_beat_the_heartbeat(env):
    env.publish()
    assert len(env.sleeps) >= 4
    assert all(3 <= s <= 12 for s in env.sleeps)  # bornes par defaut : compte neuf
    assert len(set(env.sleeps)) > 1  # pas un intervalle mecanique
    assert env.ticks >= len(env.sleeps)


def test_action_delays_follow_the_configured_bounds(tmp_path, monkeypatch):
    env = Env(tmp_path, monkeypatch, settings={"min_action_delay_s": 2, "max_action_delay_s": 8})
    env.publish()
    assert all(2 <= s <= 8 for s in env.sleeps)


@pytest.mark.parametrize("settings", [
    {"min_action_delay_s": 9, "max_action_delay_s": 3},
    {"min_action_delay_s": -1},
    {"max_posts_per_day": 0},
    {"min_gap_minutes": -5},
])
def test_invalid_pacing_settings_are_refused_in_french(tmp_path, monkeypatch, settings):
    env = Env(tmp_path, monkeypatch, settings=settings)
    with pytest.raises(tiktok.TikTokError, match=r"\[tiktok\]"):
        env.publish()
    assert env.opened == []


def test_check_limits_caps_posts_per_day_and_enforces_the_min_gap():
    s = dict(tiktok.CONFIG_DEFAULTS)
    tz = timezone.utc
    day = datetime(2026, 10, 1, 8, 0, tzinfo=tz)
    assert tiktok.check_limits([], day, s, tz) is None
    assert "1 publication" in tiktok.check_limits([day], day.replace(hour=20), s, tz)  # plafond du jour
    assert tiktok.check_limits([day], day + timedelta(days=1), s, tz) is None  # autre jour
    loose = {**s, "max_posts_per_day": 3}
    assert "480" in tiktok.check_limits([day], day + timedelta(hours=7, minutes=59), loose, tz)  # ecart trop court
    assert tiktok.check_limits([day], day + timedelta(hours=8), loose, tz) is None
    assert "480" in tiktok.check_limits([day], day - timedelta(hours=2), loose, tz)  # ecart aussi vers l'avant


# ---------------------------------------------------------------- (5) selecteurs hors du code


def test_selectors_file_is_marked_to_verify_and_has_every_key():
    text = SELECTORS.read_text(encoding="utf-8")
    assert "A VERIFIER SUR LA VRAIE PAGE" in text
    data = tomllib.loads(text)
    for key in tiktok.REQUIRED_SELECTORS:
        assert data["selectors"][key]
    assert data["urls"]["upload"].startswith("https://")


def test_missing_selector_key_or_file_is_an_explicit_error(tmp_path):
    bad = tmp_path / "s.toml"
    bad.write_text('[urls]\nupload = "https://x"\n[expect]\nupload_url_prefix = "https://x"\nlogin_url_markers = []\n'
                   '[selectors]\nfile_input = "a"\n[detect]\ncaptcha = []\nverification = []\nlogin = []\n', encoding="utf-8")
    with pytest.raises(tiktok.TikTokError, match="upload_done"):
        tiktok.load_selectors(bad)
    with pytest.raises(tiktok.TikTokError, match="introuvable"):
        tiktok.load_selectors(tmp_path / "absent.toml")


def test_no_selector_or_url_is_hardcoded_in_tiktok_py():
    data = tomllib.loads(SELECTORS.read_text(encoding="utf-8"))
    values = set()

    def collect(node):
        if isinstance(node, str):
            values.add(node)
        elif isinstance(node, dict):
            for v in node.values():
                collect(v)
        elif isinstance(node, list):
            for v in node:
                collect(v)

    collect(data)
    strings = [n.value for n in ast.walk(ast.parse((ROOT / "clipper" / "tiktok.py").read_text(encoding="utf-8")))
               if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    assert not [s for s in strings if s in values]
    assert not [s for s in strings if "http" in s or "tiktok.com" in s or "data-e2e" in s or "input[" in s]


# ---------------------------------------------------------------- evenements console


def test_events_are_appended_and_read_back_in_order(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tiktok.emit_event({"level": "error", "account": "ma_chaine", "reason": "captcha"}, now=NOW)
    tiktok.emit_event({"level": "info", "account": "ma_chaine", "reason": "ok"}, now=NOW + timedelta(seconds=1))
    events = tiktok.read_events()
    assert [e["reason"] for e in events] == ["captcha", "ok"]
    assert tiktok.read_events(since=NOW.isoformat())[0]["reason"] == "ok"
    assert (tmp_path / "state" / "tiktok" / "events.json").is_file()


def test_events_file_keeps_only_the_last_entries(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for i in range(tiktok.MAX_EVENTS + 5):
        tiktok.emit_event({"level": "info", "reason": str(i)}, now=NOW + timedelta(seconds=i))
    events = tiktok.read_events()
    assert len(events) == tiktok.MAX_EVENTS and events[-1]["reason"] == str(tiktok.MAX_EVENTS + 4)


def test_corrupt_events_file_is_an_explicit_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "state" / "tiktok" / "events.json"
    path.parent.mkdir(parents=True)
    path.write_text("{pas du json", encoding="utf-8")
    with pytest.raises(tiktok.TikTokError, match="événements"):
        tiktok.read_events()
