from __future__ import annotations

import json
import os
import re
import sys
import time
import tomllib
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterator
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
    """Invalid channel name, an unknown channel referenced by name, or a
    malformed preset file."""


# Verrou de fichier inter-processus (stdlib seulement) : le worker et l'API
# web sont deux processus (ADR-4f6e) qui reecrivent les memes fichiers
# state/. Un cycle lecture-modification-ecriture se fait sous
# ``file_lock(path)``, l'ecriture elle-meme par ``atomic_write_json``.
_REPLACE_ATTEMPTS = 5
_REPLACE_DELAY_S = 0.05
_LOCK_POLL_S = 0.01


@contextmanager
def file_lock(path: str | Path) -> Iterator[None]:
    """Verrou exclusif inter-processus sur ``<path>.lock`` (fcntl.flock sous
    Linux/macOS, msvcrt.locking sous Windows), bloquant jusqu'a obtention,
    libere en sortie meme sur exception."""
    lock_path = Path(str(path) + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        if sys.platform == "win32":
            import msvcrt

            handle.seek(0)
            while True:
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    time.sleep(_LOCK_POLL_S)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def atomic_write_json(path: str | Path, data: Any) -> None:
    """Ecrit ``data`` en JSON dans un fichier temporaire du meme dossier puis
    ``os.replace`` (jamais de fichier a moitie ecrit). Sous Windows, le
    remplacement est reessaye si un lecteur tient encore le fichier ouvert."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == _REPLACE_ATTEMPTS - 1:
                tmp.unlink(missing_ok=True)
                raise
            time.sleep(_REPLACE_DELAY_S)


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
        try:
            with path.open("rb") as f:
                data = tomllib.load(f)
        except tomllib.TOMLDecodeError as exc:
            raise ChannelError(f"preset TOML invalide : {path} ({exc})") from exc
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
