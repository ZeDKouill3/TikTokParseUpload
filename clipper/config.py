from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

VALID_MODES = ("review", "auto")

DEFAULTS: dict[str, object] = {
    "mode": "review",
    "workspace_dir": "workspace",
    "output_dir": "output",
}


class ConfigError(Exception):
    """config.toml is missing, malformed, or holds an unknown/invalid key."""


@dataclass(frozen=True)
class Config:
    mode: str
    workspace_dir: Path
    output_dir: Path

    def __post_init__(self) -> None:
        if self.mode not in VALID_MODES:
            raise ConfigError(
                f"mode invalide: {self.mode!r} (attendu: {' | '.join(VALID_MODES)})"
            )


def load_config(path: str | Path = "config.toml") -> Config:
    path = Path(path)
    data: dict[str, object] = {}
    if path.exists():
        with path.open("rb") as f:
            data = tomllib.load(f)

    unknown = set(data) - set(DEFAULTS)
    if unknown:
        raise ConfigError(f"cle(s) de config inconnue(s): {', '.join(sorted(unknown))}")

    merged = {**DEFAULTS, **data}
    return Config(
        mode=merged["mode"],
        workspace_dir=Path(merged["workspace_dir"]),
        output_dir=Path(merged["output_dir"]),
    )
