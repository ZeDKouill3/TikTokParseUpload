"""Construction de l'application FastAPI de clipper/web (voir le docstring
du paquet). Appelee par ``python -m clipper serve`` et par les tests
(clipper.web.app.create_app avec un pipeline/worker simules).

ADR-4f6e §1 : cette API n'appelle jamais pipeline.run/render dans son propre
processus ; le traitement passe toujours par la file (clipper.worker)."""

from __future__ import annotations

import ast
import asyncio
import csv
import importlib
import inspect
import json
import os
import re
import tempfile
import tomllib
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from email.parser import BytesParser
from email.policy import HTTP as _EMAIL_HTTP
from typing import Any, AsyncIterator
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse as _PlainJSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from clipper import channel as channel_mod
from clipper import gpu as gpu_mod
from clipper import outcomes as outcomes_mod
from clipper import pipeline
from clipper import publish as publish_mod
from clipper import reframe as reframe_mod
from clipper import watch as watch_mod
from clipper import worker as worker_mod
from clipper.config import (
    DEFAULTS as _CONFIG_FLAT_DEFAULTS,
    VALID_MODES,
    Config,
    ConfigError,
    _section_defaults,
    load_config,
    write_config,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"
# Video/clip ids sont soit des ids YouTube (11 caracteres alphanumeriques),
# soit des clip_id du pipeline (ex. "03-p2") : jamais de '/' ni de '..' pour
# empecher toute traversee de chemin dans /media.
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")

_LOOPBACK_HOST = "127.0.0.1"
_PRESETS_DIR = "presets"
_PROTECTED_PREFIXES = ("/api", "/media")
_TOKEN_HEADER = "x-clipper-token"
_TOKEN_COOKIE = "clipper_token"


class WebConfigError(Exception):
    """[web] host hors bouclage sans jeton configure (ADR-4f6e §5, ADR-ad2e :
    jamais d'exposition silencieuse)."""


_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def _strip_ansi(value: Any) -> Any:
    """Retire les sequences ANSI (couleurs de yt-dlp...) de toute chaine d'une
    structure JSON : l'interface affiche du texte, jamais des codes terminal."""
    if isinstance(value, str):
        return _ANSI_RE.sub("", value)
    if isinstance(value, list):
        return [_strip_ansi(v) for v in value]
    if isinstance(value, dict):
        return {k: _strip_ansi(v) for k, v in value.items()}
    return value


class JSONResponse(_PlainJSONResponse):
    """Toute reponse JSON de l'API (raisons d'echec, journal, erreurs) sort
    sans sequence ANSI."""

    def render(self, content: Any) -> bytes:
        return super().render(_strip_ansi(content))


def _safe_video_file(directory: Path, name: str) -> Path:
    if not _SAFE_ID.fullmatch(name):
        raise HTTPException(status_code=404, detail=f"identifiant invalide : {name!r}")
    path = directory / f"{name}.mp4"
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"fichier introuvable : {path}")
    return path


def _list_states(config: Config) -> list[dict[str, Any]]:
    root = Path(config.workspace_dir)
    if not root.is_dir():
        return []
    states = []
    for path in sorted(root.glob(f"*/{pipeline.STATE_FILE}")):
        states.append(json.loads(path.read_text(encoding="utf-8")))
    return states


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _source_duration(video_dir: Path) -> tuple[float | None, str | None]:
    """Duree de la source (meta.json de l'etape download) ; sinon (None, raison)
    : une donnee introuvable est affichee, jamais remplacee par une valeur."""
    path = video_dir / "meta.json"
    if not path.exists():
        return None, f"{path} absent : le telechargement n'est pas termine"
    duration = _read_json(path).get("duration")
    if not isinstance(duration, (int, float)) or duration <= 0:
        return None, f"duree de la source inconnue dans {path}"
    return duration, None


def _moment_transcript(video_dir: Path, start: float, end: float) -> tuple[str | None, str | None]:
    """Texte du moment via pipeline._moment_text (pas de logique dupliquee) ;
    sinon (None, raison)."""
    path = video_dir / "transcript.json"
    if not path.exists():
        return None, f"{path} absent : la transcription n'est pas faite"
    return pipeline._moment_text(video_dir, start, end), None
# Statuts valides d'une video (contrat pipeline.json) : un filtre hors de cette
# liste est une erreur, jamais une liste vide silencieuse (ADR-ad2e).
_VIDEO_STATUSES = ("pending", "running", "awaiting_review", "queued", "done", "failed")


def _parse_ts(video_id: str, step: str, key: str, value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"horodatage illisible ({key}) pour l'etape {step} de {video_id} : {value!r}",
        ) from exc


def _step_durations(state: dict[str, Any]) -> dict[str, float | None]:
    """Duree (s) de chaque etape = finished_at - started_at ; None tant que
    l'etape n'a pas fini (aucune duree inventee)."""
    out: dict[str, float | None] = {}
    for name, step in (state.get("steps") or {}).items():
        started, finished = step.get("started_at"), step.get("finished_at")
        if started and finished:
            video_id = state.get("video_id", "?")
            delta = _parse_ts(video_id, name, "finished_at", finished) - _parse_ts(video_id, name, "started_at", started)
            out[name] = delta.total_seconds()
        else:
            out[name] = None
    return out


def _current_step(state: dict[str, Any]) -> str | None:
    steps = state.get("steps") or {}
    for name, step in steps.items():
        if step.get("status") == "running":
            return name
    for name, step in steps.items():
        if step.get("status") != "done":
            return name
    return None


def _enrich(state: dict[str, Any], config: Config) -> dict[str, Any]:
    """Etat pipeline.json + titre (meta.json de download, sinon l'identifiant
    avec la raison), etape courante et duree par etape."""
    video_id = state["video_id"]
    out = dict(state)
    meta_path = Path(config.workspace_dir) / video_id / "meta.json"
    title = None
    if meta_path.exists():
        title = _read_json(meta_path).get("title")
        reason = None if title else f"meta.json de {video_id} sans titre"
    else:
        reason = f"titre inconnu : meta.json absent pour {video_id} (telechargement pas encore fait)"
    out["title"] = title or video_id
    out["title_reason"] = reason
    out["current_step"] = _current_step(state)
    out["durations"] = _step_durations(state)
    return out


def _matches(video: dict[str, Any], channel: str | None, status: str | None, q: str | None) -> bool:
    if channel is not None and video.get("channel") != channel:
        return False
    if status is not None and video.get("status") != status:
        return False
    if q:
        needle = q.lower()
        haystack = (video["video_id"], video["title"], video.get("source_url") or "")
        if not any(needle in text.lower() for text in haystack):
            return False
    return True


def _list_moments(config: Config, video_id: str) -> list[dict[str, Any]]:
    video_dir = Path(config.workspace_dir) / video_id
    parts_path = video_dir / "parts.json"
    if not parts_path.exists():
        raise HTTPException(status_code=404, detail=f"pas de moments a valider pour {video_id}")

    parts_by_id = {m["id"]: m for m in _read_json(parts_path)["moments"]}
    moments_path = video_dir / "moments.json"
    scores_by_id = {m["id"]: m for m in _read_json(moments_path)["moments"]} if moments_path.exists() else {}
    review_path = video_dir / "review.json"
    decisions = _read_json(review_path)["decisions"] if review_path.exists() else {}

    source_duration, duration_error = _source_duration(video_dir)

    out = []
    for moment_id, part in sorted(parts_by_id.items()):
        scored = scores_by_id.get(moment_id, {})
        transcript, transcript_error = _moment_transcript(video_dir, part["start"], part["end"])
        out.append({
            "id": moment_id,
            "start": part["start"],
            "end": part["end"],
            "duration": part["duration"],
            "format": part["format"],
            "parts_total": part["parts_total"],
            "score": scored.get("final_score"),
            "justification": scored.get("justification"),
            "hook_text": scored.get("hook_text"),
            "decision": decisions.get(str(moment_id)),
            "preview_url": f"/media/source/{video_id}",
            "transcript": transcript,
            "transcript_error": transcript_error,
            "source_duration": source_duration,
            "source_duration_error": duration_error,
        })
    return out


def _validate_video_id(video_id: str) -> None:
    if not _SAFE_ID.fullmatch(video_id):
        raise HTTPException(status_code=400, detail=f"identifiant video invalide : {video_id!r}")


def _validate_channel_name(channel: str) -> None:
    if not channel_mod.NAME_RE.match(channel):
        raise HTTPException(status_code=400, detail=f"nom de chaîne invalide : {channel!r}")


def _channel_of(video_id: str, config: Config) -> str | None:
    try:
        state = pipeline.load_state(video_id, config=config)
    except pipeline.PipelineError:
        return None
    return state.get("channel")


def _enqueue(url: str, channel: str | None, action: str, force_steps: list[str] | None,
             config: Config) -> JSONResponse:
    try:
        entry = worker_mod.enqueue(url, channel, action, force_steps, config=config)
    except worker_mod.WorkerError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return JSONResponse(entry, status_code=202)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _queue_path(config: Config) -> Path:
    return Path(config.section("worker")["queue_path"])


def _state_kind_and_id(path: Path, state_root: Path) -> tuple[str, str]:
    """'queue.json' directement sous state/ -> kind='queue' ; un fichier sous
    un sous-dossier (publish/<chaine>.json, watch/<chaine>.json) -> kind=nom
    du sous-dossier, id=nom de chaine."""
    rel = path.relative_to(state_root)
    if len(rel.parts) == 1:
        return path.stem, path.stem
    return rel.parts[0], path.stem


def _scan_watched(workspace_root: Path, state_root: Path) -> list[tuple[Path, str, str]]:
    found: list[tuple[Path, str, str]] = []
    if workspace_root.is_dir():
        for p in workspace_root.glob(f"*/{pipeline.STATE_FILE}"):
            found.append((p, "video", p.parent.name))
    if state_root.is_dir():
        for p in state_root.rglob("*.json"):
            kind, id_ = _state_kind_and_id(p, state_root)
            found.append((p, kind, id_))
    return found


