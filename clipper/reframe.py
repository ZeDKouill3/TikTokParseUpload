"""Etape reframe : cadrage 9:16 plein ecran d'un clip, mise en page par plan,
visages jamais coupes.

Entrees : workspace/<video_id>/<video_id>.mp4 et scenes.json (etape scenes).
Sortie  : workspace/<video_id>/reframe/<clip_id>.json, plus une image
annotee par plan dans workspace/<video_id>/reframe/<clip_id>/.

    {"video_id", "clip_id", "start", "end",
     "source": {"width", "height"}, "output": {"width", "height"},
     "layout": mise en page couvrant la plus grande part du clip,
     "plans": [{"index", "start", "end", "image", "llm",
                "layout": facecam_gameplay | single | fallback_blur | split,
                "reason": pourquoi un repli (null sinon),
                "faces": [{"id", "first", "last", "box", "retained"}],
                "panels": [{"name", "dest": {x, y, w, h}, "effect"?,
                            "rects": [{"start", "end", "x", "y", "w", "h"}]}]}]}

Les temps sont absolus dans la video source (comme scenes.json). Chaque
panneau dit quelle zone de la source (``rects``, un rectangle par
intervalle de temps) va ou dans l'image de sortie (``dest``) :
- single : ``main`` plein ecran, qui suit le visage choisi ;
- facecam_gameplay : ``camera`` en haut, ``gameplay`` en bas ;
- split : ``top`` et ``bottom``, un visage chacun ;
- fallback_blur : ``background`` (source entiere, floutee, etiree en plein
  ecran, ``effect: blur``) sous ``main`` (source entiere, a l'echelle).

Deroulement :
1. plans du clip = scenes.json coupe a [start, end] ;
2. detection locale des visages (``detector`` en config, mediapipe par
   defaut) sur ``sample_fps`` images par seconde, doublons d'une meme image
   fusionnes (``duplicate_iou``), suivi en pistes numerotees, pistes qui se
   suivent a la meme place recollees ; le detecteur est ferme avant tout
   appel LLM (ADR-fb9b : un LLM local ne cohabite jamais avec lui). Un
   visage est *retenu* s'il est detecte assez souvent dans le plan
   (``min_face_presence``) et assez grand (``min_face_height``) : seuls les
   visages retenus (et celui que suit le cadre) sont gardes entiers ;
3. par plan, une image annotee (visages encadres, ``#id``) est envoyee a
   clipper.llm (usage ``layout``), qui repond facecam_gameplay (avec le
   rectangle de la camera) ou single (avec le visage a suivre) ;
4. plan de recadrage : position voulue lissee (moyenne glissante puis zone
   morte), puis ramenee dans l'ensemble des positions ou chaque visage
   suivi est entier dans le cadre et ou aucun autre visage retenu n'est
   coupe (entier dedans ou entier dehors). Sans position possible a un
   instant, le plan passe en repli ``split`` (deux visages retenus
   distincts, si ``fallback = auto`` ; chaque panneau cadre son visage a
   ``split_face_height``) ou ``fallback_blur``, avec la raison dans
   ``reason``.

Modele mediapipe : ``model_path`` (defaut
~/.cache/clipper/blaze_face_short_range.tflite) ; s'il manque, il est
telecharge une fois depuis ``model_url`` ; ``model_url = ""`` interdit le
telechargement (erreur explicite).
"""

from __future__ import annotations

import gc
import json
import logging
import math
import shutil
import urllib.request
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from clipper import llm
from clipper.gpu import Device, get_device

log = logging.getLogger(__name__)

CONFIG_DEFAULTS: dict[str, object] = {
    # Detecteur de visages local (seul "mediapipe" est fourni).
    "detector": "mediapipe",
    # Modele .tflite de mediapipe ; "" = ~/.cache/clipper/blaze_face_short_range.tflite.
    "model_path": "",
    # Telecharge une fois si model_path manque ; "" = jamais de telechargement.
    "model_url": (
        "https://storage.googleapis.com/mediapipe-models/face_detector/"
        "blaze_face_short_range/float16/latest/blaze_face_short_range.tflite"
    ),
    "min_confidence": 0.5,
    # Grilles de detection : 1 = image entiere, 2 = 2x2 tuiles qui se
    # chevauchent (visages petits, ex. facecam dans un coin).
    "tiles": [1, 2],
    # Images analysees par seconde de plan.
    "sample_fps": 5.0,
    # Une piste plus courte est une fausse detection, ignoree.
    "min_track_seconds": 0.5,
    # Deux detections d'une meme image dont l'IoU atteint ce seuil sont un
    # seul visage (ex. image entiere et tuile) : la plus sure est gardee. Le
    # meme seuil recolle deux pistes qui se suivent dans le temps (voir
    # track_merge_seconds).
    "duplicate_iou": 0.3,
    # Deux pistes dont la seconde commence au plus tant de secondes apres la
    # fin de la premiere, a la meme place (IoU des boites de jonction >=
    # duplicate_iou), sont un seul visage perdu un moment par le detecteur.
    "track_merge_seconds": 3.0,
    # Visage retenu (jamais coupe par le cadre) : reellement detecte sur au
    # moins cette part des images analysees du plan (une fausse detection
    # clignote, un vrai visage a l'image est vu presque partout)...
    "min_face_presence": 0.6,
    # ... et de hauteur moyenne au moins cette part de la hauteur source.
    # Les autres pistes restent annotees pour le LLM, mais ne contraignent
    # pas le cadre.
    "min_face_height": 0.05,
    # Ecran partage : part de la hauteur d'un panneau occupee par son visage
    # (le cadre est agrandi par paliers si l'autre visage retenu serait
    # coupe, jusqu'au plus grand cadre possible).
    "split_face_height": 0.35,
    # Marge autour de chaque visage (fraction de sa taille, de chaque cote) :
    # couvre le mouvement entre deux images analysees.
    "face_margin": 0.15,
    # Fenetre de la moyenne glissante du suivi.
    "smooth_seconds": 1.0,
    # Zone morte du suivi, fraction de la largeur du cadre.
    "deadzone": 0.1,
    # Part de la hauteur de sortie donnee a la camera en facecam_gameplay.
    "facecam_height_ratio": 0.4,
    # Repli quand aucun cadre ne garde les visages entiers :
    # "auto" = split si au moins deux visages, sinon fallback_blur ;
    # "blur" = toujours fallback_blur.
    "fallback": "auto",
    "output_width": 1080,
    "output_height": 1920,
    # Largeur maximale de l'image annotee envoyee au LLM.
    "annotated_max_width": 1280,
    "jpeg_quality": 90,
}

