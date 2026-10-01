"""Construction de l'application FastAPI de clipper/web (voir le docstring
du paquet). Appelee par ``python -m clipper serve`` et par les tests
(clipper.web.app.create_app avec un pipeline/worker simules).

ADR-4f6e §1 : cette API n'appelle jamais pipeline.run/render dans son propre
processus ; le traitement passe toujours par la file (clipper.worker)."""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from clipper import channel as channel_mod
from clipper import pipeline
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
        try:
            worker_mod.move_to_front(video_id, config=config)
        except worker_mod.WorkerError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"video_id": video_id, "moved": True}

    @app.delete("/api/queue/{video_id}")
    def queue_remove(video_id: str) -> dict[str, Any]:
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
    def list_videos() -> list[dict[str, Any]]:
        return _list_states(config)

    @app.get("/api/videos/{video_id}")
    def get_video(video_id: str) -> dict[str, Any]:
        try:
            return pipeline.load_state(video_id, config=config)
        except pipeline.PipelineError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

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
        return _enqueue(video_id, _channel_of(video_id, config), "render", None, config)

    @app.post("/api/videos/{video_id}/cancel")
    def cancel_video(video_id: str) -> dict[str, Any]:
        try:
            worker_mod.Worker(config=config).cancel(video_id)
        except worker_mod.WorkerError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"video_id": video_id, "cancelled": True}

    @app.post("/api/videos/{video_id}/retry", status_code=202)
    def retry_video(video_id: str, body: RetryBody) -> JSONResponse:
        if body.from_step not in pipeline.STEPS:
            raise HTTPException(status_code=400, detail=f"etape inconnue : {body.from_step!r}")
        force_steps = list(pipeline.STEPS[pipeline.STEPS.index(body.from_step):])
        return _enqueue(video_id, _channel_of(video_id, config), "render", force_steps, config)

    @app.get("/api/videos/{video_id}/events")
    def video_events(video_id: str, since: str | None = None) -> list[dict[str, Any]]:
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