# --------------------------------------------------------------------------
# Tableau de bord (SPEC-c100 E1, T2, T8) : lecture de fichiers seulement.
# Une donnee introuvable est null avec une cle <champ>_error en francais,
# jamais un 0 ou une liste vide muets (ADR-ad2e).
# --------------------------------------------------------------------------

_NEXT_PUBLICATIONS = 5
_COST_WEEK_DAYS = 7
_MIB = 1024 * 1024


def _fill(out: dict[str, Any], fields: tuple[str, ...], label: str, build) -> None:
    """Renseigne ``fields`` avec ``build()`` (un dict champ -> valeur) ; si la
    lecture echoue, chaque champ vaut null et ``<champ>_error`` dit pourquoi."""
    try:
        out.update(build())
    except (OSError, ValueError, KeyError, TypeError, publish_mod.PublishError) as exc:
        for name in fields:
            out[name] = None
            out[f"{name}_error"] = f"{label} illisible : {exc}"


def _dashboard_videos(config: Config) -> dict[str, Any]:
    states = _list_states(config)
    running = []
    for state in states:
        if state.get("status") != "running":
            continue
        step = _current_step(state)
        running.append({
            "video_id": state["video_id"], "channel": state.get("channel"), "source_url": state.get("source_url"),
            "step": step, "progress": state["steps"][step].get("progress") if step else None,
        })

    def problem(status: str) -> list[dict[str, Any]]:
        return [
            {"video_id": s["video_id"], "channel": s.get("channel"), "step": _current_step(s),
             "reason": s.get("reason"), "retry_at": s.get("retry_at")}
            for s in states if s.get("status") == status
        ]

    return {"running": running, "failed": problem("failed"), "queued": problem("queued")}


def _dashboard_watch(config: Config) -> dict[str, Any]:
    pending: list[dict[str, Any]] = []
    watch_dir = Path(config.section("watch")["state_dir"])
    for path in sorted(watch_dir.glob("*.json")) if watch_dir.is_dir() else []:
        try:
            pending.extend({**vod, "channel": path.stem} for vod in _read_json(path)["pending"])
        except (ValueError, KeyError, TypeError) as exc:
            raise ValueError(f"{path.name} : {exc}") from exc
    return {"watch_pending": pending}


def _dashboard_clips_to_review(config: Config) -> dict[str, Any]:
    states = _list_states(config)
    publish_dir = Path(config.section("publish")["state_dir"])
    count = 0
    for channel in {s.get("channel") for s in states}:
        if channel is None:  # sans chaine, aucun fichier de publication n'existe
            for state in (s for s in states if s.get("channel") is None):
                out_dir = Path(config.output_dir) / state["video_id"]
                count += sum(1 for p in out_dir.glob("*.json") if _read_json(p).get("ready"))
        else:
            count += len(publish_mod.list_pending(
                channel, workspace_dir=config.workspace_dir, output_dir=config.output_dir, state_dir=publish_dir))
    return {"clips_to_review": count}


def _scheduled_entries(publish_dir: Path) -> list[dict[str, Any]]:
    entries = []
    for path in sorted(publish_dir.glob("*.json")) if publish_dir.is_dir() else []:
        for entry in _read_json(path):
            for field_name in ("video_id", "clip_id", "status", "slot_at"):
                if field_name not in entry:
                    raise ValueError(f"{path.name} : champ {field_name!r} absent d'une entree")
            if entry["status"] == "scheduled" and entry["slot_at"]:
                entries.append({**entry, "channel": path.stem})
    return entries


def _dashboard_next_publications(config: Config) -> dict[str, Any]:
    entries = _scheduled_entries(Path(config.section("publish")["state_dir"]))
    entries.sort(key=lambda e: datetime.fromisoformat(e["slot_at"]).astimezone(timezone.utc))
    entries = entries[:_NEXT_PUBLICATIONS]
    for entry in entries:
        sidecar = Path(config.output_dir) / entry["video_id"] / f"{entry['clip_id']}.json"
        entry["screen_title"] = _read_json(sidecar).get("screen_title") if sidecar.is_file() else None
    return {"next_publications": entries}


def _dashboard_llm_cost(config: Config) -> dict[str, Any]:
    """Somme de workspace/*/llm_usage.jsonl : ``today`` = jour calendaire local,
    ``week`` = les 7 derniers jours locaux (aujourd'hui compris), ``by_usage`` =
    cout de la semaine par usage ; les appels sans cout rapporte sont comptes
    a part (``unreported_calls``), jamais pour 0."""
    now = datetime.now().astimezone()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=_COST_WEEK_DAYS - 1)
    cost: dict[str, Any] = {"today": 0.0, "week": 0.0, "by_usage": {}, "unreported_calls": 0}
    root = Path(config.workspace_dir)
    for path in sorted(root.glob("*/llm_usage.jsonl")) if root.is_dir() else []:
        for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not raw.strip():
                continue
            try:
                entry = json.loads(raw)
                # clipper.llm date chaque appel de "timestamp" ; "recorded_at" est la forme du contrat
                recorded = datetime.fromisoformat(entry.get("recorded_at") or entry["timestamp"]).astimezone()
                usage = entry["usage"]
            except (ValueError, KeyError, TypeError) as exc:
                raise ValueError(f"{path.parent.name}/{path.name} ligne {number} : {exc}") from exc
            if recorded < week_start or recorded > now:
                continue
            amount = entry.get("cost_usd")
            if amount is None:
                cost["unreported_calls"] += 1
                continue
            cost["week"] += amount
            cost["by_usage"][usage] = cost["by_usage"].get(usage, 0.0) + amount
            if recorded >= today_start:
                cost["today"] += amount
    return {"llm_cost": cost}


def _dashboard_hardware() -> dict[str, Any]:
    try:
        device = gpu_mod.get_device().type
    except Exception as exc:  # get_device ne leve pas en pratique ; jamais de device invente
        return {"hardware": None, "hardware_error": f"device illisible : {exc}"}
    hardware: dict[str, Any] = {"device": device, "vram_used_mb": None}
    if device != "cpu":
        try:
            hardware["vram_used_mb"] = gpu_mod.vram_used_mb()
        except gpu_mod.GpuError as exc:  # nvidia-smi absent ou illisible : indisponible, avec la raison
            hardware["vram_used_mb_error"] = f"VRAM utilisée indisponible : {exc}"
    return {"hardware": hardware}


def _dashboard(config: Config) -> dict[str, Any]:
    out: dict[str, Any] = {}
    _fill(out, ("running", "failed", "queued"), "etat des videos (workspace/*/pipeline.json)",
          lambda: _dashboard_videos(config))
    queue_path = _queue_path(config)
    _fill(out, ("queue",), f"file d'attente ({queue_path.name})",
          lambda: {"queue": _read_json(queue_path) if queue_path.exists() else []})
    _fill(out, ("watch_pending",), "surveillance (state/watch)", lambda: _dashboard_watch(config))
    _fill(out, ("clips_to_review",), "clips a valider", lambda: _dashboard_clips_to_review(config))
    _fill(out, ("next_publications",), "publications (state/publish)", lambda: _dashboard_next_publications(config))
    _fill(out, ("llm_cost",), "journal llm_usage.jsonl", lambda: _dashboard_llm_cost(config))
    out.update(_dashboard_hardware())
    return out


async def _event_stream(config: Config) -> AsyncIterator[str]:
    """Scrute workspace/*/pipeline.json et state/**/*.json par mtime,
    sans broker (ADR-4f6e §4) ; un evenement {kind, id, at} par changement,
    jamais pour l'etat deja vu a la connexion."""
    interval = float(config.section("web")["sse_poll_interval_s"])
    workspace_root = Path(config.workspace_dir)
    state_root = Path("state")
    mtimes: dict[Path, float] = {}

    for p, _kind, _id in _scan_watched(workspace_root, state_root):
        try:
            mtimes[p] = p.stat().st_mtime
        except FileNotFoundError:
            pass

    while True:
        await asyncio.sleep(interval)
        for p, kind, id_ in _scan_watched(workspace_root, state_root):
            try:
                mtime = p.stat().st_mtime
            except FileNotFoundError:
                continue
            previous = mtimes.get(p)
            if previous is None or mtime > previous:
                mtimes[p] = mtime
                event = {"kind": kind, "id": id_, "at": _now_iso()}
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


# --------------------------------------------------------------------------
# Ecran Clips (SPEC-c100 E4, T4 ; SPEC-fc0c §4.5). L'API ne touche jamais un
# mp4 ni un sidecar : le texte passe par publish.edit_caption, le rendu par la
# file (worker.enqueue). Les statuts de publication sont ceux de
# SPEC-fc0c §4 ; un clip absent du fichier de publication est « à valider ».
# --------------------------------------------------------------------------

_TO_VALIDATE = "à valider"
_CLIP_STATUSES = (_TO_VALIDATE, *publish_mod.VALID_STATUSES)
_RERENDER_STEPS = ["render", "qa"]


def _validate_clip_id(clip_id: str) -> None:
    if not _SAFE_ID.fullmatch(clip_id):
        raise HTTPException(status_code=400, detail=f"identifiant de clip invalide : {clip_id!r}")


def _publish_dir(config: Config) -> Path:
    return Path(config.section("publish")["state_dir"])


def _publish_entries(config: Config, channel: str | None) -> dict[tuple[str, str], dict[str, Any]]:
    """Entrees de state/publish/<chaine>.json par (video_id, clip_id) ; un
    fichier illisible leve une 500 en francais, jamais un statut invente."""
    if channel is None:
        return {}
    path = _publish_dir(config) / f"{channel}.json"
    if not path.is_file():
        return {}
    try:
        entries = _read_json(path)
        return {(e["video_id"], e["clip_id"]): e for e in entries}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=500, detail=f"fichier de publication illisible ({path.name}) : {exc}") from exc


def _clip_view(sidecar: dict[str, Any], channel: str | None, entry: dict[str, Any] | None) -> dict[str, Any]:
    qa = sidecar.get("qa") or {}
    video_id, clip_id = sidecar["video_id"], sidecar["clip_id"]
    clip = dict(sidecar)
    clip.update({
        "channel": channel,
        "description": sidecar.get("caption"),
        "video_url": f"/media/clip/{video_id}/{clip_id}",
        "thumbnail_url": f"/media/clip/{video_id}/{clip_id}/thumbnail",
        "qa_status": qa.get("status"),
        "issues": qa.get("issues"),
        "publish_status": entry["status"] if entry else _TO_VALIDATE,
        "slot_at": entry.get("slot_at") if entry else None,
        "publish_error": entry.get("error") if entry else None,
    })
    return clip


def _read_clip_sidecar(config: Config, video_id: str, clip_id: str) -> dict[str, Any]:
    path = Path(config.output_dir) / video_id / f"{clip_id}.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"clip introuvable : {video_id}/{clip_id}")
    try:
        return _read_json(path)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=f"sidecar illisible ({path.name}) : {exc}") from exc


def _list_clip_views(config: Config, channel: str | None, video_id: str | None,
                     status: str | None) -> list[dict[str, Any]]:
    root = Path(config.output_dir)
    if not root.is_dir():
        return []
    entries_by_channel: dict[str | None, dict[tuple[str, str], dict[str, Any]]] = {}
    clips = []
    for video_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        if video_id is not None and video_dir.name != video_id:
            continue
        video_channel = _channel_of(video_dir.name, config)
        if channel is not None and video_channel != channel:
            continue
        if video_channel not in entries_by_channel:
            entries_by_channel[video_channel] = _publish_entries(config, video_channel)
        entries = entries_by_channel[video_channel]
        for path in sorted(video_dir.glob("*.json")):
            sidecar = _read_clip_sidecar(config, video_dir.name, path.stem)
            clip = _clip_view(sidecar, video_channel, entries.get((video_dir.name, path.stem)))
            if status is None or clip["publish_status"] == status:
                clips.append(clip)
    return clips


def _require_channel(video_id: str, clip_id: str, config: Config) -> str:
    channel = _channel_of(video_id, config)
    if channel is None:
        raise HTTPException(
            status_code=409,
            detail=f"la vidéo {video_id} n'a pas de chaîne : publier {clip_id} demande une chaîne (presets/<chaîne>.toml)",
        )
    return channel


def _enqueue_clip_render(video_id: str, config: Config) -> dict[str, Any]:
    try:
        return worker_mod.enqueue(video_id, _channel_of(video_id, config), "render", list(_RERENDER_STEPS), config=config)
    except worker_mod.WorkerError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


# --------------------------------------------------------------------------
# Ecran Chaines (SPEC-c100 E5, SPEC-fc0c §1) : un preset de chaine est un
# fichier presets/<nom>.toml ; l'API le lit/ecrit uniquement par
# clipper.channel (save_channel : relu et valide avant remplacement).
# --------------------------------------------------------------------------

_BASE_CONFIG = "config.toml"
# Sections du formulaire : [channel], agencement, titre/CTA/badge, sous-titres,
# moments/grille. Les autres tables d'un preset sont conservees telles quelles.
_CHANNEL_FORM_SECTIONS = ("channel", "reframe", "render", "subtitles", "moments")
_NEXT_SLOTS = 10
_LOGO_MAX_BYTES = 5 * _MIB
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_TYPE_NAMES = {bool: "booléen", int: "entier", float: "nombre", str: "texte", list: "liste"}


def _comment_above(lines: list[str], lineno: int) -> str:
    """Bloc de lignes de commentaire collees juste au-dessus de la ligne
    ``lineno`` (1-based) du source, sans le « # » ; vide s'il n'y en a pas."""
    block: list[str] = []
    index = lineno - 2
    while index >= 0 and lines[index].strip().startswith("#"):
        block.insert(0, lines[index].strip().lstrip("#").strip())
        index -= 1
    return " ".join(part for part in block if part)


def _defaults_documentation(section: str) -> dict[str, dict[str, Any]]:
    """CONFIG_DEFAULTS de clipper.<section> : pour chaque cle, son defaut et le
    commentaire place au-dessus dans le source (inspect.getsource + ast : le
    source n'est lu que pour ses commentaires, jamais evalue)."""
    defaults = _section_defaults(section)
    module = importlib.import_module(f"clipper.{section}")
    lines = inspect.getsource(module).splitlines()
    comments: dict[str, str] = {}
    for node in ast.walk(ast.parse("\n".join(lines))):
        targets = [node.target] if isinstance(node, ast.AnnAssign) else getattr(node, "targets", [])
        if not any(isinstance(t, ast.Name) and t.id == "CONFIG_DEFAULTS" for t in targets):
            continue
        if isinstance(node.value, ast.Dict):
            for key in node.value.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    comments[key.value] = _comment_above(lines, key.lineno)
    return {key: {"default": value, "comment": comments.get(key, "")} for key, value in defaults.items()}


def _check_preset_types(preset: dict[str, Any]) -> None:
    """Chaque valeur d'une section a le type de son defaut dans CONFIG_DEFAULTS
    (booleen, entier, nombre, texte, liste) : erreur « [section] cle : ... »
    nommant le champ, jamais une conversion silencieuse (ADR-ad2e)."""
    for section, table in preset.items():
        if not isinstance(table, dict):
            continue
        defaults = _section_defaults(section)
        for key, value in table.items():
            if key not in defaults:
                continue  # cle inconnue : refusee par load_config, qui la nomme
            kind = next((t for t in (bool, int, float, str, list) if type(defaults[key]) is t), None)
            if kind is None:
                continue
            ok = (
                isinstance(value, bool) if kind is bool
                else isinstance(value, (int, float)) and not isinstance(value, bool) if kind is float
                else isinstance(value, kind) and not isinstance(value, bool)
            )
            if not ok:
                raise ConfigError(f"[{section}] {key} : {_TYPE_NAMES[kind]} attendu, reçu {value!r}")
    timezone_name = (preset.get("channel") or {}).get("timezone")
    if timezone_name:
        try:
            ZoneInfo(timezone_name)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ConfigError(f"[channel] timezone : fuseau horaire inconnu ({timezone_name!r})") from exc


def _validate_preset(name: str, preset: dict[str, Any]) -> None:
    """Valide ``preset`` comme save_channel puis load_channel le feront, dans un
    dossier temporaire : le fichier reel n'est touche que si tout passe
    (SPEC-fc0c 1.5). load_channel ajoute les regles de [channel] (mode,
    creneaux) que save_channel ne controle pas."""
    _check_preset_types(preset)
    with tempfile.TemporaryDirectory() as tmp:
        channel_mod.save_channel(name, preset, presets_dir=tmp, base=_BASE_CONFIG)
        channel_mod.load_channel(name, presets_dir=tmp, base=_BASE_CONFIG)


def _check_channel_name(name: str) -> None:
    if not channel_mod.NAME_RE.match(name):
        raise HTTPException(
            status_code=422,
            detail=f"nom de chaîne invalide : {name!r} (attendu : lettres minuscules, chiffres, _ ou -, 1 à 40 caractères)",
        )


def _channel_preset_path(name: str) -> Path:
    _check_channel_name(name)
    path = Path(_PRESETS_DIR) / f"{name}.toml"
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"chaîne inconnue : {name!r}")
    return path


def _load_channel(name: str) -> tuple[Config, dict[str, Any]]:
    _channel_preset_path(name)
    try:
        return channel_mod.load_channel(name, presets_dir=_PRESETS_DIR, base=_BASE_CONFIG)
    except channel_mod.ChannelError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _channel_detail(name: str) -> dict[str, Any]:
    """Preset brut (ce qu'il redefinit), valeurs effectives (preset > config.toml
    > CONFIG_DEFAULTS) et documentation des defauts, section par section."""
    config, channel = _load_channel(name)
    path = _channel_preset_path(name)
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
        effective = {s: channel if s == "channel" else config.section(s) for s in _CHANNEL_FORM_SECTIONS}
        defaults = {s: _defaults_documentation(s) for s in _CHANNEL_FORM_SECTIONS}
    except (OSError, tomllib.TOMLDecodeError, ConfigError) as exc:
        raise HTTPException(status_code=422, detail=f"preset illisible ({path.name}) : {exc}") from exc
    return {"name": name, "raw": raw, "effective": effective, "defaults": defaults}


def _subspreview_config(name: str, draft: str | None) -> Config:
    """Config effective de la chaine pour l'apercu des sous-titres. Avec
    ``draft`` (JSON ``{"subtitles": {...}, "reframe": {...}}`` : les tables du
    formulaire pas encore enregistrees), le preset est recompose avec ces
    tables puis relu par save_channel/load_channel dans un dossier temporaire
    (heritage compris, comme a l'enregistrement) ; le fichier reel n'est
    jamais touche."""
    config, _channel = _load_channel(name)
    if not draft:
        return config
    try:
        tables = json.loads(draft)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"draft : JSON invalide ({exc})") from exc
    if not isinstance(tables, dict) or any(not isinstance(v, dict) for v in tables.values()):
        raise HTTPException(status_code=422, detail="draft : attendu un objet {section: {cle: valeur}}")
    if set(tables) - {"subtitles", "reframe"}:
        raise HTTPException(status_code=422, detail="draft : seules les sections subtitles et reframe sont admises")
    preset = tomllib.loads(_channel_preset_path(name).read_text(encoding="utf-8"))
    for section, table in tables.items():
        if table:
            preset[section] = table
        else:
            preset.pop(section, None)
    try:
        _check_preset_types(preset)
        with tempfile.TemporaryDirectory() as tmp:
            channel_mod.save_channel(name, preset, presets_dir=tmp, base=_BASE_CONFIG)
            return channel_mod.load_channel(name, presets_dir=tmp, base=_BASE_CONFIG)[0]
    except ConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _save_channel_preset(name: str, preset: dict[str, Any]) -> None:
    if "channel" not in preset:
        preset = {**preset, "channel": {}}  # sans [channel], le preset ne serait plus une chaine
    try:
        _validate_preset(name, preset)
        channel_mod.save_channel(name, preset, presets_dir=_PRESETS_DIR, base=_BASE_CONFIG)
    except ConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# --------------------------------------------------------------------------
# Ecran Reglages (SPEC-c100 E8, ADR-4f6e §2 et §5) : config.toml en formulaire.
# L'ecriture passe par config.write_config (relu par load_config avant le
# remplacement atomique) ; le jeton [web] token n'est jamais lu ni ecrit par
# l'interface : il se change dans le fichier, puis redemarrage.
# --------------------------------------------------------------------------

_SETTINGS_FLAT = tuple(_CONFIG_FLAT_DEFAULTS)
_SETTINGS_SECTIONS = ("llm", "web", "worker")
_SETTINGS_TOKEN_MASK = "•" * 8
_SETTINGS_QUOTED = re.compile(r'"(?:[^"\\]|\\.)*"|\'[^\']*\'')


def _settings_read_raw() -> tuple[dict[str, Any], bool, str]:
    path = Path(_BASE_CONFIG)
    if not path.is_file():
        return {}, False, ""
    try:
        text = path.read_text(encoding="utf-8")
        return tomllib.loads(text), True, text
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise HTTPException(status_code=422, detail=f"{_BASE_CONFIG} illisible : {exc}") from exc


def _settings_has_comments(text: str) -> bool:
    return any("#" in _SETTINGS_QUOTED.sub("", line) for line in text.splitlines())


def _settings_without_token(web: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in web.items() if k != "token"}


def _settings_access(web_cfg: dict[str, Any]) -> dict[str, Any]:
    """Acces tel que le serveur en cours l'applique (lecture seule) : l'hote et
    le port ne changent qu'au redemarrage, le jeton n'est jamais renvoye."""
    host, port, token = str(web_cfg["host"]), int(web_cfg["port"]), str(web_cfg["token"])
    command = f"python -m clipper serve --port {port}"
    if host != _LOOPBACK_HOST:
        command = f"python -m clipper serve --host {host} --port {port}"
    return {
        "host": host, "port": port, "loopback": host == _LOOPBACK_HOST,
        "token_set": bool(token), "token": _SETTINGS_TOKEN_MASK if token else None, "command": command,
    }


def _settings_detail(running_web: dict[str, Any]) -> dict[str, Any]:
    """Valeurs effectives de config.toml (relu a chaque appel), brut du fichier
    et CONFIG_DEFAULTS commentes des sections du formulaire."""
    raw, exists, text = _settings_read_raw()
    try:
        config = load_config(_BASE_CONFIG) if exists else load_config()
        effective: dict[str, Any] = {"mode": config.mode, "workspace_dir": str(config.workspace_dir),
                                     "output_dir": str(config.output_dir)}
        defaults: dict[str, Any] = {
            "general": {k: {"default": v, "comment": ""} for k, v in _CONFIG_FLAT_DEFAULTS.items()},
        }
        from clipper import llm as llm_mod

        for section in _SETTINGS_SECTIONS:
            # [llm] est fusionne en profondeur avec ses defauts par clipper.llm : meme vue ici
            effective[section] = llm_mod._settings(config) if section == "llm" else config.section(section)
            defaults[section] = _defaults_documentation(section)
    except ConfigError as exc:
        raise HTTPException(status_code=422, detail=f"{_BASE_CONFIG} invalide : {exc}") from exc
    file_web = effective["web"]
    effective["web"] = _settings_without_token(file_web)
    defaults["web"].pop("token", None)
    if "web" in raw:
        raw = {**raw, "web": _settings_without_token(raw["web"])}
    restart = any(file_web[k] != running_web[k] for k in ("host", "port", "token"))
    return {
        "path": _BASE_CONFIG, "exists": exists, "comments_lost": _settings_has_comments(text),
        "raw": raw, "effective": effective, "defaults": defaults,
        "modes": list(VALID_MODES), "backends": list(llm_mod._BACKENDS),
        "access": _settings_access(running_web), "restart_required": restart,
    }


def _settings_check_llm(llm: dict[str, Any]) -> None:
    from clipper import llm as llm_mod

    known = " | ".join(llm_mod._BACKENDS)

    def backend(value: Any, where: str) -> None:
        if value not in llm_mod._BACKENDS:
            raise ConfigError(f"[llm] {where} : backend inconnu {value!r} (attendu : {known})")

    if "backend" in llm:
        backend(llm["backend"], "backend")
    usages = llm.get("usages", {})
    if not isinstance(usages, dict):
        raise ConfigError("[llm] usages : table attendue")
    for usage, table in usages.items():
        if not isinstance(table, dict) or not all(isinstance(v, str) for v in table.values()):
            raise ConfigError(f"[llm] usages.{usage} : table de textes attendue (backend, model)")
        unknown = set(table) - {"backend", "model"}
        if unknown:
            raise ConfigError(f"[llm] usages.{usage} : cle(s) inconnue(s) {', '.join(sorted(unknown))}")
        if "backend" in table:
            backend(table["backend"], f"usages.{usage}.backend")
    for key, value in llm.items():
        if isinstance(_section_defaults("llm").get(key), dict) and key != "usages":
            models = value.get("models", {}) if isinstance(value, dict) else None
            if not isinstance(models, dict) or not all(isinstance(m, str) and m for m in models.values()):
                raise ConfigError(f"[llm] {key}.models : table niveau -> nom de modele (textes non vides) attendue")