LAYOUTS = ("facecam_gameplay", "single")
_FALLBACKS = ("auto", "blur")

LAYOUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "layout": {"type": "string", "enum": list(LAYOUTS)},
        "camera": {
            "type": ["object", "null"],
            "properties": {k: {"type": "number", "minimum": 0, "maximum": 1} for k in "xywh"},
            "required": list("xywh"),
            "additionalProperties": False,
        },
        "face": {"type": ["integer", "null"]},
        "reason": {"type": "string"},
    },
    "required": ["layout", "camera", "face", "reason"],
    "additionalProperties": False,
}

Box = tuple[float, float, float, float]  # x0, y0, x1, y1 en pixels source
Detection = tuple[float, float, float, float, float]  # boite + score


class ReframeError(Exception):
    """Entree manquante, detecteur inconnu ou modele introuvable."""


class _Infeasible(Exception):
    """Aucun cadre ne garde les visages entiers : repli necessaire."""


# --------------------------------------------------------------------------
# Detecteur mediapipe
# --------------------------------------------------------------------------


def _default_model_path() -> Path:
    return Path.home() / ".cache" / "clipper" / "blaze_face_short_range.tflite"


def _download(url: str, dest: Path) -> None:
    with urllib.request.urlopen(url, timeout=60) as response, open(dest, "wb") as f:
        shutil.copyfileobj(response, f)


