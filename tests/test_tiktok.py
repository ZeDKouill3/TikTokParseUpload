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
    def __init__(self, page, selector, href=None, text="", value=None, on_click=None, visible=True):
        self.page, self.selector, self.href = page, selector, href
        self.text, self.value, self.on_click, self.visible = text, value, on_click, visible
        self.children: dict[str, "FakeElement"] = {}

    def click(self, **kwargs):
        self.page.calls.append(("click", self.selector))
        if self.page.fail_click:
            raise RuntimeError("Target page, context or browser has been closed")
        for added in self.page.after_click.get(self.selector, ()):
            self.page.present.add(added)
        if self.on_click is not None:
            self.on_click()

    def fill(self, text, **kwargs):
        self.page.calls.append(("fill", self.selector, text))

    def get_attribute(self, name):
        return self.href if name == "href" else None

    def inner_text(self):
        return self.text() if callable(self.text) else self.text

    def input_value(self):
        return self.value() if callable(self.value) else self.value

    def is_visible(self):
        return self.visible and self.selector not in self.page.hidden

    def query_selector(self, selector):
        return self.children.get(selector)


class FakeKeyboard:
    def __init__(self, page):
        self.page = page

    def press(self, key, **kwargs):
        self.page.calls.append(("press", key))

    def type(self, text, **kwargs):
        self.page.calls.append(("type", text))


class FakeModal(FakeElement):
    """Une fenetre surgissante : un bouton par libelle ; le clic la ferme."""

    def __init__(self, page, text, labels):
        super().__init__(page, _sel()["modal"]["container"], text=text)
        self.labels = list(labels)
        template = _sel()["modal"]["button"]
        for label in labels:
            self.children[template.format(label=label)] = FakeElement(
                page, template.format(label=label), on_click=lambda label=label: self.close(label))

    def close(self, label):
        self.page.modals.remove(self)
        self.page.popups_closed.append(label)


class FakePage:
    """``present`` : selecteurs actuellement affiches ; ``redirect`` : adresse
    reelle apres goto ; ``after_click`` : selecteur clique -> selecteurs qui apparaissent ;
    ``texts`` / ``lists`` : texte d'un selecteur, elements d'un query_selector_all ;
    ``timeline`` : une fonction par ``wait_for_timeout`` (l'etat de la page evolue)."""

    def __init__(self, present, *, redirect=None, link=LINK, screenshot_error=None):
        self.present = set(present)
        self.redirect, self.link, self.screenshot_error = redirect, link, screenshot_error
        self.after_click: dict[str, list[str]] = {}
        self.texts: dict[str, str] = {}
        self.lists: dict[str, list[FakeElement]] = {}
        self.hidden: set[str] = set()
        self.modals: list[FakeModal] = []
        self.popups_closed: list[str] = []
        self.timeline: list = []
        self.waits = 0
        self.keyboard = FakeKeyboard(self)
        self.fail_click = False
        self.url = "about:blank"
        self.calls: list[tuple] = []

    def goto(self, url, **kwargs):
        self.calls.append(("goto", url))
        self.url = self.redirect or url

    def make(self, selector):
        return FakeElement(self, selector, href=self.link, text=self.texts.get(selector, ""))

    def query_selector(self, selector):
        return self.make(selector) if selector in self.present else None

    def query_selector_all(self, selector):
        if selector == _sel()["modal"]["container"]:
            return list(self.modals)
        return list(self.lists.get(selector, []))

    def wait_for_selector(self, selector, timeout=None, state=None):
        self.calls.append(("wait", selector))
        if selector not in self.present:
            raise TimeoutError(f"Timeout {timeout}ms exceeded waiting for {selector}")
        return self.make(selector)

    def wait_for_timeout(self, ms):
        self.calls.append(("poll", ms))
        step = self.timeline[self.waits] if self.waits < len(self.timeline) else None
        self.waits += 1
        if step is not None:
            step()

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

    def typed(self):
        return [c[1] for c in self.calls if c[0] == "type"]


class FakeContext:
    def __init__(self, page):
        self.page, self.pages = page, [page]

    def new_page(self):
        return self.page


MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
          "novembre", "décembre"]


