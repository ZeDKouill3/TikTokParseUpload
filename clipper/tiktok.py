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
    "min_action_delay_s": 3,
    "max_action_delay_s": 12,
    "schedule_max_days": 10,           # limite native de TikTok Studio
    "schedule_min_minutes": 15,        # avance minimale native de TikTok Studio
    "action_timeout_s": 30,            # attente d'un element de la page
    "upload_timeout_s": 300,           # attente de la fin de l'envoi du mp4
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
    "file_input", "upload_done", "caption_editor", "visibility_dropdown", "visibility_public",
    "visibility_private", "schedule_toggle", "schedule_date_input", "schedule_time_input",
    "post_button", "schedule_button", "success_marker", "post_link",
)
REQUIRED_STATS_SELECTORS = ("row", "post_link", "views", "likes", "comments", "shares", "avg_watch", "watched_full")
_DETECT_KINDS = ("captcha", "verification", "login")
_COUNTS = ("views", "likes", "comments", "shares")
_POST_ID = re.compile(r"/video/(\d+)")


class TikTokError(Exception):
    """Reglage, clip, date ou backend invalide ; fichier de selecteurs ou d'evenements illisible."""


class TikTokStop(TikTokError):
    """Arret sur de la page (SPEC-9225 R4). ``code`` : captcha | verification | login |
    element_missing | unexpected_page ; ``capture`` : la capture d'ecran, ou None."""

    def __init__(self, code: str, reason: str, capture: Path | None = None) -> None:
        super().__init__(reason)
        self.code, self.reason, self.capture = code, reason, capture


# ---------------------------------------------------------------- reglages et selecteurs


def get_settings(config: Config | None) -> dict[str, Any]:
    settings = dict(config.section("tiktok")) if config is not None else dict(CONFIG_DEFAULTS)
    for key, allowed in (("backend", BACKENDS), ("publish_mode", MODES), ("visibility", VISIBILITIES)):
        if settings[key] not in allowed:
            raise TikTokError(f"[tiktok] {key} invalide : {settings[key]!r} (attendu : {' | '.join(allowed)})")
    for key, minimum in (("max_posts_per_day", 1), ("min_gap_minutes", 0), ("min_action_delay_s", 0),
                         ("max_action_delay_s", 0), ("schedule_max_days", 1), ("schedule_min_minutes", 0),
                         ("action_timeout_s", 1), ("upload_timeout_s", 1)):
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
    need("urls", "stats", str)
    need("expect", "stats_url_prefix", str)
    for key in REQUIRED_STATS_SELECTORS:
        need("stats", key, str)
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

