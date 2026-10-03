from __future__ import annotations

import importlib
import time
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import tomli_w

VALID_MODES = ("review", "auto")

_REPLACE_ATTEMPTS = 5
_REPLACE_DELAY_S = 0.05

DEFAULTS: dict[str, object] = {
    "mode": "review",
    "workspace_dir": "workspace",
    "output_dir": "output",
}


class ConfigError(Exception):
    """config.toml is missing, malformed, or holds an unknown/invalid key."""


def _section_defaults(name: str) -> dict[str, object]:
    """Import clipper.<name> on demand and return its CONFIG_DEFAULTS.

    There is no central list of valid sections: any module under clipper/
    that declares a CONFIG_DEFAULTS dict can be configured through a [name]
    table in config.toml.
    """
    target = f"clipper.{name}"
    try:
        module = importlib.import_module(target)
    except ImportError as exc:
        if exc.name is not None and exc.name != target:
            raise ConfigError(
                f"section [{name}] : clipper.{name} ne peut pas etre importe, "
                f"dependance manquante : {exc.name}"
            ) from exc
        raise ConfigError(f"section [{name}] : pas de module clipper.{name}") from exc

    defaults = getattr(module, "CONFIG_DEFAULTS", None)
    if not isinstance(defaults, dict):
        raise ConfigError(
            f"section [{name}] : clipper.{name} ne declare pas CONFIG_DEFAULTS"
        )
    return defaults


def _section_legacy_keys(name: str) -> tuple[str, ...]:
    """Cles qu'une section n'a plus mais tolere encore dans un fichier (LEGACY_KEYS du module, optionnel) :
    ignorees a la lecture, le module qui les declare les signale et les retire."""
    _section_defaults(name)
    return tuple(getattr(importlib.import_module(f"clipper.{name}"), "LEGACY_KEYS", ()))


def _validate_section(name: str, table: dict[str, object]) -> None:
    defaults = _section_defaults(name)
    unknown = set(table) - set(defaults) - set(_section_legacy_keys(name))
    if unknown:
        raise ConfigError(
            f"cle(s) inconnue(s) dans la section [{name}]: {', '.join(sorted(unknown))}"
        )


@dataclass(frozen=True)
class Config:
    mode: str
    workspace_dir: Path
    output_dir: Path
    _sections: dict[str, dict[str, object]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.mode not in VALID_MODES:
            raise ConfigError(
                f"mode invalide: {self.mode!r} (attendu: {' | '.join(VALID_MODES)})"
            )

    def section(self, name: str) -> dict[str, object]:
        """CONFIG_DEFAULTS of clipper.<name> merged with the [name] table
        from config.toml (defaults only if the table is absent). Nested
        values (tables under [name]) are passed through unchanged."""
        defaults = _section_defaults(name)
        legacy = _section_legacy_keys(name)
        table = {k: v for k, v in self._sections.get(name, {}).items() if k not in legacy}
        return {**defaults, **table}


_UNSET = object()


def _parse_toml_file(path: Path, *, required: bool) -> dict[str, object]:
    if path.exists():
        with path.open("rb") as f:
            return tomllib.load(f)
    if required:
        raise ConfigError(f"fichier de config introuvable : {path}")
    return {}


def _merge_raw(base: dict[str, object], preset: dict[str, object]) -> dict[str, object]:
    """Merge preset over base: flat keys merged, then each section merged
    key by key (preset wins). A nested sub-table is a single value under its
    key, so it is replaced wholesale, never merged further."""
    base_flat = {k: v for k, v in base.items() if not isinstance(v, dict)}
    base_sections = {k: v for k, v in base.items() if isinstance(v, dict)}
    preset_flat = {k: v for k, v in preset.items() if not isinstance(v, dict)}
    preset_sections = {k: v for k, v in preset.items() if isinstance(v, dict)}

    merged_flat = {**base_flat, **preset_flat}
    merged_sections = {k: dict(v) for k, v in base_sections.items()}
    for name, table in preset_sections.items():
        merged_sections[name] = {**merged_sections.get(name, {}), **table}

    return {**merged_flat, **merged_sections}


def load_config(
    path: str | Path | object = _UNSET, *, base: str | Path | None = None
) -> Config:
    explicit = path is not _UNSET
    path = Path(path) if explicit else Path("config.toml")
    data = _parse_toml_file(path, required=explicit)

    if base is not None:
        base_data = _parse_toml_file(Path(base), required=True)
        data = _merge_raw(base_data, data)

    flat = {k: v for k, v in data.items() if not isinstance(v, dict)}
    sections = {k: v for k, v in data.items() if isinstance(v, dict)}

    unknown_flat = set(flat) - set(DEFAULTS)
    if unknown_flat:
        raise ConfigError(f"cle(s) de config inconnue(s): {', '.join(sorted(unknown_flat))}")

    for name, table in sections.items():
        _validate_section(name, table)

    merged = {**DEFAULTS, **flat}
    return Config(
        mode=merged["mode"],
        workspace_dir=Path(merged["workspace_dir"]),
        output_dir=Path(merged["output_dir"]),
        _sections=sections,
    )


def _atomic_replace(tmp: Path, path: Path) -> None:
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            tmp.replace(path)
            return
        except PermissionError:
            if attempt == _REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(_REPLACE_DELAY_S)


def write_config(
    path: str | Path, data: dict[str, object], *, base: str | Path | None = None
) -> None:
    """Serialize data to TOML, reread it through load_config with the same
    base to validate it, then replace path atomically. A ConfigError leaves
    the original file untouched and propagates (ADR-ad2e: no silent
    fallback)."""
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(tomli_w.dumps(data), encoding="utf-8")
    try:
        if base is not None:
            load_config(tmp, base=base)
        else:
            load_config(tmp)
    except ConfigError:
        tmp.unlink(missing_ok=True)
        raise
    _atomic_replace(tmp, path)
