"""Carnet local des comptes (SPEC-6fa4) : libelle, plateforme, identifiant,
notes dans state/accounts.json ; le mot de passe va UNIQUEMENT dans le coffre
de l'OS via keyring (service « clipper-accounts », cle = id du compte).

Pas de repli (ADR-ad2e) : sans coffre sur (backend fail/null/en clair), toute
operation qui touche un mot de passe echoue avec une erreur explicite, jamais
vers un fichier, une variable ou la memoire. Aucun message d'erreur, aucune
trace ni aucun journal ne porte un mot de passe : les exceptions de keyring
sont remplacees par un message maison, jamais recopiees.

Compte de publication (SPEC-00d1) : en plus, l'etat de connexion TikTok verifie par l'appelant
(``login`` : never | connected | expired, jamais lu ici : aucun import d'une autre etape) et la case
« pret a publier », cochable seulement si la connexion verifiee est ``connected`` ; elle se decoche
d'elle-meme (journal + ``ready_note``) quand la session expire ou apres un arret R4.

Module d'etape isole : n'importe aucune autre etape (ADR-b16b) ; la route web
passe par ici, le generateur de mot de passe aussi (secrets, CSPRNG).
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import string
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import keyring
from keyring.errors import PasswordDeleteError

from clipper.config import Config

logger = logging.getLogger(__name__)

CONFIG_DEFAULTS: dict[str, object] = {
    # Fichier des comptes (sans mot de passe) ; state/ est ignore par git.
    "state_file": "state/accounts.json",
    # Longueur par defaut du mot de passe genere (bornes : 12 a 64).
    "password_length": 20,
}

SERVICE = "clipper-accounts"
MIN_LENGTH = 12
MAX_LENGTH = 64
_AMBIGUOUS = "Il1O0o|"
_SYMBOLS = "!@#$%^&*()-_=+[]{};:,.?"
_FIELDS = ("label", "platform", "username", "notes")
_MAX_LEN = {"label": 120, "platform": 60, "username": 254, "notes": 2000}
_MAX_PASSWORD = 512
LOGIN_STATES = ("never", "connected", "expired")
_REPLACE_ATTEMPTS = 5
_REPLACE_DELAY_S = 0.05

_lock = threading.Lock()
_backend_override: Any = None


class AccountsError(Exception):
    """Entree invalide, coffre indisponible ou fichier illisible."""


class AccountNotFound(AccountsError):
    """Compte (ou mot de passe) inexistant."""


class VaultUnavailable(AccountsError):
    """Pas de coffre sur : on refuse, sans repli (R2)."""


def use_backend(backend: Any) -> None:
    """Branche un backend keyring (tests : en memoire) ; None = celui de l'OS."""
    global _backend_override
    _backend_override = backend


# ---------------------------------------------------------------- coffre


def _backend_is_unsafe(backend: Any) -> bool:
    members = getattr(backend, "backends", None)
    if members is not None:  # ChainerBackend : tous ses membres doivent etre surs
        members = list(members)
        return not members or any(_backend_is_unsafe(b) for b in members)
    cls = type(backend)
    if cls.__module__.startswith(("keyring.backends.fail", "keyring.backends.null", "keyrings.alt")):
        return True
    if "plaintext" in cls.__name__.lower():
        return True
    try:
        return float(backend.priority) <= 0
    except Exception:  # noqa: BLE001 - priority leve RuntimeError sur un backend inutilisable
        return True


def _vault() -> Any:
    try:
        backend = _backend_override if _backend_override is not None else keyring.get_keyring()
    except Exception as exc:  # noqa: BLE001
        logger.error("coffre : initialisation impossible (%s)", type(exc).__name__)
        raise VaultUnavailable("coffre de l'OS indisponible : keyring n'a pas pu s'initialiser") from None
    if _backend_is_unsafe(backend):
        raise VaultUnavailable(
            "pas de coffre sûr sur ce poste (keyring n'a trouvé ni Gestionnaire d'identification "
            "Windows, ni trousseau, ni Secret Service) : le mot de passe n'est pas enregistré, "
            "il n'est jamais écrit dans un fichier ni gardé en mémoire"
        )
    return backend