def _settings_merge(raw: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    """Ce que le formulaire controle (mode, dossiers, [llm], [web], [worker])
    remplace le fichier ; le reste (autres sections) et le jeton sont conserves."""
    unknown = set(settings) - set(_SETTINGS_FLAT) - set(_SETTINGS_SECTIONS)
    if unknown:
        raise ConfigError(
            f"{', '.join(sorted(unknown))} : non modifiable depuis les réglages "
            f"(éditable : {', '.join((*_SETTINGS_FLAT, *_SETTINGS_SECTIONS))})"
        )
    for key in _SETTINGS_FLAT:
        if key in settings and not (isinstance(settings[key], str) and settings[key].strip()):
            raise ConfigError(f"{key} : texte non vide attendu, reçu {settings[key]!r}")
    for section in _SETTINGS_SECTIONS:
        if section in settings and not isinstance(settings[section], dict):
            raise ConfigError(f"[{section}] : table attendue")
    _check_preset_types({s: settings[s] for s in _SETTINGS_SECTIONS if s in settings})
    web = settings.get("web", {})
    if "token" in web:
        raise ConfigError("[web] token : le jeton ne se modifie pas depuis l'interface (fichier + redémarrage)")
    if "llm" in settings:
        _settings_check_llm(settings["llm"])
    port = web.get("port")
    if port is not None and not 1 <= port <= 65535:
        raise ConfigError(f"[web] port : entre 1 et 65535 attendu, reçu {port!r}")
    data = {k: v for k, v in raw.items()}
    for key in _SETTINGS_FLAT:
        if key in settings:
            data[key] = settings[key]
    for section in _SETTINGS_SECTIONS:
        if section in settings:
            data[section] = dict(settings[section])
    token = raw.get("web", {}).get("token", "")
    if "web" in settings and token:
        data["web"]["token"] = token
    final_web = data.get("web", {})
    if final_web.get("host", _section_defaults("web")["host"]) != _LOOPBACK_HOST and not final_web.get("token"):
        raise ConfigError(
            "[web] host hors bouclage : un jeton ([web] token) est exigé, à écrire dans config.toml "
            "(sinon 'serve' refuserait de démarrer, ADR-4f6e §5)"
        )
    return data


class SettingsBody(BaseModel):
    settings: dict[str, Any]

# Editeur d'agencement stream split (SPEC-c100 E5, SPEC-76dc) : memes cles et
# memes validations que [reframe] (c'est reframe qui refuse, pas le JS).
# L'image cle est un fichier deja produit par l'etape scenes.
# --------------------------------------------------------------------------

_LAYOUT_KEYS = ("split_webcam_dest", "split_gameplay_dest", "badge_dest", "split_subtitle_dest")
_LAYOUT_KEYFRAME_DIRS = ("frames", "scenes")  # frames/ : sortie de clipper.scenes


def _layout_keyframes(config: Config, video_id: str) -> list[Path]:
    video_dir = Path(config.workspace_dir) / video_id
    return sorted(p for d in _LAYOUT_KEYFRAME_DIRS for p in (video_dir / d).glob("*.jpg") if p.is_file())


def _layout_keyframe_path(config: Config, name: str, video_id: str | None) -> Path:
    """Image cle du milieu d'une video de la chaine (celle demandee, sinon la
    premiere qui en a) : 404 en francais si aucune n'existe."""
    if video_id is not None:
        if not _SAFE_ID.fullmatch(video_id):
            raise HTTPException(status_code=404, detail=f"identifiant invalide : {video_id!r}")
        if _channel_of(video_id, config) != name:
            raise HTTPException(status_code=404, detail=f"la vidéo {video_id!r} n'appartient pas à la chaîne {name!r}")
        frames = _layout_keyframes(config, video_id)
        if not frames:
            raise HTTPException(status_code=404, detail=f"aucune image clé pour la vidéo {video_id!r} (étape scenes non faite)")
        return frames[len(frames) // 2]
    for state in sorted(_list_states(config), key=lambda s: s["video_id"]):
        if state.get("channel") == name and _SAFE_ID.fullmatch(state["video_id"]):
            frames = _layout_keyframes(config, state["video_id"])
            if frames:
                return frames[len(frames) // 2]
    raise HTTPException(
        status_code=404,
        detail=f"aucune image clé : aucune vidéo de la chaîne {name!r} n'a passé l'étape scenes",
    )


def _layout_view(name: str) -> dict[str, Any]:
    """Rectangles effectifs (preset > config.toml > defauts SPEC-76dc), defauts,
    canevas et zone sure, tels que reframe les lit."""
    config, _channel = _load_channel(name)
    reframe = config.section("reframe")
    defaults = _section_defaults("reframe")
    return {
        "name": name,
        **{key: reframe[key] for key in _LAYOUT_KEYS},
        "defaults": {key: defaults[key] for key in _LAYOUT_KEYS},
        "canvas": {"w": reframe["output_width"], "h": reframe["output_height"]},
        "safe": {"left": reframe["safe_left"], "top": reframe["safe_top"],
                 "right": reframe["safe_right"], "bottom": reframe["safe_bottom"]},
    }


def _layout_check_geometry(name: str, preset: dict[str, Any]) -> None:
    """Fait relire ``preset`` (stream_variant force a "split") par reframe :
    load_config ne controle que les cles, c'est reframe._settings qui refuse un
    rectangle hors canevas, chevauchant ou hors zone sure. Son message est
    renvoye tel quel (ReframeError)."""
    candidate = {**preset, "reframe": {**preset["reframe"], "stream_variant": "split"}}
    _check_preset_types(candidate)
    with tempfile.TemporaryDirectory() as tmp:
        channel_mod.save_channel(name, candidate, presets_dir=tmp, base=_BASE_CONFIG)
        config, _channel = channel_mod.load_channel(name, presets_dir=tmp, base=_BASE_CONFIG)
    try:
        reframe_mod._settings(config)
    except reframe_mod.ReframeError as exc:
        raise ConfigError(str(exc)) from exc


def _layout_save(name: str, body: dict[str, Any]) -> None:
    """Ecrit les rectangles dans [reframe] du preset par save_channel, apres
    avoir verifie la geometrie comme reframe la verifiera au rendu : l'editeur
    ne laisse jamais passer un agencement que reframe refuserait."""
    given = {key: body[key] for key in _LAYOUT_KEYS if body.get(key) is not None}
    if not given:
        raise HTTPException(status_code=422, detail=f"aucun rectangle à enregistrer (attendu : {', '.join(_LAYOUT_KEYS)})")
    path = _channel_preset_path(name)
    try:
        preset = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise HTTPException(status_code=422, detail=f"preset illisible ({path.name}) : {exc}") from exc
    preset["reframe"] = {**preset.get("reframe", {}), **given}
    try:
        _layout_check_geometry(name, preset)
    except ConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _save_channel_preset(name, preset)

def _png_from_multipart(content_type: str, body: bytes) -> bytes:
    """Contenu du champ « file » d'un POST multipart (stdlib, sans dependance)."""
    if not content_type.lower().startswith("multipart/form-data"):
        raise HTTPException(status_code=422, detail="envoi multipart/form-data attendu (champ « file », image PNG)")
    message = BytesParser(policy=_EMAIL_HTTP).parsebytes(
        b"Content-Type: " + content_type.encode("latin-1") + b"\r\n\r\n" + body)
    for part in message.iter_parts() if message.is_multipart() else []:
        if part.get_param("name", header="content-disposition") == "file":
            data = part.get_payload(decode=True) or b""
            if not data.startswith(_PNG_SIGNATURE):
                raise HTTPException(status_code=422, detail="le logo doit être une image PNG")
            return data
    raise HTTPException(status_code=422, detail="champ « file » absent de l'envoi multipart")


# ----------------------------------------------------------------
# Statistiques (SPEC-c100 E7, TASK-7d86)
# ----------------------------------------------------------------

_STATS_STEP_ORDER = tuple(pipeline.STEPS)


def _stats_bound(name: str, value: str | None, *, end_of_day: bool) -> datetime | None:
    """Borne de periode « AAAA-MM-JJ » ou horodatage ISO 8601 (UTC si sans fuseau)."""
    if not value:
        return None
    try:
        bound = datetime.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"date invalide pour {name} : {value!r} (attendu AAAA-MM-JJ ou horodatage ISO 8601)",
        ) from exc
    if end_of_day and len(value) == 10:
        bound = bound.replace(hour=23, minute=59, second=59, microsecond=999999)
    return bound if bound.tzinfo else bound.replace(tzinfo=timezone.utc)


def _stats_period(since: str | None, until: str | None) -> tuple[datetime | None, datetime | None]:
    lower = _stats_bound("since", since, end_of_day=False)
    upper = _stats_bound("until", until, end_of_day=True)
    if lower is not None and upper is not None and lower > upper:
        raise HTTPException(status_code=422, detail=f"periode inversee : since={since!r} est apres until={until!r}")
    return lower, upper


def _stats_in_period(stamp: str | None, lower: datetime | None, upper: datetime | None, where: str) -> bool:
    if lower is None and upper is None:
        return True
    if not stamp:
        raise HTTPException(status_code=500, detail=f"horodatage absent ({where}) : impossible de le placer dans la periode")
    try:
        moment = datetime.fromisoformat(stamp)
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=f"horodatage illisible ({where}) : {stamp!r}") from exc
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return (lower is None or moment >= lower) and (upper is None or moment <= upper)


def _stats_read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    entries = []
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            entries.append(json.loads(raw))
        except ValueError as exc:
            raise HTTPException(status_code=500, detail=f"{path.name} ligne {number} illisible : {exc}") from exc
    return entries


def _stats_outcomes(config: Config) -> list[dict[str, Any]]:
    path = Path(str(config.section("outcomes")["journal_path"]))
    try:
        return outcomes_mod.read(path)
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=500, detail=f"{path.name} illisible : {exc}") from exc


def _stats_clips(config: Config, lower: datetime | None, upper: datetime | None) -> dict[str, Any]:
    """Un element par sidecar de output/ cree dans la periode, joint aux resultats
    d'outcomes (qa du sidecar, decision humaine, mesure de plateforme la plus
    recente). Le CSV de plateforme ne porte que ``clip_id`` : une mesure n'est
    rattachee que si un seul clip porte cet id, sinon elle est rendue a part
    (``stats_unmatched``) avec la raison, jamais attribuee au hasard."""
    journal = _stats_outcomes(config)
    feedback_path = Path(str(config.section("feedback")["journal_path"]))
    decisions: dict[tuple[str, Any], str] = {}
    for entry in _stats_read_jsonl(feedback_path):
        try:
            decisions[(entry["video_id"], entry["moment"]["id"])] = entry["decision"]
        except (KeyError, TypeError) as exc:
            raise HTTPException(status_code=500, detail=f"{feedback_path.name} : entree sans video_id/moment/decision ({exc})") from exc
    results: dict[tuple[Any, Any], Any] = {}
    measures: dict[str, list[tuple[str, int, dict[str, Any]]]] = {}
    for index, entry in enumerate(journal):
        if entry.get("kind") == "result":
            if entry.get("human_decision") is not None:
                results[(entry["video_id"], entry["clip_id"])] = entry["human_decision"]
        elif entry.get("kind") == "stats":
            stats = entry["stats"]
            measures.setdefault(entry["clip_id"], []).append((str(stats.get("date")), index, stats))

    root = Path(config.output_dir)
    sidecars: list[tuple[str, str, dict[str, Any]]] = []
    for video_dir in sorted(p for p in root.iterdir() if p.is_dir()) if root.is_dir() else []:
        for path in sorted(video_dir.glob("*.json")):
            sidecar = _read_clip_sidecar(config, video_dir.name, path.stem)
            sidecars.append((video_dir.name, path.stem, sidecar))
    holders: dict[str, int] = {}
    for _, clip_id, _ in sidecars:
        holders[clip_id] = holders.get(clip_id, 0) + 1

    clips = []
    for video_id, clip_id, sidecar in sidecars:
        if not _stats_in_period(sidecar.get("created_at"), lower, upper, f"sidecar {video_id}/{clip_id}"):
            continue
        qa = sidecar.get("qa") or {}
        moment_id = sidecar.get("moment_id")
        decision, source = results.get((video_id, clip_id)), "outcomes"
        if decision is None:
            decision, source = decisions.get((video_id, moment_id)), "feedback"
        found = measures.get(clip_id) if holders[clip_id] == 1 else None
        clips.append({
            "video_id": video_id, "clip_id": clip_id, "moment_id": moment_id,
            "channel": _channel_of(video_id, config), "screen_title": sidecar.get("screen_title"),
            "created_at": sidecar.get("created_at"),
            "qa_status": qa.get("status"), "issues": qa.get("issues"),
            "human_decision": decision, "decision_source": source if decision is not None else None,
            "stats": max(found)[2] if found else None,
        })
    unmatched = []
    for clip_id in sorted(measures):
        if holders.get(clip_id, 0) == 1:
            continue
        reason = (f"le clip {clip_id} existe dans plusieurs vidéos : le CSV n'a pas de video_id"
                  if holders.get(clip_id) else f"aucun clip {clip_id} dans {config.output_dir}")
        unmatched.append({"clip_id": clip_id, "reason": reason, "stats": max(measures[clip_id])[2]})
    return {"clips": clips, "stats_unmatched": unmatched}


