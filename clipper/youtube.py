"""Comptes YouTube : socle de la publication par YouTube Studio (SPEC-5e50 R1, R5, R8 ; ADR-58c0).

Cette tache pose la connexion et la verification « pret a publier » ; la publication et les statistiques
viendront ensuite. Meme principe que TikTok : un vrai Chrome visible sur le profil persistant du compte
(``clipper.browser``), connexion Google faite a la main (Chrome NORMAL, jamais Playwright), aucun
identifiant saisi. Toutes les adresses et tous les reperes de la page vivent dans
``clipper/assets/youtube_selectors.toml``.

``verify_login`` ouvre YouTube Studio sur le profil : connecte quand l'adresse devient
``studio.youtube.com/channel/<UC...>/...`` et que la navigation affiche « Votre chaîne <nom> ». La page
de connexion Google, une page inattendue, un repere absent ou une fenetre inconnue rendent « pas pret »
avec la raison (et une capture), jamais un contournement ni un clic au hasard (R3, ADR-ad2e).

Module d'etape isole : n'importe aucune autre etape ni ``clipper.web`` (ADR-b16b) ; seul ``clipper.browser``
(profil, verrou d'un seul compte pilote) est partage.
"""

from __future__ import annotations

import logging
import random
import re
import time
import tomllib
from contextlib import AbstractContextManager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from clipper import browser
from clipper.config import Config

logger = logging.getLogger(__name__)

CONFIG_DEFAULTS: dict[str, object] = {
    "min_action_delay_s": 0.3,   # pause humaine entre deux actions sur la page
    "max_action_delay_s": 1,
    "max_posts_per_day": 3,      # plafond par compte (R5)
    "min_gap_minutes": 120,      # ecart minimal entre deux publications d'un compte (R5)
    "action_timeout_s": 30,      # attente de l'adresse de chaine apres l'ouverture de Studio
    "poll_interval_s": 1,        # pas d'attente entre deux lectures de l'adresse
}

SELECTORS_PATH = Path(__file__).parent / "assets" / "youtube_selectors.toml"
MAX_POPUP_ROUNDS = 5   # fenetres successives fermees avant d'abandonner

Opener = Callable[..., AbstractContextManager]


class YouTubeError(Exception):
    """Reglage invalide ou fichier de reperes illisible."""


# ---------------------------------------------------------------- reglages et reperes