def _vault_call(action: str, fn, *args):
    try:
        return fn(*args)
    except Exception as exc:  # noqa: BLE001 - jamais str(exc) : il pourrait porter le mot de passe
        logger.error("coffre : %s impossible (%s)", action, type(exc).__name__)
        raise AccountsError(f"le coffre de l'OS a refusé l'opération : {action}") from None


def _vault_set(account_id: str, password: str) -> None:
    backend = _vault()
    _vault_call("écriture du mot de passe", backend.set_password, SERVICE, account_id, password)


def _vault_get(account_id: str) -> str | None:
    backend = _vault()
    return _vault_call("lecture du mot de passe", backend.get_password, SERVICE, account_id)


def _vault_delete(account_id: str) -> None:
    backend = _vault()
    try:
        backend.delete_password(SERVICE, account_id)
    except PasswordDeleteError:
        if _vault_call("lecture du mot de passe", backend.get_password, SERVICE, account_id) is not None:
            raise AccountsError("le coffre de l'OS a refusé l'opération : suppression du mot de passe") from None
    except Exception as exc:  # noqa: BLE001
        logger.error("coffre : suppression du mot de passe impossible (%s)", type(exc).__name__)
        raise AccountsError("le coffre de l'OS a refusé l'opération : suppression du mot de passe") from None


# ---------------------------------------------------------------- fichier


def _path(config: Config) -> Path:
    return Path(str(config.section("accounts")["state_file"]))


def _read(config: Config) -> list[dict[str, Any]]:
    path = _path(config)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AccountsError(f"fichier des comptes illisible : {path} ({type(exc).__name__})") from None
    if not isinstance(data, dict) or not isinstance(data.get("accounts"), list):
        raise AccountsError(f"fichier des comptes invalide : {path} (attendu : {{\"accounts\": [...]}})")
    return data["accounts"]


def _write(config: Config, accounts: list[dict[str, Any]]) -> None:
    path = _path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"accounts": accounts}, f, ensure_ascii=False, indent=2)
        for attempt in range(_REPLACE_ATTEMPTS):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:  # Windows : fichier momentanement verrouille
                if attempt == _REPLACE_ATTEMPTS - 1:
                    raise
                time.sleep(_REPLACE_DELAY_S)
    except OSError as exc:
        Path(tmp).unlink(missing_ok=True)
        raise AccountsError(f"écriture du fichier des comptes impossible : {path} ({type(exc).__name__})") from None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _public(account: dict[str, Any]) -> dict[str, Any]:
    out = {k: account.get(k, "") for k in ("id", *_FIELDS)}
    out.update(has_password=bool(account.get("has_password")),
               created_at=account.get("created_at"), updated_at=account.get("updated_at"),
               ready_to_publish=bool(account.get("ready_to_publish")),
               ready_note=account.get("ready_note"), login=account.get("login"))
    return out


def _clean(data: Any, *, creating: bool) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise AccountsError("corps invalide : un objet JSON est attendu")
    unknown = set(data) - {*_FIELDS, "password"}
    if unknown:
        raise AccountsError(f"champ(s) inconnu(s) : {', '.join(sorted(unknown))}")
    out: dict[str, Any] = {}
    for key in _FIELDS:
        if key not in data:
            continue
        value = data[key]
        if not isinstance(value, str):
            raise AccountsError(f"{key} : une chaîne est attendue")
        value = value.strip()
        if len(value) > _MAX_LEN[key]:
            raise AccountsError(f"{key} : {_MAX_LEN[key]} caractères au maximum")
        out[key] = value
    if creating and not out.get("label"):
        raise AccountsError("label : un libellé est obligatoire")
    if not creating and "label" in out and not out["label"]:
        raise AccountsError("label : un libellé est obligatoire")
    if "password" in data:
        password = data["password"]
        if not isinstance(password, str):
            raise AccountsError("password : une chaîne est attendue")
        if len(password) > _MAX_PASSWORD:
            raise AccountsError(f"password : {_MAX_PASSWORD} caractères au maximum")
        out["password"] = password
    return out


# ---------------------------------------------------------------- comptes


def list_accounts(config: Config) -> list[dict[str, Any]]:
    """Comptes sans mot de passe (champ has_password seulement, R4)."""
    with _lock:
        return [_public(a) for a in _read(config)]


def _find(accounts: list[dict[str, Any]], account_id: str) -> dict[str, Any]:
    for account in accounts:
        if account.get("id") == account_id:
            return account
    raise AccountNotFound(f"compte introuvable : {account_id!r}")


def add_account(config: Config, data: Any) -> dict[str, Any]:
    fields = _clean(data, creating=True)
    password = fields.pop("password", "")
    with _lock:
        accounts = _read(config)
        account_id = secrets.token_hex(6)
        if password:
            _vault_set(account_id, password)
        now = _now()
        account = {"id": account_id, **{k: fields.get(k, "") for k in _FIELDS},
                   "has_password": bool(password), "created_at": now, "updated_at": now}
        try:
            _write(config, [*accounts, account])
        except AccountsError:
            if password:
                _vault_delete(account_id)  # pas de secret orphelin dans le coffre
            raise
    logger.info("compte ajouté : %s", account_id)
    return _public(account)


def update_account(config: Config, account_id: str, data: Any) -> dict[str, Any]:
    """Champs absents inchangés ; password absent = inchangé, "" = supprimé du coffre."""
    fields = _clean(data, creating=False)
    password = fields.pop("password", None)
    with _lock:
        accounts = _read(config)
        account = _find(accounts, account_id)
        if password:
            _vault_set(account_id, password)
            account["has_password"] = True
        elif password == "" and account.get("has_password"):
            _vault_delete(account_id)
            account["has_password"] = False
        account.update(fields)
        account["updated_at"] = _now()
        _write(config, accounts)
    logger.info("compte modifié : %s", account_id)
    return _public(account)


def delete_account(config: Config, account_id: str) -> None:
    """Supprime le compte ET son entrée du coffre (le coffre d'abord : pas de secret orphelin)."""
    with _lock:
        accounts = _read(config)
        account = _find(accounts, account_id)
        if account.get("has_password"):
            _vault_delete(account_id)
        _write(config, [a for a in accounts if a is not account])
    logger.info("compte supprimé : %s", account_id)


def get_password(config: Config, account_id: str) -> str:
    """Seule sortie d'un mot de passe : appelée au clic (Afficher / Copier)."""
    with _lock:
        account = _find(_read(config), account_id)
    if not account.get("has_password"):
        raise AccountNotFound(f"aucun mot de passe enregistré pour le compte {account_id!r}")
    password = _vault_get(account_id)
    if password is None:
        raise AccountsError(
            f"le coffre de l'OS ne contient plus le mot de passe du compte {account_id!r} : "
            "saisis-le de nouveau (Modifier)"
        )
    return password


# ---------------------------------------------------------------- compte de publication


def ready_blocked_reason(account: dict[str, Any]) -> str | None:
    """Pourquoi la case « pret a publier » ne peut pas etre cochee (None : elle peut l'etre)."""
    login = account.get("login") or {}
    if login.get("state") == "connected":
        return None
    if login.get("state") == "expired":
        return "session TikTok expirée : reconnecte-toi (Se connecter)"
    return "connexion TikTok non vérifiée : clique sur Se connecter, connecte-toi à la main puis ferme la fenêtre"


def record_login(config: Config, account_id: str, observed: dict[str, Any]) -> dict[str, Any]:
    """Enregistre la connexion verifiee (``{"state", "checked_at", "expires_at"}``, R2). Un cookie de session
    disparu d'un compte qui etait connecte vaut « expired ». Quand l'etat n'est plus ``connected``, la case
    « pret a publier » se decoche (R3) : journal, ``ready_note`` et ``auto_unchecked`` True dans la reponse
    (l'appelant en fait un evenement console)."""
    state = observed.get("state") if isinstance(observed, dict) else None
    if state not in LOGIN_STATES:
        raise AccountsError(f"état de connexion invalide : {state!r} (attendu : {' | '.join(LOGIN_STATES)})")
    with _lock:
        accounts = _read(config)
        account = _find(accounts, account_id)
        previous = (account.get("login") or {}).get("state")
        if state == "never" and previous in ("connected", "expired"):
            state = "expired"  # Chrome a purge le cookie expire : le compte etait connecte
        login = {"state": state, "checked_at": observed.get("checked_at") or _now(),
                 "expires_at": observed.get("expires_at")}
        unchecked = False
        if state != "connected" and account.get("ready_to_publish"):
            reason = ready_blocked_reason({"login": login})
            account.update(ready_to_publish=False, ready_note=f"décoché automatiquement le {_now()} : {reason}")
            unchecked = True
            logger.warning("compte %s : « prêt à publier » décoché (%s)", account_id, state)
        if login != account.get("login") or unchecked:
            account["login"] = login
            _write(config, accounts)
        out = _public({**account, "login": login})
    out["auto_unchecked"] = unchecked
    return out


def set_ready(config: Config, account_id: str, ready: Any) -> dict[str, Any]:
    """Coche ou decoche « pret a publier » (R3) ; cocher exige une connexion verifiee (``record_login``
    juste avant), sinon ``AccountsError`` avec la raison."""
    if not isinstance(ready, bool):
        raise AccountsError("ready : un booléen est attendu")
    with _lock:
        accounts = _read(config)
        account = _find(accounts, account_id)
        if ready:
            reason = ready_blocked_reason(account)
            if reason is not None:
                raise AccountsError(f"« prêt à publier » refusé pour le compte {account_id} : {reason}")
        account.update(ready_to_publish=ready, ready_note=None)
        account["updated_at"] = _now()
        _write(config, accounts)
    logger.info("compte %s : prêt à publier = %s", account_id, ready)
    return _public(account)


def uncheck_ready(config: Config, account_id: str, reason: str) -> bool:
    """Decoche « pret a publier » apres un arret R4 (captcha, verification...), journalise, avec la raison
    affichee dans ``ready_note`` ; rend True si la case etait cochee."""
    with _lock:
        accounts = _read(config)
        account = _find(accounts, account_id)
        if not account.get("ready_to_publish"):
            return False
        account.update(ready_to_publish=False, ready_note=f"décoché automatiquement le {_now()} : {reason}")
        _write(config, accounts)
    logger.warning("compte %s : « prêt à publier » décoché (%s)", account_id, reason)
    return True


# ---------------------------------------------------------------- generateur


def generate_password(
    config: Config, length: Any = None, *, symbols: bool = False, avoid_ambiguous: bool = False
) -> str:
    """Mot de passe aleatoire (secrets) : minuscules, majuscules, chiffres, symboles en option,
    au moins un caractere de chaque classe choisie."""
    if length is None:
        length = config.section("accounts")["password_length"]
    if isinstance(length, bool) or not isinstance(length, int):
        raise AccountsError("longueur invalide : un entier est attendu")
    if not MIN_LENGTH <= length <= MAX_LENGTH:
        raise AccountsError(f"longueur invalide : {length} (attendu : {MIN_LENGTH} à {MAX_LENGTH})")
    classes = [string.ascii_lowercase, string.ascii_uppercase, string.digits]
    if symbols:
        classes.append(_SYMBOLS)
    if avoid_ambiguous:
        classes = ["".join(c for c in cls if c not in _AMBIGUOUS) for cls in classes]
    chars = [secrets.choice(cls) for cls in classes]
    pool = "".join(classes)
    chars += [secrets.choice(pool) for _ in range(length - len(chars))]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)