class StudioPage(FakePage):
    """TikTok Studio simule : repliement des parametres, visibilite, Maintenant/Programmer, calendrier
    (mois navigable par fleches), selecteur d'heure, verification de contenu, bouton final unique."""

    def __init__(self, *, folded=False, calendar=(2026, 10), minute_step=5, check="ok", confirm=("navigation",),
                 content_links=None, **kwargs):
        super().__init__(set(), **kwargs)
        sel = _sel()["selectors"]
        self.s = sel
        self.confirm = list(confirm)  # une issue par clic sur le bouton final : navigation | message | none | dialog
        self.content_links = [("Ma legende #un #deux", LINK)] if content_links is None else list(content_links)
        self.cal = list(calendar)
        self.time_value, self.date_value = "10:00", "2026-10-01"
        self.mode = "now"
        self.posted: list[str] = []
        self.arrows: list[str] = []
        self.present |= {sel[k] for k in ("file_input", "upload_done", "caption_editor", "advanced_settings",
                                          "visibility_public", "visibility_private", "schedule_now",
                                          "schedule_later", "post_button", "discard_button", "schedule_picker_close")}
        if folded:
            self.present.add(sel["advanced_settings"])
            self.after_click[sel["advanced_settings"]] = [sel["visibility_dropdown"]]
        else:
            self.present.add(sel["visibility_dropdown"])
        self.set_check(check)
        # Programmer / Maintenant : le texte du bouton final suit
        self.on_click = {sel["schedule_later"]: self.choose_scheduled, sel["schedule_now"]: self.choose_now}
        self.texts[sel["post_button"]] = _sel()["labels"]["post_now"]
        self.time_el = FakeElement(self, sel["schedule_inputs"], value=lambda: self.time_value,
                                   on_click=lambda: self.open("time"))
        self.date_el = FakeElement(self, sel["schedule_inputs"], value=lambda: self.date_value,
                                   on_click=lambda: self.open("date"))
        self.minute_step = minute_step

    # -- verification de contenu
    def set_check(self, check):
        sel = self.s
        for key in ("content_check_running", "content_check_ok", "content_check_problem"):
            self.present.discard(sel[key])
        self.present.add({"ok": sel["content_check_ok"], "running": sel["content_check_running"],
                          "problem": sel["content_check_problem"]}[check])

    # -- elements
    def make(self, selector):
        sel = self.s
        if selector == sel["post_button"]:
            return FakeElement(self, selector, text=self.texts[selector], on_click=self.after_post)
        if selector == sel["calendar_month_title"]:
            return FakeElement(self, selector, text=lambda: MONTHS[self.cal[1] - 1])
        if selector == sel["calendar_year_title"]:
            return FakeElement(self, selector, text=lambda: str(self.cal[0]))
        if selector == sel["schedule_picker_close"]:
            return FakeElement(self, selector, on_click=self.close_pickers)
        element = super().make(selector)
        element.on_click = self.on_click.get(selector)
        return element

    def after_post(self):
        self.posted.append(self.mode)
        outcome = self.confirm.pop(0) if self.confirm else "none"
        if outcome == "navigation":
            self.url = _sel()["expect"]["published_url_prefix"]
        elif outcome == "message":
            self.present.add(self.s["published_marker"])
        elif outcome in ("dialog", "dialog_recheck"):
            if outcome == "dialog_recheck":  # la verification de contenu repart apres l'annulation
                self.set_check("running")
            self.modals.append(FakeModal(self, "Continuer à publier ? Nous sommes encore en train de vérifier…",
                                         ["Annuler", "Publier maintenant"]))

    def wait_for_selector(self, selector, timeout=None, state=None):
        if selector == _sel()["stats"]["post_link"] and self.url.startswith(_sel()["expect"]["published_url_prefix"]) \
                and self.content_links:
            self.calls.append(("wait", selector))
            return FakeElement(self, selector)
        return super().wait_for_selector(selector, timeout=timeout, state=state)

    def choose_scheduled(self):
        self.mode = "scheduled"
        self.texts[self.s["post_button"]] = _sel()["labels"]["post_scheduled"]
        self.present.add(self.s["schedule_inputs"])

    def choose_now(self):
        self.mode = "now"
        self.texts[self.s["post_button"]] = _sel()["labels"]["post_now"]

    def open(self, which):
        sel = self.s
        names = (("calendar_month_title", "calendar_year_title", "calendar_arrow", "calendar_day") if which == "date"
                 else ("timepicker_hour", "timepicker_minute"))
        self.present |= {sel[k] for k in names}

    def close_pickers(self):
        sel = self.s
        for key in ("calendar_month_title", "calendar_year_title", "calendar_arrow", "calendar_day",
                    "timepicker_hour", "timepicker_minute"):
            self.present.discard(sel[key])

    def query_selector_all(self, selector):
        sel = self.s
        if selector == _sel()["stats"]["post_link"]:
            if not self.url.startswith(_sel()["expect"]["published_url_prefix"]):
                return []
            return [FakeElement(self, selector, href=href, text=text) for text, href in self.content_links]
        if selector == sel["schedule_inputs"]:
            return [self.time_el, self.date_el] if selector in self.present else []
        if selector == sel["calendar_arrow"] and selector in self.present:
            return [FakeElement(self, selector, on_click=lambda: self.arrow(-1)),
                    FakeElement(self, selector, on_click=lambda: self.arrow(+1))]
        if selector == sel["calendar_day"] and selector in self.present:
            return [FakeElement(self, selector, text=str(d), on_click=lambda d=d: self.pick_day(d))
                    for d in range(1, 31)]
        if selector == sel["timepicker_hour"] and selector in self.present:
            return [FakeElement(self, selector, text=f"{h:02d}", on_click=lambda h=h: self.pick_time(hour=h))
                    for h in range(24)]
        if selector == sel["timepicker_minute"] and selector in self.present:
            return [FakeElement(self, selector, text=f"{m:02d}", on_click=lambda m=m: self.pick_time(minute=m))
                    for m in range(0, 60, self.minute_step)]
        return super().query_selector_all(selector)

    def arrow(self, delta):
        self.arrows.append("next" if delta > 0 else "prev")
        index = self.cal[0] * 12 + self.cal[1] - 1 + delta
        self.cal = [index // 12, index % 12 + 1]

    def pick_day(self, day):
        self.date_value = f"{self.cal[0]}-{self.cal[1]:02d}-{day:02d}"

    def pick_time(self, hour=None, minute=None):
        h, m = self.time_value.split(":")
        self.time_value = f"{hour if hour is not None else int(h):02d}:{minute if minute is not None else int(m):02d}"


class Env:
    """Une publication complete contre un TikTok Studio simule."""

    def __init__(self, tmp_path, monkeypatch, *, remove=(), detect=None, page_kwargs=None, settings=None):
        monkeypatch.chdir(tmp_path)
        self.page = StudioPage(**(page_kwargs or {}))
        for name in remove:
            self.page.present.discard(_sel()["selectors"][name])
            self.page.after_click.pop(_sel()["selectors"][name], None)
        for kind in (detect or ()):
            self.page.present.add(_sel()["detect"][kind][0])
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


# ---------------------------------------------------------------- (2) publication


def test_immediate_publish_uploads_mp4_with_caption_and_hashtags_and_returns_the_post(env):
    result = env.publish()

    sel = _sel()["selectors"]
    assert env.opened == [("ma_chaine", False)]  # navigateur visible (ADR-1a58)
    assert env.page.calls[0] == ("goto", _sel()["urls"]["upload"])
    assert ("upload", sel["file_input"], str(env.mp4)) in env.page.calls
    assert ("wait", sel["upload_done"]) in env.page.calls  # fin d'envoi : conteneur « Importé »
    assert env.page.clicks() == [sel["caption_editor"], sel["visibility_dropdown"], sel["visibility_public"],
                                 sel["schedule_now"], sel["post_button"]]
    assert env.page.posted == ["now"]  # un seul bouton final
    assert result == {"post_url": LINK, "post_id": "7300000000000000001", "state": "published",
                      "publish_at": NOW.isoformat(), "note": None}


def test_the_caption_is_cleared_then_typed_one_character_at_a_time_never_filled(env):
    env.publish()

    keys = [c for c in env.page.calls if c[0] in ("press", "type")]
    text = "Ma legende #un #deux"
    assert keys[:2] == [("press", "Control+A"), ("press", "Backspace")]  # pre-rempli du nom du fichier : vide
    assert keys[2:] == [("type", ch) for ch in text]
    assert env.page.fills() == []  # pas de fill sur l'editeur Draft.js
    first_click = env.page.calls.index(("click", _sel()["selectors"]["caption_editor"]))
    assert first_click < env.page.calls.index(("press", "Control+A"))


def test_private_visibility_selects_the_private_option(tmp_path, monkeypatch):
    env = Env(tmp_path, monkeypatch, settings={"visibility": "private"})
    env.publish()
    sel = _sel()["selectors"]
    assert env.page.clicks() == [sel["caption_editor"], sel["visibility_dropdown"], sel["visibility_private"],
                                 sel["schedule_now"], sel["post_button"]]


def test_folded_settings_are_expanded_with_show_more_only_when_needed(tmp_path, monkeypatch):
    sel = _sel()["selectors"]
    folded = Env(tmp_path, monkeypatch, page_kwargs={"folded": True})
    folded.publish()
    assert folded.page.clicks()[:2] == [sel["caption_editor"], sel["advanced_settings"]]

    open_ = Env(tmp_path, monkeypatch)
    open_.publish()
    assert sel["advanced_settings"] not in open_.page.clicks()


def test_visibility_options_are_targeted_by_option_id_with_the_text_as_fallback():
    sel = _sel()["selectors"]
    for key, option_id, text in (("visibility_public", '0', "Tout le monde"), ("visibility_private", '1', "Toi uniquement")):
        assert f"option-\"{option_id}\"" in sel[key] and text in sel[key]
    assert "video_visibility_container" in sel["visibility_dropdown"] and "combobox" in sel["visibility_dropdown"]


def test_scheduled_publish_sets_the_time_and_date_through_the_pickers(env):
    when = (NOW + timedelta(days=2)).astimezone().replace(hour=15, minute=30, second=0, microsecond=0)
    result = env.publish("scheduled", when)

    sel = _sel()["selectors"]
    assert env.page.clicks() == [sel["caption_editor"], sel["visibility_dropdown"], sel["visibility_public"],
                                 sel["schedule_later"], sel["schedule_inputs"], sel["calendar_day"],
                                 sel["schedule_picker_close"], sel["schedule_inputs"], sel["timepicker_hour"],
                                 sel["timepicker_minute"], sel["schedule_picker_close"], sel["post_button"]]
    assert env.page.fills() == []
    assert (env.page.date_value, env.page.time_value) == (when.strftime("%Y-%m-%d"), "15:30")
    assert env.page.posted == ["scheduled"]  # le meme bouton, devenu « Programmer »
    assert env.page.arrows == []  # meme mois : aucune fleche
    assert result["state"] == "scheduled_on_tiktok"
    assert result["publish_at"] == when.isoformat() and result["note"] is None


@pytest.mark.parametrize("start, target_days, arrows", [
    ((2026, 10), 35, ["next"]),                 # 5 novembre : un mois plus tard
    ((2027, 1), 35, ["prev", "prev"]),          # le calendrier affiche janvier 2027 : deux fleches arriere
    ((2026, 11), 35, []),
])
def test_scheduled_publish_navigates_months_with_the_arrows_to_the_target_month(tmp_path, monkeypatch, start, target_days, arrows):
    env = Env(tmp_path, monkeypatch, page_kwargs={"calendar": start}, settings={"schedule_max_days": 40})
    when = (NOW + timedelta(days=target_days)).astimezone().replace(hour=9, minute=15, second=0, microsecond=0)

    env.publish("scheduled", when)

    assert env.page.arrows == arrows
    assert env.page.date_value == when.strftime("%Y-%m-%d")
    assert env.page.time_value == "09:15"


def test_scheduled_minutes_are_rounded_to_the_step_offered_by_tiktok_and_logged(tmp_path, monkeypatch, caplog):
    env = Env(tmp_path, monkeypatch, page_kwargs={"minute_step": 15})
    when = (NOW + timedelta(days=2)).astimezone().replace(hour=12, minute=7, second=0, microsecond=0)

    with caplog.at_level("WARNING"):
        result = env.publish("scheduled", when)

    assert env.page.time_value == "12:00"
    assert "07" in caplog.text and "00" in caplog.text and "arrondi" in caplog.text
    assert result["publish_at"] == when.replace(minute=0).isoformat()  # l'instant reellement programme
    assert "arrondi" in result["note"]


def test_a_hidden_or_wrong_schedule_field_is_an_unexpected_page_stop_not_a_guess(tmp_path, monkeypatch):
    env = Env(tmp_path, monkeypatch)
    env.page.time_value = "pas une heure"  # le premier champ n'est pas l'heure (« : » attendu)
    with pytest.raises(tiktok.TikTokStop) as stop:
        env.publish("scheduled", NOW + timedelta(days=2))
    assert stop.value.code == "unexpected_page" and "heure" in str(stop.value)
    assert env.page.posted == []


def test_the_final_button_label_must_match_the_mode(tmp_path, monkeypatch):
    env = Env(tmp_path, monkeypatch)
    env.page.on_click[_sel()["selectors"]["schedule_now"]] = lambda: env.page.texts.__setitem__(
        _sel()["selectors"]["post_button"], "Programmer")  # la page est restee sur « Programmer »
    with pytest.raises(tiktok.TikTokStop) as stop:
        env.publish()
    assert stop.value.code == "unexpected_page" and "Publier" in str(stop.value)
    assert env.page.posted == []


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


# ---------------------------------------------------------------- TASK-e4bf : preuve de publication, lien du post


def _published_prefix() -> str:
    return _sel()["expect"]["published_url_prefix"]


def test_a_private_post_cannot_be_scheduled_and_is_refused_before_any_browser_is_opened(tmp_path, monkeypatch):
    env = Env(tmp_path, monkeypatch, settings={"visibility": "private"})
    when = NOW + timedelta(days=2)

    with pytest.raises(tiktok.TikTokError, match="privée") as refused:
        env.publish("scheduled", when)

    assert "programm" in str(refused.value) and "visibility" in str(refused.value)
    assert env.opened == [] and env.page.calls == []  # aucun navigateur ouvert, aucune page touchee
    # le mode immediat reste possible pour un post prive
    assert env.publish("immediate")["state"] == "published"


def test_publication_is_proved_by_the_navigation_to_the_content_page(tmp_path, monkeypatch):
    env = Env(tmp_path, monkeypatch, page_kwargs={"confirm": ["navigation"]})

    result = env.publish()

    assert env.page.url.startswith(_published_prefix())
    assert _sel()["selectors"]["published_marker"] not in env.page.present  # aucun message : la navigation suffit
    assert result["state"] == "published" and result["post_url"] == LINK


def test_publication_is_proved_by_the_published_message_when_the_url_does_not_change(tmp_path, monkeypatch):
    env = Env(tmp_path, monkeypatch, page_kwargs={"confirm": ["message"]})

    result = env.publish()

    assert not env.page.url.startswith(_published_prefix()) or ("goto", _sel()["urls"]["stats"]) in env.page.calls
    assert result["state"] == "published"
    assert ("goto", _sel()["urls"]["stats"]) in env.page.calls  # le lien est cherche sur la page Publications
    assert result["post_url"] == LINK


def test_no_sign_of_publication_is_an_r4_failure_with_a_capture_never_an_assumed_success(tmp_path, monkeypatch):
    env = Env(tmp_path, monkeypatch, page_kwargs={"confirm": ["none"]},
              settings={"publish_confirm_timeout_s": 10, "poll_interval_s": 5})

    with pytest.raises(tiktok.TikTokStop) as stop:
        env.publish()

    assert stop.value.code == "publish_unconfirmed"
    assert "10 s" in str(stop.value) and "publish_confirm_timeout_s" in str(stop.value)
    assert stop.value.capture is not None and stop.value.capture.is_file()
    assert env.page.posted == ["now"]  # le bouton a ete clique une fois, jamais re-clique a l'aveugle
    assert [c for c in env.page.calls if c[0] == "poll"] == [("poll", 5000.0), ("poll", 5000.0)]


def test_publish_confirm_timeout_has_a_default_and_is_validated(tmp_path):
    assert tiktok.CONFIG_DEFAULTS["publish_confirm_timeout_s"] >= 1
    config = Config(mode="review", workspace_dir=tmp_path, output_dir=tmp_path,
                    _sections={"tiktok": {"publish_confirm_timeout_s": 0}})
    with pytest.raises(tiktok.TikTokError, match="publish_confirm_timeout_s"):
        tiktok.get_settings(config)


def test_the_continue_publishing_window_is_cancelled_then_the_post_is_retried_once(tmp_path, monkeypatch, caplog):
    env = Env(tmp_path, monkeypatch, page_kwargs={"confirm": ["dialog", "navigation"]})
    sel = _sel()

    with caplog.at_level("INFO"):
        result = env.publish()

    cancel = sel["modal"]["button"].format(label="Annuler")
    clicks = env.page.clicks()
    assert clicks[-3:] == [sel["selectors"]["post_button"], cancel, sel["selectors"]["post_button"]]
    assert env.page.popups_closed == ["Annuler"] and env.page.modals == []
    assert env.page.posted == ["now", "now"]  # un nouvel essai, une fois
    assert "Continuer à publier" in caplog.text
    assert result["state"] == "published" and result["post_url"] == LINK


def test_the_continue_publishing_window_waits_for_the_content_check_before_retrying(tmp_path, monkeypatch):
    env = Env(tmp_path, monkeypatch, page_kwargs={"confirm": ["dialog_recheck", "navigation"]})
    env.page.timeline = [lambda: None, lambda: env.page.set_check("ok")]  # « en cours » deux lectures, puis OK

    env.publish()

    polls = [c for c in env.page.calls if c[0] == "poll"]
    assert len(polls) >= 2  # il a attendu la fin de la verification avant le nouvel essai
    assert env.page.posted == ["now", "now"]
    last_poll = max(i for i, c in enumerate(env.page.calls) if c[0] == "poll")
    second_post = [i for i, c in enumerate(env.page.calls) if c == ("click", env.page.s["post_button"])][1]
    assert last_poll < second_post


def test_the_continue_publishing_window_twice_is_an_r4_failure(tmp_path, monkeypatch):
    env = Env(tmp_path, monkeypatch, page_kwargs={"confirm": ["dialog", "dialog"]})

    with pytest.raises(tiktok.TikTokStop) as stop:
        env.publish()

    assert stop.value.code == "publish_unconfirmed"
    assert "Continuer à publier" in str(stop.value) and stop.value.capture is not None
    assert env.page.posted == ["now", "now"]  # un seul nouvel essai


def test_the_post_link_is_the_first_video_link_whose_text_starts_the_published_caption(tmp_path, monkeypatch):
    other = "https://www.tiktok.com/@ma_chaine/video/7299999999999999999"
    mine = "/@ma_chaine/video/7300000000000000042?lang=fr"
    env = Env(tmp_path, monkeypatch, page_kwargs={"content_links": [
        ("Une autre legende", other), ("Ma legende #un", mine), ("Ma legende #un #deux", LINK)]})

    result = env.publish()

    # texte tronque = debut de la legende publiee ; href relatif complete par l'adresse de la page
    assert result["post_url"] == "https://www.tiktok.com/@ma_chaine/video/7300000000000000042?lang=fr"
    assert result["post_id"] == "7300000000000000042"  # fin du href
    assert result["note"] is None and result["state"] == "published"


def test_a_post_link_not_found_is_a_published_post_with_an_explicit_missing_link_note(tmp_path, monkeypatch):
    env = Env(tmp_path, monkeypatch, page_kwargs={"content_links": [
        ("Une autre legende", "https://www.tiktok.com/@ma_chaine/video/7299999999999999999")]})

    result = env.publish()

    assert result["state"] == "published"  # la publication a reussi
    assert result["post_url"] is None and result["post_id"] is None  # pas d'id invente
    assert "lien" in result["note"] and "introuvable" in result["note"]


def test_a_post_link_lookup_that_breaks_never_turns_a_proved_publication_into_a_failure(tmp_path, monkeypatch):
    env = Env(tmp_path, monkeypatch, page_kwargs={"content_links": []})  # la page ne montre aucun lien

    result = env.publish()

    assert result["state"] == "published" and result["post_url"] is None and "lien" in result["note"]


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
    ("content_check_failed", {"page_kwargs": {"check": "problem"}}, "content_check", "problème"),
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


def test_only_the_caption_and_the_schedule_pickers_are_ever_typed_never_credentials(tmp_path, monkeypatch):
    for kwargs in ({"detect": ["login"]}, {"detect": ["captcha"]}, {}):
        env = Env(tmp_path, monkeypatch, **kwargs)
        try:
            env.publish("scheduled", NOW + timedelta(days=2))
        except tiktok.TikTokStop:
            pass
        assert env.page.fills() == []
        assert "".join(env.page.typed()) in ("", "Ma legende #un #deux")  # la legende, rien d'autre


# ---------------------------------------------------------------- verification de contenu (criteres 4 et 7)


def test_content_check_in_progress_then_ok_waits_before_the_final_click(tmp_path, monkeypatch):
    env = Env(tmp_path, monkeypatch, page_kwargs={"check": "running"})
    sel = _sel()["selectors"]

    def finished():
        env.page.set_check("ok")

    env.page.timeline = [lambda: None, lambda: None, finished]

    result = env.publish()

    assert env.page.waits == 3
    assert env.page.posted == ["now"] and result["state"] == "published"
    polls = [i for i, c in enumerate(env.page.calls) if c[0] == "poll"]
    post = env.page.calls.index(("click", sel["post_button"]))
    assert polls and max(polls) < post  # attente terminee AVANT le clic final
    assert env.ticks >= env.page.waits  # le battement du worker continue pendant l'attente


def test_content_check_problem_is_an_explicit_r4_failure_and_nothing_is_posted(tmp_path, monkeypatch):
    env = Env(tmp_path, monkeypatch, page_kwargs={"check": "running"})
    env.page.timeline = [lambda: env.page.set_check("problem")]

    with pytest.raises(tiktok.TikTokStop) as stop:
        env.publish()

    assert stop.value.code == "content_check" and "problème" in str(stop.value)
    assert stop.value.capture is not None and stop.value.capture.is_file()
    assert env.page.posted == [] and _sel()["selectors"]["post_button"] not in env.page.clicks()


def test_content_check_timeout_is_an_explicit_r4_failure(tmp_path, monkeypatch):
    env = Env(tmp_path, monkeypatch, page_kwargs={"check": "running"},
              settings={"content_check_timeout_s": 10, "poll_interval_s": 5})

    with pytest.raises(tiktok.TikTokStop) as stop:
        env.publish()

    assert stop.value.code == "content_check"
    assert "10 s" in str(stop.value) and "content_check_timeout_s" in str(stop.value)
    assert env.page.waits == 2 and env.page.posted == []


def test_content_check_timeout_defaults_to_900_seconds_and_is_validated(tmp_path):
    assert tiktok.CONFIG_DEFAULTS["content_check_timeout_s"] == 900
    for bad in (0, -1, "900", True):
        config = Config(mode="review", workspace_dir=tmp_path, output_dir=tmp_path,
                        _sections={"tiktok": {"content_check_timeout_s": bad}})
        with pytest.raises(tiktok.TikTokError, match="content_check_timeout_s"):
            tiktok.get_settings(config)


def test_content_check_is_also_awaited_for_a_scheduled_post(tmp_path, monkeypatch):
    env = Env(tmp_path, monkeypatch, page_kwargs={"check": "running"})
    env.page.timeline = [lambda: env.page.set_check("ok")]
    env.publish("scheduled", NOW + timedelta(days=2))
    assert env.page.waits == 1 and env.page.posted == ["scheduled"]


# ---------------------------------------------------------------- fenetres surgissantes (criteres 5 et 7)


def test_known_popups_are_closed_with_their_button_and_logged(tmp_path, monkeypatch, caplog):
    env = Env(tmp_path, monkeypatch)
    env.page.modals = [
        FakeModal(env.page, "Activer les vérifications automatiques du contenu ?\nAnnuler Activer", ["Annuler", "Activer"]),
        FakeModal(env.page, "Nouvelles fonctionnalités d'édition ajoutées\nJ'ai compris", ["J'ai compris"]),
    ]

    with caplog.at_level("INFO"):
        result = env.publish()

    assert env.page.popups_closed == ["Annuler", "J'ai compris"]  # Annuler : jamais « Activer »
    assert env.page.modals == []
    assert "Activer les vérifications automatiques" in caplog.text and "Annuler" in caplog.text
    assert "Nouvelles fonctionnalités" in caplog.text and "J'ai compris" in caplog.text
    assert result["state"] == "published"


def test_a_known_popup_appearing_mid_flow_is_closed_before_the_next_action(tmp_path, monkeypatch):
    env = Env(tmp_path, monkeypatch)
    sel = _sel()["selectors"]
    modal = FakeModal(env.page, "Nouvelles fonctionnalités d'édition ajoutées", ["J'ai compris"])
    env.page.on_click[sel["schedule_now"]] = lambda: env.page.modals.append(modal)

    env.publish()

    assert env.page.popups_closed == ["J'ai compris"] and env.page.posted == ["now"]


def test_an_unknown_modal_window_is_an_r4_stop_and_is_never_clicked(tmp_path, monkeypatch):
    env = Env(tmp_path, monkeypatch)
    env.page.modals = [FakeModal(env.page, "Votre compte a été restreint\nOK", ["OK"])]

    with pytest.raises(tiktok.TikTokStop) as stop:
        env.publish()

    assert stop.value.code == "unexpected_page"
    assert "fenêtre" in str(stop.value) and "Votre compte a été restreint" in str(stop.value)
    assert stop.value.capture is not None and stop.value.capture.is_file()
    assert env.page.popups_closed == [] and env.page.posted == []  # jamais de clic de repli


def test_a_known_popup_without_its_button_is_an_r4_stop(tmp_path, monkeypatch):
    env = Env(tmp_path, monkeypatch)
    env.page.modals = [FakeModal(env.page, "Activer les vérifications automatiques du contenu ?", ["Activer"])]

    with pytest.raises(tiktok.TikTokStop) as stop:
        env.publish()

    assert stop.value.code == "element_missing" and "Annuler" in str(stop.value)
    assert env.page.popups_closed == []  # « Activer » n'est pas le bouton prevu : pas cliqué


def test_a_popup_that_keeps_coming_back_is_an_r4_stop(tmp_path, monkeypatch):
    env = Env(tmp_path, monkeypatch)

    class Stubborn(FakeModal):
        def close(self, label):
            self.page.popups_closed.append(label)  # reste affichee

    env.page.modals = [Stubborn(env.page, "Nouvelles fonctionnalités d'édition ajoutées", ["J'ai compris"])]
    with pytest.raises(tiktok.TikTokStop) as stop:
        env.publish()
    assert stop.value.code == "unexpected_page" and "fenêtre" in str(stop.value)


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


def test_selectors_file_says_what_is_verified_for_real_and_what_is_not():
    text = SELECTORS.read_text(encoding="utf-8")
    header = text.split("version =", 1)[0]
    assert "VERIFIE EN REEL" in header and "A VERIFIER SUR LA VRAIE PAGE" in header
    assert "confirmation apres publication" in header.lower().replace("é", "e").replace("è", "e")
    data = tomllib.loads(text)
    for key in tiktok.REQUIRED_SELECTORS:
        assert data["selectors"][key]
    assert data["urls"]["upload"].startswith("https://")


def test_selectors_file_carries_the_real_markers_of_tiktok_studio():
    sel = _sel()["selectors"]
    assert "upload_status_container" in sel["upload_done"] and "Importé" in sel["upload_done"]
    assert "caption_container" in sel["caption_editor"] and "contenteditable" in sel["caption_editor"]
    assert "advanced_settings_container" in sel["advanced_settings"]
    assert "schedule_container" in sel["schedule_now"] and "Maintenant" in sel["schedule_now"]
    assert "schedule_container" in sel["schedule_later"] and "Programmer" in sel["schedule_later"]
    assert "schedule_container" in sel["schedule_inputs"] and "TUXTextInputCore-input" in sel["schedule_inputs"]
    assert "month-title" in sel["calendar_month_title"] and "year-title" in sel["calendar_year_title"]
    assert "arrow" in sel["calendar_arrow"] and "day" in sel["calendar_day"] and "valid" in sel["calendar_day"]
    assert "tiktok-timepicker-left" in sel["timepicker_hour"] and "tiktok-timepicker-right" in sel["timepicker_minute"]
    assert sel["post_button"] == "button[data-e2e='post_video_button']"
    assert sel["discard_button"] == "button[data-e2e='discard_post_button']"
    assert "upload_status_success" not in str(_sel()) and "schedule_video_button" not in str(_sel())
    assert "privacy_container" not in str(_sel()) and "schedule_radio" not in str(_sel())
    assert _sel()["labels"] == {"post_now": "Publier", "post_scheduled": "Programmer"}
    assert _sel()["popups"] == {
        "Activer les vérifications automatiques du contenu": "Annuler",
        "Nouvelles fonctionnalités d'édition ajoutées": "J'ai compris",
    }
    assert len(_sel()["calendar"]["months"]) == 12


def test_selectors_file_carries_the_publication_proof_post_link_and_analytics_markers():
    data = _sel()
    assert data["expect"]["published_url_prefix"] == "https://www.tiktok.com/tiktokstudio/content"
    assert "Vidéo publiée" in data["selectors"]["published_marker"]
    assert data["continue_publish"] == {"dialog": "Continuer à publier", "cancel": "Annuler"}
    assert data["stats"]["post_link"] == "a[href*='/video/']"
    assert data["urls"]["analytics"] == "https://www.tiktok.com/tiktokstudio/analytics/{post_id}?qa_enter_from=analytics"
    assert data["expect"]["analytics_url_prefix"] == "https://www.tiktok.com/tiktokstudio/analytics/"
    assert data["stats"]["metric_card"] == "[data-tt='VideoOverviewPage_VideoMetricsCard_FlexItem']"  # data-tt, pas css-xxxx
    assert data["metrics"] == {
        "views": "Vues de vidéo", "watch_total": "Temps de lecture total", "watch_avg": "Temps de visionnage moyen",
        "watched_full": "A regardé toute la vidéo", "new_followers": "Nouveaux followers", "retention": "Taux de rétention",
    }
    assert data["stats"]["processing"] == "en cours de traitement"
    assert "css-" not in str(data["stats"])


def test_a_missing_metrics_table_or_analytics_url_is_an_explicit_error(tmp_path):
    import re

    text = SELECTORS.read_text(encoding="utf-8")
    broken = re.sub(r"^\[metrics\]\n(?:(?!\[).*\n)*", "", text, flags=re.M)
    assert broken != text
    bad = tmp_path / "s.toml"
    bad.write_text(broken, encoding="utf-8")
    with pytest.raises(tiktok.TikTokError, match="metrics"):
        tiktok.load_selectors(bad)


def test_missing_selector_key_or_file_is_an_explicit_error(tmp_path):
    bad = tmp_path / "s.toml"
    bad.write_text('[urls]\nupload = "https://x"\n[expect]\nupload_url_prefix = "https://x"\nlogin_url_markers = []\n'
                   '[selectors]\nfile_input = "a"\n[detect]\ncaptcha = []\nverification = []\nlogin = []\n', encoding="utf-8")
    with pytest.raises(tiktok.TikTokError, match="upload_done"):
        tiktok.load_selectors(bad)
    with pytest.raises(tiktok.TikTokError, match="introuvable"):
        tiktok.load_selectors(tmp_path / "absent.toml")


@pytest.mark.parametrize("table", ["popups", "modal", "calendar", "labels"])
def test_a_missing_popup_modal_calendar_or_label_table_is_an_explicit_error(tmp_path, table):
    import re

    text = SELECTORS.read_text(encoding="utf-8")
    broken = re.sub(rf"^\[{table}\]\n(?:(?!\[).*\n)*", "", text, flags=re.M)
    assert broken != text
    bad = tmp_path / "s.toml"
    bad.write_text(broken, encoding="utf-8")
    with pytest.raises(tiktok.TikTokError, match=table):
        tiktok.load_selectors(bad)


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


# ---------------------------------------------------------------- statistiques (SPEC-9225 R7)


class FakeCell:
    def __init__(self, text=None, href=None):
        self.text, self.href = text, href

    def inner_text(self):
        return self.text

    def get_attribute(self, name):
        return self.href if name == "href" else None


class FakeRow:
    def __init__(self, cells):
        self.cells = cells  # selecteur -> FakeCell ; absent = non affiche

    def query_selector(self, selector):
        return self.cells.get(selector)


class FakeStatsPage(FakePage):
    """Page Publications (une ligne par post) puis page d'analyse d'un post (cartes « libelle | valeur »)."""

    def __init__(self, rows, cards, sources=None, **kwargs):
        super().__init__(set(), **kwargs)
        self.rows, self.cards, self.sources = rows, cards, sources or {}

    def goto(self, url, **kwargs):
        super().goto(url)
        sel, expect = _sel()["stats"], _sel()["expect"]
        for key in ("row", "metric_card", "traffic_sources"):
            self.present.discard(sel[key])
        self.texts.pop(sel["traffic_sources"], None)
        if self.url.startswith(expect["stats_url_prefix"]) and self.rows:
            self.present.add(sel["row"])
        elif self.url.startswith(expect["analytics_url_prefix"]):
            post_id = self.url.split("/analytics/")[1].split("?")[0]
            if post_id in self.cards:
                self.present.add(sel["metric_card"])
            if post_id in self.sources:
                self.present.add(sel["traffic_sources"])
                self.texts[sel["traffic_sources"]] = self.sources[post_id]

    def query_selector_all(self, selector):
        self.calls.append(("all", selector))
        sel = _sel()["stats"]
        if selector == sel["row"]:
            return list(self.rows)
        if selector == sel["metric_card"] and sel["metric_card"] in self.present:
            return list(self.cards[self.url.split("/analytics/")[1].split("?")[0]])
        return []


def _row(post_id, *, likes="85", comments="7", account="ma_chaine"):
    sel = _sel()["stats"]
    cells = {sel["post_link"]: FakeCell(href=f"https://www.tiktok.com/@{account}/video/{post_id}")}
    for key, value in (("likes", likes), ("comments", comments)):
        if value is not None:
            cells[sel[key]] = FakeCell(value)
    return FakeRow(cells)


def _cards(*, views="1 200", total="1h:02m:03s", avg="12s", full="23%", followers="4",
           retention="en cours de traitement", only=None):
    """Les cartes de metriques d'un post, texte « libelle | valeur » (releve reel, FR)."""
    labels = _sel()["metrics"]
    values = {"views": views, "watch_total": total, "watch_avg": avg, "watched_full": full,
              "new_followers": followers, "retention": retention}
    return [FakeCell(f"{labels[key]} | {value}") for key, value in values.items()
            if value is not None and (only is None or key in only)]


ID_A, ID_B, ID_C = "7300000000000000001", "7300000000000000002", "7300000000000000003"


def analytics_url(post_id):
    return _sel()["urls"]["analytics"].format(post_id=post_id)


class StatsEnv:
    """Un releve complet contre une fausse page ; ``posts`` : id -> cartes de metriques. Un sidecar de clip
    publie (``tiktok_post``) est ecrit pour chaque id, sauf ``clips=False`` ; ``rows`` : la page Publications."""

    def __init__(self, tmp_path, monkeypatch, posts, *, rows=None, sources=None, clips=True, detect=None,
                 redirect=None, settings=None):
        monkeypatch.chdir(tmp_path)
        rows = [_row(post_id) for post_id in posts] if rows is None else rows
        self.page = FakeStatsPage(rows, posts, sources, redirect=redirect)
        for kind in (detect or ()):
            self.page.present.add(_sel()["detect"][kind][0])
        self.sleeps: list[float] = []
        self.config = Config(mode="review", workspace_dir=tmp_path / "w", output_dir=tmp_path / "output",
                             _sections={"tiktok": settings or {}})
        self.path = tmp_path / "state" / "stats" / "tiktok" / "ma_chaine.json"
        self.tmp = tmp_path
        for number, post_id in enumerate(posts, start=1):
            if clips:
                self.clip("aaaaaaaaaaa", f"{number:02d}", post_id=post_id)

    def clip(self, video_id, clip_id, post_id=None, url=None, account="ma_chaine", state="published"):
        out = self.tmp / "output" / video_id
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{clip_id}.json").write_text(json.dumps({
            "video_id": video_id, "clip_id": clip_id,
            "tiktok_post": {"url": url, "id": post_id, "state": state, "account": account}}), encoding="utf-8")

    @contextmanager
    def opener(self, account, *, headless):
        self.opened = (account, headless)
        yield FakeContext(self.page)

    def fetch(self, **kwargs):
        return tiktok.fetch_stats("ma_chaine", config=self.config, now=NOW, opener=self.opener,
                                  sleep=self.sleeps.append, rng=random.Random(1), **kwargs)


def test_stats_interval_default_is_24_hours_and_invalid_values_are_refused(tmp_path, monkeypatch):
    assert tiktok.CONFIG_DEFAULTS["stats_interval_h"] == 24
    assert tiktok.CONFIG_DEFAULTS["stats_dir"] == "state/stats/tiktok"
    for bad in (0, -1, "24", True):
        config = Config(mode="review", workspace_dir=tmp_path, output_dir=tmp_path,
                        _sections={"tiktok": {"stats_interval_h": bad}})
        with pytest.raises(tiktok.TikTokError, match="stats_interval_h"):
            tiktok.get_settings(config)


def test_fetch_stats_goes_straight_to_the_analytics_page_of_each_published_post(tmp_path, monkeypatch):
    env = StatsEnv(tmp_path, monkeypatch, {ID_A: _cards(), ID_B: _cards(views="3,4 K")})

    result = env.fetch()

    assert env.opened == ("ma_chaine", False)  # navigateur visible
    gotos = [c[1] for c in env.page.calls if c[0] == "goto"]
    assert gotos == [_sel()["urls"]["stats"], analytics_url(ID_A), analytics_url(ID_B)]
    assert analytics_url(ID_A) == f"https://www.tiktok.com/tiktokstudio/analytics/{ID_A}?qa_enter_from=analytics"
    assert env.page.clicks() == [] and env.page.fills() == []  # lecture seule
    assert [p["post_id"] for p in result["posts"]] == [ID_A, ID_B]
    assert result["fetched_at"] == NOW.isoformat() and result["account"] == "ma_chaine"


def test_filled_metrics_are_read_by_label_and_converted(tmp_path, monkeypatch):
    env = StatsEnv(tmp_path, monkeypatch, {ID_A: _cards(views="1 200", total="1h:02m:03s", avg="12s", full="23%",
                                                        followers="4")},
                   rows=[_row(ID_A, likes="85", comments="7")])

    post = env.fetch()["posts"][0]

    assert post["post_id"] == ID_A and post["post_url"] == f"https://www.tiktok.com/@ma_chaine/video/{ID_A}"
    assert post["views"] == 1200 and isinstance(post["views"], int)
    assert post["watch_total_s"] == 3723.0  # 1h 02m 03s
    assert post["avg_watch_s"] == 12.0
    assert post["watched_full"] == pytest.approx(0.23)  # part vue en entier : pourcentage lu
    assert post["new_followers"] == 4
    assert (post["likes"], post["comments"]) == (85, 7)  # depuis la ligne de la page Publications


def test_metrics_at_zero_are_real_zeros_not_nulls(tmp_path, monkeypatch):
    env = StatsEnv(tmp_path, monkeypatch, {ID_A: _cards(views="0", total="0h:00m:00s", avg="0s", full="0%",
                                                        followers="0")},
                   rows=[_row(ID_A, likes="0", comments="0")])

    post = env.fetch()["posts"][0]

    assert post["views"] == 0 and post["watch_total_s"] == 0.0 and post["avg_watch_s"] == 0.0
    assert post["watched_full"] == 0.0 and post["new_followers"] == 0
    assert post["likes"] == 0 and post["comments"] == 0
    assert post["watch_total_s"] is not None and post["watched_full"] is not None