def get_settings(config: Config | None) -> dict[str, Any]:
    settings = dict(config.section("youtube")) if config is not None else dict(CONFIG_DEFAULTS)
    for key, minimum in (("max_posts_per_day", 1), ("min_gap_minutes", 0), ("min_action_delay_s", 0),
                         ("max_action_delay_s", 0), ("action_timeout_s", 1), ("poll_interval_s", 1)):
        value = settings[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < minimum:
            raise YouTubeError(f"[youtube] {key} invalide : {value!r} (un nombre >= {minimum} est attendu)")
    if settings["min_action_delay_s"] > settings["max_action_delay_s"]:
        raise YouTubeError(
            f"[youtube] min_action_delay_s ({settings['min_action_delay_s']}) dépasse max_action_delay_s "
            f"({settings['max_action_delay_s']})"
        )
    return settings


def load_selectors(path: str | Path | None = None) -> dict[str, Any]:
    """Adresses et reperes de YouTube Studio, valides ou ``YouTubeError`` qui nomme la cle."""
    target = Path(path) if path is not None else SELECTORS_PATH
    try:
        data = tomllib.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise YouTubeError(f"fichier de repères YouTube introuvable : {target}") from None
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise YouTubeError(f"fichier de repères YouTube illisible ({target}) : {exc}") from exc

    def need(table: str, key: str, kind: type) -> None:
        value = data.get(table, {}).get(key)
        if kind is list:
            ok = isinstance(value, list) and bool(value) and all(isinstance(v, str) and v for v in value)
        else:
            ok = isinstance(value, kind) and bool(value)
        if not ok:
            raise YouTubeError(f"fichier de repères YouTube ({target.name}) : [{table}] {key} manquant ou invalide")

    need("urls", "studio", str)
    need("expect", "channel_url_pattern", str)
    need("expect", "login_url_markers", list)
    need("labels", "channel_prefix", str)
    need("selectors", "navigation", str)
    need("modal", "container", str)
    need("modal", "button", str)
    try:
        pattern = re.compile(data["expect"]["channel_url_pattern"])
    except re.error as exc:
        raise YouTubeError(f"fichier de repères YouTube ({target.name}) : [expect] channel_url_pattern "
                           f"invalide ({exc})") from None
    if pattern.groups < 1:
        raise YouTubeError(f"fichier de repères YouTube ({target.name}) : [expect] channel_url_pattern doit "
                           f"capturer l'identifiant de la chaîne (un groupe)")
    popups = data.get("popups")
    if not (isinstance(popups, dict) and popups and all(
            isinstance(k, str) and k and isinstance(v, str) and v and '"' not in v for k, v in popups.items())):
        raise YouTubeError(f"fichier de repères YouTube ({target.name}) : [popups] manquant ou invalide "
                           f"(texte de la fenêtre -> libellé du bouton, sans guillemet double)")
    return data


def studio_url(selectors: dict[str, Any] | None = None) -> str:
    """Page de connexion et de verification : YouTube Studio."""
    return str((selectors or load_selectors())["urls"]["studio"])


# ---------------------------------------------------------------- verification « pret a publier » (R1)


class _Check:
    """Une verification sur une page : chaque etape rend la raison de l'echec (jamais d'exception de page)."""

    def __init__(self, page: Any, account: str, sel: dict[str, Any], settings: dict[str, Any], *,
                 now: datetime, sleep: Callable[[float], None], rng: Any) -> None:
        self.page, self.account, self.sel, self.settings = page, account, sel, settings
        self.now, self._sleep, self.rng = now, sleep, rng

    def pause(self) -> None:
        self._sleep(self.rng.uniform(float(self.settings["min_action_delay_s"]),
                                     float(self.settings["max_action_delay_s"])))

    def refuse(self, reason: str, *, capture: bool = False) -> dict[str, Any]:
        path: Path | None = None
        if capture:
            target = browser.profile_dir(self.account) / "captures" / f"{self.now.strftime('%Y%m%dT%H%M%S')}-youtube.png"
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                self.page.screenshot(path=str(target), full_page=True)
                path = target
            except Exception as exc:  # noqa: BLE001 - dit dans la raison, jamais avale
                reason += f" (capture d'écran impossible : {exc})"
        logger.warning("YouTube %s : pas prêt à publier : %s", self.account, reason)
        return {"ready": False, "reason": reason, "channel": None, "capture": str(path) if path else None}

    def wait_channel_url(self) -> tuple[str | None, str | None]:
        """Attend (borne) l'adresse de chaine. Rend ``(identifiant UC, None)``, ou ``(None, raison)`` pour la
        connexion Google ou une page inattendue."""
        pattern = re.compile(str(self.sel["expect"]["channel_url_pattern"]))
        markers = self.sel["expect"]["login_url_markers"]
        poll = float(self.settings["poll_interval_s"])
        rounds = max(1, int(float(self.settings["action_timeout_s"]) / poll))
        url = ""
        for attempt in range(rounds):
            url = str(self.page.url)
            if any(marker in url for marker in markers):
                return None, ("page de connexion Google affichée : connecte-toi à la main (Se connecter), "
                              "puis ferme la fenêtre")
            found = pattern.search(url)
            if found:
                return found.group(1), None
            if attempt < rounds - 1:
                self.page.wait_for_timeout(int(poll * 1000))
        return None, (f"page inattendue : YouTube Studio ne s'est pas ouvert sur une chaîne après "
                      f"{self.settings['action_timeout_s']:g} s (adresse : {url})")

    def close_popups(self) -> str | None:
        """Ferme les fenetres connues (``[popups]``) ; une fenetre inconnue ou sans son bouton rend la raison."""
        known = self.sel["popups"]
        for _ in range(MAX_POPUP_ROUNDS):
            shown = [m for m in self.page.query_selector_all(self.sel["modal"]["container"]) if m.is_visible()]
            if not shown:
                return None
            for modal in shown:
                text = " ".join(str(modal.inner_text()).split())
                fragment = next((f for f in known if f.casefold() in text.casefold()), None)
                if fragment is None:
                    return f"fenêtre inattendue : {text[:150]!r}"
                label = known[fragment]
                button = modal.query_selector(self.sel["modal"]["button"].format(label=label))
                if button is None:
                    return f"fenêtre connue « {fragment} » sans son bouton « {label} »"
                button.click()
                self.pause()
                logger.info("YouTube %s : fenêtre connue « %s » fermée par « %s »", self.account, fragment, label)
        return f"fenêtres surgissantes qui reviennent après {MAX_POPUP_ROUNDS} fermetures"

    def channel_name(self) -> tuple[str | None, str | None]:
        """Nom de la chaine : le texte « Votre chaîne <nom> » de la navigation."""
        prefix = str(self.sel["labels"]["channel_prefix"])
        pattern = re.compile(re.escape(prefix) + r"[ \t ]+([^\n]*)", re.IGNORECASE)
        found = False
        for nav in self.page.query_selector_all(self.sel["selectors"]["navigation"]):
            match = pattern.search(str(nav.inner_text()))
            if match:
                found = True
                name = " ".join(match.group(1).split())
                if name:
                    return name, None
        if found:
            return None, f"nom de la chaîne illisible : « {prefix} » est affiché sans nom"
        return None, f"navigation sans « {prefix} <nom> » : la chaîne n'est pas affichée"


def verify_login(
    account: str, *, config: Config | None = None, selectors: dict[str, Any] | None = None,
    opener: Opener | None = None, sleep: Callable[[float], None] = time.sleep, rng: Any = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Ouvre YouTube Studio sur le profil du compte (R1) et rend
    ``{"ready": bool, "reason": str | None, "channel": {"name", "id"} | None, "capture": chemin | None}``.
    Pret quand l'adresse est ``studio.youtube.com/channel/<UC...>/...`` et que la navigation affiche
    « Votre chaîne <nom> » (la fenetre « Bienvenue dans YouTube Studio » de la 1re visite est fermee par
    « Continuer »). Chrome ou Playwright absent : ``BrowserError`` (jamais de repli)."""
    browser.validate_account(account)
    settings = get_settings(config)
    sel = selectors or load_selectors()
    open_profile = opener or browser._open_context
    with open_profile(account, headless=False) as context:  # visible : jamais de navigateur cache (ADR-58c0)
        page = context.pages[0] if context.pages else context.new_page()
        check = _Check(page, account, sel, settings, now=now or datetime.now(timezone.utc), sleep=sleep,
                       rng=rng or random.Random())
        page.goto(str(sel["urls"]["studio"]))
        check.pause()
        channel_id, reason = check.wait_channel_url()
        if channel_id is None:
            return check.refuse(reason or "page inattendue", capture="inattendue" in (reason or ""))
        reason = check.close_popups()
        if reason is not None:
            return check.refuse(reason, capture=True)
        name, reason = check.channel_name()
        if name is None:
            return check.refuse(reason or "chaîne illisible", capture=True)
    logger.info("YouTube %s : prêt à publier, chaîne %s (%s)", account, name, channel_id)
    return {"ready": True, "reason": None, "channel": {"name": name, "id": channel_id}, "capture": None}
