"""Seul point d'appel a un LLM dans clipper (ADR-b1c1).

    from clipper import llm
    data = llm.ask("moments", prompt, [frame1, frame2], SCHEMA)

``ask`` choisit backend et modele d'apres la section [llm] de config.toml
pour cet usage, ajoute au prompt la consigne de repondre en JSON conforme a
``schema``, puis valide la reponse : JSON invalide ou non conforme leve
SchemaError, quota/reseau/surcharge leve TransientLLMError, le reste
LLMError. Seuls du texte et des images fixes (fichiers) sont envoyes.

Backends : ``claude-cli`` (defaut, voir clipper.llm.claude_cli pour la facon
dont ``claude -p`` recoit les images), ``claude-api``, ``ollama``. Pour les
tests des autres etapes : ``clipper.llm.fake.FakeBackend`` et
``llm.use_backend(fake)``.

Configuration (fusionnee en profondeur avec CONFIG_DEFAULTS) :

    [llm]
    backend = "claude-cli"

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
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Any

from clipper.llm.backend import Backend, LLMRequest
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
    "use_backend",
]

DEFAULT_TIER = "fast"

CONFIG_DEFAULTS: dict[str, object] = {
    "backend": "claude-cli",
    # Modele fort pour le jugement lourd (moments, coupes), rapide ailleurs.
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


def ask(
    usage: str,
    prompt: str,
    images: Sequence[str | Path],
    schema: dict[str, Any],
    *,
    config: Any = None,
) -> Any:
    """Ask the model configured for ``usage`` and return its JSON answer,
    validated against ``schema``. ``config`` defaults to load_config()."""
    settings = _settings(config)
    name, model, backend_settings = _resolve(usage, settings)
    backend = _override if _override is not None else _BACKENDS[name][1](backend_settings)
    request = LLMRequest(
        usage=usage,
        model=model,
        prompt=_with_schema_instruction(prompt, schema),
        images=[Path(p) for p in images],
        schema=schema,
    )
    value = parse_json(backend.complete(request))
    validate(value, schema)
    return value


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
