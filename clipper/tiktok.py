"""Publication TikTok par pilotage d'un vrai navigateur (ADR-1a58, SPEC-9225 R3-R6).

Seul module qui parle a TikTok : ``publish`` et ``fetch_stats`` passent par un
backend choisi par ``[tiktok] backend`` (``browser`` : Playwright sur le vrai
Chrome visible, profil persistant du compte via ``clipper.browser`` ; ``api`` :
erreur explicite tant que l'app developpeur n'existe pas).

Arret sur (R4) : captcha, verification, connexion expiree, element attendu absent
apres delai, page inattendue -> ``TikTokStop`` (code + raison en francais + capture
d'ecran sous ``state/browser/<compte>/captures/``). Jamais de resolution de captcha,
jamais de clic de repli, jamais d'identifiant saisi : seuls la legende, la date et
l'heure de programmation sont remplis.

Fenetres surgissantes : celles du ``[popups]`` du toml (texte -> bouton) sont fermees et
journalisees ; toute autre fenetre modale est un arret R4. Avant le clic final, la
verification de contenu de TikTok doit conclure « Aucun probleme constate » (probleme ou
delai ``content_check_timeout_s`` = arret R4, code ``content_check``).

Tous les selecteurs et adresses vivent dans ``clipper/assets/tiktok_selectors.toml``
(R5) ; aucun n'est ecrit ici. Rythme (R6) : delais aleatoires bornes entre actions,
plafonds par compte (``check_limits``). Pas d'etape : bibliotheque (ADR-b16b), la
file et le worker l'appellent.
"""

from __future__ import annotations

import json
import logging
import random
import re
import time
import tomllib
from contextlib import AbstractContextManager
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin

from clipper import browser
from clipper import channel as channel_mod
from clipper.config import Config

logger = logging.getLogger(__name__)

# Defauts d'un compte neuf (docs/tiktok-cadence.md 3.1) ; ceux d'un compte etabli
# (3 posts par jour, 240 min, delais 2-8 s) sont donnes dans le README.
CONFIG_DEFAULTS: dict[str, object] = {
    "backend": "browser",              # browser | api (pas encore disponible)
    "publish_mode": "immediate",       # immediate | scheduled (programme cote TikTok)
    "visibility": "public",            # public | private (test reel : private)
    "max_posts_per_day": 1,
    "min_gap_minutes": 480,
    "min_action_delay_s": 1,
    "max_action_delay_s": 3,
    "schedule_max_days": 10,           # limite native de TikTok Studio
    "schedule_min_minutes": 15,        # avance minimale native de TikTok Studio
    "action_timeout_s": 30,            # attente d'un element de la page
    "upload_timeout_s": 300,           # attente de la fin de l'envoi du mp4
    "publish_confirm_timeout_s": 60,   # attente de la preuve de publication apres « Publier »
    "content_check": "off",            # off : coupe la verification de contenu de TikTok avant de publier
                                       # (rapide, comme a la main) ; wait : attend son resultat (~10 min)
    "content_check_timeout_s": 900,    # attente du resultat de la verification de contenu (~10 min)
    "poll_interval_s": 5,              # pas d'attente entre deux lectures de la verification
    "type_delay_ms": 50,               # delai entre deux touches de la legende
    "events_path": "state/tiktok/events.json",
    "stats_interval_h": 24,            # releve periodique des statistiques par le worker (R7)
    "stats_dir": "state/stats/tiktok",  # un releve par compte : <stats_dir>/<compte>.json
}

MODES = ("immediate", "scheduled")
VISIBILITIES = ("public", "private")
BACKENDS = ("browser", "api")
MAX_EVENTS = 50
SELECTORS_PATH = Path(__file__).parent / "assets" / "tiktok_selectors.toml"
REQUIRED_SELECTORS = (
    "file_input", "upload_done", "caption_editor", "advanced_settings", "visibility_dropdown",
    "visibility_public", "visibility_private", "schedule_now", "schedule_later", "schedule_inputs",
    "calendar_month_title", "calendar_year_title", "calendar_arrow", "calendar_day", "timepicker_hour",
    "timepicker_minute", "schedule_picker_close", "content_check_running", "content_check_ok",
    "content_check_problem", "post_button", "discard_button", "published_marker",
)
MAX_POPUP_ROUNDS = 5   # fenetres successives fermees par un meme controle avant d'abandonner
MAX_MONTH_STEPS = 24   # fleches du calendrier cliquees au plus avant d'abandonner
REQUIRED_STATS_SELECTORS = ("row", "post_link", "likes", "comments", "metric_card", "traffic_sources", "processing")
METRICS = ("views", "watch_total", "watch_avg", "watched_full", "new_followers", "retention")
_DETECT_KINDS = ("captcha", "verification", "login")
_POST_ID = re.compile(r"/video/(\d+)")
_POST_ID_END = re.compile(r"/video/(\d+)/?(?:[?#].*)?$")


class TikTokError(Exception):
    """Reglage, clip, date ou backend invalide ; fichier de selecteurs ou d'evenements illisible."""


class TikTokStop(TikTokError):
    """Arret sur de la page (SPEC-9225 R4). ``code`` : captcha | verification | login |
    element_missing | unexpected_page | content_check | publish_unconfirmed ; ``capture`` : la capture d'ecran, ou None."""

    def __init__(self, code: str, reason: str, capture: Path | None = None) -> None:
        super().__init__(reason)
        self.code, self.reason, self.capture = code, reason, capture


# ---------------------------------------------------------------- reglages et selecteurs