def ensure_mediapipe_model(
    settings: dict[str, Any], fetch: Callable[[str, Path], None] = _download
) -> Path:
    """Chemin du modele .tflite, telecharge une fois depuis ``model_url`` s'il
    manque."""
    path = Path(settings["model_path"]).expanduser() if settings["model_path"] else _default_model_path()
    if path.exists():
        return path
    url = settings["model_url"]
    if not url:
        raise ReframeError(
            f"modele mediapipe absent : {path} (le placer la, ou renseigner "
            "model_url dans [reframe] pour le telecharger)"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    log.info("telechargement du modele de visages %s -> %s", url, path)
    try:
        fetch(url, part)
    except Exception as exc:
        part.unlink(missing_ok=True)
        raise ReframeError(f"telechargement du modele mediapipe impossible ({url}) : {exc}") from exc
    part.replace(path)
    return path


def _nms(detections: list[Detection], iou_threshold: float) -> list[Detection]:
    kept: list[Detection] = []
    for det in sorted(detections, key=lambda d: d[4], reverse=True):
        if all(_iou(det[:4], k[:4]) < iou_threshold for k in kept):
            kept.append(det)
    return kept


def _tiles(width: int, height: int, n: int, overlap: float = 0.25) -> list[tuple[int, int, int, int]]:
    if n <= 1:
        return [(0, 0, width, height)]
    tw = min(width, math.ceil(width / n * (1 + overlap)))
    th = min(height, math.ceil(height / n * (1 + overlap)))
    xs = [round(i * (width - tw) / (n - 1)) for i in range(n)]
    ys = [round(i * (height - th) / (n - 1)) for i in range(n)]
    return [(x, y, x + tw, y + th) for y in ys for x in xs]


class _MediapipeDetector:
    def __init__(self, detector: Any, tiles: Sequence[int]):
        self._detector = detector
        self._grids = list(tiles) or [1]

    def detect(self, frame: np.ndarray) -> list[Detection]:
        import mediapipe as mp

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        height, width = rgb.shape[:2]
        found: list[Detection] = []
        for n in self._grids:
            for x0, y0, x1, y1 in _tiles(width, height, int(n)):
                tile = np.ascontiguousarray(rgb[y0:y1, x0:x1])
                image = mp.Image(image_format=mp.ImageFormat.SRGB, data=tile)
                for det in self._detector.detect(image).detections:
                    bb = det.bounding_box
                    score = det.categories[0].score if det.categories else 1.0
                    found.append((
                        x0 + max(0, bb.origin_x),
                        y0 + max(0, bb.origin_y),
                        x0 + min(x1 - x0, bb.origin_x + bb.width),
                        y0 + min(y1 - y0, bb.origin_y + bb.height),
                        float(score),
                    ))
        return found  # doublons image entiere / tuiles : fusionnes par _detect

    def close(self) -> None:
        if self._detector is not None:
            self._detector.close()
            self._detector = None


def mediapipe_detector(settings: dict[str, Any], device: Device) -> _MediapipeDetector:
    """FaceDetector mediapipe (Tasks API). Delegue GPU si clipper.gpu voit
    CUDA ; mediapipe ne le propose pas partout (Windows), auquel cas le CPU
    donne les memes detections, plus lentement."""
    from mediapipe.tasks.python import BaseOptions, vision

    model = ensure_mediapipe_model(settings)

    def build(delegate: Any) -> Any:
        options = vision.FaceDetectorOptions(
            base_options=BaseOptions(model_asset_path=str(model), delegate=delegate),
            min_detection_confidence=float(settings["min_confidence"]),
        )
        return vision.FaceDetector.create_from_options(options)

    if device.type == "cuda":
        try:
            return _MediapipeDetector(build(BaseOptions.Delegate.GPU), settings["tiles"])
        except Exception as exc:  # delegue GPU absent de cette plateforme
            log.warning("mediapipe : delegue GPU indisponible (%s), detection sur CPU", exc)
    return _MediapipeDetector(build(BaseOptions.Delegate.CPU), settings["tiles"])


_DETECTORS: dict[str, Callable[[dict[str, Any], Device], Any]] = {
    "mediapipe": mediapipe_detector,
}


# --------------------------------------------------------------------------
# Lecture des images
# --------------------------------------------------------------------------


def read_frames(video_path: Path, times: Sequence[float]) -> Iterator[tuple[float, np.ndarray]]:
    """Images de la video aux temps demandes (croissants), en lisant
    sequentiellement et en ne sautant qu'au-dela de quelques secondes."""
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise ReframeError(f"video illisible : {video_path}")
    try:
        fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
        half_frame = 0.5 / fps
        position: float | None = None
        for t in times:
            if position is None or t - position > 3.0 or t < position - half_frame:
                capture.set(cv2.CAP_PROP_POS_MSEC, max(0.0, t - half_frame) * 1000)
            while True:
                position = capture.get(cv2.CAP_PROP_POS_MSEC) / 1000
                if position >= t - half_frame:
                    break
                if not capture.grab():
                    raise ReframeError(f"image introuvable a {t:.3f}s dans {video_path}")
            ok, frame = capture.read()
            if not ok:
                raise ReframeError(f"image introuvable a {t:.3f}s dans {video_path}")
            position = capture.get(cv2.CAP_PROP_POS_MSEC) / 1000
            yield t, frame
    finally:
        capture.release()


# --------------------------------------------------------------------------
# Geometrie
# --------------------------------------------------------------------------


def _iou(a: Sequence[float], b: Sequence[float]) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def _center(box: Box) -> tuple[float, float]:
    return (box[0] + box[2]) / 2, (box[1] + box[3]) / 2


def _with_margin(box: Box, margin: float, width: int, height: int) -> Box:
    mx = (box[2] - box[0]) * margin
    my = (box[3] - box[1]) * margin
    return (max(0.0, box[0] - mx), max(0.0, box[1] - my), min(width, box[2] + mx), min(height, box[3] + my))


def _window(width: int, height: int, aspect: float) -> tuple[int, int]:
    """Plus grand cadre de rapport ``aspect`` (largeur/hauteur) dans la source."""
    if width / height > aspect:
        return min(width, round(height * aspect)), height
    return width, min(height, round(width / aspect))


def _contains(rect: tuple[int, int, int, int], box: Box) -> bool:
    x, y, w, h = rect
    return x <= box[0] and y <= box[1] and box[2] <= x + w and box[3] <= y + h


def _cuts(rect: tuple[int, int, int, int], box: Box) -> bool:
    x, y, w, h = rect
    touches = box[0] < x + w and x < box[2] and box[1] < y + h and y < box[3]
    return touches and not _contains(rect, box)


Intervals = list[tuple[int, int]]


def _intersect(a: Intervals, b: Intervals) -> Intervals:
    out: Intervals = []
    for lo1, hi1 in a:
        for lo2, hi2 in b:
            lo, hi = max(lo1, lo2), min(hi1, hi2)
            if lo <= hi:
                out.append((lo, hi))
    return sorted(out)


def _allowed(extent: int, win: int, required: Iterable[tuple[float, float]], others: Iterable[tuple[float, float]]) -> Intervals:
    """Positions entieres du bord gauche (ou haut) d'un cadre de taille
    ``win`` dans [0, extent] : chaque segment requis entier dedans, aucun
    autre segment coupe (entier dedans ou entier dehors)."""
    allowed: Intervals = [(0, extent - win)]
    for a0, a1 in required:
        allowed = _intersect(allowed, [(math.ceil(a1 - win), math.floor(a0))])
    for b0, b1 in others:
        allowed = _intersect(
            allowed,
            [
                (-(10**9), math.floor(b0 - win)),
                (math.ceil(b1 - win), math.floor(b0)),
                (math.ceil(b1), 10**9),
            ],
        )
    return allowed


def _project(x: float, allowed: Intervals) -> int | None:
    best: int | None = None
    for lo, hi in allowed:
        candidate = min(max(round(x), lo), hi)
        if best is None or abs(candidate - x) < abs(best - x):
            best = candidate
    return best


def _place_2d(
    width: int,
    height: int,
    w: int,
    h: int,
    required: Box | None,
    others: Sequence[Box],
    x: float,
    y: float,
) -> tuple[int, int] | None:
    """Position entiere (gauche, haut) d'un cadre ``w`` x ``h`` dans la source,
    la plus proche de (``x``, ``y``), qui garde ``required`` entier dedans et
    ne coupe aucun de ``others`` (entier dedans ou entier dehors). Chaque
    coordonnee de la meilleure position est soit la cible ramenee dans les
    bornes, soit une limite d'un des visages : ce sont les seules candidates."""
    xr = [(0, width - w)]
    yr = [(0, height - h)]
    if required is not None:
        xr = _intersect(xr, [(math.ceil(required[2] - w), math.floor(required[0]))])
        yr = _intersect(yr, [(math.ceil(required[3] - h), math.floor(required[1]))])
    if not xr or not yr:
        return None
    (xlo, xhi), (ylo, yhi) = xr[0], yr[0]

    def candidates(v: float, lo: int, hi: int, edges: Iterable[tuple[float, float]], size: int) -> list[int]:
        out = {round(v)}
        for b0, b1 in edges:
            out.update((math.floor(b0 - size), math.ceil(b1), math.floor(b0), math.ceil(b1 - size)))
        return sorted({min(max(c, lo), hi) for c in out})

    best: tuple[float, tuple[int, int]] | None = None
    for cx in candidates(x, xlo, xhi, [(b[0], b[2]) for b in others], w):
        for cy in candidates(y, ylo, yhi, [(b[1], b[3]) for b in others], h):
            if any(_cuts((cx, cy, w, h), b) for b in others):
                continue
            dist = (cx - x) ** 2 + (cy - y) ** 2
            if best is None or dist < best[0]:
                best = (dist, (cx, cy))
    return best[1] if best else None


def _nearest_known(values: list[Any]) -> list[Any]:
    """Chaque valeur manquante (None) remplacee par la plus proche connue."""
    known = [i for i, v in enumerate(values) if v is not None]
    return [v if v is not None else values[min(known, key=lambda k: abs(k - i))] for i, v in enumerate(values)]


def _smooth(values: list[float], radius: int, deadzone: float) -> list[float]:
    """Moyenne glissante centree, puis zone morte : le cadre ne bouge que
    si la cible s'eloigne de plus de ``deadzone``."""
    averaged = []
    for i in range(len(values)):
        window = values[max(0, i - radius): i + radius + 1]
        averaged.append(sum(window) / len(window))
    out: list[float] = []
    for value in averaged:
        if not out:
            out.append(value)
            continue
        delta = value - out[-1]
        out.append(out[-1] if abs(delta) <= deadzone else value - math.copysign(deadzone, delta))
    return out


# --------------------------------------------------------------------------
# Suivi des visages
# --------------------------------------------------------------------------


@dataclass
class _Track:
    id: int
    boxes: list[Box | None]  # une boite par image analysee, interpolee dans les trous
    detected: int = 0  # images ou le visage est reellement detecte (hors interpolation)
    retained: bool = True  # voir _retain : seul un visage retenu contraint le cadre

    def present(self) -> list[int]:
        return [i for i, b in enumerate(self.boxes) if b is not None]

    def span(self, i: int) -> Box | None:
        """Place balayee par le visage sur l'intervalle de l'image ``i`` (du
        milieu avec la precedente au milieu avec la suivante) : un visage
        rapide ne sort pas du cadre entre deux images analysees. Aux bords
        du plan, le mouvement est prolonge d'une demi-image."""
        box = self.boxes[i]
        if box is None:
            return None
        n = len(self.boxes)
        parts = [box]
        for j in (i - 1, i + 1):
            if 0 <= j < n and self.boxes[j] is not None:
                other = self.boxes[j]
                parts.append(tuple((a + b) / 2 for a, b in zip(box, other)))  # type: ignore[arg-type]
                if (i == 0 and j == 1) or (i == n - 1 and j == n - 2):
                    parts.append(tuple(a + (a - b) / 2 for a, b in zip(box, other)))  # type: ignore[arg-type]
        return (
            min(p[0] for p in parts),
            min(p[1] for p in parts),
            max(p[2] for p in parts),
            max(p[3] for p in parts),
        )

    def mean_box(self) -> Box:
        boxes = [b for b in self.boxes if b is not None]
        return tuple(sum(b[k] for b in boxes) / len(boxes) for k in range(4))  # type: ignore[return-value]


def _merge_fragments(raw: list[dict[int, Box]], max_gap: int, iou: float) -> list[dict[int, Box]]:
    """Recolle les pistes qui se suivent : une piste qui commence au plus
    ``max_gap`` images apres la fin d'une autre, a la meme place (IoU des
    boites de jonction >= ``iou``), la prolonge."""
    merged: list[dict[int, Box]] = []
    for seen in sorted(raw, key=min):
        first = min(seen)
        best: tuple[float, dict[int, Box]] | None = None
        for track in merged:
            last = max(track)
            if last < first and first - last <= max_gap:
                score = _iou(track[last], seen[first])
                if score >= iou and (best is None or score > best[0]):
                    best = (score, track)
        if best is None:
            merged.append(dict(seen))
        else:
            best[1].update(seen)
    return merged


def _build_tracks(detections: list[list[Box]], fps: float, settings: dict[str, Any]) -> list[_Track]:
    """Associe les detections d'une image a l'autre (plus proche d'abord),
    recolle les pistes qui se suivent a la meme place, comble les trous par
    interpolation lineaire, ecarte les pistes trop courtes, numerote de
    gauche a droite."""
    max_gap = max(1, round(fps))  # une seconde sans detection clot la piste
    raw: list[dict[int, Box]] = []
    last_seen: list[int] = []
    for i, boxes in enumerate(detections):
        pairs = []
        for d, box in enumerate(boxes):
            for t, track in enumerate(raw):
                gap = i - last_seen[t]
                if gap > max_gap:
                    continue
                prev = track[last_seen[t]]
                size = math.hypot(prev[2] - prev[0], prev[3] - prev[1])
                (cx, cy), (px, py) = _center(box), _center(prev)
                dist = math.hypot(cx - px, cy - py)
                if dist <= size * gap or _iou(box, prev) > 0.2:
                    pairs.append((dist, d, t))
        used_d: set[int] = set()
        used_t: set[int] = set()
        for _, d, t in sorted(pairs):
            if d in used_d or t in used_t:
                continue
            raw[t][i] = boxes[d]
            last_seen[t] = i
            used_d.add(d)
            used_t.add(t)
        for d, box in enumerate(boxes):
            if d not in used_d:
                raw.append({i: box})
                last_seen.append(i)
    raw = _merge_fragments(
        raw, round(float(settings["track_merge_seconds"]) * fps), float(settings["duplicate_iou"])
    )

    min_samples = max(1, math.ceil(float(settings["min_track_seconds"]) * fps - 1e-9))
    n = len(detections)
    tracks = []
    for seen in raw:
        if len(seen) < min_samples:
            continue
        filled: list[Box | None] = [None] * n
        keys = sorted(seen)
        for a, b in zip(keys, keys[1:] + [keys[-1]]):
            for i in range(a, b + 1):
                w = (i - a) / (b - a) if b > a else 0.0
                filled[i] = tuple(seen[a][k] * (1 - w) + seen[b][k] * w for k in range(4))  # type: ignore[assignment]
        tracks.append(_Track(id=-1, boxes=filled, detected=len(seen)))
    tracks.sort(key=lambda tr: _center(tr.mean_box())[0])
    for i, track in enumerate(tracks):
        track.id = i
    return tracks


def _retain(tracks: list[_Track], samples: int, height: int, settings: dict[str, Any]) -> None:
    """Marque les visages retenus : detectes sur au moins ``min_face_presence``
    des images du plan et de hauteur moyenne au moins ``min_face_height`` de
    la source. Une piste fantome, un visage minuscule ou une fausse detection
    qui clignote ne contraignent pas le cadre."""
    presence = float(settings["min_face_presence"])
    min_h = float(settings["min_face_height"]) * height
    for tr in tracks:
        box = tr.mean_box()
        tr.retained = tr.detected >= presence * samples - 1e-9 and box[3] - box[1] >= min_h


# --------------------------------------------------------------------------
# Plan de recadrage
# --------------------------------------------------------------------------


@dataclass
class _Plan:
    index: int
    start: float
    end: float
    times: list[float]
    detections: list[list[Box]] = field(default_factory=list)
    preview: np.ndarray | None = None
    preview_scale: float = 1.0
    preview_rank: tuple[int, float] = (-1, 0.0)
    preview_time: float = 0.0
    tracks: list[_Track] = field(default_factory=list)


def _sample_times(start: float, end: float, fps: float) -> list[float]:
    count = max(1, math.floor((end - start) * fps + 1e-9))
    step = (end - start) / count
    return [start + (k + 0.5) * step for k in range(count)]


def _bounds(plan: _Plan) -> list[tuple[float, float]]:
    """Intervalle couvert par chaque image analysee : du milieu avec la
    precedente au milieu avec la suivante, bornes du plan aux extremites."""
    cuts = [plan.start] + [(a + b) / 2 for a, b in zip(plan.times, plan.times[1:])] + [plan.end]
    return list(zip(cuts, cuts[1:]))


def _rects(plan: _Plan, positions: list[tuple[int, int, int, int]]) -> list[dict[str, Any]]:
    """Un rectangle par intervalle, les intervalles voisins identiques fusionnes."""
    out: list[dict[str, Any]] = []
    for (start, end), (x, y, w, h) in zip(_bounds(plan), positions):
        if out and (out[-1]["x"], out[-1]["y"], out[-1]["w"], out[-1]["h"]) == (x, y, w, h):
            out[-1]["end"] = end
        else:
            out.append({"start": start, "end": end, "x": x, "y": y, "w": w, "h": h})
    return out


class _Geometry:
    def __init__(self, width: int, height: int, settings: dict[str, Any]):
        self.width = width
        self.height = height
        self.settings = settings
        self.out_w = int(settings["output_width"])
        self.out_h = int(settings["output_height"])
        self.fps = float(settings["sample_fps"])

    def margin(self, box: Box) -> Box:
        return _with_margin(box, float(self.settings["face_margin"]), self.width, self.height)

    def follow(
        self,
        plan: _Plan,
        aspect: float,
        required: list[_Track],
        others: list[_Track],
        desired_center: tuple[float, float] | None = None,
    ) -> list[tuple[int, int, int, int]]:
        """Positions d'un cadre de rapport ``aspect`` qui suit les visages
        ``required`` (entiers dedans) sans couper ``others``."""
        ww, wh = _window(self.width, self.height, aspect)
        axis = 0 if ww < self.width else 1
        extent, win = (self.width, ww) if axis == 0 else (self.height, wh)
        n = len(plan.times)

        wanted: list[float | None] = []
        for i in range(n):
            boxes = [tr.boxes[i] for tr in required if tr.boxes[i] is not None]
            if boxes:
                wanted.append(sum(_center(b)[axis] for b in boxes) / len(boxes))
            elif not required and desired_center is not None:
                wanted.append(desired_center[axis])
            else:
                wanted.append(None)
        known = [w for w in wanted if w is not None]
        if not known:
            wanted = [extent / 2] * n
        else:  # instants sans cible : la plus proche position connue
            for i in range(n):
                if wanted[i] is None:
                    j = min((k for k in range(n) if wanted[k] is not None), key=lambda k: abs(k - i))
                    wanted[i] = wanted[j]
        lefts = [min(max(c - win / 2, 0.0), extent - win) for c in wanted]  # type: ignore[operator]
        radius = max(0, round(float(self.settings["smooth_seconds"]) * self.fps / 2))
        smoothed = _smooth(lefts, radius, float(self.settings["deadzone"]) * win)

        positions = []
        for i in range(n):
            req = [self.margin(tr.span(i)) for tr in required if tr.boxes[i] is not None]
            oth = [self.margin(tr.span(i)) for tr in others if tr.boxes[i] is not None]
            allowed = _allowed(
                extent,
                win,
                [(b[axis], b[axis + 2]) for b in req],
                [(b[axis], b[axis + 2]) for b in oth],
            )
            pos = _project(smoothed[i], allowed)
            if pos is None:
                faces = ", ".join(f"#{tr.id}" for tr in required) or "aucun"
                raise _Infeasible(
                    f"a {plan.times[i]:.2f}s, aucun cadre {ww}x{wh} ne garde entier(s) le(s) "
                    f"visage(s) {faces} sans couper un autre visage"
                )
            positions.append((pos, 0, win, wh) if axis == 0 else (0, pos, ww, win))
        return positions

    def dest(self, x: int, y: int, w: int, h: int) -> dict[str, int]:
        return {"x": x, "y": y, "w": w, "h": h}

    def single(self, plan: _Plan, face: int | None) -> list[dict[str, Any]]:
        required = [tr for tr in plan.tracks if tr.id == face]
        others = [tr for tr in plan.tracks if tr.id != face and tr.retained]
        positions = self.follow(plan, self.out_w / self.out_h, required, others)
        return [{"name": "main", "dest": self.dest(0, 0, self.out_w, self.out_h), "rects": _rects(plan, positions)}]

    def split(self, plan: _Plan) -> list[dict[str, Any]]:
        retained = [tr for tr in plan.tracks if tr.retained]
        if len(retained) < 2:
            raise _Infeasible("moins de deux visages retenus : pas d'ecran partage possible")
        # Les deux visages retenus les plus detectes, puis de gauche a droite.
        pair = sorted(retained, key=lambda tr: -tr.detected)[:2]
        pair.sort(key=lambda tr: _center(tr.mean_box())[0])
        half = self.out_h // 2
        panels = []
        for name, track, y, h in (("top", pair[0], 0, half), ("bottom", pair[1], half, self.out_h - half)):
            others = [tr for tr in retained if tr is not track]
            positions = self.frame(plan, self.out_w / h, track, others)
            panels.append({"name": name, "dest": self.dest(0, y, self.out_w, h), "rects": _rects(plan, positions)})
        return panels

    def frame(self, plan: _Plan, aspect: float, track: _Track, others: list[_Track]) -> list[tuple[int, int, int, int]]:
        """Positions d'un cadre de rapport ``aspect`` a la taille du visage
        ``track`` (``split_face_height``) et centre sur lui, sans couper
        ``others`` ; agrandi par paliers de 10 % jusqu'au plus grand cadre
        possible tant qu'aucune position ne convient."""
        max_w, max_h = _window(self.width, self.height, aspect)
        face_h = max(b[3] - b[1] for b in track.boxes if b is not None)
        h = face_h / float(self.settings["split_face_height"])
        while True:
            size = (max_w, max_h) if h >= max_h else (min(max_w, round(h * aspect)), round(h))
            try:
                return self._place(plan, *size, track, others)
            except _Infeasible:
                if size == (max_w, max_h):
                    raise
                h *= 1.1

    def _place(
        self, plan: _Plan, w: int, h: int, track: _Track, others: list[_Track]
    ) -> list[tuple[int, int, int, int]]:
        n = len(plan.times)
        centers = _nearest_known([_center(b) if b is not None else None for b in track.boxes])
        radius = max(0, round(float(self.settings["smooth_seconds"]) * self.fps / 2))
        deadzone = float(self.settings["deadzone"])
        xs = _smooth([min(max(c[0] - w / 2, 0.0), self.width - w) for c in centers], radius, deadzone * w)
        ys = _smooth([min(max(c[1] - h / 2, 0.0), self.height - h) for c in centers], radius, deadzone * h)
        positions = []
        for i in range(n):
            req = self.margin(track.span(i)) if track.boxes[i] is not None else None  # type: ignore[arg-type]
            oth = [self.margin(tr.span(i)) for tr in others if tr.boxes[i] is not None]  # type: ignore[arg-type]
            pos = _place_2d(self.width, self.height, w, h, req, oth, xs[i], ys[i])
            if pos is None:
                raise _Infeasible(
                    f"a {plan.times[i]:.2f}s, aucun cadre {w}x{h} ne garde entier le visage "
                    f"#{track.id} sans couper un autre visage"
                )
            positions.append((pos[0], pos[1], w, h))
        return positions

    def facecam(self, plan: _Plan, camera: dict[str, float]) -> list[dict[str, Any]]:
        cam_h = round(self.out_h * float(self.settings["facecam_height_ratio"]))
        zone = (
            camera["x"] * self.width,
            camera["y"] * self.height,
            (camera["x"] + camera["w"]) * self.width,
            (camera["y"] + camera["h"]) * self.height,
        )
        retained = [tr for tr in plan.tracks if tr.retained]
        inside = [tr for tr in retained if _contains_point(zone, _center(tr.mean_box()))]
        outside = [tr for tr in retained if tr not in inside]
        needed = [zone] + [self.margin(tr.span(i)) for tr in inside for i in tr.present()]
        x0 = min(b[0] for b in needed)
        y0 = min(b[1] for b in needed)
        x1 = max(b[2] for b in needed)
        y1 = max(b[3] for b in needed)

        aspect = self.out_w / cam_h
        bw, bh = x1 - x0, y1 - y0
        if bw / bh > aspect:
            bh = bw / aspect
        else:
            bw = bh * aspect
        w, h = math.ceil(bw), math.ceil(bh)
        if w > self.width or h > self.height:
            raise _Infeasible(f"la camera ({w}x{h} au format du panneau) depasse l'image source")
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        x = min(max(math.floor(cx - w / 2), 0), self.width - w)
        y = min(max(math.floor(cy - h / 2), 0), self.height - h)
        rect = (x, y, w, h)
        for i in range(len(plan.times)):
            for tr in retained:
                if tr.boxes[i] is None:
                    continue
                box = self.margin(tr.span(i))
                if (tr in inside and not _contains(rect, box)) or (tr in outside and _cuts(rect, box)):
                    raise _Infeasible(f"le panneau camera couperait le visage #{tr.id} a {plan.times[i]:.2f}s")
        camera_rects = _rects(plan, [rect] * len(plan.times))

        game_h = self.out_h - cam_h
        positions = self.follow(
            plan, self.out_w / game_h, [], retained, desired_center=(self.width / 2, self.height / 2)
        )
        return [
            {"name": "camera", "dest": self.dest(0, 0, self.out_w, cam_h), "rects": camera_rects},
            {"name": "gameplay", "dest": self.dest(0, cam_h, self.out_w, game_h), "rects": _rects(plan, positions)},
        ]

    def blur(self, plan: _Plan) -> list[dict[str, Any]]:
        full = _rects(plan, [(0, 0, self.width, self.height)] * len(plan.times))
        h = min(self.out_h, round(self.out_w * self.height / self.width))
        return [
            {"name": "background", "effect": "blur", "dest": self.dest(0, 0, self.out_w, self.out_h), "rects": full},
            {"name": "main", "dest": self.dest(0, (self.out_h - h) // 2, self.out_w, h), "rects": [dict(r) for r in full]},
        ]


def _contains_point(box: Box, point: tuple[float, float]) -> bool:
    return box[0] <= point[0] <= box[2] and box[1] <= point[1] <= box[3]


# --------------------------------------------------------------------------
# Appel LLM
# --------------------------------------------------------------------------


def _annotate(plan: _Plan, path: Path, quality: int) -> None:
    """Image la plus riche en visages du plan, visages encadres et numerotes."""
    assert plan.preview is not None
    image = plan.preview.copy()
    scale = plan.preview_scale
    k = plan.times.index(plan.preview_time)
    thickness = max(2, round(image.shape[1] / 400))
    for tr in plan.tracks:
        box = tr.boxes[k]
        if box is None:
            continue
        x0, y0, x1, y1 = (round(v * scale) for v in box)
        cv2.rectangle(image, (x0, y0), (x1, y1), (0, 255, 0), thickness)
        cv2.putText(
            image, f"#{tr.id}", (x0, max(0, y0 - 2 * thickness)),
            cv2.FONT_HERSHEY_SIMPLEX, thickness / 2, (0, 255, 0), thickness,
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(path), image, [cv2.IMWRITE_JPEG_QUALITY, quality]):
        raise ReframeError(f"ecriture de l'image annotee impossible : {path}")


def _prompt(plan: _Plan, width: int, height: int) -> str:
    if plan.tracks:
        faces = "\n".join(
            "- #{id} : environ x={x:.2f}, y={y:.2f} (normalise), present {p}/{n} images".format(
                id=tr.id,
                x=_center(tr.mean_box())[0] / width,
                y=_center(tr.mean_box())[1] / height,
                p=len(tr.present()),
                n=len(plan.times),
            )
            for tr in plan.tracks
        )
    else:
        faces = "(aucun visage detecte)"
    return (
        f"Image extraite d'un plan de video ({width}x{height}) qui va etre recadree en "
        "vertical 9:16 plein ecran pour TikTok. Les visages detectes sont encadres en vert "
        f"et numerotes :\n{faces}\n\n"
        "Choisis la mise en page :\n"
        "- facecam_gameplay : une webcam (facecam) incrustee par-dessus un jeu, un ecran "
        "partage ou une autre video. camera = rectangle de la webcam en coordonnees "
        "normalisees (x, y, w, h entre 0 et 1, origine en haut a gauche) ; face = null.\n"
        "- single : un plan filme classique. face = numero du visage a suivre (la personne "
        "qui parle ou le sujet principal), null s'il n'y a aucun visage ; camera = null.\n"
        "reason : une phrase de justification."
    )


def _check_answer(answer: dict[str, Any], plan: _Plan) -> None:
    """Contraintes que le schema JSON ne sait pas dire : une reponse qui les
    viole est un echec (ADR-b1c1), jamais une donnee."""
    if answer["layout"] == "facecam_gameplay":
        camera = answer["camera"]
        if camera is None:
            raise llm.SchemaError("layout facecam_gameplay sans rectangle camera")
        if camera["w"] <= 0 or camera["h"] <= 0:
            raise llm.SchemaError(f"rectangle camera vide : {camera}")
        if camera["x"] + camera["w"] > 1 + 1e-6 or camera["y"] + camera["h"] > 1 + 1e-6:
            raise llm.SchemaError(f"rectangle camera hors de l'image : {camera}")
    else:
        face = answer["face"]
        if face is not None and face not in {tr.id for tr in plan.tracks}:
            raise llm.SchemaError(
                f"visage #{face} inconnu (visages du plan : {[tr.id for tr in plan.tracks]})"
            )


# --------------------------------------------------------------------------
# Entree de l'etape
# --------------------------------------------------------------------------


def _settings(config: Any) -> dict[str, Any]:
    if config is None:
        from clipper.config import load_config

        config = load_config()
    settings = {**CONFIG_DEFAULTS, **config.section("reframe")}
    if settings["fallback"] not in _FALLBACKS:
        raise ReframeError(f"[reframe] fallback invalide {settings['fallback']!r} (attendu : {' | '.join(_FALLBACKS)})")
    return settings


def _plans(scenes_file: Path, start: float, end: float, fps: float) -> list[_Plan]:
    if not scenes_file.exists():
        raise ReframeError(f"scenes.json absent : {scenes_file}")
    scenes = json.loads(scenes_file.read_text(encoding="utf-8"))["scenes"]
    plans = []
    for scene in scenes:
        s, e = max(start, scene["start"]), min(end, scene["end"])
        if e - s > 1e-3:
            plans.append(_Plan(index=len(plans), start=s, end=e, times=_sample_times(s, e, fps)))
    if not plans:
        raise ReframeError(f"aucun plan de scenes.json ne recouvre le clip [{start}, {end}]")
    return plans


def _detect(
    plans: list[_Plan],
    video: Path,
    settings: dict[str, Any],
    factory: Callable[[dict[str, Any], Device], Any],
    frame_source: Callable[[Path, Sequence[float]], Iterable[tuple[float, np.ndarray]]],
) -> tuple[int, int]:
    """Detecte les visages sur toutes les images analysees du clip et garde
    par plan l'image la plus riche en visages ; le detecteur est libere
    avant de rendre la main (ADR-fb9b). Renvoie la taille de la source."""
    owner = {t: plan for plan in plans for t in plan.times}
    times = sorted(owner)
    min_conf = float(settings["min_confidence"])
    dup_iou = float(settings["duplicate_iou"])
    max_w = int(settings["annotated_max_width"])
    size: tuple[int, int] | None = None
    detector = factory(settings, get_device())
    try:
        for t, frame in frame_source(video, times):
            plan = owner[t]
            height, width = frame.shape[:2]
            size = size or (width, height)
            found = [tuple(float(v) for v in d[:5]) for d in detector.detect(frame) if d[4] >= min_conf]
            boxes = [d[:4] for d in _nms(found, dup_iou)]  # type: ignore[arg-type]
            plan.detections.append(boxes)  # type: ignore[arg-type]
            mid = (plan.start + plan.end) / 2
            rank = (len(boxes), -abs(t - mid))
            if rank > plan.preview_rank:
                scale = min(1.0, max_w / width)
                plan.preview = frame if scale == 1.0 else cv2.resize(frame, (round(width * scale), round(height * scale)))
                plan.preview_scale = scale
                plan.preview_rank = rank
                plan.preview_time = t
    finally:
        detector.close()
        detector = None
        gc.collect()
    if size is None or any(len(p.detections) != len(p.times) for p in plans):
        raise ReframeError(f"images manquantes dans {video}")
    return size


def _majority_layout(plans: list[dict[str, Any]]) -> str:
    durations: dict[str, float] = {}
    for plan in plans:
        durations[plan["layout"]] = durations.get(plan["layout"], 0.0) + plan["end"] - plan["start"]
    return max(durations, key=lambda k: durations[k])


def reframe(
    video_id: str,
    clip_id: str,
    start: float,
    end: float,
    workspace_dir: str | Path = "workspace",
    *,
    config: Any = None,
    force: bool = False,
    detector_factory: Callable[[dict[str, Any], Device], Any] | None = None,
    frame_source: Callable[[Path, Sequence[float]], Iterable[tuple[float, np.ndarray]]] = read_frames,
) -> Path:
    """Calcule le plan de recadrage du clip [start, end] de la video dans
    workspace/<video_id>/reframe/<clip_id>.json et renvoie ce chemin. Un
    resultat deja present n'est pas refait, sauf ``force``."""
    video_dir = Path(workspace_dir) / video_id
    out_dir = video_dir / "reframe"
    out = out_dir / f"{clip_id}.json"
    if out.exists() and not force:
        return out

    settings = _settings(config)
    if detector_factory is None:
        if settings["detector"] not in _DETECTORS:
            raise ReframeError(
                f"[reframe] detecteur inconnu {settings['detector']!r} (attendu : {' | '.join(_DETECTORS)})"
            )
        detector_factory = _DETECTORS[settings["detector"]]
    video = video_dir / f"{video_id}.mp4"
    if not video.exists():
        raise ReframeError(f"video absente : {video}")
    fps = float(settings["sample_fps"])
    plans = _plans(video_dir / "scenes.json", start, end, fps)

    width, height = _detect(plans, video, settings, detector_factory, frame_source)
    geometry = _Geometry(width, height, settings)
    for plan in plans:
        plan.tracks = _build_tracks(plan.detections, fps, settings)
        _retain(plan.tracks, len(plan.times), height, settings)

    results = []
    for plan in plans:
        image = out_dir / clip_id / f"plan_{plan.index:03d}.jpg"
        _annotate(plan, image, int(settings["jpeg_quality"]))
        answer = llm.ask("layout", _prompt(plan, width, height), [image], LAYOUT_SCHEMA, config=config)
        _check_answer(answer, plan)

        layout, reason = answer["layout"], None
        try:
            if layout == "facecam_gameplay":
                panels = geometry.facecam(plan, answer["camera"])
            else:
                panels = geometry.single(plan, answer["face"])
        except _Infeasible as exc:
            reason = str(exc)
            panels = None
            if settings["fallback"] == "auto":
                try:
                    panels, layout = geometry.split(plan), "split"
                except _Infeasible as exc2:
                    reason = f"{reason} ; split impossible : {exc2}"
            if panels is None:
                panels, layout = geometry.blur(plan), "fallback_blur"
            log.warning("reframe %s/%s plan %d : repli %s (%s)", video_id, clip_id, plan.index, layout, reason)

        results.append({
            "index": plan.index,
            "start": plan.start,
            "end": plan.end,
            "image": image.relative_to(video_dir).as_posix(),
            "llm": answer,
            "layout": layout,
            "reason": reason,
            "faces": [
                {
                    "id": tr.id,
                    "first": plan.times[tr.present()[0]],
                    "last": plan.times[tr.present()[-1]],
                    "box": [round(v, 1) for v in tr.mean_box()],
                    "retained": tr.retained,
                }
                for tr in plan.tracks
            ],
            "panels": panels,
        })

    data = {
        "video_id": video_id,
        "clip_id": clip_id,
        "start": start,
        "end": end,
        "source": {"width": width, "height": height},
        "output": {"width": geometry.out_w, "height": geometry.out_h},
        "layout": _majority_layout(results),
        "plans": results,
    }
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(out)
    return out
