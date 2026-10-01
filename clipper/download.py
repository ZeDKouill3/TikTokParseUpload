from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

import yt_dlp

from clipper import browser

log = logging.getLogger(__name__)

CONFIG_DEFAULTS: dict[str, object] = {
    "cookies_file": None,
    "cookies_from_browser": None,
    # Compte (state/browser/<compte>/) dont les cookies YouTube sont exportes vers un
    # cookies.txt pour yt-dlp ; reglé, il remplace cookies_from_browser (SPEC-9225 R8).
    "cookies_profile": "",
    "js_runtimes": "node",
}

# meilleure qualite jusqu'a 1080p, conteneur mp4 (ADR-b16b: sortie normalisee
# pour les etapes suivantes du pipeline).
_FORMAT = (
    "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]"
    "/best[height<=1080][ext=mp4]/best[height<=1080]"
)

_YOUTUBE_HOSTS = {"youtube.com", "m.youtube.com", "music.youtube.com"}
_TWITCH_HOSTS = {"twitch.tv"}
_TWITCH_VOD_PATH = re.compile(r"/videos/(\d+)/?$")


class DownloadError(Exception):
    """The URL couldn't be resolved to a video_id, or yt-dlp failed."""


def extract_video_id(url: str) -> str:
    """Pull the video id out of a YouTube or Twitch URL.

    Handles youtube.com/watch?v=, youtu.be/, /shorts/ and /live/ forms
    (see TASK-4ca0's done_criteria), and Twitch VOD URLs
    (twitch.tv/videos/<chiffres>, see TASK-9290's done_criteria). The Twitch
    id is returned exactly as yt-dlp assigns it (prefixe 'v', ex.
    v2887271276) : jamais un id YouTube de 11 caracteres, pas de collision
    possible entre les deux espaces d'id.
    """
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[len("www.") :]

    if host == "youtu.be":
        video_id = parsed.path.strip("/").split("/")[0]
        if video_id:
            return video_id

    if host in _YOUTUBE_HOSTS:
        if parsed.path == "/watch":
            values = parse_qs(parsed.query).get("v")
            if values:
                return values[0]
        for prefix in ("/shorts/", "/live/"):
            if parsed.path.startswith(prefix):
                video_id = parsed.path[len(prefix) :].strip("/").split("/")[0]
                if video_id:
                    return video_id

    if host in _TWITCH_HOSTS:
        match = _TWITCH_VOD_PATH.match(parsed.path)
        if match:
            return f"v{match.group(1)}"
        raise DownloadError(
            f"Twitch : seules les VOD (twitch.tv/videos/<id>) sont prises en charge, "
            f"pas les chaines, clips ou lives ({url!r})"
        )

    raise DownloadError(f"impossible d'extraire le video_id de {url!r}")


def _build_meta(info: dict[str, Any], url: str) -> dict[str, Any]:
    return {
        "video_id": info["id"],
        # info["webpage_url"] est la source de verite (yt-dlp la renseigne
        # toujours) ; l'URL demandee est un repli honnete si un extracteur ne
        # la fournit pas, jamais une URL reconstruite a partir du video_id
        # (ADR-ad2e : celle-ci suppose YouTube, fausse pour une VOD Twitch).
        "webpage_url": info.get("webpage_url") or url,
        "title": info.get("title"),
        "description": info.get("description"),
        "duration": info.get("duration"),
        "channel": info.get("channel") or info.get("uploader"),
        "language": info.get("language"),
        "chapters": info.get("chapters") or [],
        "heatmap": info.get("heatmap") or [],
        "sponsorblock_segments": info.get("sponsorblock_chapters") or [],
    }


def _format_speed(bytes_per_second: float | None) -> str:
    if not bytes_per_second:
        return "?"
    return f"{bytes_per_second / 1_000_000:.1f} Mo/s"