def test_retention_and_traffic_sources_still_processing_are_explicit_nulls(tmp_path, monkeypatch):
    processing = _sel()["stats"]["processing"]
    env = StatsEnv(tmp_path, monkeypatch, {ID_A: _cards(retention=processing)}, sources={ID_A: processing})

    post = env.fetch()["posts"][0]

    assert "retention" in post and post["retention"] is None
    assert "traffic_sources" in post and post["traffic_sources"] is None
    assert post["views"] == 1200  # le reste est lu normalement


def test_a_metric_the_page_does_not_show_is_an_explicit_null_never_an_invented_zero(tmp_path, monkeypatch):
    env = StatsEnv(tmp_path, monkeypatch, {ID_A: _cards(only=("views",))},
                   rows=[_row(ID_A, likes=None, comments="—")])

    post = env.fetch()["posts"][0]

    assert post["views"] == 1200
    for key in ("watch_total_s", "avg_watch_s", "watched_full", "new_followers", "retention", "likes", "comments"):
        assert key in post and post[key] is None


def test_a_post_missing_from_the_publications_list_has_null_likes_and_comments(tmp_path, monkeypatch):
    env = StatsEnv(tmp_path, monkeypatch, {ID_A: _cards()}, rows=[_row(ID_B)])

    post = env.fetch()["posts"][0]

    assert post["likes"] is None and post["comments"] is None and post["views"] == 1200


