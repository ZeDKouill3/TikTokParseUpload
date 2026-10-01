"""Seul point d'appel a un LLM dans clipper (ADR-b1c1).

    from clipper import llm
    data = llm.ask("moments", prompt, [frame1, frame2], SCHEMA)

``ask`` choisit backend et modele d'apres la section [llm] de config.toml
pour cet usage, ajoute au prompt la consigne de repondre en JSON conforme a
``schema``, puis valide la reponse : JSON invalide ou non conforme leve
SchemaError, quota/reseau/surcharge leve TransientLLMError, le reste
LLMError. Seuls du texte et des images fixes (fichiers) sont envoyes.

``check`` (facultatif) controle ce que le schema ne sait pas exprimer
(nombre de mots, doublons...) : appele sur la reponse deja conforme au
schema, il leve SchemaError pour la refuser. Une reponse refusee (JSON
invalide, schema ou ``check``) est renvoyee au meme modele avec la demande
d'origine et le message d'erreur exact, ``repair_attempts`` fois au plus ;
si la reponse reparee est encore refusee, la derniere SchemaError remonte
(aucune valeur de secours). Une erreur transitoire n'est jamais re-essayee
ici.

``log_path`` (facultatif) journalise les reponses refusees : chaque refus
(JSON invalide, schema ou ``check``) ajoute une ligne JSON a ce fichier
(horodatage, usage, modele, numero de tentative, texte brut refuse, erreur
exacte) ; si une correction finit acceptee, une derniere ligne
``accepted: true`` l'enregistre. Sans ``log_path``, rien n'est ecrit, et une
reponse acceptee du premier coup n'est jamais journalisee.

``usage_log(path)`` (gestionnaire de contexte) fixe le ``usage_log_path`` par
defaut de tout ``ask()`` du bloc qui n'en precise pas le sien ;
``clipper.pipeline`` l'ouvre pour la duree d'un passage sur une video. C'est
une variable de module ordinaire, pas une contextvar : une contextvar n'est
jamais copiee vers un thread cree hors asyncio, alors qu'une etape (ex.
``subtitles``, via ``ThreadPoolExecutor``) doit journaliser ses appels LLM au
meme titre que celles qui restent dans le thread principal.

Backends : ``claude-cli`` (defaut, voir clipper.llm.claude_cli pour la facon
dont ``claude -p`` recoit les images), ``claude-api``, ``ollama``. Pour les
tests des autres etapes : ``clipper.llm.fake.FakeBackend`` et
``llm.use_backend(fake)``.

Configuration (fusionnee en profondeur avec CONFIG_DEFAULTS) :

    [llm]
    backend = "claude-cli"
    repair_attempts = 1          # 0 : une reponse refusee echoue tout de suite

    [llm.usages.moments]         # par usage : backend et/ou modele
    model = "strong"             # un niveau (strong|fast) ou un nom de modele

    [llm.usages.vision]
    backend = "ollama"

    [llm.claude_cli.models]      # niveau -> modele, propre a chaque backend
    strong = "opus"
    fast = "sonnet"

Un usage absent de ``usages`` prend le backend global et le niveau ``fast``.
"""

from __future__ import annotations

import contextlib
import json
import logging
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from clipper.llm.backend import Backend, LLMRequest, Usage
from clipper.llm.claude_api import ClaudeAPIBackend
from clipper.llm.claude_cli import ClaudeCLIBackend
from clipper.llm.errors import LLMError, SchemaError, TransientLLMError
from clipper.llm.ollama import OllamaBackend
from clipper.llm.schema import parse_json, validate

__all__ = [
    "CONFIG_DEFAULTS",
    "LLMError",
    "LLMRequest",
    "SchemaError",
    "TransientLLMError",
    "ask",
    "register_backend",
    "usage_log",
    "use_backend",
]

log = logging.getLogger(__name__)

DEFAULT_TIER = "fast"

CONFIG_DEFAULTS: dict[str, object] = {
    "backend": "claude-cli",
    # Nombre de fois où une réponse refusée (schéma ou check) est renvoyée au
    # modèle avec l'erreur pour qu'il la corrige.
    "repair_attempts": 1,
    # Modèle fort pour le jugement lourd (moments, coupes), rapide ailleurs.
    "usages": {
        "moments": {"model": "strong"},
        "parts": {"model": "strong"},
    },
    "claude_cli": {
        "command": "claude",
        "timeout": 900,
        "models": {"strong": "opus", "fast": "sonnet"},
    },
    "claude_api": {
        "max_tokens": 8192,
        "timeout": 900,
        "models": {"strong": "opus", "fast": "sonnet"},
    },
    "ollama": {
        "url": "http://127.0.0.1:11434",
        "timeout": 900,
        "models": {"strong": "qwen2.5:7b", "fast": "qwen2.5vl:7b"},
    },
}