def _progress_hook(video_id: str) -> Callable[[dict[str, Any]], None]:
    """Journalise la progression du telechargement (pourcentage, debit) :
    DEBUG a chaque evenement yt-dlp, INFO au plus toutes les 30 s ou tous les
    10 % (done_criteria de TASK-8abc)."""
    last: dict[str, float] = {"pct": 0.0, "t": time.monotonic()}

    def hook(d: dict[str, Any]) -> None:
        if d.get("status") != "downloading":
            return
        total = d.get("total_bytes") or d.get("total_bytes_estimate")
        downloaded = d.get("downloaded_bytes")
        speed = _format_speed(d.get("speed"))
        if not total or downloaded is None:
            log.debug("%s : telechargement, %s octets telecharges (%s)", video_id, downloaded, speed)
            return
        pct = downloaded / total * 100
        log.debug("%s : telechargement %.1f%% (%s)", video_id, pct, speed)
        now = time.monotonic()
        if pct >= 100.0 - 1e-9 or pct - last["pct"] >= 10.0 or now - last["t"] >= 30.0:
            last["pct"], last["t"] = pct, now
            log.info("%s : telechargement %.1f%% (%s)", video_id, pct, speed)

    return hook


def _ydl_opts(
    video_dir: Path,
    cookies_file: str | Path | None,
    cookies_from_browser: str | None,
    js_runtimes: str | None,
    video_id: str,
) -> dict[str, Any]:
    opts: dict[str, Any] = {
        "format": _FORMAT,
        "merge_output_format": "mp4",
        "outtmpl": str(video_dir / "%(id)s.%(ext)s"),
        "postprocessors": [{"key": "SponsorBlock", "categories": ["all"]}],
        "quiet": True,
        "noprogress": True,
        "progress_hooks": [_progress_hook(video_id)],
    }
    if cookies_file:
        opts["cookiefile"] = str(cookies_file)
    if cookies_from_browser:
        opts["cookiesfrombrowser"] = (cookies_from_browser,)
    if js_runtimes:
        # yt-dlp doit resoudre les challenges JS (nsig) pour signer les URLs
        # des formats video/audio ; sans, YouTube renvoie 403 au telechargement.
        opts["js_runtimes"] = {js_runtimes: {}}
    return opts


def download(
    url: str,
    workspace_dir: str | Path = "workspace",
    *,
    cookies_file: str | Path | None = None,
    cookies_from_browser: str | None = None,
    cookies_profile: str | None = "",
    js_runtimes: str | None = "node",
    ydl_factory: Callable[[dict[str, Any]], Any] = yt_dlp.YoutubeDL,
) -> dict[str, Any]:
    """Download a YouTube video and write its metadata (ADR-b16b: a step
    reads its inputs and writes workspace/<video_id>/ itself).

    A video already present (video file and meta.json both on disk) is not
    re-downloaded; the recorded meta.json is returned as-is instead.
    """
    video_id = extract_video_id(url)
    video_dir = Path(workspace_dir) / video_id
    meta_file = video_dir / "meta.json"
    video_file = video_dir / f"{video_id}.mp4"

    if meta_file.exists() and video_file.exists():
        return json.loads(meta_file.read_text(encoding="utf-8"))

    if cookies_profile:
        if cookies_file:
            raise DownloadError(
                "[download] cookies_profile et cookies_file sont tous deux regles : "
                "yt-dlp ne lit qu'un fichier de cookies, retire l'un des deux"
            )
        try:
            cookies_file = browser.export_cookies(cookies_profile)
        except browser.BrowserError as exc:
            raise DownloadError(f"cookies du profil {cookies_profile!r} : {exc}") from exc
        cookies_from_browser = None  # le profil prime sur la lecture des cookies d'un navigateur

    video_dir.mkdir(parents=True, exist_ok=True)
    opts = _ydl_opts(video_dir, cookies_file, cookies_from_browser, js_runtimes, video_id)
    with ydl_factory(opts) as ydl:
        info = ydl.extract_info(url, download=True)

    meta = _build_meta(info, url)
    meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta
