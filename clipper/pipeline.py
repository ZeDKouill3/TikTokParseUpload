"""Orchestrateur du pipeline clipper : seul module qui importe les etapes
(ADR-b16b). La CLI (``python -m clipper``) et l'interface web passent par lui.

Enchainement, par video (``STEPS``, dans l'ordre d'execution) :

    download, transcribe, scenes, audio, moments, vision, parts,
    captions, reframe, subtitles, render, qa

- chaque etape saute d'elle-meme ce qui est deja fait (resultat present sous
  workspace/<video_id>/ ou output/<video_id>/), sauf ``force`` ;
- ``moments`` recoit ``examples=feedback.examples(k)`` ; apres ``vision``,
  moments est relance sans force : si vision.json est plus recent que
  moments.json, ses candidats sont re-notes (bonus des images marquantes)
  sans nouvel appel LLM ;
- un seul modele lourd en VRAM a la fois (ADR-fb9b) : les etapes tournent en
  sequence et chacune libere son modele (whisper dans transcribe, detecteur de
  visages dans reframe) avant de rendre la main ;
- ``reframe`` passe avant ``subtitles`` : les bandes a ne pas recouvrir
  (``avoid_zones``) se deduisent plan par plan des visages du plan de
  recadrage, et la bande de l'accroche (``hook_zones``) des reglages de
  render ;
- un clip n'est pret que si ``qa.is_ready`` le dit.

Modes (``mode`` de config.toml, ADR-ad2e) :

- ``review`` : ``run`` s'arrete apres moments et parts (statut
  ``awaiting_review``) ; chaque moment de parts.json attend une decision
  humaine, donnee par ``decide`` (journalisee par clipper.feedback, et gardee
  dans workspace/<video_id>/review.json) ; ``render`` reprend : moments
  refuses retires de parts.json, bornes ajustees reportees dans moments.json
  (parts refait), puis captions .. qa. Sans decision pour chaque moment,
  ``render`` refuse.
- ``auto`` : ``run`` va jusqu'au bout. Une erreur transitoire (quota, reseau,
  surcharge : ``llm.TransientLLMError``, erreurs reseau) met la video en file
  d'attente (statut ``queued``, ``retry_at`` d'apres ``retry_delays``) ;
  ``process_queue`` la reprend a l'heure dite. Au-dela de ``max_attempts``,
  ou pour toute autre erreur : ``failed``. Aucune valeur de secours.

Etat par video : workspace/<video_id>/pipeline.json, reecrit a chaque
transition (lisible a tout moment, par exemple par l'interface web) :

    {
      "video_id": "abcdefghijk",
      "source_url": "https://www.youtube.com/watch?v=abcdefghijk",
      "mode": "review" | "auto",
      "status": "pending" | "running" | "awaiting_review" | "queued"
                | "done" | "failed",
      "reason": null | "pourquoi failed / queued",
      "attempts": 0,              # echecs transitoires consecutifs
      "retry_at": null | "ISO 8601 UTC",   # queued seulement
      "awaiting": [0, 3],         # moments sans decision (awaiting_review)
      "updated_at": "ISO 8601 UTC",
      "steps": {                  # une entree par nom de STEPS, dans l'ordre
        "download": {"status": "pending" | "running" | "done" | "failed",
                     "reason": null | "Type: message de l'erreur",
                     "started_at": null | "ISO", "finished_at": null | "ISO"},
        ...
      },
      "clips": [                  # rempli quand status = done
        {"clip_id": "03-p2", "ready": true, "qa_status": "passed",
         "issues": [...], "mp4": "output/.../03-p2.mp4",
         "json": "output/.../03-p2.json"}
      ]
    }
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from clipper import (
    audio,
    captions,
    download,
    feedback,
    llm,
    moments,
    parts,
    qa,
    reframe,
    render as render_step,
    scenes,
    subtitles,
    transcribe,
    vision,
)
from clipper.config import Config, load_config

log = logging.getLogger(__name__)

CONFIG_DEFAULTS: dict[str, object] = {
    # Echecs transitoires consecutifs avant de passer la video en failed.
    "max_attempts": 5,
    # Delais (s) avant re-essai, par echec ; le dernier sert au-dela.
    "retry_delays": [300, 900, 1800, 3600],
    # Decisions passees (clipper.feedback) donnees en exemples a moments.
    "feedback_examples": 10,
}

STEPS = (
    "download", "transcribe", "scenes", "audio", "moments", "vision", "parts",
    "captions", "reframe", "subtitles", "render", "qa",
)
STEP_STATUSES = ("pending", "running", "done", "failed")
# Premiere etape qui suit la revue humaine en mode review.
_AFTER_REVIEW = "captions"

EXIT_QUEUED = 75  # EX_TEMPFAIL

STATE_FILE = "pipeline.json"
REVIEW_FILE = "review.json"


class PipelineError(Exception):
    """Demande impossible en l'etat : video inconnue, decisions manquantes,
    decision invalide."""


# --------------------------------------------------------------------------
# Etat
# --------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _video_dir(video_id: str, config: Config) -> Path:
    return Path(config.workspace_dir) / video_id


def new_state(video_id: str, source_url: str, mode: str) -> dict[str, Any]:
    return {
        "video_id": video_id,
        "source_url": source_url,
        "mode": mode,
        "status": "pending",
        "reason": None,
        "attempts": 0,
        "retry_at": None,
        "awaiting": [],
        "updated_at": _iso(_now()),
        "steps": {
            name: {"status": "pending", "reason": None, "started_at": None, "finished_at": None}
            for name in STEPS
        },
        "clips": [],
    }


# Sous Windows, Path.replace leve PermissionError si un autre processus (CLI
# de progression, interface web) a le fichier destination ouvert en lecture au
# meme instant : CreateFile ne pose pas FILE_SHARE_DELETE par defaut, et
# MoveFileExW echoue tant que ce handle est ouvert. La collision est
# transitoire (le lecteur referme vite), donc on reessaie avant de relever.
_REPLACE_ATTEMPTS = 5
_REPLACE_DELAY_S = 0.05


def _atomic_replace(tmp: Path, path: Path) -> None:
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            tmp.replace(path)
            return
        except PermissionError:
            if attempt == _REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(_REPLACE_DELAY_S)


def save_state(state: dict[str, Any], *, config: Config | None = None) -> Path:
    config = config or load_config()
    path = _video_dir(state["video_id"], config) / STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = _iso(_now())
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    _atomic_replace(tmp, path)
    return path


def load_state(video_id: str, *, config: Config | None = None) -> dict[str, Any]:
    config = config or load_config()
    path = _video_dir(video_id, config) / STATE_FILE
    if not path.exists():
        raise PipelineError(f"aucun etat pour la video {video_id} ({path}) : lancer d'abord 'run <url>'")
    return json.loads(path.read_text(encoding="utf-8"))


def _read_json(path: Path) -> Any:
    if not path.exists():
        raise PipelineError(f"fichier absent : {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: Any) -> None:
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    _atomic_replace(tmp, path)


# --------------------------------------------------------------------------
# Erreurs transitoires
# --------------------------------------------------------------------------


def _transient_types() -> tuple[type[BaseException], ...]:
    types: list[type[BaseException]] = [
        llm.TransientLLMError, ConnectionError, TimeoutError, urllib.error.URLError,
    ]
    try:
        from yt_dlp.networking.exceptions import TransportError

        types.append(TransportError)
    except ImportError:
        pass
    return tuple(types)


def is_transient(exc: BaseException) -> bool:
    """Vrai si l'erreur (ou une erreur qu'elle enveloppe : cause, contexte,
    ``exc_info`` de yt-dlp) peut disparaitre en reessayant plus tard."""
    types = _transient_types()
    seen: set[int] = set()
    todo: list[BaseException | None] = [exc]
    while todo:
        e = todo.pop()
        if e is None or id(e) in seen:
            continue
        seen.add(id(e))
        if isinstance(e, llm.LLMError) and not isinstance(e, llm.TransientLLMError):
            continue
        if isinstance(e, types):
            return True
        wrapped = getattr(e, "exc_info", None)
        if isinstance(wrapped, tuple) and len(wrapped) > 1 and isinstance(wrapped[1], BaseException):
            todo.append(wrapped[1])
        todo += [e.__cause__, e.__context__]
    return False


# --------------------------------------------------------------------------
# Etapes
# --------------------------------------------------------------------------


class _Run:
    """Contexte d'un passage du pipeline sur une video."""

    def __init__(self, state: dict[str, Any], config: Config, force: bool,
                 step_options: dict[str, dict[str, Any]] | None):
        self.state = state
        self.config = config
        self.force = force
        self.options = step_options or {}
        self.video_id = state["video_id"]
        self.ws = Path(config.workspace_dir)
        self.out = Path(config.output_dir)
        self.dir = self.ws / self.video_id

    def opts(self, name: str) -> dict[str, Any]:
        return dict(self.options.get(name, {}))

    def journal(self) -> str:
        return str(self.config.section("feedback")["journal_path"])

    def clips(self) -> list[dict[str, Any]]:
        return _read_json(self.dir / "captions.json")["clips"]

    # -- une methode par etape -------------------------------------------

    def download(self) -> None:
        settings = self.config.section("download")
        download.download(self.state["source_url"], self.ws, **settings, **self.opts("download"))

    def transcribe(self) -> None:
        transcribe.transcribe(self.video_id, self.ws, config=self.config, force=self.force,
                              **self.opts("transcribe"))

    def scenes(self) -> None:
        settings = self.config.section("scenes")
        scenes.detect_scenes(self.dir / f"{self.video_id}.mp4", self.ws, self.video_id,
                             force=self.force, **settings, **self.opts("scenes"))

    def audio(self) -> None:
        s = self.config.section("audio")
        audio.run(self.video_id, self.ws, force=self.force, sample_rate=s["sample_rate"],
                  window_seconds=s["window_seconds"], median_window_seconds=s["median_window_seconds"],
                  threshold_db=s["peak_threshold_db"], **self.opts("audio"))

    def _moments(self, force: bool) -> None:
        k = int(self.config.section("pipeline")["feedback_examples"])
        examples = feedback.examples(k, path=self.journal())
        moments.run(self.video_id, self.ws, config=self.config, force=force, examples=examples,
                    **self.opts("moments"))

    def moments(self) -> None:
        self._moments(self.force)

    def vision(self) -> None:
        vision.run(self.video_id, self.ws, config=self.config, force=self.force, **self.opts("vision"))
        # vision.json plus recent que moments.json : moments, relance sans
        # force, re-note ses candidats (bonus visuel) sans rappeler le LLM.
        self._moments(False)

    def parts(self) -> None:
        parts.run(self.video_id, self.ws, config=self.config, force=self.force, **self.opts("parts"))

    def captions(self) -> None:
        if self.config.mode == "review":
            _apply_review(self)
        captions.run(self.video_id, self.ws, config=self.config, force=self.force, **self.opts("captions"))

    def reframe(self) -> None:
        for clip in self.clips():
            reframe.reframe(self.video_id, clip["id"], clip["start"], clip["end"], self.ws,
                            config=self.config, force=self.force, **self.opts("reframe"))

    def subtitles(self) -> None:
        for clip in self.clips():
            plan = _read_json(self.dir / "reframe" / f"{clip['id']}.json")
            subtitles.generate(self.video_id, clip["id"], clip["start"], clip["end"], self.ws,
                               config=self.config, force=self.force, avoid_zones=avoid_zones(plan),
                               reserved_zones=hook_zones(clip, self.config), **self.opts("subtitles"))

    def render(self) -> None:
        for clip in self.clips():
            render_step.render(self.video_id, clip["id"], self.ws, self.out, config=self.config,
                               force=self.force, **self.opts("render"))

    def qa(self) -> None:
        if not self.clips():
            return
        qa.run(self.video_id, self.ws, self.out, config=self.config, force=self.force, **self.opts("qa"))


