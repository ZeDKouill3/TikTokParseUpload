from __future__ import annotations

import re
import tomllib
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from clipper.config import Config, ConfigError, VALID_MODES, load_config, write_config

NAME_RE = re.compile(r"^[a-z0-9_-]{1,40}$")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

CONFIG_DEFAULTS: dict[str, object] = {
    "display_name": "",
    "source_url": "",
    "watch": False,
    "watch_interval_s": 1800,
    "watch_min_duration_s": 600,
    "mode": "",
    "slots": [],
    "timezone": "Europe/Paris",
    "tiktok_account": "",
    "logo": "",
}


class ChannelError(Exception):
    """Invalid channel name, or an unknown channel referenced by name."""


def _preset_path(presets_dir: str | Path, name: str) -> Path:
    return Path(presets_dir) / f"{name}.toml"


def _validate_name(name: str) -> None:
    if not NAME_RE.match(name):
        raise ChannelError(
            f"nom de chaine invalide : {name!r} (attendu ^[a-z0-9_-]{{1,40}}$)"
        )


def list_channels(presets_dir: str | Path) -> list[str]:
    """Preset names under presets_dir that declare a [channel] table,
    sorted by name. A preset without [channel] stays a valid CLI preset and
    is skipped, its name never checked (SPEC-fc0c 1.4)."""
    names = []
    for path in Path(presets_dir).glob("*.toml"):
        with path.open("rb") as f:
            data = tomllib.load(f)
        if "channel" in data:
            name = path.stem
            _validate_name(name)
            names.append(name)
    return sorted(names)


def _validate_slots(slots: list[object]) -> None:
    for slot in slots:
        day = slot.get("day") if isinstance(slot, dict) else None
        time_str = slot.get("time") if isinstance(slot, dict) else None
        if day not in _DAYS or not isinstance(time_str, str) or not _TIME_RE.match(time_str):
            raise ConfigError(f"creneau invalide dans [channel].slots : {slot!r}")


def load_channel(
    name: str,
    *,
    presets_dir: str | Path = "presets",
    base: str | Path = "config.toml",
) -> tuple[Config, dict[str, object]]:
    """The merged Config (preset over base) and the validated [channel]
    dict: display_name defaults to the channel name, mode defaults to the
    global config mode (SPEC-fc0c 1.3)."""
    _validate_name(name)
    path = _preset_path(presets_dir, name)
    if not path.exists():
        raise ChannelError(f"chaine inconnue : {name!r}")

    config = load_config(path, base=base)
    channel = dict(config.section("channel"))

    if not channel["display_name"]:
        channel["display_name"] = name

    _validate_slots(channel["slots"])

    if not channel["mode"]:
        channel["mode"] = config.mode
    elif channel["mode"] not in VALID_MODES:
        raise ConfigError(
            f"mode invalide dans [channel] de {name!r}: {channel['mode']!r} "
            f"(attendu: {' | '.join(VALID_MODES)})"
        )

    return config, channel


def save_channel(
    name: str,
    data: dict[str, object],
    *,
    presets_dir: str | Path = "presets",
    base: str | Path = "config.toml",
) -> None:
    """Serialize data (the full preset, e.g. {"channel": {...}}) and replace
    the preset file, via config.write_config: reread and validated against
    base first, an invalid file is left intact (SPEC-fc0c 1.5)."""
    _validate_name(name)
    write_config(_preset_path(presets_dir, name), data, base=base)


def delete_channel(name: str, *, presets_dir: str | Path = "presets") -> None:
    _validate_name(name)
    path = _preset_path(presets_dir, name)
    if not path.exists():
        raise ChannelError(f"chaine inconnue : {name!r}")
    path.unlink()


def next_slots(channel: dict[str, object], after: datetime, n: int) -> list[datetime]:
    """The n next slot datetimes strictly after `after`, in the channel's
    timezone, chronologically sorted."""
    slots = channel["slots"]
    if n <= 0 or not slots:
        return []

    tz = ZoneInfo(str(channel["timezone"]))
    after_local = after.astimezone(tz) if after.tzinfo is not None else after.replace(tzinfo=tz)

    weeks_needed = n // len(slots) + 2
    candidates: list[datetime] = []
    for slot in slots:
        day_idx = _DAYS.index(slot["day"])
        hour, minute = (int(part) for part in slot["time"].split(":"))
        delta_to_day = (day_idx - after_local.weekday()) % 7
        for week in range(weeks_needed):
            candidate = (after_local + timedelta(days=delta_to_day + 7 * week)).replace(
                hour=hour, minute=minute, second=0, microsecond=0
            )
            if candidate > after_local:
                candidates.append(candidate)

    candidates.sort()
    return candidates[:n]