def get_settings(config: Config | None) -> dict[str, Any]:
    settings = dict(config.section("tiktok")) if config is not None else dict(CONFIG_DEFAULTS)
    for key, allowed in (("backend", BACKENDS), ("publish_mode", MODES), ("visibility", VISIBILITIES),
                         ("content_check", ("off", "wait"))):
        if settings[key] not in allowed:
            raise TikTokError(f"[tiktok] {key} invalide : {settings[key]!r} (attendu : {' | '.join(allowed)})")
    for key, minimum in (("max_posts_per_day", 1), ("min_gap_minutes", 0), ("min_action_delay_s", 0),
                         ("max_action_delay_s", 0), ("schedule_max_days", 1), ("schedule_min_minutes", 0),
                         ("action_timeout_s", 1), ("upload_timeout_s", 1), ("publish_confirm_timeout_s", 1),
                         ("content_check_timeout_s", 1),
                         ("poll_interval_s", 1), ("type_delay_ms", 0)):
        value = settings[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < minimum:
            raise TikTokError(f"[tiktok] {key} invalide : {value!r} (un nombre >= {minimum} est attendu)")
    hours = settings["stats_interval_h"]
    if isinstance(hours, bool) or not isinstance(hours, (int, float)) or hours <= 0:
        raise TikTokError(f"[tiktok] stats_interval_h invalide : {hours!r} (un nombre d'heures > 0 est attendu)")
    if not isinstance(settings["stats_dir"], str) or not settings["stats_dir"]:
        raise TikTokError(f"[tiktok] stats_dir invalide : {settings['stats_dir']!r} (un chemin est attendu)")
    if settings["min_action_delay_s"] > settings["max_action_delay_s"]:
        raise TikTokError(
            f"[tiktok] min_action_delay_s ({settings['min_action_delay_s']}) dépasse max_action_delay_s "
            f"({settings['max_action_delay_s']})"
        )
    return settings


def load_selectors(path: str | Path | None = None) -> dict[str, Any]:
    """Selecteurs et adresses de TikTok Studio (R5), valides ou ``TikTokError`` qui nomme la cle."""
    target = Path(path) if path is not None else SELECTORS_PATH
    try:
        data = tomllib.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise TikTokError(f"fichier de sélecteurs TikTok introuvable : {target}") from None
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise TikTokError(f"fichier de sélecteurs TikTok illisible ({target}) : {exc}") from exc

    def need(table: str, key: str, kind: type) -> None:
        value = data.get(table, {}).get(key)
        ok = isinstance(value, kind) and (bool(value) or kind is list)
        if kind is list:
            ok = isinstance(value, list) and all(isinstance(v, str) and v for v in value)
        if not ok:
            raise TikTokError(f"fichier de sélecteurs TikTok ({target.name}) : [{table}] {key} manquant ou invalide")

    need("urls", "upload", str)
    need("expect", "upload_url_prefix", str)
    need("expect", "login_url_markers", list)
    for key in REQUIRED_SELECTORS:
        need("selectors", key, str)
    for key in _DETECT_KINDS:
        need("detect", key, list)
    need("labels", "post_now", str)
    need("labels", "post_scheduled", str)
    need("continue_publish", "dialog", str)
    need("continue_publish", "cancel", str)
    need("expect", "published_url_prefix", str)
    need("modal", "container", str)
    need("modal", "button", str)
    months = data.get("calendar", {}).get("months")
    if not (isinstance(months, list) and len(months) == 12 and all(isinstance(m, str) and m for m in months)):
        raise TikTokError(f"fichier de sélecteurs TikTok ({target.name}) : [calendar] months manquant ou invalide (12 noms de mois attendus)")
    popups = data.get("popups")
    if not (isinstance(popups, dict) and popups and all(
            isinstance(k, str) and k and isinstance(v, str) and v and '"' not in v for k, v in popups.items())):
        raise TikTokError(f"fichier de sélecteurs TikTok ({target.name}) : [popups] manquant ou invalide "
                          f"(texte de la fenêtre -> libellé du bouton, sans guillemet double)")
    need("urls", "stats", str)
    need("urls", "analytics", str)
    need("expect", "stats_url_prefix", str)
    need("expect", "analytics_url_prefix", str)
    for key in REQUIRED_STATS_SELECTORS:
        need("stats", key, str)
    for key in METRICS:
        need("metrics", key, str)
    return data


# ---------------------------------------------------------------- contenu, limites


def clip_payload(sidecar: dict[str, Any], output_dir: str | Path) -> dict[str, Any]:
    """Le mp4 et la legende + hashtags d'un sidecar de clip (SPEC-6a47)."""
    if not isinstance(sidecar.get("caption"), str) or not sidecar["caption"].strip():
        raise TikTokError(f"clip {sidecar.get('video_id')}/{sidecar.get('clip_id')} : caption absente du sidecar")
    hashtags = sidecar.get("hashtags")
    if not isinstance(hashtags, list):
        raise TikTokError(f"clip {sidecar.get('video_id')}/{sidecar.get('clip_id')} : hashtags absents du sidecar")
    path = Path(output_dir) / sidecar["video_id"] / f"{sidecar['clip_id']}.mp4"
    return {"video_path": path, "caption": sidecar["caption"], "hashtags": list(hashtags)}


def check_limits(times: list[datetime], target: datetime, settings: dict[str, Any], tz: tzinfo) -> str | None:
    """R6 : ``None`` si une publication a ``target`` respecte les plafonds du compte
    (``times`` : ses autres publications), sinon la raison, en francais."""
    local = target.astimezone(tz)
    cap = int(settings["max_posts_per_day"])
    same_day = [t for t in times if t.astimezone(tz).date() == local.date()]
    if len(same_day) >= cap:
        return f"plafond de {cap} publication(s) par jour atteint le {local.date().isoformat()}"
    gap = timedelta(minutes=float(settings["min_gap_minutes"]))
    for t in sorted(times):
        if abs(t - target) < gap:
            return (f"écart minimal de {settings['min_gap_minutes']} minutes non respecté avec la "
                    f"publication du {t.astimezone(tz).strftime('%Y-%m-%d %H:%M')}")
    return None


# ---------------------------------------------------------------- evenements console


def _events_path(config: Config | None) -> Path:
    return Path(get_settings(config)["events_path"])


def emit_event(event: dict[str, Any], *, config: Config | None = None, now: datetime | None = None) -> dict[str, Any]:
    """Ajoute un evenement au journal lu par la console (ecriture atomique ; la console le
    voit changer par son flux d'evenements) ; seuls les ``MAX_EVENTS`` derniers restent."""
    path = _events_path(config)
    entry = {**event, "at": (now or datetime.now(timezone.utc)).isoformat()}
    with channel_mod.file_lock(path):
        events = read_events(config=config)
        events.append(entry)
        channel_mod.atomic_write_json(path, events[-MAX_EVENTS:])
    return entry


def read_events(since: str | None = None, *, config: Config | None = None) -> list[dict[str, Any]]:
    path = _events_path(config)
    if not path.is_file():
        return []
    try:
        events = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(events, list):
            raise ValueError("pas une liste")
        return [e for e in events if since is None or e["at"] > since]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise TikTokError(f"journal des événements TikTok illisible ({path}) : {exc}") from exc


# ---------------------------------------------------------------- lecture des chiffres affiches

_ABSENT = frozenset({"", "-", "--", "–", "—", "N/A", "n/a"})
_SUFFIX = {"": 1, "k": 1_000, "m": 1_000_000, "md": 1_000_000_000, "b": 1_000_000_000}
_COUNT = re.compile(r"(\d[\d ]*)(?:[.,](\d+))?\s*([kKmMbB]|Md)?")
_PERCENT = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")
_CLOCK = re.compile(r"(?:(\d+):)?(\d+):(\d{2})")
_HMS = re.compile(r"(?:(\d+)\s*h\s*:?\s*)?(?:(\d+)\s*m\s*:?\s*)?(?:(\d+(?:[.,]\d+)?)\s*s)?")  # 0h:00m:00s, 12s
_SECONDS = re.compile(r"(?:(\d+)\s*min\s*)?(?:(\d+(?:[.,]\d+)?)\s*s)?|(\d+)\s*min")


def _squash(text: str) -> str:
    return " ".join(text.replace("\u202f", " ").replace("\xa0", " ").split())


def _text(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError(f"texte attendu, reçu {value!r}")
    return value.replace("\u202f", " ").replace("\xa0", " ").strip()


def parse_count(value: Any) -> int | None:
    """« 1 200 », « 1,2 K », « 2.5M » -> entier ; tiret ou vide -> ``None`` ; autre -> ``ValueError``."""
    text = _text(value)
    if text in _ABSENT:
        return None
    match = _COUNT.fullmatch(text)
    if match is None or (match[2] and not match[3]):  # decimale sans K/M : ambigu, pas de supposition
        raise ValueError(f"nombre illisible : {text!r}")
    number = float(match[1].replace(" ", "") + ("." + match[2] if match[2] else ""))
    return int(round(number * _SUFFIX[(match[3] or "").lower()]))


def parse_percent(value: Any) -> float | None:
    """« 23,4 % » -> 0.234 (fraction) ; tiret ou vide -> ``None`` ; autre -> ``ValueError``."""
    text = _text(value)
    if text in _ABSENT:
        return None
    match = _PERCENT.fullmatch(text)
    if match is None:
        raise ValueError(f"pourcentage illisible : {text!r}")
    return round(float(match[1].replace(",", ".")) / 100, 6)


def parse_duration(value: Any) -> float | None:
    """« 12,5 s », « 0h:01m:05s », « 1:05 », « 1 min 5 s » -> secondes ; tiret ou vide -> ``None`` ; autre -> ``ValueError``."""
    text = _text(value)
    if text in _ABSENT:
        return None
    clock = _CLOCK.fullmatch(text)
    if clock:
        return float(int(clock[1] or 0) * 3600 + int(clock[2]) * 60 + int(clock[3]))
    hms = _HMS.fullmatch(text)
    if hms is not None and any(hms.groups()):
        return float(int(hms[1] or 0) * 3600 + int(hms[2] or 0) * 60 + float((hms[3] or "0").replace(",", ".")))
    match = _SECONDS.fullmatch(text)
    if match is None or not text or not any(match.groups()):
        raise ValueError(f"durée illisible : {text!r}")
    minutes = match[1] or match[3]
    return float(int(minutes or 0) * 60 + float((match[2] or "0").replace(",", ".")))


# ---------------------------------------------------------------- backend browser


Opener = Callable[..., AbstractContextManager]


class _Flow:
    """Une publication pilotee sur une page. Chaque methode garde d'abord la page
    (captcha, verification, connexion) avant d'agir."""

    def __init__(self, page: Any, account: str, selectors: dict[str, Any], settings: dict[str, Any], *,
                 now: datetime, sleep: Callable[[float], None], rng: Any, on_tick: Callable[[], None] | None) -> None:
        self.page, self.account, self.sel, self.settings = page, account, selectors, settings
        self.now, self._sleep, self.rng, self.on_tick = now, sleep, rng, on_tick

    # -- arret sur
    def stop(self, code: str, reason: str) -> TikTokStop:
        capture: Path | None = None
        target = browser.profile_dir(self.account) / "captures" / f"{self.now.strftime('%Y%m%dT%H%M%S')}-{code}.png"
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            self.page.screenshot(path=str(target), full_page=True)
            capture = target
        except Exception as exc:  # noqa: BLE001 - dit dans la raison, jamais avale
            reason += f" (capture d'écran impossible : {exc})"
        logger.error("TikTok %s : %s", self.account, reason)
        return TikTokStop(code, reason, capture)

    def guard(self, modals: bool = True) -> None:
        url = str(self.page.url)
        if any(marker in url for marker in self.sel["expect"]["login_url_markers"]):
            raise self.stop("login", f"connexion expirée : reconnecte le compte {self.account} (page : {url})")
        for code, label in (("captcha", "captcha détecté : arrêt immédiat, à résoudre à la main"),
                            ("verification", "vérification de compte demandée : arrêt immédiat, à faire à la main"),
                            ("login", f"connexion expirée : reconnecte le compte {self.account}")):
            for css in self.sel["detect"][code]:
                if self.page.query_selector(css) is not None:
                    raise self.stop(code, label)
        if modals:
            self.close_popups()

    def close_popups(self) -> None:
        """Ferme les fenetres connues (``[popups]`` : texte -> bouton) et le journalise ; toute autre
        fenetre modale est un arret R4 (jamais de clic de repli)."""
        known = self.sel["popups"]
        for _ in range(MAX_POPUP_ROUNDS):
            shown = [m for m in self.page.query_selector_all(self.sel["modal"]["container"]) if m.is_visible()]
            if not shown:
                return
            for modal in shown:
                text = " ".join(str(modal.inner_text()).split())
                fragment = next((f for f in known if f.casefold() in text.casefold()), None)
                if fragment is None:
                    raise self.stop("unexpected_page", f"fenêtre inattendue : {text[:150]!r}")
                label = known[fragment]
                button = modal.query_selector(self.sel["modal"]["button"].format(label=label))
                if button is None:
                    raise self.stop("element_missing", f"fenêtre connue « {fragment} » sans son bouton « {label} »")
                button.click()
                logger.info("TikTok %s : fenêtre connue « %s » fermée par « %s »", self.account, fragment, label)
        raise self.stop("unexpected_page", f"fenêtres surgissantes qui reviennent après {MAX_POPUP_ROUNDS} fermetures")

    # -- actions
    def pause(self) -> None:
        if self.on_tick is not None:
            self.on_tick()
        self._sleep(self.rng.uniform(float(self.settings["min_action_delay_s"]), float(self.settings["max_action_delay_s"])))
        if self.on_tick is not None:
            self.on_tick()

    def wait(self, name: str, *, timeout_key: str = "action_timeout_s", state: str | None = None,
             table: str = "selectors", modals: bool = True) -> Any:
        self.guard(modals)
        timeout = float(self.settings[timeout_key])
        try:
            element = self.page.wait_for_selector(self.sel[table][name], timeout=timeout * 1000, state=state)
        except Exception as exc:
            if "Timeout" not in type(exc).__name__:
                raise
            element = None
        if element is None:
            raise self.stop("element_missing", f"élément attendu absent après {timeout:g} s : {name}")
        return element

    def click(self, name: str) -> None:
        self.wait(name).click()
        self.pause()

    def all(self, name: str) -> list[Any]:
        """Tous les elements d'un selecteur, une fois le premier apparu."""
        self.wait(name)
        return list(self.page.query_selector_all(self.sel["selectors"][name]))

    def type_caption(self, text: str) -> None:
        """L'editeur Draft.js est pre-rempli du nom du fichier : clic, tout selectionner, effacer, puis
        le texte d'un coup par insert_text (un seul evenement de saisie, instantane ; ``fill`` n'est pas
        pris en compte par l'editeur)."""
        self.wait("caption_editor").click()
        keyboard = self.page.keyboard
        keyboard.press("Control+A")
        keyboard.press("Backspace")
        keyboard.insert_text(text)
        self.pause()

    def expand_settings(self) -> None:
        """« Afficher plus » seulement si les parametres sont repliees (visibilite non affichee)."""
        dropdown = self.page.query_selector(self.sel["selectors"]["visibility_dropdown"])
        if dropdown is None or not dropdown.is_visible():
            self.click("advanced_settings")

    def schedule_now(self) -> None:
        # Video privee : TikTok grise « Maintenant » et « Programmer », « Maintenant » deja coche.
        # Clic inutile (et impossible) quand le choix est deja fait ; grise ET non coche = arret.
        radio = self.wait("schedule_now").query_selector(self.sel["selectors"]["radio_input"])
        if radio is not None and radio.is_checked():
            logger.info("TikTok %s : « Maintenant » deja choisi, aucun clic", self.account)
            return
        if radio is not None and not radio.is_enabled():
            raise self.stop("unexpected_page", "« Maintenant » est grisé sans être coché : publication impossible")
        self.click("schedule_now")

    def schedule_later(self, target: datetime) -> tuple[datetime, str | None]:
        """Programmation par les champs de TikTok : Programmer, date (calendrier), heure (selecteur).
        Rend l'instant reellement programme (minutes arrondies au pas propose) et une note ou None."""
        local = target.astimezone()
        self.click("schedule_later")
        if len(self.all("schedule_inputs")) != 2 or ":" not in str(self.field(0).input_value()):
            raise self.stop("unexpected_page", "champs de programmation inattendus : l'heure (valeur avec « : »), "
                                               "puis la date, sont attendus")
        self.field(1).click()
        self.pause()
        self.pick_date(local)
        self.click("schedule_picker_close")
        self.field(0).click()
        self.pause()
        minute = self.pick_time(local)
        self.click("schedule_picker_close")
        effective = local.replace(minute=minute, second=0, microsecond=0) if minute != local.minute else local
        shown = (str(self.field(1).input_value()).strip(), str(self.field(0).input_value()).strip())
        expected = (effective.strftime("%Y-%m-%d"), effective.strftime("%H:%M"))
        if shown != expected:
            raise self.stop("unexpected_page", f"programmation non prise en compte : {shown[0]} {shown[1]} affiché, "
                                               f"{expected[0]} {expected[1]} attendu")
        note = None
        if minute != local.minute:
            note = f"minutes arrondies au pas proposé par TikTok : {local.minute:02d} -> {minute:02d}"
            logger.warning("TikTok %s : %s (heure demandée %s)", self.account, note, local.strftime("%H:%M"))
        return effective, note

    def field(self, index: int) -> Any:
        """Champ de programmation (0 heure, 1 date), relu a chaque fois : la page les redessine."""
        fields = self.page.query_selector_all(self.sel["selectors"]["schedule_inputs"])
        if len(fields) != 2:
            raise self.stop("unexpected_page", f"{len(fields)} champ(s) de programmation affiché(s), 2 attendus")
        return fields[index]

    def pick_date(self, target: datetime) -> None:
        months = [m.casefold() for m in self.sel["calendar"]["months"]]
        for _ in range(MAX_MONTH_STEPS + 1):
            month_text = str(self.wait("calendar_month_title").inner_text()).strip()
            year_text = str(self.wait("calendar_year_title").inner_text()).strip()
            if month_text.casefold() not in months or not year_text.isdigit():
                raise self.stop("unexpected_page", f"mois affiché illisible dans le calendrier : {month_text!r} {year_text!r}")
            gap = (target.year - int(year_text)) * 12 + target.month - (months.index(month_text.casefold()) + 1)
            if gap == 0:
                break
            arrows = self.all("calendar_arrow")
            if len(arrows) < 2:
                raise self.stop("element_missing", "flèches du calendrier absentes (2 attendues : précédent, suivant)")
            arrows[1 if gap > 0 else 0].click()
            self.pause()
        else:
            raise self.stop("unexpected_page", f"mois cible {target.year}-{target.month:02d} introuvable dans le calendrier")
        for day in self.all("calendar_day"):
            if str(day.inner_text()).strip() == str(target.day):
                day.click()
                self.pause()
                return
        raise self.stop("element_missing", f"jour {target.day} absent du calendrier ({target.strftime('%Y-%m')})")

    def pick_time(self, target: datetime) -> int:
        """Clique l'heure et la minute ; rend la minute choisie (la plus proche de la demandee
        parmi celles que TikTok propose)."""
        for option in self.all("timepicker_hour"):
            if str(option.inner_text()).strip().isdigit() and int(str(option.inner_text()).strip()) == target.hour:
                option.click()
                self.pause()
                break
        else:
            raise self.stop("element_missing", f"heure {target.hour:02d} absente du sélecteur d'heure")
        offered = {int(t): o for o in self.all("timepicker_minute") if (t := str(o.inner_text()).strip()).isdigit()}
        if not offered:
            raise self.stop("element_missing", "minutes absentes du sélecteur d'heure")
        minute = min(offered, key=lambda m: (abs(m - target.minute), m))
        offered[minute].click()
        self.pause()
        return minute

    def disable_content_check(self) -> None:
        """Coupe l'interrupteur « Verification de contenu simple » s'il est actif (TikTok modere de toute
        facon apres publication) : plus d'attente ni de fenetre « Continuer a publier ? »."""
        switch = self.page.query_selector(self.sel["selectors"]["content_check_switch"])
        if switch is None:
            raise self.stop("element_missing", "interrupteur « Vérification de contenu simple » introuvable")
        if switch.is_checked():
            switch.uncheck(force=True)
            self.pause()
            if switch.is_checked():
                raise self.stop("unexpected_page", "la vérification de contenu n'a pas pu être coupée")
            logger.info("TikTok %s : vérification de contenu coupée avant publication", self.account)

    def await_content_check(self) -> None:
        """Avant le clic final : attend « Aucun probleme constate ». Probleme signale ou delai depasse :
        arret R4 (code ``content_check``), jamais de publication d'un contenu non verifie."""
        sel = self.sel["selectors"]
        timeout, interval = float(self.settings["content_check_timeout_s"]), float(self.settings["poll_interval_s"])
        waited = 0.0
        while True:
            self.guard()
            if self.page.query_selector(sel["content_check_ok"]) is not None:
                logger.info("TikTok %s : vérification de contenu sans problème constaté", self.account)
                return
            problem = self.page.query_selector(sel["content_check_problem"])
            if problem is not None:
                detail = " ".join(str(problem.inner_text()).split())[:150]
                raise self.stop("content_check", "vérification de contenu : problème signalé par TikTok"
                                + (f" ({detail})" if detail else ""))
            if self.page.query_selector(sel["content_check_ok"]) is not None:
                logger.info("TikTok %s : vérification de contenu sans problème constaté", self.account)
                return
            if waited >= timeout:
                raise self.stop("content_check", f"vérification de contenu non terminée après {timeout:g} s "
                                                 f"([tiktok] content_check_timeout_s)")
            self.page.wait_for_timeout(interval * 1000)
            waited += interval
            if self.on_tick is not None:
                self.on_tick()

    def post(self, mode: str) -> None:
        """Le bouton final unique ; son texte doit correspondre au mode, sinon la page n'est pas dans l'etat voulu."""
        button = self.wait("post_button")
        expected = self.sel["labels"]["post_scheduled" if mode == "scheduled" else "post_now"]
        label = " ".join(str(button.inner_text()).split())
        if label != expected:
            raise self.stop("unexpected_page", f"bouton final « {label} » au lieu de « {expected} » : "
                                               f"la page n'est pas en mode {mode}")
        button.click()
        self.pause()

    def await_published(self, mode: str) -> None:
        """Preuve de publication apres le clic final : navigation vers la page Publications (principale)
        ou message « Video publiee » (secours), avant ``publish_confirm_timeout_s``. La fenetre « Continuer
        a publier ? » (verification encore en cours) est annulee, la fin de la verification attendue, puis
        le bouton re-clique UNE fois. Ni preuve ni fenetre : arret R4 ``publish_unconfirmed``, jamais un
        succes suppose."""
        sel, labels = self.sel["selectors"], self.sel["continue_publish"]
        timeout, interval = float(self.settings["publish_confirm_timeout_s"]), float(self.settings["poll_interval_s"])
        waited, retried = 0.0, False
        while True:
            self.guard(modals=False)  # la fenetre « Continuer a publier ? » est connue : traitee ci-dessous
            dialog = self.continue_dialog()
            if dialog is not None:
                if retried:
                    raise self.stop("publish_unconfirmed", f"la fenêtre « {labels['dialog']} ? » est revenue "
                                                           f"après le nouvel essai : publication non confirmée")
                button = dialog.query_selector(self.sel["modal"]["button"].format(label=labels["cancel"]))
                if button is None:
                    raise self.stop("element_missing", f"fenêtre « {labels['dialog']} ? » sans son bouton "
                                                       f"« {labels['cancel']} »")
                button.click()
                logger.info("TikTok %s : fenêtre « %s ? » annulée, attente de la vérification de contenu avant "
                            "un nouvel essai", self.account, labels["dialog"])
                self.pause()
                self.await_content_check()
                self.post(mode)
                retried, waited = True, 0.0
                continue
            if str(self.page.url).startswith(self.sel["expect"]["published_url_prefix"]):
                logger.info("TikTok %s : publication prouvée par la navigation vers la page Publications", self.account)
                return
            if self.page.query_selector(sel["published_marker"]) is not None:
                logger.info("TikTok %s : publication prouvée par le message de confirmation", self.account)
                return
            if waited >= timeout:
                raise self.stop("publish_unconfirmed",
                                f"aucune preuve de publication après {timeout:g} s ([tiktok] publish_confirm_timeout_s) : "
                                f"ni navigation vers la page Publications ni message de confirmation ; la vidéo "
                                f"est peut-être publiée, à vérifier à la main avant de réessayer")
            self.page.wait_for_timeout(interval * 1000)
            waited += interval
            if self.on_tick is not None:
                self.on_tick()

    def continue_dialog(self) -> Any | None:
        fragment = self.sel["continue_publish"]["dialog"].casefold()
        for modal in self.page.query_selector_all(self.sel["modal"]["container"]):
            if modal.is_visible() and fragment in " ".join(str(modal.inner_text()).split()).casefold():
                return modal
        return None

    def run(self, clip: dict[str, Any], mode: str, schedule_at: datetime | None) -> dict[str, Any]:
        self.page.goto(self.sel["urls"]["upload"])
        self.guard()
        if not str(self.page.url).startswith(self.sel["expect"]["upload_url_prefix"]):
            raise self.stop("unexpected_page", f"page inattendue : {self.page.url}")
        self.pause()

        self.wait("file_input", state="attached")
        self.page.set_input_files(self.sel["selectors"]["file_input"], str(clip["video_path"]))
        self.pause()
        self.wait("upload_done", timeout_key="upload_timeout_s")
        self.pause()

        self.type_caption(" ".join([clip["caption"], *clip["hashtags"]]))
        self.expand_settings()
        self.click("visibility_dropdown")
        self.click("visibility_" + str(self.settings["visibility"]))

        effective, note = schedule_at, None
        if mode == "scheduled":
            effective, note = self.schedule_later(schedule_at)
        else:
            self.schedule_now()

        if self.settings["content_check"] == "off":
            self.disable_content_check()
        else:
            self.await_content_check()
        self.post(mode)

        self.await_published(mode)
        return self.result(clip, mode, schedule_at, effective, note)

    def find_post_link(self, clip: dict[str, Any]) -> tuple[str | None, str | None]:
        """Page Publications : le premier lien de post dont le texte est le debut de la legende publiee.
        Rend (adresse complete, id) ou (None, raison). Ne leve jamais : la publication est deja prouvee."""
        try:
            if not str(self.page.url).startswith(self.sel["expect"]["stats_url_prefix"]):
                self.page.goto(self.sel["urls"]["stats"])
            selector = self.sel["stats"]["post_link"]
            try:
                self.page.wait_for_selector(selector, timeout=float(self.settings["action_timeout_s"]) * 1000)
            except Exception as exc:
                if "Timeout" not in type(exc).__name__:
                    raise
                return None, f"aucun lien de post affiché après {float(self.settings['action_timeout_s']):g} s"
            published = _squash(" ".join([clip["caption"], *clip["hashtags"]]))
            for link in self.page.query_selector_all(selector):
                text = _squash(str(link.inner_text())).rstrip("….").rstrip()
                href = link.get_attribute("href") or ""
                if text and (published.startswith(text) or text.startswith(published)) and _POST_ID_END.search(href):
                    return urljoin(str(self.page.url), href), _POST_ID_END.search(href).group(1)
            return None, "aucun lien dont le texte correspond à la légende publiée"
        except Exception as exc:  # noqa: BLE001 - dit dans la note, jamais avale
            return None, f"{type(exc).__name__} : {exc}"

    def stats(self, post_ids: list[str]) -> list[dict[str, Any]]:
        """Releve les posts ``post_ids`` (R7), lecture seule, aucun clic : likes et commentaires dans la
        ligne de la page Publications, puis le reste sur l'analyse directe de chaque post."""
        self.page.goto(self.sel["urls"]["stats"])
        self.guard()
        if not str(self.page.url).startswith(self.sel["expect"]["stats_url_prefix"]):
            raise self.stop("unexpected_page", f"page inattendue : {self.page.url}")
        self.pause()
        self.wait("row", table="stats")
        self.guard()
        rows = self.read_rows()
        return [self.read_post(post_id, rows.get(post_id, {})) for post_id in post_ids]

    def read_rows(self) -> dict[str, dict[str, Any]]:
        sel = self.sel["stats"]
        found: dict[str, dict[str, Any]] = {}
        for number, row in enumerate(self.page.query_selector_all(sel["row"]), start=1):
            link = row.query_selector(sel["post_link"])
            href = (link.get_attribute("href") or "") if link is not None else ""
            match = _POST_ID.search(href)
            if match is None:
                raise self.stop("unexpected_page", f"ligne {number} de la liste sans lien de post exploitable")
            cells = {key: row.query_selector(sel[key]) for key in ("likes", "comments")}
            found.setdefault(match.group(1), {
                "post_url": urljoin(str(self.page.url), href),
                **{key: self.read_value(None if cell is None else cell.inner_text(), key, parse_count, f"ligne {number}")
                   for key, cell in cells.items()}})
        return found

    def read_value(self, text: Any, key: str, parse: Callable[[Any], Any], where: str) -> Any:
        """Une valeur affichee, convertie ; absente de la page ou « en cours de traitement » : ``None``
        explicite, jamais un 0 invente ; illisible : arret sur."""
        if text is None:
            return None
        if isinstance(text, str) and self.sel["stats"]["processing"].casefold() in text.casefold():
            return None
        try:
            return parse(text)
        except ValueError:
            raise self.stop("unexpected_page", f"valeur illisible ({where}, {key}) : {text!r}") from None

    def read_post(self, post_id: str, row: dict[str, Any]) -> dict[str, Any]:
        """Analyse directe d'un post : cartes de metriques lues par libelle."""
        self.page.goto(self.sel["urls"]["analytics"].format(post_id=post_id))
        self.guard()
        if not str(self.page.url).startswith(self.sel["expect"]["analytics_url_prefix"]):
            raise self.stop("unexpected_page", f"page inattendue : {self.page.url}")
        self.pause()
        self.wait("metric_card", table="stats")
        self.guard()
        cards: dict[str, str] = {}
        for card in self.page.query_selector_all(self.sel["stats"]["metric_card"]):
            parts = [part.strip() for part in re.split(r"\s*\|\s*|\n+", str(card.inner_text())) if part.strip()]
            if len(parts) >= 2:
                cards.setdefault(_squash(parts[0]).casefold(), " ".join(parts[1:]))
        post: dict[str, Any] = {"post_id": post_id, "post_url": row.get("post_url")}
        for key, field, parse in (("views", "views", parse_count), ("watch_total", "watch_total_s", parse_duration),
                                  ("watch_avg", "avg_watch_s", parse_duration), ("watched_full", "watched_full", parse_percent),
                                  ("new_followers", "new_followers", parse_count), ("retention", "retention", parse_percent)):
            value = cards.get(_squash(self.sel["metrics"][key]).casefold())
            post[field] = self.read_value(value, key, parse, f"post {post_id}")
        post.update(likes=row.get("likes"), comments=row.get("comments"), shares=None)
        sources = self.page.query_selector(self.sel["stats"]["traffic_sources"])
        text = _squash(str(sources.inner_text())) if sources is not None else ""
        post["traffic_sources"] = None if not text or self.sel["stats"]["processing"].casefold() in text.casefold() else text
        return post

    def result(self, clip: dict[str, Any], mode: str, schedule_at: datetime | None,
               effective: datetime | None = None, rounding: str | None = None) -> dict[str, Any]:
        notes = [rounding] if rounding else []
        url, found = self.find_post_link(clip)
        post_id = found if url is not None else None
        if url is None:
            notes.append("post programmé : son adresse publique n'existe pas encore" if mode == "scheduled"
                         else f"publication réussie mais lien du post introuvable sur la page Publications "
                              f"({found}) : à vérifier à la main")
        when = (effective if rounding else schedule_at) if mode == "scheduled" else self.now
        return {
            "post_url": url,
            "post_id": post_id,
            "state": "scheduled_on_tiktok" if mode == "scheduled" else "published",
            "publish_at": when.isoformat(),
            "note": " ; ".join(notes) or None,
        }


class BrowserBackend:
    def publish(self, clip: dict[str, Any], account: str, *, mode: str, schedule_at: datetime | None,
                settings: dict[str, Any], selectors: dict[str, Any], now: datetime, opener: Opener | None,
                sleep: Callable[[float], None], rng: Any, on_tick: Callable[[], None] | None) -> dict[str, Any]:
        open_profile = opener or browser._open_context
        with open_profile(account, headless=False) as context:  # visible : jamais de navigateur cache (ADR-1a58)
            page = context.pages[0] if context.pages else context.new_page()
            flow = _Flow(page, account, selectors, settings, now=now, sleep=sleep, rng=rng, on_tick=on_tick)
            try:
                return flow.run(clip, mode, schedule_at)
            except TikTokStop:
                raise
            except Exception as exc:  # noqa: BLE001 - erreur Playwright : arret sur avec capture
                raise flow.stop("unexpected_page", f"page inattendue : {type(exc).__name__} : {exc}") from exc

    def fetch_stats(self, account: str, post_ids: list[str], *, settings: dict[str, Any], selectors: dict[str, Any],
                    now: datetime, opener: Opener | None, sleep: Callable[[float], None], rng: Any,
                    on_tick: Callable[[], None] | None) -> list[dict[str, Any]]:
        open_profile = opener or browser._open_context
        with open_profile(account, headless=False) as context:
            page = context.pages[0] if context.pages else context.new_page()
            flow = _Flow(page, account, selectors, settings, now=now, sleep=sleep, rng=rng, on_tick=on_tick)
            try:
                return flow.stats(post_ids)
            except TikTokStop:
                raise
            except Exception as exc:  # noqa: BLE001 - erreur Playwright : arret sur avec capture
                raise flow.stop("unexpected_page", f"page inattendue : {type(exc).__name__} : {exc}") from exc


class ApiBackend:
    def publish(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise TikTokError("backend api pas encore disponible : règle [tiktok] backend = \"browser\"")

    def fetch_stats(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        raise TikTokError("backend api pas encore disponible : statistiques seulement par le navigateur")


_BACKENDS = {"browser": BrowserBackend, "api": ApiBackend}


# ---------------------------------------------------------------- interface


def publish(
    clip: dict[str, Any], account: str, *, mode: str | None = None, schedule_at: datetime | None = None,
    config: Config | None = None, now: datetime | None = None, selectors: dict[str, Any] | None = None,
    opener: Opener | None = None, sleep: Callable[[float], None] = time.sleep, rng: Any = None,
    on_tick: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """Publie ``clip`` ({video_path, caption, hashtags}) sur le compte, ``mode`` ``immediate``
    ou ``scheduled`` (date ``schedule_at``, programmation cote TikTok). Rend
    ``{post_url, post_id, state, publish_at, note}`` ; leve ``TikTokError`` (reglage, date,
    clip), ``TikTokStop`` (R4) ou ``BrowserError`` (Chrome/Playwright absent)."""
    settings = get_settings(config)
    backend = _BACKENDS[settings["backend"]]()
    mode = mode if mode is not None else str(settings["publish_mode"])
    if not account:
        raise TikTokError("compte TikTok manquant : la chaîne n'a pas de tiktok_account")
    if mode not in MODES:
        raise TikTokError(f"mode de publication invalide : {mode!r} (attendu : {' | '.join(MODES)})")
    if not Path(clip["video_path"]).is_file():
        raise TikTokError(f"mp4 introuvable : {clip['video_path']}")
    now = now or datetime.now(timezone.utc)
    if mode == "scheduled":
        if settings["visibility"] == "private":
            raise TikTokError("programmation refusée : TikTok ne programme pas une vidéo privée (« Les vidéos privées "
                              "ne peuvent pas être programmées ») : règle [tiktok] visibility = \"public\" ou publie "
                              "en mode immédiat")
        _check_schedule(schedule_at, settings, now)
    if isinstance(backend, ApiBackend):
        return backend.publish()
    return backend.publish(
        clip, browser.validate_account(account), mode=mode, schedule_at=schedule_at, settings=settings,
        selectors=selectors or load_selectors(), now=now, opener=opener, sleep=sleep,
        rng=rng or random.Random(), on_tick=on_tick,
    )


def _check_schedule(schedule_at: datetime | None, settings: dict[str, Any], now: datetime) -> None:
    if schedule_at is None or schedule_at.tzinfo is None:
        raise TikTokError("publication programmée : une date avec fuseau horaire est requise")
    days, minutes = settings["schedule_max_days"], settings["schedule_min_minutes"]
    if schedule_at > now + timedelta(days=days):
        raise TikTokError(
            f"programmation refusée : {schedule_at.isoformat()} dépasse la limite de {days} jours "
            f"de TikTok ([tiktok] schedule_max_days)"
        )
    if schedule_at < now + timedelta(minutes=minutes):
        raise TikTokError(
            f"programmation refusée : {schedule_at.isoformat()} est à moins de {minutes} minutes "
            f"(avance minimale de TikTok, [tiktok] schedule_min_minutes) : publie en mode immédiat"
        )


# ---------------------------------------------------------------- statistiques (R7)


def _stats_path(account: str, settings: dict[str, Any]) -> Path:
    return Path(settings["stats_dir"]) / f"{browser.validate_account(account)}.json"


def read_stats(account: str, *, config: Config | None = None) -> dict[str, Any] | None:
    """Le dernier releve de ``account`` (state/stats/tiktok/<compte>.json), ``None`` s'il n'y en a
    pas encore ; un fichier illisible est une ``TikTokError`` (jamais ignore)."""
    path = _stats_path(account, get_settings(config))
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("posts"), list):
            raise ValueError("objet {posts: [...]} attendu")
        return data
    except (OSError, ValueError) as exc:
        raise TikTokError(f"relevé des statistiques TikTok illisible ({path}) : {exc}") from exc


def read_all_stats(*, config: Config | None = None) -> list[dict[str, Any]]:
    """Les releves de tous les comptes (un fichier par compte), tries par compte."""
    root = Path(get_settings(config)["stats_dir"])
    return [read_stats(path.stem, config=config) for path in sorted(root.glob("*.json"))] if root.is_dir() else []


def _published_posts(account: str, config: Config | None) -> list[dict[str, Any]]:
    """Posts publies de ``account`` connus par les sidecars de clips (``tiktok_post``, ecrit a la
    publication) : ce qui relie un relevé aux clips, par l'id ou l'adresse du post."""
    root = Path(config.output_dir if config is not None else "output")
    found = []
    for path in sorted(root.glob("*/*.json")) if root.is_dir() else []:
        try:
            sidecar = json.loads(path.read_text(encoding="utf-8"))
            post = sidecar.get("tiktok_post") if isinstance(sidecar, dict) else None
            if not isinstance(post, dict) or post.get("account") != account:
                continue
            post_id = post.get("id") or (_POST_ID.search(post["url"]).group(1) if post.get("url") else None)
            if post_id:
                found.append({"video_id": path.parent.name, "clip_id": path.stem, "post_id": str(post_id)})
        except (OSError, ValueError, AttributeError) as exc:
            raise TikTokError(f"sidecar illisible pour relier les statistiques ({path}) : {exc}") from exc
    return found


def stats_accounts(*, config: Config | None = None) -> list[str]:
    """Comptes ayant au moins un post publie a mesurer (id ou adresse enregistres a la publication)."""
    root = Path(config.output_dir if config is not None else "output")
    accounts: set[str] = set()
    for path in sorted(root.glob("*/*.json")) if root.is_dir() else []:
        try:
            post = json.loads(path.read_text(encoding="utf-8")).get("tiktok_post")
        except (OSError, ValueError, AttributeError) as exc:
            raise TikTokError(f"sidecar illisible ({path}) : {exc}") from exc
        if isinstance(post, dict) and post.get("account") and (post.get("id") or post.get("url")):
            accounts.add(post["account"])
    return sorted(accounts)


def stats_due(account: str, *, config: Config | None = None, now: datetime | None = None) -> bool:
    """Vrai si le dernier essai de releve (reussi ou arrete) date de ``stats_interval_h`` ou plus,
    ou s'il n'y en a jamais eu : un arret sur n'est pas retente a chaque passage du worker."""
    data = read_stats(account, config=config)
    if data is None:
        return True
    stamps = [t for t in (data.get("fetched_at"), (data.get("error") or {}).get("at")) if t]
    if not stamps:
        return True
    interval = timedelta(hours=float(get_settings(config)["stats_interval_h"]))
    return (now or datetime.now(timezone.utc)) - max(datetime.fromisoformat(t) for t in stamps) >= interval


def _write_stats(account: str, settings: dict[str, Any], update: Callable[[dict[str, Any] | None], dict[str, Any]]) -> dict[str, Any]:
    path = _stats_path(account, settings)
    with channel_mod.file_lock(path):
        previous = None
        if path.is_file():
            try:
                previous = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise TikTokError(f"relevé des statistiques TikTok illisible ({path}) : {exc}") from exc
        data = update(previous)
        channel_mod.atomic_write_json(path, data)
    return data


def _record_stats_failure(account: str, exc: Exception, config: Config | None, settings: dict[str, Any],
                          now: datetime) -> None:
    """R4 : l'echec est ecrit a cote du dernier releve (qui reste), et signale a la console."""
    code = exc.code if isinstance(exc, TikTokStop) else "browser"
    capture = str(exc.capture) if isinstance(exc, TikTokStop) and exc.capture else None
    reason = exc.reason if isinstance(exc, TikTokStop) else str(exc)
    error = {"at": now.isoformat(), "code": code, "reason": reason, "capture": capture}
    _write_stats(account, settings, lambda prev: {
        **(prev or {"account": account, "fetched_at": None, "posts": []}), "error": error})
    emit_event({"level": "error", "account": account, "channel": None, "video_id": None, "clip_id": None,
                "reason": f"relevé des statistiques : {reason}", "capture": capture}, config=config, now=now)


def fetch_stats(
    account: str, *, config: Config | None = None, now: datetime | None = None,
    selectors: dict[str, Any] | None = None, opener: Opener | None = None,
    sleep: Callable[[float], None] = time.sleep, rng: Any = None, on_tick: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """Releve les statistiques des posts publies de ``account`` (ids enregistres a la publication) dans
    TikTok Studio (R7, lecture seule) : analyse directe de chaque post, likes et commentaires depuis la page
    Publications ; les relie aux clips et ecrit ``<stats_dir>/<compte>.json`` (horodate, atomique). Une
    valeur absente de la page ou « en cours de traitement » (retention, sources) est ``None``.
    Leve ``TikTokStop`` (R4 : l'echec est aussi ecrit a cote du dernier releve et signale a la
    console), ``BrowserError`` ou ``TikTokError``."""
    settings = get_settings(config)
    backend = _BACKENDS[settings["backend"]]()
    if not account:
        raise TikTokError("compte TikTok manquant : aucun relevé de statistiques sans compte")
    if isinstance(backend, ApiBackend):
        return backend.fetch_stats()
    account = browser.validate_account(account)
    now = now or datetime.now(timezone.utc)
    known = {p["post_id"]: p for p in _published_posts(account, config)}
    if not known:
        raise TikTokError(f"aucun post publié à mesurer pour le compte {account} : "
                          f"aucun clip n'a d'id ou d'adresse de post enregistré (tiktok_post)")
    try:
        posts = backend.fetch_stats(
            account, list(known), settings=settings, selectors=selectors or load_selectors(), now=now, opener=opener,
            sleep=sleep, rng=rng or random.Random(), on_tick=on_tick)
    except (TikTokStop, browser.BrowserError) as exc:
        _record_stats_failure(account, exc, config, settings, now)
        raise
    linked = [{**post, "video_id": known.get(post["post_id"], {}).get("video_id"),
               "clip_id": known.get(post["post_id"], {}).get("clip_id")} for post in posts]
    return _write_stats(account, settings, lambda _prev: {
        "account": account, "fetched_at": now.isoformat(), "source": "tiktok_studio", "posts": linked, "error": None})
