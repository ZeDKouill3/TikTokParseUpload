"""Construction de l'application FastAPI de clipper/web (voir le docstring
du paquet). Appelee par ``python -m clipper serve`` et par les tests
(clipper.web.app.create_app avec un pipeline simule)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from clipper import pipeline
from clipper.config import Config, load_config

STATIC_DIR = Path(__file__).resolve().parent / "static"
# Video/clip ids sont soit des ids YouTube (11 caracteres alphanumeriques),
# soit des clip_id du pipeline (ex. "03-p2") : jamais de '/' ni de '..' pour
# empecher toute traversee de chemin dans /media.
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")


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


class SubmitBody(BaseModel):
    url: str


class DecideBody(BaseModel):
    decision: str
    start: float | None = None
    end: float | None = None
    comment: str | None = None


def create_app(config: Config | None = None) -> FastAPI:
    config = config or load_config()
    app = FastAPI(title="Clipper")
    app.state.config = config
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.post("/api/videos", status_code=202)
    def submit_video(body: SubmitBody, background_tasks: BackgroundTasks) -> JSONResponse:
        background_tasks.add_task(pipeline.run, body.url, config=config)
        return JSONResponse({"url": body.url, "submitted": True}, status_code=202)

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
    def start_render(video_id: str, background_tasks: BackgroundTasks) -> JSONResponse:
        background_tasks.add_task(pipeline.render, video_id, config=config)
        return JSONResponse({"video_id": video_id, "submitted": True}, status_code=202)

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