@pytest.mark.parametrize("text,expected", [
    ("0h:00m:00s", 0.0), ("1h:02m:03s", 3723.0), ("0h:05m:30s", 330.0), ("12s", 12.0), ("0s", 0.0),
    ("12,5 s", 12.5), ("1:05", 65.0), ("1 min 5 s", 65.0), ("—", None),
])
def test_durations_are_converted_to_seconds(text, expected):
    assert tiktok.parse_duration(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("1 200", 1200), ("1\u202f200", 1200), ("1,2 K", 1200), ("1.5M", 1500000), ("2,5 Md", 2500000000), ("987", 987),
])
def test_counts_are_parsed_from_the_displayed_text(tmp_path, monkeypatch, text, expected):
    env = StatsEnv(tmp_path, monkeypatch, {ID_A: _cards(views=text)})
    assert env.fetch()["posts"][0]["views"] == expected


def test_an_unreadable_value_is_an_unexpected_page_stop_not_a_guess(tmp_path, monkeypatch):
    env = StatsEnv(tmp_path, monkeypatch, {ID_A: _cards(views="beaucoup")})

    with pytest.raises(tiktok.TikTokStop) as stop:
        env.fetch()

    assert stop.value.code == "unexpected_page" and "views" in stop.value.reason
    assert stop.value.capture is not None and stop.value.capture.is_file()


