from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

import yt_dlp

CONFIG_DEFAULTS: dict[str, object] = {
    "cookies_file": None,
    "cookies_from_browser": None,
}

# meilleure qualite jusqu'a 1080p, conteneur mp4 (ADR-b16b: sortie normalisee
# pour les etapes suivantes du pipeline).
_FORMAT = (
    "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]"
    "/best[height<=1080][ext=mp4]/best[height<=1080]"
)

_YOUTUBE_HOSTS = {"youtube.com", "m.youtube.com", "music.youtube.com"}


class DownloadError(Exception):
    """The URL couldn't be resolved to a video_id, or yt-dlp failed."""


def extract_video_id(url: str) -> str:
    """Pull the 11-character video id out of a YouTube URL.

    Handles youtube.com/watch?v=, youtu.be/, /shorts/ and /live/ forms
    (see TASK-4ca0's done_criteria).
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

    raise DownloadError(f"impossible d'extraire le video_id de {url!r}")


def _build_meta(info: dict[str, Any]) -> dict[str, Any]:
    return {
        "video_id": info["id"],
        "title": info.get("title"),
        "description": info.get("description"),
        "duration": info.get("duration"),
        "channel": info.get("channel") or info.get("uploader"),
        "language": info.get("language"),
        "chapters": info.get("chapters") or [],
        "heatmap": info.get("heatmap") or [],
        "sponsorblock_segments": info.get("sponsorblock_chapters") or [],
    }


def _ydl_opts(
    video_dir: Path,
    cookies_file: str | Path | None,
    cookies_from_browser: str | None,
) -> dict[str, Any]:
    opts: dict[str, Any] = {
        "format": _FORMAT,
        "merge_output_format": "mp4",
        "outtmpl": str(video_dir / "%(id)s.%(ext)s"),
        "postprocessors": [{"key": "SponsorBlock", "categories": ["all"]}],
        "quiet": True,
        "noprogress": True,
    }
    if cookies_file:
        opts["cookiefile"] = str(cookies_file)
    if cookies_from_browser:
        opts["cookiesfrombrowser"] = (cookies_from_browser,)
    return opts


def download(
    url: str,
    workspace_dir: str | Path = "workspace",
    *,
    cookies_file: str | Path | None = None,
    cookies_from_browser: str | None = None,
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

    video_dir.mkdir(parents=True, exist_ok=True)
    opts = _ydl_opts(video_dir, cookies_file, cookies_from_browser)
    with ydl_factory(opts) as ydl:
        info = ydl.extract_info(url, download=True)

    meta = _build_meta(info)
    meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta
