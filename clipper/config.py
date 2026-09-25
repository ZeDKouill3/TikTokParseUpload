from __future__ import annotations

import importlib
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

VALID_MODES = ("review", "auto")

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


def _validate_section(name: str, table: dict[str, object]) -> None:
    defaults = _section_defaults(name)
    unknown = set(table) - set(defaults)
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
        table = self._sections.get(name, {})
        return {**defaults, **table}


def load_config(path: str | Path = "config.toml") -> Config:
    path = Path(path)
    data: dict[str, object] = {}
    if path.exists():
        with path.open("rb") as f:
            data = tomllib.load(f)

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