def test_the_report_is_written_atomically_and_linked_to_clips_by_post_id_and_url(tmp_path, monkeypatch):
    env = StatsEnv(tmp_path, monkeypatch, {ID_A: _cards(), ID_B: _cards()}, clips=False)
    env.clip("aaaaaaaaaaa", "01", post_id=ID_A)
    env.clip("aaaaaaaaaaa", "02", url=f"https://www.tiktok.com/@ma_chaine/video/{ID_B}")
    env.clip("bbbbbbbbbbb", "01", post_id=ID_C, account="autre")  # autre compte : jamais releve ici

    env.fetch()

    data = json.loads(env.path.read_text(encoding="utf-8"))
    assert data["account"] == "ma_chaine" and data["fetched_at"] == NOW.isoformat() and data["error"] is None
    linked = {(p["post_id"]): (p["video_id"], p["clip_id"]) for p in data["posts"]}
    assert linked == {ID_A: ("aaaaaaaaaaa", "01"), ID_B: ("aaaaaaaaaaa", "02")}
    assert ("goto", analytics_url(ID_C)) not in env.page.calls
    assert not [p for p in env.path.parent.iterdir() if p.suffix == ".tmp"]  # aucun .tmp laisse


def test_a_second_fetch_replaces_the_report(tmp_path, monkeypatch):
    env = StatsEnv(tmp_path, monkeypatch, {ID_A: _cards(views="10")})
    env.fetch()
    env.page.cards = {ID_A: _cards(views="20")}
    env.fetch()
    assert json.loads(env.path.read_text(encoding="utf-8"))["posts"][0]["views"] == 20