# Nom de backend -> (cle de sa table de reglages dans [llm], fabrique).
_BACKENDS: dict[str, tuple[str, Callable[[dict[str, Any]], Backend]]] = {
    "claude-cli": ("claude_cli", ClaudeCLIBackend),
    "claude-api": ("claude_api", ClaudeAPIBackend),
    "ollama": ("ollama", OllamaBackend),
}

_override: Backend | None = None
# Chemin par defaut de usage_log_path pour ask() dans ce bloc (usage_log()) ;
# variable de module ordinaire (pas une contextvar) : visible telle quelle
# depuis un thread lance pendant le bloc, cf. usage_log().
_usage_log_path: Path | None = None


def _deep_merge(base: dict[str, Any], top: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in top.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _settings(config: Any) -> dict[str, Any]:
    if config is None:
        from clipper.config import load_config

        config = load_config()
    return _deep_merge(CONFIG_DEFAULTS, config.section("llm"))


def _resolve(usage: str, settings: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    """(backend name, model, backend settings) for this usage."""
    entry = settings.get("usages", {}).get(usage, {})
    unknown = set(entry) - {"backend", "model"}
    if unknown:
        raise LLMError(f"[llm.usages.{usage}] : cle(s) inconnue(s) {sorted(unknown)}")
    name = entry.get("backend", settings["backend"])
    if name not in _BACKENDS:
        raise LLMError(f"backend LLM inconnu {name!r} (attendu : {' | '.join(_BACKENDS)})")
    key, _ = _BACKENDS[name]
    backend_settings = settings.get(key, {})
    wanted = entry.get("model", DEFAULT_TIER)
    model = backend_settings.get("models", {}).get(wanted, wanted)
    return name, model, backend_settings


def _with_schema_instruction(prompt: str, schema: dict[str, Any]) -> str:
    return (
        f"{prompt}\n\n"
        "Reponds uniquement avec un JSON conforme a ce schema JSON, sans texte "
        f"ni balise autour :\n{json.dumps(schema, ensure_ascii=False)}"
    )


def _with_repair_instruction(prompt: str, refused: str, error: SchemaError) -> str:
    return (
        f"{prompt}\n\n"
        "## Ta reponse precedente a ete refusee\n"
        f"Reponse refusee :\n{refused}\n\n"
        f"Erreur : {error}\n\n"
        "Corrige-la : renvoie la reponse complete, conforme au schema et sans "
        "cette erreur, uniquement le JSON."
    )


def _accept(text: str, schema: dict[str, Any], check: Callable[[Any], None] | None) -> Any:
    value = parse_json(text)
    validate(value, schema)
    if check is not None:
        check(value)
    return value


# Plusieurs threads (etape subtitles, clips en parallele) peuvent journaliser
# en meme temps sur le meme fichier : sans verrou, deux open(mode="a") +
# write() concurrents entrelacent leurs lignes (fichier JSONL corrompu).
_log_lock = threading.Lock()


def _log_line(log_path: Path, entry: dict[str, Any]) -> None:
    line = json.dumps(entry, ensure_ascii=False) + "\n"
    with _log_lock:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line)


_USAGE_FIELDS = ("input_tokens", "output_tokens", "cache_read_tokens", "cost_usd")


def _call_backend(backend: Backend, request: LLMRequest) -> tuple[str, float, Usage]:
    log.debug(
        "llm %s : appel modele %s, prompt %d caracteres, %d image(s)",
        request.usage, request.model, len(request.prompt), len(request.images),
    )
    start = time.monotonic()
    text = backend.complete(request)
    duration = time.monotonic() - start
    usage = getattr(backend, "last_usage", None)
    return text, duration, usage if isinstance(usage, Usage) else Usage()


def _fmt_usage(usage: Usage) -> str:
    def fmt(value: Any) -> str:
        return "?" if value is None else str(value)

    cost = f"{usage.cost_usd:.4f}$" if usage.cost_usd is not None else "?"
    return f"tokens entree={fmt(usage.input_tokens)} sortie={fmt(usage.output_tokens)} cache={fmt(usage.cache_read_tokens)} cout={cost}"


def _log_call(usage: str, model: str, status: str, call_usage: Usage, duration: float) -> None:
    """Une ligne par appel LLM (done_criteria de TASK-8abc) : usage, modele,
    tokens entree/sortie/cache, cout, duree, et l'issue de cet appel precis
    (reussi, reessai avant reparation, ou echec definitif)."""
    log.info(
        "llm %s : modele %s, %s (%s), duree %.1fs", usage, model, status, _fmt_usage(call_usage), duration,
    )


def _accumulate(totals: dict[str, float | int | None], usage: Usage) -> None:
    for field_name in _USAGE_FIELDS:
        value = getattr(usage, field_name)
        if value is not None:
            totals[field_name] = value if totals[field_name] is None else totals[field_name] + value


def _usage_entry(usage: str, model: str, totals: dict[str, float | int | None], duration_s: float) -> dict[str, Any]:
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "usage": usage,
        "model": model,
        **totals,
        "duration_s": duration_s,
    }


