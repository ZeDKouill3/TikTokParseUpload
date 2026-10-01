"""Profils de navigateur persistants par compte (ADR-1a58, SPEC-9225 R1, R8).

Un profil Playwright vit dans ``state/browser/<compte>/`` (ignore par git, jamais
copie hors de ``state/``). « Se connecter » ouvre le vrai Chrome visible sur ce
profil : l'utilisateur se connecte a la main, aucune fonction d'ici ne saisit
d'identifiant ni de mot de passe. Les cookies YouTube d'un profil s'exportent
vers ``cookies.txt`` (format Netscape) pour yt-dlp.

Pas de repli (ADR-ad2e) : Playwright ou Chrome absent, profil absent, aucun
cookie a exporter = ``BrowserError`` en francais avec la commande a lancer.

Module isole : n'importe aucune etape ni ``clipper.web`` (ADR-b16b). Playwright
est importe a la demande ; les tests branchent un faux avec ``use_playwright``.
"""

from __future__ import annotations

import logging
import os
import re
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator
from urllib.parse import urlparse

from clipper.config import Config

logger = logging.getLogger(__name__)

CONFIG_DEFAULTS: dict[str, object] = {
    # Page ouverte par « clipper browser login <compte> » sans --url.
    "login_url": "https://www.tiktok.com/login",
    # Domaines dont les cookies sortent du profil vers cookies.txt (yt-dlp) ;
    # les autres cookies du profil (TikTok...) ne sont jamais exportes.
    "cookie_domains": ["youtube.com", "google.com"],
    # Delai (s) pour que la fenetre s'ouvre quand la console la demande.
    "launch_timeout_s": 60,
}

STATE_DIR = Path("state") / "browser"
COOKIES_FILE = "cookies.txt"
CHANNEL = "chrome"  # le vrai Chrome, jamais un Chromium embarque (SPEC-9225 R1)
INSTALL_PLAYWRIGHT = "uv pip install playwright"
INSTALL_CHROME = "playwright install chrome"

_ACCOUNT_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
_NETSCAPE_HEADER = "# Netscape HTTP Cookie File"

_override: Callable[[], Any] | None = None
_lock = threading.Lock()
_active: dict[str, Any] = {}  # comptes dont la fenetre de connexion est ouverte


class BrowserError(Exception):
    """Compte ou URL invalide, Playwright/Chrome absent, profil absent, export impossible."""


def use_playwright(factory: Callable[[], Any] | None) -> None:
    """Branche une fabrique ``sync_playwright`` (tests : faux) ; None = le vrai."""
    global _override
    _override = factory


def _playwright_factory() -> Callable[[], Any]:
    if _override is not None:
        return _override
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise BrowserError(
            "Playwright n'est pas installé : lance « " + INSTALL_PLAYWRIGHT + " » "
            "(ou relance tools/setup.ps1), puis « " + INSTALL_CHROME + " » si Chrome manque"
        ) from None
    return sync_playwright


def _settings(config: Config | None) -> dict[str, object]:
    return config.section("browser") if config is not None else dict(CONFIG_DEFAULTS)


# ---------------------------------------------------------------- profil


def validate_account(account: object) -> str:
    """Id de compte sur pour un nom de dossier : ni separateur, ni point, ni traversee."""
    if not isinstance(account, str) or not _ACCOUNT_ID.fullmatch(account):
        raise BrowserError(
            f"identifiant de compte invalide : {account!r} (attendu : 1 à 64 caractères parmi lettres, chiffres, _ et -)"
        )
    return account


def profile_dir(account: object) -> Path:
    return STATE_DIR / validate_account(account)


def profile_status(account: object) -> dict[str, Any]:
    """``{"present": bool, "modified_at": ISO UTC | None}`` : un profil existe quand son
    dossier contient quelque chose (Chrome y ecrit des l'ouverture)."""
    directory = profile_dir(account)
    try:
        times = [p.stat().st_mtime for p in directory.iterdir()]
    except FileNotFoundError:
        return {"present": False, "modified_at": None}
    except OSError as exc:
        raise BrowserError(f"profil illisible : {directory} ({type(exc).__name__})") from None
    if not times:
        return {"present": False, "modified_at": None}
    stamp = datetime.fromtimestamp(max(times), tz=timezone.utc).isoformat(timespec="seconds")
    return {"present": True, "modified_at": stamp}


# ---------------------------------------------------------------- ouverture


def _is_missing_chrome(message: str) -> bool:
    low = message.lower()
    return "distribution" in low and "not found" in low or "playwright install" in low or "executable doesn't exist" in low


@contextmanager
def _open_context(account: str, *, headless: bool) -> Iterator[Any]:
    directory = profile_dir(account)
    manager = _playwright_factory()()
    pw = manager.start()
    try:
        try:
            context = pw.chromium.launch_persistent_context(
                str(directory), channel=CHANNEL, headless=headless, no_viewport=True,
            )
        except Exception as exc:  # noqa: BLE001 - erreur Playwright : retraduite, jamais avalee
            message = str(exc)
            if _is_missing_chrome(message):
                raise BrowserError(
                    "Chrome est introuvable : installe Google Chrome, ou lance « " + INSTALL_CHROME + " »"
                ) from None
            raise BrowserError(f"ouverture du navigateur impossible : {message.strip().splitlines()[0] if message.strip() else type(exc).__name__}") from None
        try:
            yield context
        finally:
            try:
                context.close()
            except Exception as exc:  # noqa: BLE001 - fenetre deja fermee par l'utilisateur
                logger.debug("fermeture du contexte : %s", type(exc).__name__)
    finally:
        pw.stop()