_STAT_FIELDS = {"avg_watch": "avg_watch_s"}
_ABSENT = frozenset({"", "-", "--", "–", "—", "N/A", "n/a"})
_SUFFIX = {"": 1, "k": 1_000, "m": 1_000_000, "md": 1_000_000_000, "b": 1_000_000_000}
_COUNT = re.compile(r"(\d[\d ]*)(?:[.,](\d+))?\s*([kKmMbB]|Md)?")
_PERCENT = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")
_CLOCK = re.compile(r"(?:(\d+):)?(\d+):(\d{2})")
_SECONDS = re.compile(r"(?:(\d+)\s*min\s*)?(?:(\d+(?:[.,]\d+)?)\s*s)?|(\d+)\s*min")


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
    """« 12,5 s », « 1:05 », « 1 min 5 s » -> secondes ; tiret ou vide -> ``None`` ; autre -> ``ValueError``."""
    text = _text(value)
    if text in _ABSENT:
        return None
    clock = _CLOCK.fullmatch(text)
    if clock:
        return float(int(clock[1] or 0) * 3600 + int(clock[2]) * 60 + int(clock[3]))
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

    def guard(self) -> None:
        url = str(self.page.url)
        if any(marker in url for marker in self.sel["expect"]["login_url_markers"]):
            raise self.stop("login", f"connexion expirée : reconnecte le compte {self.account} (page : {url})")
        for code, label in (("captcha", "captcha détecté : arrêt immédiat, à résoudre à la main"),
                            ("verification", "vérification de compte demandée : arrêt immédiat, à faire à la main"),
                            ("login", f"connexion expirée : reconnecte le compte {self.account}")):
            for css in self.sel["detect"][code]:
                if self.page.query_selector(css) is not None:
                    raise self.stop(code, label)

    # -- actions
    def pause(self) -> None:
        if self.on_tick is not None:
            self.on_tick()
        self._sleep(self.rng.uniform(float(self.settings["min_action_delay_s"]), float(self.settings["max_action_delay_s"])))
        if self.on_tick is not None:
            self.on_tick()

    def wait(self, name: str, *, timeout_key: str = "action_timeout_s", state: str | None = None,
             table: str = "selectors") -> Any:
        self.guard()
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

    def fill(self, name: str, text: str) -> None:
        self.wait(name).fill(text)
        self.pause()

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

        self.fill("caption_editor", " ".join([clip["caption"], *clip["hashtags"]]))
        self.click("visibility_dropdown")
        self.click("visibility_" + str(self.settings["visibility"]))

        if mode == "scheduled":
            local = schedule_at.astimezone()
            self.click("schedule_toggle")
            self.fill("schedule_date_input", local.strftime("%Y-%m-%d"))
            self.fill("schedule_time_input", local.strftime("%H:%M"))
            self.click("schedule_button")
        else:
            self.click("post_button")

        self.wait("success_marker")
        return self.result(mode, schedule_at)

    def stats(self) -> list[dict[str, Any]]:
        """Releve les lignes de la liste des contenus (R7) : lecture seule, aucun clic."""
        self.page.goto(self.sel["urls"]["stats"])
        self.guard()
        if not str(self.page.url).startswith(self.sel["expect"]["stats_url_prefix"]):
            raise self.stop("unexpected_page", f"page inattendue : {self.page.url}")
        self.pause()
        self.wait("row", table="stats")
        self.guard()
        rows = self.page.query_selector_all(self.sel["stats"]["row"])
        return [self.read_row(number, row) for number, row in enumerate(rows, start=1)]

    def read_row(self, number: int, row: Any) -> dict[str, Any]:
        sel = self.sel["stats"]
        link = row.query_selector(sel["post_link"])
        url = (link.get_attribute("href") or None) if link is not None else None
        match = _POST_ID.search(url) if url else None
        if match is None:
            raise self.stop("unexpected_page", f"ligne {number} de la liste sans lien de post exploitable : {url!r}")
        post: dict[str, Any] = {"post_id": match.group(1), "post_url": url}
        for key, parse in (*((k, parse_count) for k in _COUNTS), ("avg_watch", parse_duration),
                           ("watched_full", parse_percent)):
            cell = row.query_selector(sel[key])
            if cell is None:  # non affichee par la page : null explicite, jamais un 0 invente
                post[_STAT_FIELDS.get(key, key)] = None
                continue
            text = cell.inner_text()
            try:
                post[_STAT_FIELDS.get(key, key)] = parse(text)
            except ValueError:
                raise self.stop("unexpected_page",
                                f"valeur illisible dans la ligne {number} ({key}) : {text!r}") from None
        return post

    def result(self, mode: str, schedule_at: datetime | None) -> dict[str, Any]:
        url = None
        link = self.page.query_selector(self.sel["selectors"]["post_link"])
        if link is not None:
            url = link.get_attribute("href") or None
        match = _POST_ID.search(url) if url else None
        note = None
        if url is None:
            note = ("post programmé : son adresse publique n'existe pas encore" if mode == "scheduled"
                    else "lien du post introuvable dans la confirmation TikTok : à vérifier à la main")
        return {
            "post_url": url,
            "post_id": match.group(1) if match else None,
            "state": "scheduled_on_tiktok" if mode == "scheduled" else "published",
            "publish_at": (schedule_at if mode == "scheduled" else self.now).isoformat(),
            "note": note,
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

    def fetch_stats(self, account: str, *, settings: dict[str, Any], selectors: dict[str, Any], now: datetime,
                    opener: Opener | None, sleep: Callable[[float], None], rng: Any,
                    on_tick: Callable[[], None] | None) -> list[dict[str, Any]]:
        open_profile = opener or browser._open_context
        with open_profile(account, headless=False) as context:
            page = context.pages[0] if context.pages else context.new_page()
            flow = _Flow(page, account, selectors, settings, now=now, sleep=sleep, rng=rng, on_tick=on_tick)
            try:
                return flow.stats()
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
    """Releve les statistiques des posts publies de ``account`` dans TikTok Studio (R7, lecture
    seule), les relie aux clips par l'id ou l'adresse enregistres a la publication et ecrit
    ``<stats_dir>/<compte>.json`` (horodate, atomique). Une valeur absente de la page est ``None``.
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
    try:
        posts = backend.fetch_stats(
            account, settings=settings, selectors=selectors or load_selectors(), now=now, opener=opener,
            sleep=sleep, rng=rng or random.Random(), on_tick=on_tick)
    except (TikTokStop, browser.BrowserError) as exc:
        _record_stats_failure(account, exc, config, settings, now)
        raise
    known = {p["post_id"]: p for p in _published_posts(account, config)}
    linked = [{**post, "video_id": known.get(post["post_id"], {}).get("video_id"),
               "clip_id": known.get(post["post_id"], {}).get("clip_id")} for post in posts]
    return _write_stats(account, settings, lambda _prev: {
        "account": account, "fetched_at": now.isoformat(), "source": "tiktok_studio", "posts": linked, "error": None})
