"""Construction de l'application FastAPI de clipper/web (voir le docstring
du paquet). Appelee par ``python -m clipper serve`` et par les tests
(clipper.web.app.create_app avec un pipeline/worker simules).

ADR-4f6e §1 : cette API n'appelle jamais pipeline.run/render dans son propre
processus ; le traitement passe toujours par la file (clipper.worker)."""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from clipper import channel as channel_mod
from clipper import gpu as gpu_mod
from clipper import pipeline
from clipper import publish as publish_mod
from clipper import worker as worker_mod
from clipper.config import Config, load_config

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

    out = []
    for moment_id, part in sorted(parts_by_id.items()):
        scored = scores_by_id.get(moment_id, {})
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
        })
    return out


def _validate_video_id(video_id: str) -> None:
    if not _SAFE_ID.fullmatch(video_id):
        raise HTTPException(status_code=400, detail=f"identifiant video invalide : {video_id!r}")


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

_WATCH_DIR = Path("state") / "watch"
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


def _current_step(state: dict[str, Any]) -> str | None:
    steps = state.get("steps", {})
    for name, step in steps.items():
        if step.get("status") == "running":
            return name
    for name, step in steps.items():
        if step.get("status") != "done":
            return name
    return None


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


def _dashboard_watch() -> dict[str, Any]:
    pending: list[dict[str, Any]] = []
    for path in sorted(_WATCH_DIR.glob("*.json")) if _WATCH_DIR.is_dir() else []:
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


def _vram_used_mb() -> int:
    import torch  # lourd et optionnel : charge seulement si le device est CUDA

    if not torch.cuda.is_available():
        raise RuntimeError("torch.cuda n'est pas disponible")
    free, total = torch.cuda.mem_get_info()
    return (total - free) // _MIB


def _dashboard_hardware() -> dict[str, Any]:
    try:
        device = gpu_mod.get_device().type
    except Exception as exc:  # get_device ne leve pas en pratique ; jamais de device invente
        return {"hardware": None, "hardware_error": f"device illisible : {exc}"}
    hardware: dict[str, Any] = {"device": device, "vram_used_mb": None}
    if device != "cpu":
        try:
            hardware["vram_used_mb"] = _vram_used_mb()
        except Exception as exc:  # torch absent (ImportError), CUDA indisponible...
            hardware["vram_used_mb_error"] = f"VRAM utilisée illisible (torch) : {exc}"
    return {"hardware": hardware}


def _dashboard(config: Config) -> dict[str, Any]:
    out: dict[str, Any] = {}
    _fill(out, ("running", "failed", "queued"), "etat des videos (workspace/*/pipeline.json)",
          lambda: _dashboard_videos(config))
    queue_path = _queue_path(config)
    _fill(out, ("queue",), f"file d'attente ({queue_path.name})",
          lambda: {"queue": _read_json(queue_path) if queue_path.exists() else []})
    _fill(out, ("watch_pending",), "surveillance (state/watch)", _dashboard_watch)
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

    app = FastAPI(title="Clipper")
    app.state.config = config
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
            clips.append(clip)
        return clips

    # ----------------------------------------------------------------
    # Chaines (SPEC-fc0c §1) et temps reel (ADR-4f6e §4)
    # ----------------------------------------------------------------

    @app.get("/api/channels")
    def list_channels_route() -> list[str]:
        return channel_mod.list_channels(_PRESETS_DIR)

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

    return app