def _login_url(url: str | None, config: Config | None) -> str:
    value = url if url is not None else str(_settings(config)["login_url"])
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise BrowserError(f"URL invalide : {value!r} (une adresse http(s) complète est attendue)")
    return value


def login(
    account: str, url: str | None = None, *, config: Config | None = None,
    on_open: Callable[[], None] | None = None,
) -> None:
    """Ouvre le profil du compte, visible, sur la page de connexion, et attend que la
    fenetre soit fermee. L'utilisateur se connecte lui-meme."""
    validate_account(account)
    target = _login_url(url, config)
    with _open_context(account, headless=False) as context:
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(target)
        if on_open is not None:
            on_open()
        context.wait_for_event("close", timeout=0)


def start_login(
    account: str, url: str | None = None, *, config: Config | None = None,
) -> None:
    """``login`` dans un fil, pour la console : rend la main une fois la fenetre ouverte
    (ou leve ``BrowserError`` si elle n'a pas pu s'ouvrir). Une seule fenetre par profil."""
    validate_account(account)
    _login_url(url, config)
    timeout = float(_settings(config)["launch_timeout_s"])
    ready = threading.Event()
    failure: list[BrowserError] = []

    def run() -> None:
        try:
            login(account, url, config=config, on_open=ready.set)
        except BrowserError as exc:
            failure.append(exc)
        except Exception as exc:  # noqa: BLE001
            failure.append(BrowserError(f"connexion interrompue : {type(exc).__name__}"))
        finally:
            with _lock:
                _active.pop(account, None)
            ready.set()

    thread = threading.Thread(target=run, name=f"browser-login-{account}", daemon=True)
    with _lock:
        if account in _active:
            raise BrowserError(f"la fenêtre de connexion du compte {account} est déjà ouverte")
        _active[account] = thread
    thread.start()
    if not ready.wait(timeout):
        raise BrowserError(f"le navigateur ne s'est pas ouvert dans les {timeout:g} s")
    if failure:
        raise failure[0]


# ---------------------------------------------------------------- cookies


def _in_domains(domain: str, suffixes: list[str]) -> bool:
    host = domain.lstrip(".").lower()
    return any(host == s or host.endswith("." + s) for s in suffixes)


def format_netscape(cookies: list[dict[str, Any]]) -> str:
    """Cookies Playwright -> texte au format Netscape lu par yt-dlp (``#HttpOnly_`` pour
    les cookies HttpOnly, expiration 0 pour un cookie de session)."""
    lines = [_NETSCAPE_HEADER, ""]
    for c in cookies:
        name, value, domain = str(c["name"]), str(c["value"]), str(c["domain"])
        if any(ch in field for field in (name, value, domain) for ch in "\t\r\n"):
            raise BrowserError(f"cookie {name!r} inexportable : tabulation ou saut de ligne dans ses champs")
        expires = int(c.get("expires") or -1)
        fields = [
            ("#HttpOnly_" if c.get("httpOnly") else "") + domain,
            "TRUE" if domain.startswith(".") else "FALSE",
            str(c.get("path") or "/"),
            "TRUE" if c.get("secure") else "FALSE",
            str(expires if expires > 0 else 0),
            name,
            value,
        ]
        lines.append("\t".join(fields))
    return "\n".join(lines) + "\n"


def export_cookies(account: str, *, config: Config | None = None) -> Path:
    """Exporte les cookies YouTube/Google du profil vers ``state/browser/<compte>/cookies.txt``
    (ecriture atomique, lisible par le seul utilisateur) et rend son chemin."""
    directory = profile_dir(account)
    if account in _active:
        raise BrowserError(
            f"la fenêtre de connexion du compte {account} est encore ouverte : ferme-la avant d'exporter les cookies"
        )
    if not profile_status(account)["present"]:
        raise BrowserError(
            f"profil absent pour le compte {account} : connecte-toi d'abord avec "
            f"« clipper browser login {account} --url https://www.youtube.com »"
        )
    suffixes = [str(d).lower() for d in _settings(config)["cookie_domains"]]
    with _open_context(account, headless=True) as context:
        cookies = [c for c in context.cookies() if _in_domains(str(c.get("domain", "")), suffixes)]
    if not cookies:
        raise BrowserError(
            f"aucun cookie {' / '.join(suffixes)} dans le profil du compte {account} : "
            f"connecte-toi avec « clipper browser login {account} --url https://www.youtube.com »"
        )
    path = directory / COOKIES_FILE
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(format_netscape(cookies), encoding="utf-8")
    try:
        tmp.chmod(0o600)
    except OSError:
        pass  # Windows : droits herites du dossier
    os.replace(tmp, path)
    return path