def test_fetch_without_any_published_post_to_measure_is_an_explicit_error_before_the_browser(tmp_path, monkeypatch):
    env = StatsEnv(tmp_path, monkeypatch, {}, clips=False)
    env.opened = None

    with pytest.raises(tiktok.TikTokError, match="aucun post publié"):
        env.fetch()

    assert env.opened is None and env.page.calls == []


@pytest.mark.parametrize("kwargs,code", [
    ({"detect": ["captcha"]}, "captcha"),
    ({"detect": ["verification"]}, "verification"),
    ({"detect": ["login"]}, "login"),
    ({"redirect": "https://www.tiktok.com/login?redirect=studio"}, "login"),
    ({"redirect": "https://www.tiktok.com/erreur"}, "unexpected_page"),
])
def test_r4_the_fetch_stops_safely_and_records_the_failure_keeping_the_last_report(tmp_path, monkeypatch, kwargs, code):
    first = StatsEnv(tmp_path, monkeypatch, {ID_A: _cards()})
    first.fetch()
    env = StatsEnv(tmp_path, monkeypatch, {ID_A: _cards()}, **kwargs)

    with pytest.raises(tiktok.TikTokStop) as stop:
        tiktok.fetch_stats("ma_chaine", config=env.config, now=NOW + timedelta(hours=1), opener=env.opener,
                           sleep=env.sleeps.append, rng=random.Random(1))

    assert stop.value.code == code
    assert stop.value.capture is not None and stop.value.capture.is_file()
    assert env.page.clicks() == [] and env.page.fills() == []  # aucun clic, aucune saisie
    data = json.loads(env.path.read_text(encoding="utf-8"))
    assert data["fetched_at"] == NOW.isoformat() and data["posts"][0]["views"] == 1200  # dernier releve intact
    assert data["error"]["code"] == code and data["error"]["reason"] == stop.value.reason
    assert data["error"]["at"] == (NOW + timedelta(hours=1)).isoformat()
    event = tiktok.read_events(config=env.config)[-1]
    assert event["level"] == "error" and event["account"] == "ma_chaine" and stop.value.reason in event["reason"]
    assert event["capture"] == str(stop.value.capture)


def test_r4_no_post_row_after_the_delay_is_an_element_missing_stop(tmp_path, monkeypatch):
    env = StatsEnv(tmp_path, monkeypatch, {ID_A: _cards()}, rows=[])

    with pytest.raises(tiktok.TikTokStop) as stop:
        env.fetch()

    assert stop.value.code == "element_missing" and "row" in stop.value.reason
    assert json.loads(env.path.read_text(encoding="utf-8"))["error"]["code"] == "element_missing"


def test_a_missing_chrome_during_the_fetch_is_recorded_and_raised(tmp_path, monkeypatch):
    env = StatsEnv(tmp_path, monkeypatch, {ID_A: _cards()})

    @contextmanager
    def no_chrome(account, *, headless):
        raise browser.BrowserError("Chrome introuvable")
        yield

    with pytest.raises(browser.BrowserError):
        tiktok.fetch_stats("ma_chaine", config=env.config, now=NOW, opener=no_chrome)

    assert "Chrome introuvable" in json.loads(env.path.read_text(encoding="utf-8"))["error"]["reason"]


def test_fetch_stats_refuses_a_missing_account_and_the_api_backend(tmp_path, monkeypatch):
    env = StatsEnv(tmp_path, monkeypatch, {ID_A: _cards()})
    with pytest.raises(tiktok.TikTokError, match="compte"):
        tiktok.fetch_stats("", config=env.config, opener=env.opener)
    api = Config(mode="review", workspace_dir=tmp_path, output_dir=tmp_path, _sections={"tiktok": {"backend": "api"}})
    with pytest.raises(tiktok.TikTokError, match="api"):
        tiktok.fetch_stats("ma_chaine", config=api)


def test_stats_due_follows_the_interval_since_the_last_attempt_success_or_failure(tmp_path, monkeypatch):
    env = StatsEnv(tmp_path, monkeypatch, {ID_A: _cards()})
    assert tiktok.stats_due("ma_chaine", config=env.config, now=NOW)  # jamais releve

    env.fetch()
    assert not tiktok.stats_due("ma_chaine", config=env.config, now=NOW + timedelta(hours=23))
    assert tiktok.stats_due("ma_chaine", config=env.config, now=NOW + timedelta(hours=24))

    env.page.present.add(_sel()["detect"]["captcha"][0])
    with pytest.raises(tiktok.TikTokStop):
        tiktok.fetch_stats("ma_chaine", config=env.config, now=NOW + timedelta(hours=24), opener=env.opener,
                           sleep=env.sleeps.append)
    # l'echec compte comme une tentative : pas de nouvelle ouverture du navigateur avant l'intervalle
    assert not tiktok.stats_due("ma_chaine", config=env.config, now=NOW + timedelta(hours=30))
    assert tiktok.stats_due("ma_chaine", config=env.config, now=NOW + timedelta(hours=49))


def test_stats_accounts_lists_accounts_with_a_post_to_measure_only(tmp_path, monkeypatch):
    env = StatsEnv(tmp_path, monkeypatch, {}, clips=False)
    env.clip("aaaaaaaaaaa", "01", post_id=ID_A)
    env.clip("aaaaaaaaaaa", "02", post_id=None, url=None, state="scheduled_on_tiktok")  # pas d'adresse publique
    env.clip("bbbbbbbbbbb", "01", post_id=ID_B, account="autre")
    assert tiktok.stats_accounts(config=env.config) == ["autre", "ma_chaine"]


def test_read_stats_returns_none_without_a_report_and_refuses_a_corrupt_one(tmp_path, monkeypatch):
    env = StatsEnv(tmp_path, monkeypatch, {}, clips=False)
    assert tiktok.read_stats("ma_chaine", config=env.config) is None
    env.path.parent.mkdir(parents=True)
    env.path.write_text("{pas du json", encoding="utf-8")
    with pytest.raises(tiktok.TikTokError, match="illisible"):
        tiktok.read_stats("ma_chaine", config=env.config)


def test_stats_selectors_live_in_the_selectors_file_marked_to_verify():
    text = SELECTORS.read_text(encoding="utf-8")
    data = tomllib.loads(text)
    assert data["urls"]["stats"].startswith("https://") and data["expect"]["stats_url_prefix"].startswith("https://")
    for key in tiktok.REQUIRED_STATS_SELECTORS:
        assert data["stats"][key]
    assert text.count("A VERIFIER SUR LA VRAIE PAGE") >= 2  # un second marquage pour les pages de statistiques


def test_a_missing_stats_selector_is_an_explicit_error(tmp_path):
    text = SELECTORS.read_text(encoding="utf-8").replace("[stats]", "[stats_absent]")
    bad = tmp_path / "s.toml"
    bad.write_text(text, encoding="utf-8")
    with pytest.raises(tiktok.TikTokError, match=r"\[stats\] row"):
        tiktok.load_selectors(bad)