def avoid_zones(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Bandes verticales [haut, bas] (fraction de la hauteur de sortie)
    couvertes par les visages, plan par plan d'un plan de recadrage
    (reframe/<clip_id>.json) : ``[{"start", "end", "bands"}]``, temps en
    secondes de la video. Chaque visage visible dans un panneau donne sa
    propre bande (deux visages eloignes ne bloquent pas l'espace entre eux) ;
    le fond flou ne compte pas. Les sous-titres ne recouvrent pas ces bandes
    (SPEC-350f)."""
    out_h = float(plan["output"]["height"])
    zones = []
    for p in plan["plans"]:
        bands: list[list[float]] = []
        for face in p["faces"]:
            x0, y0, x1, y1 = face["box"]
            for panel in p["panels"]:
                if panel.get("effect") == "blur":
                    continue
                dest = panel["dest"]
                for r in panel["rects"]:
                    if face["last"] < r["start"] or face["first"] > r["end"]:
                        continue
                    iy0, iy1 = max(y0, r["y"]), min(y1, r["y"] + r["h"])
                    if max(x0, r["x"]) >= min(x1, r["x"] + r["w"]) or iy0 >= iy1:
                        continue
                    scale = dest["h"] / r["h"]
                    fy0 = dest["y"] + (iy0 - r["y"]) * scale
                    fy1 = dest["y"] + (iy1 - r["y"]) * scale
                    band = [max(0.0, fy0 / out_h), min(1.0, fy1 / out_h)]
                    if band not in bands:
                        bands.append(band)
        zones.append({"start": p["start"], "end": p["end"], "bands": bands})
    return zones


# Hauteur de ligne de l'accroche, en multiple de sa taille de police : marge
# pour les jambages et le contour du texte dessine par render (drawtext).
HOOK_LINE_HEIGHT = 1.5


def hook_zones(clip: dict[str, Any], config: Config) -> list[dict[str, Any]]:
    """Bande de l'accroche que render dessine en haut du clip (une ligne a
    ``hook_margin_top`` px, ``hook_seconds`` premieres secondes), au format de
    ``avoid_zones`` : les sous-titres ne la recouvrent jamais."""
    s = config.section("render")
    top = float(s["hook_margin_top"])
    bottom = top + HOOK_LINE_HEIGHT * float(s["hook_font_size"])
    return [{"start": clip["start"], "end": clip["start"] + float(s["hook_seconds"]),
             "bands": [[top / subtitles.PLAY_RES_Y, bottom / subtitles.PLAY_RES_Y]]}]


# --------------------------------------------------------------------------
# Revue humaine
# --------------------------------------------------------------------------


def _read_review(video_dir: Path) -> dict[str, Any]:
    path = video_dir / REVIEW_FILE
    if not path.exists():
        return {"decisions": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def _undecided(video_dir: Path) -> list[int]:
    ids = [m["id"] for m in _read_json(video_dir / "parts.json")["moments"]]
    decisions = _read_review(video_dir)["decisions"]
    return [i for i in ids if str(i) not in decisions]


def _apply_review(run: _Run) -> None:
    """Applique les decisions humaines avant captions : bornes ajustees dans
    moments.json (parts refait), moments refuses sortis de parts.json."""
    decisions = _read_review(run.dir)["decisions"]

    moments_path = run.dir / "moments.json"
    moments_data = _read_json(moments_path)
    adjusted = False
    for m in moments_data["moments"]:
        d = decisions.get(str(m["id"]))
        if d and d["decision"] == "adjusted" and (m["start"], m["end"]) != (d["start"], d["end"]):
            m["start"], m["end"] = d["start"], d["end"]
            m["duration"] = round(d["end"] - d["start"], 3)
            adjusted = True
    if adjusted:
        _write_json(moments_path, moments_data)
        parts.run(run.video_id, run.ws, config=run.config, force=True, **run.opts("parts"))

    parts_path = run.dir / "parts.json"
    parts_data = _read_json(parts_path)
    kept, refused = [], []
    for m in parts_data["moments"]:
        (refused if decisions[str(m["id"])]["decision"] == "rejected" else kept).append(m)
    if refused:
        parts_data["moments"] = kept
        parts_data["rejected"] = parts_data.get("rejected", []) + [
            {"id": m["id"], "start": m["start"], "end": m["end"], "duration": m["duration"],
             "reason": "refuse en revue humaine"}
            for m in refused
        ]
        _write_json(parts_path, parts_data)


def _moment_text(video_dir: Path, start: float, end: float) -> str:
    transcript = _read_json(video_dir / "transcript.json")
    words = [w["word"] for seg in transcript["segments"] for w in seg["words"]
             if w["start"] >= start - 1e-6 and w["end"] <= end + 1e-6]
    return "".join(words).strip()


def decide(
    video_id: str,
    moment_id: int,
    decision: str,
    *,
    start: float | None = None,
    end: float | None = None,
    comment: str | None = None,
    config: Config | None = None,
) -> dict[str, Any]:
    """Enregistre la decision humaine sur un moment (accepted | rejected |
    adjusted, ce dernier avec ses nouvelles bornes) : journal clipper.feedback
    et workspace/<video_id>/review.json. Renvoie l'entree du journal."""
    config = config or load_config()
    if decision not in feedback.VALID_DECISIONS:
        raise PipelineError(f"decision invalide {decision!r} (attendu : {' | '.join(feedback.VALID_DECISIONS)})")
    if decision == "adjusted":
        if start is None or end is None or not end > start >= 0:
            raise PipelineError("une decision adjusted demande des bornes start < end (--start, --end)")
    elif start is not None or end is not None:
        raise PipelineError(f"bornes donnees pour une decision {decision} : seules les decisions adjusted en ont")

    video_dir = _video_dir(video_id, config)
    by_id = {m["id"]: m for m in _read_json(video_dir / "moments.json")["moments"]}
    if moment_id not in by_id:
        raise PipelineError(f"moment {moment_id} absent de {video_dir / 'moments.json'} (ids : {sorted(by_id)})")

    moment = dict(by_id[moment_id])
    if decision == "adjusted":
        moment.update(start=start, end=end, duration=round(end - start, 3))
    text = _moment_text(video_dir, moment["start"], moment["end"])
    entry = feedback.record(video_id, moment, decision, text, comment,
                            path=config.section("feedback")["journal_path"])

    review = _read_review(video_dir)
    review["decisions"][str(moment_id)] = {
        "decision": decision, "start": moment["start"], "end": moment["end"],
        "comment": comment, "at": entry["horodatage"],
    }
    _write_json(video_dir / REVIEW_FILE, review)

    try:
        state = load_state(video_id, config=config)
    except PipelineError:
        return entry
    if (video_dir / "parts.json").exists():
        state["awaiting"] = _undecided(video_dir)
        save_state(state, config=config)
    return entry


# --------------------------------------------------------------------------
# Enchainement
# --------------------------------------------------------------------------


def _summary(run: _Run) -> list[dict[str, Any]]:
    out = []
    for clip in run.clips():
        json_path = run.out / run.video_id / f"{clip['id']}.json"
        data = _read_json(json_path)
        out.append({
            "clip_id": clip["id"],
            "ready": qa.is_ready(data),
            "qa_status": data["qa"]["status"],
            "issues": data["qa"]["issues"],
            "mp4": str(json_path.with_suffix(".mp4")),
            "json": str(json_path),
        })
    return out


def _fail(run: _Run, name: str, exc: BaseException) -> dict[str, Any]:
    state, config = run.state, run.config
    reason = f"{type(exc).__name__}: {exc}"
    step = state["steps"][name]
    step.update(status="failed", reason=reason, finished_at=_iso(_now()))
    settings = config.section("pipeline")
    if config.mode == "auto" and is_transient(exc):
        state["attempts"] += 1
        max_attempts = int(settings["max_attempts"])
        if state["attempts"] < max_attempts:
            delays = list(settings["retry_delays"])
            delay = delays[min(state["attempts"], len(delays)) - 1]
            state.update(status="queued", reason=f"{name} : {reason}",
                         retry_at=_iso(_now() + timedelta(seconds=float(delay))))
            log.warning("%s : %s en echec transitoire, re-essai a %s", run.video_id, name, state["retry_at"])
            save_state(state, config=config)
            return state
        reason = f"{reason} ({state['attempts']} echecs transitoires, max_attempts = {max_attempts})"
    state.update(status="failed", reason=f"{name} : {reason}", retry_at=None)
    log.error("%s : etape %s en echec : %s", run.video_id, name, reason)
    save_state(state, config=config)
    return state


def _advance(run: _Run, *, through_review: bool) -> dict[str, Any]:
    state, config = run.state, run.config
    state.update(status="running", reason=None, retry_at=None, mode=config.mode)
    save_state(state, config=config)

    for name in STEPS:
        if name == _AFTER_REVIEW and config.mode == "review":
            state["awaiting"] = _undecided(run.dir)
            reviewed = state["steps"][_AFTER_REVIEW]["status"] == "done"
            if state["awaiting"] or not (through_review or reviewed):
                state.update(status="awaiting_review", reason=None)
                save_state(state, config=config)
                if through_review:
                    raise PipelineError(
                        f"decisions manquantes pour les moments {state['awaiting']} de {run.video_id} : "
                        f"python -m clipper decide {run.video_id} <moment_id> accepted|rejected|adjusted"
                    )
                return state

        step = state["steps"][name]
        step.update(status="running", reason=None, started_at=_iso(_now()), finished_at=None)
        save_state(state, config=config)
        log.info("%s : etape %s", run.video_id, name)
        try:
            getattr(run, name)()
        except Exception as exc:  # noqa: BLE001 - toute erreur est journalisee dans l'etat
            log.debug("%s : %s", run.video_id, name, exc_info=True)
            return _fail(run, name, exc)
        step.update(status="done", finished_at=_iso(_now()))
        save_state(state, config=config)

    state.update(status="done", reason=None, retry_at=None, attempts=0, clips=_summary(run))
    save_state(state, config=config)
    return state


def _start(state: dict[str, Any], config: Config, force: bool,
           step_options: dict[str, dict[str, Any]] | None) -> _Run:
    if force:
        for step in state["steps"].values():
            step.update(status="pending", reason=None, started_at=None, finished_at=None)
    return _Run(state, config, force, step_options)


def run(
    url: str,
    *,
    config: Config | None = None,
    force: bool = False,
    step_options: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Traite la video ``url`` : jusqu'a la revue en mode review, jusqu'au
    bout en mode auto. Renvoie l'etat (voir le docstring du module).

    ``step_options`` : arguments supplementaires par etape (injection pour
    les tests, ex. ``{"download": {"ydl_factory": ...}}``)."""
    config = config or load_config()
    try:
        video_id = download.extract_video_id(url)
    except download.DownloadError as exc:
        raise PipelineError(str(exc)) from exc
    try:
        state = load_state(video_id, config=config)
    except PipelineError:
        state = new_state(video_id, url, config.mode)
    state["source_url"] = url
    return _advance(_start(state, config, force, step_options), through_review=False)


def render(
    video_id: str,
    *,
    config: Config | None = None,
    force: bool = False,
    step_options: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Reprend une video deja lancee jusqu'au bout (captions .. qa) ; en mode
    review, exige une decision pour chaque moment (PipelineError sinon)."""
    config = config or load_config()
    state = load_state(video_id, config=config)
    return _advance(_start(state, config, force, step_options), through_review=True)


def queued(*, config: Config | None = None) -> list[dict[str, Any]]:
    """Etats des videos en file d'attente, par retry_at croissant."""
    config = config or load_config()
    root = Path(config.workspace_dir)
    states = []
    for path in sorted(root.glob(f"*/{STATE_FILE}")) if root.is_dir() else []:
        state = json.loads(path.read_text(encoding="utf-8"))
        if state["status"] == "queued":
            states.append(state)
    return sorted(states, key=lambda s: s["retry_at"])


def process_queue(
    *,
    config: Config | None = None,
    now: datetime | None = None,
    step_options: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Reprend chaque video en file dont ``retry_at`` est passe ; renvoie
    leurs nouveaux etats."""
    config = config or load_config()
    now = now or _now()
    out = []
    for state in queued(config=config):
        if datetime.fromisoformat(state["retry_at"]) > now:
            continue
        out.append(_advance(_start(state, config, False, step_options), through_review=True))
    return out


def watch_queue(*, config: Config | None = None, interval: float = 60.0) -> None:
    """Traite la file d'attente en boucle (jusqu'a interruption)."""
    config = config or load_config()
    while True:
        process_queue(config=config)
        time.sleep(interval)