def _stats_llm_cost(config: Config, lower: datetime | None, upper: datetime | None) -> dict[str, Any]:
    """Couts de workspace/*/llm_usage.jsonl dans la periode : par video, par usage
    et par jour (UTC) ; les appels sans cout rapporte sont comptes a part."""
    cost: dict[str, Any] = {"total": 0.0, "unreported_calls": 0, "by_video": {}, "by_usage": {}, "by_day": {}}
    root = Path(config.workspace_dir)
    for path in sorted(root.glob("*/llm_usage.jsonl")) if root.is_dir() else []:
        video_id = path.parent.name
        for number, entry in enumerate(_stats_read_jsonl(path), start=1):
            where = f"{video_id}/{path.name} ligne {number}"
            stamp = entry.get("recorded_at") or entry.get("timestamp")
            if not _stats_in_period(stamp, lower, upper, where):
                continue
            try:
                usage = entry["usage"]
                day = datetime.fromisoformat(stamp).astimezone(timezone.utc).date().isoformat()
            except (KeyError, TypeError, ValueError) as exc:
                raise HTTPException(status_code=500, detail=f"{where} : {exc}") from exc
            video = cost["by_video"].setdefault(video_id, {"cost": 0.0, "calls": 0, "unreported_calls": 0})
            video["calls"] += 1
            amount = entry.get("cost_usd")
            if amount is None:
                video["unreported_calls"] += 1
                cost["unreported_calls"] += 1
                continue
            video["cost"] += amount
            cost["total"] += amount
            cost["by_usage"][usage] = cost["by_usage"].get(usage, 0.0) + amount
            cost["by_day"][day] = cost["by_day"].get(day, 0.0) + amount
    cost["by_day"] = dict(sorted(cost["by_day"].items()))
    return cost


def _stats_steps_and_counts(config: Config, lower: datetime | None, upper: datetime | None) -> dict[str, Any]:
    """Videos dont ``updated_at`` tombe dans la periode : comptes par statut, et
    duree moyenne / derniere (fin la plus recente) de chaque etape sur les videos done."""
    counts = {status: 0 for status in _VIDEO_STATUSES}
    samples: dict[str, list[tuple[str, float]]] = {}
    for state in _list_states(config):
        video_id = state.get("video_id", "?")
        if not _stats_in_period(state.get("updated_at"), lower, upper, f"pipeline.json de {video_id}"):
            continue
        status = state.get("status")
        if status not in counts:
            raise HTTPException(status_code=500, detail=f"statut inconnu {status!r} dans le pipeline.json de {video_id}")
        counts[status] += 1
        if status != "done":
            continue
        for name, seconds in _step_durations(state).items():
            if seconds is not None:
                samples.setdefault(name, []).append((state["steps"][name]["finished_at"], seconds))
    steps = {}
    for name in sorted(samples, key=lambda n: _STATS_STEP_ORDER.index(n) if n in _STATS_STEP_ORDER else len(_STATS_STEP_ORDER)):
        durations = [seconds for _, seconds in samples[name]]
        steps[name] = {"mean_s": sum(durations) / len(durations),
                       "last_s": max(samples[name], key=lambda s: _parse_ts("?", name, "finished_at", s[0]))[1],
                       "count": len(durations)}
    return {"steps": steps, "counts": counts}


def _stats(config: Config, since: str | None, until: str | None) -> dict[str, Any]:
    lower, upper = _stats_period(since, until)
    return {"period": {"since": since or None, "until": until or None},
            **_stats_clips(config, lower, upper),
            "llm_cost": _stats_llm_cost(config, lower, upper),
            **_stats_steps_and_counts(config, lower, upper)}


def _stats_csv_from_multipart(content_type: str, body: bytes) -> bytes:
    """Contenu du champ « file » d'un POST multipart (stdlib, sans dependance)."""
    if not content_type.lower().startswith("multipart/form-data"):
        raise HTTPException(status_code=422, detail="envoi multipart/form-data attendu (champ « file », fichier CSV)")
    message = BytesParser(policy=_EMAIL_HTTP).parsebytes(
        b"Content-Type: " + content_type.encode("latin-1") + b"\r\n\r\n" + body)
    for part in message.iter_parts() if message.is_multipart() else []:
        if part.get_param("name", header="content-disposition") == "file":
            return part.get_payload(decode=True) or b""
    raise HTTPException(status_code=422, detail="champ « file » absent de l'envoi multipart")


def _stats_import(config: Config, data: bytes) -> int:
    """Importe le CSV via clipper.outcomes ; en cas d'echec le journal est remis
    tel qu'il etait (import_stats ecrit ligne a ligne : pas d'import partiel)."""
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"le CSV doit être encodé en UTF-8 : {exc}") from exc
    journal = Path(str(config.section("outcomes")["journal_path"]))
    size = journal.stat().st_size if journal.exists() else None
    with tempfile.TemporaryDirectory() as tmp:
        csv_path = Path(tmp) / "stats.csv"
        csv_path.write_bytes(data)
        try:
            return len(outcomes_mod.import_stats(csv_path, path=journal))
        except (outcomes_mod.OutcomesError, ValueError, KeyError, TypeError, csv.Error) as exc:
            if size is None:
                journal.unlink(missing_ok=True)
            elif journal.stat().st_size != size:
                with journal.open("r+b") as f:
                    f.truncate(size)
            raise HTTPException(status_code=422, detail=f"import du CSV impossible : {exc}") from exc


class ChannelBody(BaseModel):
    preset: dict[str, Any]


class ChannelCreateBody(BaseModel):
    name: str
    preset: dict[str, Any] | None = None


class ClipPatchBody(BaseModel):
    description: str | None = None
    hashtags: list[str] | None = None
    screen_title: str | None = None
    confirm: bool = False


class SubmitBody(BaseModel):
    url: str


class QueueBody(BaseModel):
    url: str
    channel: str | None = None
    action: str
    force_steps: list[str] = []


class RetryBody(BaseModel):
    from_step: str


class DecideBody(BaseModel):
    decision: str
    start: float | None = None
    end: float | None = None
    comment: str | None = None


class LayoutBody(BaseModel):
    split_webcam_dest: dict[str, Any] | None = None
    split_gameplay_dest: dict[str, Any] | None = None
    badge_dest: dict[str, Any] | None = None
    split_subtitle_dest: dict[str, Any] | None = None


def create_app(config: Config | None = None) -> FastAPI:
    config = config or load_config()
    web_cfg = config.section("web")
    host = str(web_cfg["host"])
    token = str(web_cfg["token"])
    enforce_auth = host != _LOOPBACK_HOST
    if enforce_auth and not token:
        raise WebConfigError(
            f"[web] host={host!r} hors bouclage exige un jeton ([web] token) configure (ADR-4f6e §5)"
        )

    app = FastAPI(title="Clipper", default_response_class=JSONResponse)
    app.state.config = config

    @app.exception_handler(HTTPException)
    async def _http_error(_request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.middleware("http")
    async def _check_token(request: Request, call_next):
        if enforce_auth and request.url.path.startswith(_PROTECTED_PREFIXES):
            supplied = request.headers.get(_TOKEN_HEADER) or request.cookies.get(_TOKEN_COOKIE)
            if supplied != token:
                return JSONResponse({"detail": "jeton d'acces manquant ou invalide"}, status_code=401)
        return await call_next(request)

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/dashboard")
    def dashboard() -> dict[str, Any]:
        return _dashboard(config)

    # ----------------------------------------------------------------
    # File de traitement (SPEC-fc0c §2)
    # ----------------------------------------------------------------

    @app.post("/api/queue", status_code=202)
    def enqueue_video(body: QueueBody) -> JSONResponse:
        return _enqueue(body.url, body.channel, body.action, body.force_steps, config)

    @app.get("/api/queue")
    def list_queue() -> list[dict[str, Any]]:
        path = _queue_path(config)
        if not path.exists():
            return []
        return json.loads(path.read_text(encoding="utf-8"))

    @app.post("/api/queue/{video_id}/front")
    def queue_front(video_id: str) -> dict[str, Any]:
        _validate_video_id(video_id)
        try:
            worker_mod.move_to_front(video_id, config=config)
        except worker_mod.WorkerError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"video_id": video_id, "moved": True}

    @app.delete("/api/queue/{video_id}")
    def queue_remove(video_id: str) -> dict[str, Any]:
        _validate_video_id(video_id)
        try:
            worker_mod.remove(video_id, config=config)
        except worker_mod.WorkerError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"video_id": video_id, "removed": True}

    # ----------------------------------------------------------------
    # Videos : alias v1, etat, moments, revue, rendu, annulation, relance
    # ----------------------------------------------------------------

    @app.post("/api/videos", status_code=202)
    def submit_video(body: SubmitBody) -> JSONResponse:
        """Alias de POST /api/queue sans chaine (action 'run')."""
        return _enqueue(body.url, None, "run", None, config)

    @app.get("/api/videos")
    def list_videos(channel: str | None = None, status: str | None = None,
                    q: str | None = None) -> list[dict[str, Any]]:
        """Liste filtrable (chaine exacte, statut, texte sur video_id / titre /
        source_url), chaque video enrichie de son titre, de son etape courante
        et de la duree de chaque etape (SPEC-c100 E2)."""
        if status is not None and status not in _VIDEO_STATUSES:
            raise HTTPException(
                status_code=400,
                detail=f"statut inconnu : {status!r} (attendu : {', '.join(_VIDEO_STATUSES)})",
            )
        videos = [_enrich(state, config) for state in _list_states(config)]
        return [v for v in videos if _matches(v, channel, status, q)]

    @app.get("/api/videos/{video_id}")
    def get_video(video_id: str) -> dict[str, Any]:
        try:
            state = pipeline.load_state(video_id, config=config)
        except pipeline.PipelineError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        detail = _enrich(state, config)
        detail["clips"] = state.get("clips") or []
        detail["awaiting"] = state.get("awaiting") or []
        return detail

    @app.get("/api/videos/{video_id}/moments")
    def list_moments(video_id: str) -> list[dict[str, Any]]:
        return _list_moments(config, video_id)

    @app.post("/api/videos/{video_id}/moments/{moment_id}/decide")
    def decide_moment(video_id: str, moment_id: int, body: DecideBody) -> dict[str, Any]:
        try:
            return pipeline.decide(video_id, moment_id, body.decision, start=body.start, end=body.end,
                                   comment=body.comment, config=config)
        except pipeline.PipelineError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/videos/{video_id}/render", status_code=202)
    def start_render(video_id: str) -> JSONResponse:
        """Remet la video en file, action 'render' (ADR-4f6e §1 : jamais
        pipeline.render dans ce processus)."""
        _validate_video_id(video_id)
        return _enqueue(video_id, _channel_of(video_id, config), "render", None, config)

    @app.post("/api/videos/{video_id}/cancel")
    def cancel_video(video_id: str) -> dict[str, Any]:
        _validate_video_id(video_id)
        try:
            worker_mod.Worker(config=config).cancel(video_id)
        except worker_mod.WorkerError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"video_id": video_id, "cancelled": True}

    @app.post("/api/videos/{video_id}/retry", status_code=202)
    def retry_video(video_id: str, body: RetryBody) -> JSONResponse:
        _validate_video_id(video_id)
        if body.from_step not in pipeline.STEPS:
            raise HTTPException(status_code=400, detail=f"etape inconnue : {body.from_step!r}")
        force_steps = list(pipeline.STEPS[pipeline.STEPS.index(body.from_step):])
        return _enqueue(video_id, _channel_of(video_id, config), "render", force_steps, config)

    @app.get("/api/videos/{video_id}/events")
    def video_events(video_id: str, since: str | None = None) -> list[dict[str, Any]]:
        _validate_video_id(video_id)
        path = Path(config.workspace_dir) / video_id / pipeline.EVENTS_FILE
        if not path.exists():
            return []
        events = []
        for raw in path.read_text(encoding="utf-8").splitlines():
            if not raw:
                continue
            event = json.loads(raw)
            if since is not None and event["at"] <= since:
                continue
            events.append(event)
        return events

    @app.get("/api/videos/{video_id}/clips")
    def list_clips(video_id: str) -> list[dict[str, Any]]:
        out_dir = Path(config.output_dir) / video_id
        if not out_dir.is_dir():
            return []
        clips = []
        for path in sorted(out_dir.glob("*.json")):
            clip = _read_json(path)
            clip["video_url"] = f"/media/clip/{video_id}/{clip['clip_id']}"
            clip["thumbnail_url"] = f"/media/clip/{video_id}/{clip['clip_id']}/thumbnail"
            clips.append(clip)
        return clips

    # ----------------------------------------------------------------
    # Clips (SPEC-c100 E4)
    # ----------------------------------------------------------------

    @app.get("/api/clips")
    def list_all_clips(channel: str | None = None, video_id: str | None = None,
                       status: str | None = None) -> list[dict[str, Any]]:
        if video_id is not None:
            _validate_video_id(video_id)
        if status is not None and status not in _CLIP_STATUSES:
            raise HTTPException(
                status_code=400,
                detail=f"statut inconnu : {status!r} (attendu : {', '.join(_CLIP_STATUSES)})",
            )
        return _list_clip_views(config, channel or None, video_id, status)

    def _decide(video_id: str, clip_id: str, action: str) -> dict[str, Any]:
        _validate_video_id(video_id)
        _validate_clip_id(clip_id)
        channel = _require_channel(video_id, clip_id, config)
        kwargs: dict[str, Any] = {"output_dir": Path(config.output_dir), "state_dir": _publish_dir(config)}
        if action == "approve":
            kwargs["presets_dir"] = _PRESETS_DIR
        try:
            return getattr(publish_mod, action)(video_id, clip_id, channel, **kwargs)
        except publish_mod.PublishError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/clips/{video_id}/{clip_id}/approve")
    def approve_clip(video_id: str, clip_id: str) -> dict[str, Any]:
        return _decide(video_id, clip_id, "approve")

    @app.post("/api/clips/{video_id}/{clip_id}/reject")
    def reject_clip(video_id: str, clip_id: str) -> dict[str, Any]:
        return _decide(video_id, clip_id, "reject")

    @app.post("/api/clips/{video_id}/{clip_id}/rerender", status_code=202)
    def rerender_clip(video_id: str, clip_id: str) -> JSONResponse:
        _validate_video_id(video_id)
        _validate_clip_id(clip_id)
        _read_clip_sidecar(config, video_id, clip_id)
        return JSONResponse(_enqueue_clip_render(video_id, config), status_code=202)

    @app.patch("/api/clips/{video_id}/{clip_id}")
    def edit_clip(video_id: str, clip_id: str, body: ClipPatchBody) -> JSONResponse:
        _validate_video_id(video_id)
        _validate_clip_id(clip_id)
        if body.description is None and body.hashtags is None and body.screen_title is None:
            raise HTTPException(status_code=400, detail="rien à modifier : description, hashtags ou screen_title attendu")
        sidecar = _read_clip_sidecar(config, video_id, clip_id)
        retitle = body.screen_title is not None
        if retitle and body.screen_title == sidecar.get("screen_title"):
            raise HTTPException(status_code=400, detail="titre d'écran inchangé : rien à re-rendre")
        if retitle and not body.confirm:
            raise HTTPException(
                status_code=409,
                detail="confirmation requise (confirm: true) : changer le titre d'écran relance render puis qa pour ce clip",
            )
        channel = _require_channel(video_id, clip_id, config)
        if body.description is not None or body.hashtags is not None:
            description = body.description if body.description is not None else sidecar.get("caption")
            hashtags = body.hashtags if body.hashtags is not None else sidecar.get("hashtags")
            try:
                sidecar = publish_mod.edit_caption(
                    video_id, clip_id, channel, description, hashtags,
                    output_dir=Path(config.output_dir), state_dir=_publish_dir(config))
            except publish_mod.PublishError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
        entry = _enqueue_clip_render(video_id, config) if retitle else None
        clip = _clip_view(sidecar, channel, _publish_entries(config, channel).get((video_id, clip_id)))
        return JSONResponse({"clip": clip, "rerender": entry}, status_code=202 if retitle else 200)

    # ----------------------------------------------------------------
    # Publication (SPEC-c100 E6, SPEC-fc0c §4) : tout passe par clipper.publish
    # ----------------------------------------------------------------

    @app.get("/api/publish")
    def publish_week(channel: str | None = None, week: str | None = None) -> dict[str, Any]:
        if not channel:
            raise HTTPException(status_code=400, detail="paramètre channel obligatoire : choisis une chaîne")
        return _publish_week_view(config, channel, week)

    def _publish_action(video_id: str, clip_id: str, action: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        _validate_video_id(video_id)
        _validate_clip_id(clip_id)
        channel = _require_channel(video_id, clip_id, config)
        try:
            return getattr(publish_mod, action)(video_id, clip_id, channel, *args, state_dir=_publish_dir(config), **kwargs)
        except publish_mod.PublishError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except channel_mod.ChannelError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ConfigError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/publish/{video_id}/{clip_id}/move")
    def publish_move(video_id: str, clip_id: str, body: PublishMoveBody) -> dict[str, Any]:
        slot_at = _publish_parse_slot(body.slot_at)
        return _publish_action(video_id, clip_id, "move", slot_at, presets_dir=_PRESETS_DIR, base=_BASE_CONFIG)

    @app.post("/api/publish/{video_id}/{clip_id}/published")
    def publish_mark_published(video_id: str, clip_id: str) -> dict[str, Any]:
        return _publish_action(video_id, clip_id, "mark_published")

    @app.post("/api/publish/{video_id}/{clip_id}/unschedule")
    def publish_unschedule(video_id: str, clip_id: str) -> dict[str, Any]:
        return _publish_action(video_id, clip_id, "unschedule")

    # ----------------------------------------------------------------
    # Surveillance : VOD a confirmer (SPEC-fc0c §5.3)
    # ----------------------------------------------------------------

    @app.post("/api/watch/{channel}/{video_id}/confirm", status_code=202)
    def watch_confirm(channel: str, video_id: str) -> JSONResponse:
        _validate_channel_name(channel)
        _validate_video_id(video_id)
        try:
            entry = watch_mod.confirm(channel, video_id, config=config)
        except watch_mod.WatchError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return JSONResponse(entry, status_code=202)

    @app.post("/api/watch/{channel}/{video_id}/ignore")
    def watch_ignore(channel: str, video_id: str) -> dict[str, Any]:
        _validate_channel_name(channel)
        _validate_video_id(video_id)
        try:
            watch_mod.ignore(channel, video_id, config=config)
        except watch_mod.WatchError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"channel": channel, "video_id": video_id, "ignored": True}

    # ----------------------------------------------------------------
    # Chaines (SPEC-fc0c §1) et temps reel (ADR-4f6e §4)
    # ----------------------------------------------------------------

    @app.get("/api/channels")
    def list_channels_route() -> list[str]:
        return channel_mod.list_channels(_PRESETS_DIR)

    @app.post("/api/channels", status_code=201)
    def create_channel(body: ChannelCreateBody) -> dict[str, Any]:
        _check_channel_name(body.name)
        if (Path(_PRESETS_DIR) / f"{body.name}.toml").exists():
            raise HTTPException(status_code=409, detail=f"la chaîne {body.name!r} existe déjà")
        Path(_PRESETS_DIR).mkdir(parents=True, exist_ok=True)
        _save_channel_preset(body.name, body.preset or {"channel": {}})
        return _channel_detail(body.name)

    @app.get("/api/channels/{name}")
    def get_channel(name: str) -> dict[str, Any]:
        return _channel_detail(name)

    @app.put("/api/channels/{name}")
    def put_channel(name: str, body: ChannelBody) -> dict[str, Any]:
        _channel_preset_path(name)
        _save_channel_preset(name, body.preset)
        return _channel_detail(name)

    @app.delete("/api/channels/{name}")
    def delete_channel_route(name: str, confirm: bool = False) -> dict[str, Any]:
        _check_channel_name(name)
        if not confirm:
            raise HTTPException(
                status_code=409,
                detail=f"confirmation requise (confirm=true) : supprimer la chaîne {name!r} efface son preset",
            )
        try:
            channel_mod.delete_channel(name, presets_dir=_PRESETS_DIR)
        except channel_mod.ChannelError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        Path(_PRESETS_DIR, f"{name}.png").unlink(missing_ok=True)
        return {"name": name, "deleted": True}

    @app.get("/api/channels/{name}/slots")
    def channel_slots(name: str) -> dict[str, Any]:
        _config, channel = _load_channel(name)
        slots = channel_mod.next_slots(channel, datetime.now(timezone.utc), _NEXT_SLOTS)
        return {
            "name": name, "timezone": channel["timezone"], "slots": [s.isoformat() for s in slots],
            "reason": None if channel["slots"] else "aucun créneau défini dans [channel].slots",
        }

    @app.get("/api/channels/{name}/subtitles-preview")
    def channel_subtitles_preview(name: str, text: str = "", draft: str | None = None) -> Response:
        config = _subspreview_config(name, draft)
        try:
            png = pipeline.preview_subtitles(config, text)
        except pipeline.PipelineError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return Response(png, media_type="image/png", headers={"Cache-Control": "no-store"})

    @app.post("/api/channels/{name}/logo")
    async def upload_channel_logo(name: str, request: Request) -> dict[str, Any]:
        _channel_preset_path(name)
        data = _png_from_multipart(request.headers.get("content-type", ""), await request.body())
        if len(data) > _LOGO_MAX_BYTES:
            raise HTTPException(status_code=422, detail=f"logo trop lourd (maximum {_LOGO_MAX_BYTES // _MIB} Mo)")
        target = Path(_PRESETS_DIR) / f"{name}.png"
        tmp = target.with_name(f"{target.name}.{os.getpid()}.tmp")
        tmp.write_bytes(data)
        os.replace(tmp, target)
        return {"name": name, "logo": f"{_PRESETS_DIR}/{name}.png"}

    # ----------------------------------------------------------------
    # Reglages (SPEC-c100 E8) : config.toml, relu a chaque requete
    # ----------------------------------------------------------------

    @app.get("/api/settings")
    def get_settings() -> dict[str, Any]:
        return _settings_detail(web_cfg)

    @app.put("/api/settings")
    def put_settings(body: SettingsBody) -> dict[str, Any]:
        nonlocal config
        raw, _exists, _text = _settings_read_raw()
        try:
            write_config(_BASE_CONFIG, _settings_merge(raw, body.settings))
            config = load_config(_BASE_CONFIG)  # les entrees de file suivantes lisent le nouveau mode/backend
        except ConfigError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=f"valeur non enregistrable : {exc}") from exc
        app.state.config = config
        return _settings_detail(web_cfg)
    @app.get("/api/channels/{name}/keyframe")
    def channel_keyframe(name: str, video_id: str | None = None) -> FileResponse:
        _channel_preset_path(name)
        return FileResponse(_layout_keyframe_path(config, name, video_id), media_type="image/jpeg")

    @app.get("/api/channels/{name}/layout")
    def get_channel_layout(name: str) -> dict[str, Any]:
        return _layout_view(name)

    @app.put("/api/channels/{name}/layout")
    def put_channel_layout(name: str, body: LayoutBody) -> dict[str, Any]:
        _layout_save(name, body.model_dump())
        return _layout_view(name)
    # ----------------------------------------------------------------
    # Statistiques (SPEC-c100 E7)
    # ----------------------------------------------------------------

    @app.get("/api/stats")
    def stats(since: str | None = None, until: str | None = None) -> dict[str, Any]:
        return _stats(config, since, until)

    @app.post("/api/stats/import")
    async def stats_import(request: Request) -> dict[str, Any]:
        data = _stats_csv_from_multipart(request.headers.get("content-type", ""), await request.body())
        return {"imported": _stats_import(config, data)}

    @app.get("/api/events")
    def events_stream() -> StreamingResponse:
        return StreamingResponse(_event_stream(config), media_type="text/event-stream")

    # ----------------------------------------------------------------
    # Media
    # ----------------------------------------------------------------

    @app.get("/media/source/{video_id}")
    def media_source(video_id: str) -> FileResponse:
        if not _SAFE_ID.fullmatch(video_id):
            raise HTTPException(status_code=404, detail=f"identifiant invalide : {video_id!r}")
        path = _safe_video_file(Path(config.workspace_dir) / video_id, video_id)
        return FileResponse(path, media_type="video/mp4")

    @app.get("/media/clip/{video_id}/{clip_id}")
    def media_clip(video_id: str, clip_id: str) -> FileResponse:
        if not _SAFE_ID.fullmatch(video_id):
            raise HTTPException(status_code=404, detail=f"identifiant invalide : {video_id!r}")
        path = _safe_video_file(Path(config.output_dir) / video_id, clip_id)
        return FileResponse(path, media_type="video/mp4")

    @app.get("/media/clip/{video_id}/{clip_id}/thumbnail")
    def media_clip_thumbnail(video_id: str, clip_id: str) -> FileResponse:
        # Le web ne traite jamais de video (ADR-09ad) : pipeline.clip_thumbnail extrait et met en cache.
        if not _SAFE_ID.fullmatch(video_id):
            raise HTTPException(status_code=404, detail=f"identifiant invalide : {video_id!r}")
        _safe_video_file(Path(config.output_dir) / video_id, clip_id)  # 404 si le clip n'existe pas
        try:
            path = pipeline.clip_thumbnail(config, video_id, clip_id)
        except pipeline.PipelineError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})

    return app


# --------------------------------------------------------------------------
# Ecran Publication (SPEC-c100 E6, SPEC-fc0c §4) : vue d'une semaine de
# creneaux d'une chaine. Les creneaux viennent de channel.next_slots, les
# entrees de state/publish/<chaine>.json, les clips des sidecars ; l'API
# n'invente aucun statut (une entree sans sidecar est signalee `missing`).
# --------------------------------------------------------------------------


class PublishMoveBody(BaseModel):
    slot_at: str


def _publish_parse_slot(value: str) -> datetime:
    try:
        slot = datetime.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"slot_at invalide : {value!r} (attendu : date ISO avec fuseau)") from exc
    if slot.tzinfo is None:
        raise HTTPException(status_code=422, detail=f"slot_at sans fuseau horaire : {value!r} (attendu : date ISO avec décalage, ex. +02:00)")
    return slot


def _publish_week_start(week: str | None, tz: ZoneInfo) -> date:
    if not week:
        day = datetime.now(tz).date()
    else:
        try:
            day = date.fromisoformat(week)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"paramètre week invalide : {week!r} (attendu : AAAA-MM-JJ)") from exc
    return day - timedelta(days=day.weekday())


def _publish_entry_instant(entry: dict[str, Any], key: str) -> datetime | None:
    value = entry.get(key)
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=500,
            detail=f"fichier de publication illisible : {key} invalide pour {entry.get('video_id')}/{entry.get('clip_id')} ({value!r})",
        ) from exc


def _publish_clip_view(clips: dict[tuple[str, str], dict[str, Any]], channel: str, entry: dict[str, Any]) -> dict[str, Any]:
    clip = clips.get((entry["video_id"], entry["clip_id"]))
    if clip is not None:
        return clip
    return {
        "video_id": entry["video_id"], "clip_id": entry["clip_id"], "channel": channel, "missing": True,
        "publish_status": entry["status"], "slot_at": entry.get("slot_at"), "publish_error": entry.get("error"),
        "screen_title": None, "description": None, "hashtags": [], "video_url": None, "thumbnail_url": None,
    }


def _publish_week_view(config: Config, channel_name: str, week: str | None) -> dict[str, Any]:
    _config, channel = _load_channel(channel_name)
    tz = ZoneInfo(str(channel["timezone"]))
    monday = _publish_week_start(week, tz)
    start = datetime.combine(monday, time(0, 0), tzinfo=tz)
    end = datetime.combine(monday + timedelta(days=7), time(0, 0), tzinfo=tz)

    entries = _publish_entries(config, channel_name)
    clips = {(c["video_id"], c["clip_id"]): c for c in _list_clip_views(config, channel_name, None, None)}
    by_slot: dict[datetime, dict[str, Any]] = {}
    unscheduled, done = [], []
    for entry in entries.values():
        slot = _publish_entry_instant(entry, "slot_at")
        published = _publish_entry_instant(entry, "published_at")
        if slot is not None and entry["status"] in ("scheduled", "published", "failed"):
            by_slot[slot] = entry
        if entry["status"] == "approved" and slot is None:
            unscheduled.append(_publish_clip_view(clips, channel_name, entry))
        elif entry["status"] in ("published", "failed"):
            when = published or slot
            if when is not None and start <= when < end:
                done.append(_publish_clip_view(clips, channel_name, entry))

    slots = []
    if channel["slots"]:
        seen: set[datetime] = set()
        for slot in channel_mod.next_slots(channel, start - timedelta(microseconds=1), len(channel["slots"]) + 1):
            if slot >= end or slot in seen:
                continue
            seen.add(slot)
            entry = by_slot.get(slot)
            slots.append({
                "slot_at": slot.isoformat(),
                "clip": _publish_clip_view(clips, channel_name, entry) if entry is not None else None,
                "free": entry is None,
            })
    return {
        "channel": channel_name, "timezone": str(channel["timezone"]), "tiktok_account": channel["tiktok_account"],
        "week_start": monday.isoformat(), "week_end": (monday + timedelta(days=6)).isoformat(),
        "slots": slots, "unscheduled": unscheduled, "done": done,
        "reason": None if channel["slots"] else "aucun créneau défini dans [channel].slots",
    }