def ask(
    usage: str,
    prompt: str,
    images: Sequence[str | Path],
    schema: dict[str, Any],
    *,
    config: Any = None,
    check: Callable[[Any], None] | None = None,
    log_path: Path | None = None,
    usage_log_path: Path | None = None,
    cache_prefix: str | None = None,
) -> Any:
    """Ask the model configured for ``usage`` and return its JSON answer,
    validated against ``schema`` then by ``check`` (which raises SchemaError
    to refuse it). A refused answer is sent back to the same model with the
    error, ``[llm] repair_attempts`` times at most. ``config`` defaults to
    load_config(). When ``log_path`` is given, every refused answer appends a
    JSON line to it (timestamp, usage, model, attempt number, raw refused
    text, exact error), and an answer accepted after repair adds a final
    ``accepted: true`` line; an answer accepted on the first try is never
    logged. When ``usage_log_path`` is given, this call (successful or
    finally refused) appends one JSON line to it once it is done: usage,
    model, input_tokens, output_tokens, cache_read_tokens, cost_usd (summed
    over every backend call this ask() made, including repairs ; null for a
    field no call reported), duration_s (wall time summed over those calls).
    Without ``usage_log_path``, the default set by an enclosing ``usage_log()``
    block (if any) is used instead; with neither, nothing is written.
    ``cache_prefix``, when given, must be a prefix of ``prompt`` (else
    LLMError, ADR-ad2e) shared with other calls: forwarded to the backend as
    LLMRequest.cache_prefix, for it to mark as its own cacheable block."""
    effective_usage_log_path = usage_log_path if usage_log_path is not None else _usage_log_path
    settings = _settings(config)
    name, model, backend_settings = _resolve(usage, settings)
    attempts = int(settings["repair_attempts"])
    if attempts < 0:
        raise LLMError(f"[llm] repair_attempts doit etre >= 0, recu {attempts}")
    if cache_prefix is not None and not prompt.startswith(cache_prefix):
        raise LLMError("cache_prefix n'est pas un prefixe de prompt")
    backend = _override if _override is not None else _BACKENDS[name][1](backend_settings)
    request = LLMRequest(
        usage=usage,
        model=model,
        prompt=_with_schema_instruction(prompt, schema),
        images=[Path(p) for p in images],
        schema=schema,
        cache_prefix=cache_prefix,
    )
    totals: dict[str, float | int | None] = dict.fromkeys(_USAGE_FIELDS)
    duration_total = 0.0
    text, duration, call_usage = _call_backend(backend, request)
    duration_total += duration
    _accumulate(totals, call_usage)
    for attempt in range(attempts + 1):
        try:
            value = _accept(text, schema, check)
        except SchemaError as error:
            if log_path is not None:
                _log_line(log_path, {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "usage": usage,
                    "model": model,
                    "attempt": attempt,
                    "response": text,
                    "error": str(error),
                })
            if attempt == attempts:
                _log_call(usage, model, "echec", call_usage, duration)
                if effective_usage_log_path is not None:
                    _log_line(effective_usage_log_path, _usage_entry(usage, model, totals, duration_total))
                raise
            _log_call(usage, model, "reessai", call_usage, duration)
            text, duration, call_usage = _call_backend(
                backend, replace(request, prompt=_with_repair_instruction(request.prompt, text, error))
            )
            duration_total += duration
            _accumulate(totals, call_usage)
            continue
        _log_call(usage, model, "reussi", call_usage, duration)
        if log_path is not None and attempt > 0:
            _log_line(log_path, {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "usage": usage,
                "model": model,
                "attempt": attempt,
                "accepted": True,
                "response": value,
            })
        if effective_usage_log_path is not None:
            _log_line(effective_usage_log_path, _usage_entry(usage, model, totals, duration_total))
        return value


@contextlib.contextmanager
def usage_log(path: Path | str) -> Iterator[None]:
    """Set the default ``usage_log_path`` for every ask() of the block that
    doesn't give its own. Not a contextvar (see the module docstring): a bare
    module global, so a thread started during the block (e.g. by
    clipper.pipeline's parallel subtitles step) sees it too."""
    global _usage_log_path
    previous, _usage_log_path = _usage_log_path, Path(path)
    try:
        yield
    finally:
        _usage_log_path = previous


@contextlib.contextmanager
def use_backend(backend: Backend) -> Iterator[Backend]:
    """Route every ask() to ``backend`` (typically a FakeBackend) inside
    the block, whatever the config says."""
    global _override
    previous, _override = _override, backend
    try:
        yield backend
    finally:
        _override = previous


@contextlib.contextmanager
def register_backend(
    name: str, factory: Callable[[dict[str, Any]], Backend], settings_key: str | None = None
) -> Iterator[None]:
    """Make ``backend = name`` valid in [llm] inside the block; the factory
    receives the [llm.<settings_key>] table (``name`` by default)."""
    previous = _BACKENDS.get(name)
    _BACKENDS[name] = (settings_key or name, factory)
    try:
        yield
    finally:
        if previous is None:
            del _BACKENDS[name]
        else:
            _BACKENDS[name] = previous
