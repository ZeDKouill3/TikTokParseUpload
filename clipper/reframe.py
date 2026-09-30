"""Etape reframe : cadrage 9:16 plein ecran d'un clip (SPEC-6127).

Deux mises en page (``format`` en config) :
- ``letterbox`` (defaut) : zoom fixe centre, fond flou, aucun visage suivi,
  aucun appel LLM ; voir plus bas.
- ``crop`` : suivi de visage par plan, mise en page par plan, visages jamais
  coupes (option figee, sans nouveau developpement).

Le reste de ce docstring decrit le format crop.

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
   visage est *retenu* s'il est detecte assez souvent sur la duree de sa
   piste (``min_face_presence``, de sa premiere a sa derniere detection :
   un visage qui entre a mi-plan compte), assez longtemps
   (``min_face_seconds``) et assez grand (``min_face_height``) : seuls les
   visages retenus sont gardes entiers ;
3. par plan, une image annotee (visages encadres, ``#id``, retenus ou non)
   est envoyee a clipper.llm (usage ``layout``), qui repond
   facecam_gameplay (avec le rectangle de la camera) ou single (avec le
   visage retenu a suivre, ou null), et peut designer dans ``ignore`` des
   detections qui ne sont pas des visages (main, objet) : elles ne sont
   plus retenues ni protegees ;
4. plan de recadrage : position voulue lissee (moyenne glissante puis zone
   morte), puis ramenee dans l'ensemble des positions ou chaque visage
   suivi est entier dans le cadre et ou aucun autre visage retenu n'est
   coupe (entier dedans ou entier dehors). En single, si le visage suivi
   ne tient pas, paliers documentes dans CONFIG_DEFAULTS (``fit_margins``
   puis boite instantanee), jamais de visage rogne. Sans position possible
   a un instant (dernier palier compris), le plan passe en repli ``split``
   (deux visages retenus distincts, plan d'au moins ``split_min_seconds``,
   si ``fallback = auto`` ; chaque panneau cadre son visage a
   ``split_face_height``) ou ``fallback_blur``, avec la raison (et le
   dernier palier essaye) dans ``reason``.

Les plans de moins de ``min_plan_seconds`` (coupe de scene parasite, bord
du clip) sont fusionnes au plan voisin avant l'appel LLM.

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
    # Mise en page : "letterbox" (zoom fixe, sans visage suivi, defaut) ou
    # "crop" (suivi de visage, option figee, voir le reste de ce module).
    "format": "letterbox",
    # Format letterbox seulement (SPEC-8257, succede a SPEC-3a88) :
    # "letterbox" (defaut) ou "stream_auto" = clip en stream (facecam fixe
    # agrandie en haut, jeu en bas) si la video a une facecam et que son
    # rectangle y est present et vivant sur au moins facecam_clip_min_share
    # des images cles du clip, sinon letterbox (raison journalisee). Voir
    # detect_facecam et _clip_facecam.
    "layout": "letterbox",
    # Localisation de la facecam (une fois par video, SPEC-8257 regle 1) :
    # visage a la meme position (centre a moins de facecam_tolerance px) sur
    # au moins facecam_localize_min_share des images cles de scenes.json,
    # dans une zone de moins de facecam_max_area de l'image. Seuil distinct
    # de, et par defaut bien plus bas que, celui exige par clip
    # (facecam_clip_min_share ci-dessous) : une facecam est reperee des
    # qu'un visage y apparait de temps en temps, meme rarement (jeu sombre,
    # webcam petite, casque).
    "facecam_localize_min_share": 0.1,
    "facecam_tolerance": 40,
    "facecam_max_area": 0.25,
    # detect_facecam seulement (TASK-493f184c4ce1) : au plus ce nombre
    # d'images cles examinees (image entiere + 4 coins agrandis), a
    # intervalles reguliers sur toute la duree de la video (indices
    # equirepartis, bornes comprises) quand scenes.json en fournit plus ;
    # borne le nombre d'appels au detecteur sur une video a beaucoup
    # d'images cles (248 s sur 2326 images cles avant ce reglage).
    "facecam_max_keyframes": 200,
    # detect_facecam seulement : en plus de l'image entiere, chaque coin de
    # l'image cle est recadre a facecam_corner_size de la largeur/hauteur puis
    # agrandi facecam_corner_zoom fois avant detection (coordonnees ramenees
    # a l'image source) : une petite facecam en coin (visage ~160 px sur
    # 1920) y occupe une part bien plus grande que dans l'image entiere
    # reduite par le detecteur.
    "facecam_corner_size": 0.3,
    "facecam_corner_zoom": 2.0,
    # Rectangle source de la facecam : au format du panneau camera, centre
    # sur le visage, qui en occupe cette part de la hauteur. Repli quand les
    # bords reels de l'incrustation ne sont pas trouves (voir plus bas).
    "stream_face_height": 0.5,
    # Bords reels de l'incrustation (TASK-6404), cherches de part et d'autre
    # du visage stable plutot que devines depuis sa seule taille : premiere
    # position, en s'eloignant du visage, ou le gradient moyen (colonne pour
    # les bords gauche/droit, ligne pour haut/bas, sur l'etendue du visage)
    # depasse facecam_edge_min_gradient sur au moins facecam_edge_min_share
    # des images cles -- une discontinuite forte et constante. La recherche
    # part du bord du visage elargi de facecam_edge_gap_ratio (fraction de sa
    # largeur/hauteur, pour sauter son propre contour) et s'arrete a
    # facecam_edge_search_ratio fois sa largeur/hauteur. Un ou deux bords non
    # adjacents (un cote, ou un coin) introuvables alors que les autres sont
    # nets sont pris pour des bords de l'image elle-meme (TASK-6519, cas
    # courant : facecam collee a 1 ou 2 bords) ; au-dela (ou deux manquants
    # sur le meme axe), repli sur le rectangle centre sur le visage
    # (stream_face_height ci-dessus), raison journalisee (ADR-ad2e).
    "facecam_edge_gap_ratio": 0.05,
    "facecam_edge_search_ratio": 3.0,
    "facecam_edge_min_gradient": 30.0,
    "facecam_edge_min_share": 0.8,
    # Presence de la facecam par clip (SPEC-8257 regle 2) : un clip reste en
    # stream si le rectangle de la facecam (deja localise) y est present et
    # vivant sur au moins facecam_clip_min_share de ses images cles, SANS
    # exiger qu'un visage y soit detecte (webcam petite, jeu sombre, casque,
    # tete tournee : le visage n'est qu'un indice de localisation, pas une
    # condition par clip). Un rectangle est present et vivant sur une image
    # cle quand, a la fois :
    # (a) son contenu n'est pas noir : luminosite moyenne au moins
    #     facecam_black_min_mean, ou texture (ecart-type des niveaux de
    #     gris) au moins facecam_black_min_std ;
    # (b) ses bords sont retrouves au meme endroit qu'a la localisation
    #     (meme methode de gradient, facecam_edge_min_gradient) sur au moins
    #     facecam_clip_edge_min_share d'une paire de cotes opposes
    #     (gauche/droit ou haut/bas) : le rectangle n'est agrandi que sur un
    #     seul axe pour tenir le format du panneau camera, l'autre garde le
    #     bord reel de l'incrustation ; ignoree quand la localisation
    #     elle-meme n'a trouve aucun bord reel (repli sur le seul visage
    #     stable, edge_reason non nul dans facecam.json : rien de comparable
    #     a chercher par image cle) ;
    # (c) il n'est pas fige : au moins facecam_frozen_min_pixel_share de ses
    #     pixels different (niveaux de gris, ecart au moins
    #     facecam_frozen_min_diff pour ecarter le bruit de capteur) de
    #     l'image cle precedente du meme clip (un ecran de pause immobile ou
    #     un BRB ne satisfont pas ce critere). Part de pixels plutot que
    #     moyenne globale : le rectangle est plus grand que la personne qui
    #     y bouge (marge de stream_face_height), une moyenne diluerait un
    #     mouvement localise mais reel.
    # Un clip qui ne l'est pas assez souvent reste entierement en letterbox,
    # raison journalisee (ADR-ad2e : jamais un repli silencieux).
    "facecam_clip_min_share": 0.8,
    "facecam_black_min_mean": 12.0,
    "facecam_black_min_std": 6.0,
    "facecam_clip_edge_min_share": 0.5,
    "facecam_frozen_min_diff": 8.0,
    "facecam_frozen_min_pixel_share": 0.001,
    # Panneau camera : part de la hauteur de sortie, a partir de stream_top
    # (titre d'ecran au-dessus) ; le jeu occupe tout le bas.
    "stream_camera_ratio": 0.4,
    "stream_top": 440,
    # Agencement d'un clip deja en stream (SPEC-76dc) : n'intervient qu'apres
    # les regles 1/2 ci-dessus (aucun effet sur le choix stream/letterbox
    # lui-meme). "top" (defaut, comportement inchange) = SPEC-3a88 ci-dessus.
    # "split" = webcam en haut (~1/3 de la hauteur), jeu en bas pleine largeur,
    # badge de chaine optionnel, sous-titres a deux couleurs (voir
    # clipper.subtitles split_*).
    "stream_variant": "top",
    # Zones de sortie de l'agencement split (SPEC-76dc), en pixels du canevas
    # 1080x1920 : webcam agrandie en haut, jeu en bas pleine largeur. Chacune
    # est recadree (jamais etiree) au ratio de son rectangle dest ; doivent
    # tenir dans le canevas et ne jamais se chevaucher (erreur explicite au
    # chargement sinon, ADR-ad2e).
    "split_webcam_dest": {"x": 20, "y": 0, "w": 1040, "h": 640},
    "split_gameplay_dest": {"x": 0, "y": 640, "w": 1080, "h": 1280},
    # Bandeau de badge de chaine (logo + nom, [render] badge_*), a cheval par
    # defaut sur la jonction webcam/jeu. Doit tenir dans la zone sure TikTok
    # (erreur explicite sinon).
    "badge_dest": {"x": 330, "y": 590, "w": 420, "h": 100},
    # Zone des sous-titres de l'agencement split (clipper.subtitles split_*),
    # entierement dans la zone jeu, sans jamais recouvrir le badge. Doit
    # tenir dans la zone sure TikTok (erreur explicite sinon).
    "split_subtitle_dest": {"x": 150, "y": 710, "w": 780, "h": 150},
    # Le jeu est la plus grande fenetre, au format de son panneau, la plus
    # centree possible, qui evite la facecam elargie de cette marge (px source :
    # le cadre reel de la facecam deborde le rectangle centre sur le visage).
    "stream_exclude_margin": 80,
    # Zoom fixe du format letterbox : fenetre centrale de largeur
    # source_w / letterbox_zoom, pleine hauteur. Pensees pour une source 16:9.
    "letterbox_zoom": 1.3,
    # Ordonnee (sortie) ou commence le panneau video du format letterbox.
    "letterbox_top": 440,
    # Zone sure TikTok (sortie 1080x1920) : aucun texte hors de ces bornes.
    "safe_top": 160,
    "safe_bottom": 1520,
    "safe_left": 150,
    "safe_right": 930,
    # Ecart minimal entre un bloc de texte et le panneau video.
    "text_gap": 16,
    # Hauteur de la bande "Partie N" en bas de la zone sure.
    "part_height": 56,
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
    # moins cette part des images analysees de sa piste, de sa premiere a sa
    # derniere detection (une fausse detection clignote, un vrai visage a
    # l'image est vu presque partout, meme s'il entre a mi-plan)...
    "min_face_presence": 0.6,
    # ... sur une piste d'au moins cette duree (une piste fantome de
    # quelques images n'est pas un visage)...
    "min_face_seconds": 1.0,
    # ... et de hauteur moyenne au moins cette part de la hauteur source.
    # Les autres pistes restent annotees pour le LLM, mais ne contraignent
    # pas le cadre.
    "min_face_height": 0.05,
    # Ecran partage : part de la hauteur d'un panneau occupee par son visage
    # (le cadre est agrandi par paliers si l'autre visage retenu serait
    # coupe, jusqu'au plus grand cadre possible).
    "split_face_height": 0.35,
    # Un ecran partage n'est jamais choisi pour un plan plus court : en
    # dessous, repli fallback_blur (un split de 1 s clignote a l'ecran).
    "split_min_seconds": 3.0,
    # Plan plus court (coupe de scene parasite, bord du clip) : fusionne au
    # plan voisin avant l'appel LLM.
    "min_plan_seconds": 0.5,
    # Marge autour de chaque visage (fraction de sa taille, de chaque cote) :
    # couvre le mouvement entre deux images analysees.
    "face_margin": 0.15,
    # Paliers du cadrage single quand le visage suivi (gros plan, camera
    # portee) ne tient pas dans le cadre, essayes dans l'ordre a chaque image
    # analysee avant tout repli ; le visage suivi n'est jamais rogne et les
    # autres visages retenus gardent toujours face_margin et leur zone
    # balayee (jamais coupes) :
    # 1. marges reduites, dans l'ordre (celles < face_margin), sur la zone
    #    balayee par le visage suivi ;
    # 2. puis boite instantanee du visage suivi (marge 0) au lieu de sa zone
    #    balayee.
    "fit_margins": [0.1, 0.05, 0.0],
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
_FORMATS = ("letterbox", "crop")
_LAYOUT_MODES = ("letterbox", "stream_auto")
_STREAM_VARIANTS = ("top", "split")

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
        # Detections qui ne sont pas des visages (main, objet) : ni retenues
        # ni protegees. Facultatif : absent = aucune.
        "ignore": {"type": "array", "items": {"type": "integer"}},
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


def _retain(tracks: list[_Track], fps: float, height: int, settings: dict[str, Any]) -> None:
    """Marque les visages retenus : detectes sur au moins ``min_face_presence``
    des images de leur piste (de la premiere a la derniere detection, un
    visage qui entre a mi-plan compte), piste d'au moins ``min_face_seconds``
    et hauteur moyenne d'au moins ``min_face_height`` de la source. Une piste
    fantome, un visage minuscule ou une fausse detection qui clignote ne
    contraignent pas le cadre."""
    presence = float(settings["min_face_presence"])
    min_samples = float(settings["min_face_seconds"]) * fps
    min_h = float(settings["min_face_height"]) * height
    for tr in tracks:
        box = tr.mean_box()
        span = len(tr.present())
        tr.retained = (
            span >= min_samples - 1e-9
            and tr.detected >= presence * span - 1e-9
            and box[3] - box[1] >= min_h
        )


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


# Palier de cadrage : nom, boites a garder entieres a l'image i.
_Tier = tuple[str, Callable[[int], list[Box]]]


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
        tiers: list[_Tier] | None = None,
    ) -> list[tuple[int, int, int, int]]:
        """Positions d'un cadre de rapport ``aspect`` qui suit les visages
        ``required`` (entiers dedans) sans couper ``others``. Avec ``tiers``,
        les boites gardees entieres sont, image par image, celles du premier
        palier qui laisse une position."""
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

        if tiers is None:
            tiers = [("", lambda i: [self.margin(tr.span(i)) for tr in required if tr.boxes[i] is not None])]
        positions = []
        reached = 0
        for i in range(n):
            oth = [self.margin(tr.span(i)) for tr in others if tr.boxes[i] is not None]
            pos = None
            for k, (_, boxes_at) in enumerate(tiers):
                req = boxes_at(i)
                allowed = _allowed(
                    extent,
                    win,
                    [(b[axis], b[axis + 2]) for b in req],
                    [(b[axis], b[axis + 2]) for b in oth],
                )
                pos = _project(smoothed[i], allowed)
                if pos is not None:
                    reached = max(reached, k)
                    break
            if pos is None:
                faces = ", ".join(f"#{tr.id}" for tr in required) or "aucun"
                if tiers[-1][0]:
                    what = f"ne cadre le visage suivi {faces} sans couper" if required else "n'evite de couper"
                    raise _Infeasible(
                        f"a {plan.times[i]:.2f}s, aucun cadre {ww}x{wh} {what} un autre visage retenu "
                        f"(dernier palier : {tiers[-1][0]})"
                    )
                raise _Infeasible(
                    f"a {plan.times[i]:.2f}s, aucun cadre {ww}x{wh} ne garde entier(s) le(s) "
                    f"visage(s) {faces} sans couper un autre visage"
                )
            positions.append((pos, 0, win, wh) if axis == 0 else (0, pos, ww, win))
        if reached:
            log.info("plan %d : cadre au palier %r", plan.index, tiers[reached][0])
        return positions

    def tiers(self, track: _Track | None) -> list[_Tier]:
        """Paliers du cadrage single pour le visage suivi ``track`` (voir
        CONFIG_DEFAULTS), du plus confortable au plus degrade."""
        if track is None:
            return [("aucun visage suivi", lambda i: [])]

        def box(i: int) -> list[Box]:
            b = track.boxes[i]
            return [] if b is None else [b]

        def swept(margin: float) -> Callable[[int], list[Box]]:
            def at(i: int) -> list[Box]:
                if track.boxes[i] is None:
                    return []
                return [_with_margin(track.span(i), margin, self.width, self.height)]  # type: ignore[arg-type]

            return at

        face_margin = float(self.settings["face_margin"])
        margins = [face_margin] + sorted(
            {float(m) for m in self.settings["fit_margins"] if float(m) < face_margin}, reverse=True
        )
        out: list[_Tier] = [(f"marge {m:g} sur la zone balayee", swept(m)) for m in margins]
        out.append(("boite instantanee (marge 0)", box))
        return out

    def dest(self, x: int, y: int, w: int, h: int) -> dict[str, int]:
        return {"x": x, "y": y, "w": w, "h": h}

    def single(self, plan: _Plan, face: int | None) -> list[dict[str, Any]]:
        required = [tr for tr in plan.tracks if tr.id == face]
        others = [tr for tr in plan.tracks if tr.id != face and tr.retained]
        tiers = self.tiers(required[0] if required else None)
        positions = self.follow(plan, self.out_w / self.out_h, required, others, tiers=tiers)
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
# Format letterbox (SPEC-6127) : zoom fixe, sans visage suivi, aucun LLM.
# --------------------------------------------------------------------------


def _rects_overlap(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    return ax0 < bx1 and bx0 < ax1 and ay0 < by1 and by0 < ay1


def _letterbox_geometry(source_w: int, source_h: int, settings: dict[str, Any]) -> dict[str, Any]:
    """Fenetre source zoomee et centree, plein cadre a partir de
    ``letterbox_top`` ; zones de texte deduites, validees dans les bornes de
    sortie et sans chevaucher le panneau video."""
    zoom = float(settings["letterbox_zoom"])
    if zoom < 1:
        raise ReframeError(f"[reframe] letterbox_zoom invalide {zoom!r} (attendu >= 1)")

    out_w = int(settings["output_width"])
    out_h = int(settings["output_height"])
    letterbox_top = int(settings["letterbox_top"])

    w = round(source_w / zoom)
    if w % 2:
        w -= 1
    x = (source_w - w) // 2
    h = round(source_h * out_w / w)
    if h % 2:
        h -= 1

    main_rect = (0, letterbox_top, out_w, letterbox_top + h)

    safe_left = int(settings["safe_left"])
    safe_right = int(settings["safe_right"])
    safe_top = int(settings["safe_top"])
    safe_bottom = int(settings["safe_bottom"])
    text_gap = int(settings["text_gap"])
    part_height = int(settings["part_height"])

    zones = {
        "title": (safe_left, safe_top, safe_right, letterbox_top - text_gap),
        "subtitles": (safe_left, letterbox_top + h + text_gap, safe_right, safe_bottom - part_height - text_gap),
        "part": (safe_left, safe_bottom - part_height, safe_right, safe_bottom),
    }
    for name, (x0, y0, x1, y1) in zones.items():
        if x1 <= x0 or y1 <= y0:
            raise ReframeError(
                f"[reframe] zone {name} vide ou inversee pour une source {source_w}x{source_h} : "
                f"({x0},{y0})-({x1},{y1})"
            )
        if x0 < 0 or y0 < 0 or x1 > out_w or y1 > out_h:
            raise ReframeError(
                f"[reframe] zone {name} hors de {out_w}x{out_h} pour une source {source_w}x{source_h} : "
                f"({x0},{y0})-({x1},{y1})"
            )
        if _rects_overlap(main_rect, (x0, y0, x1, y1)):
            raise ReframeError(
                f"[reframe] zone {name} chevauche le panneau video pour une source {source_w}x{source_h} : "
                f"({x0},{y0})-({x1},{y1})"
            )

    return {"x": x, "w": w, "h": h, "out_w": out_w, "out_h": out_h, "letterbox_top": letterbox_top, "zones": zones}


def _reframe_letterbox(
    video_id: str,
    clip_id: str,
    start: float,
    end: float,
    out: Path,
    video: Path,
    settings: dict[str, Any],
    frame_source: Callable[[Path, Sequence[float]], Iterable[tuple[float, np.ndarray]]],
    *,
    layout_reason: str | None = None,
) -> Path:
    """Plan letterbox ; ``layout_reason`` (layout = stream_auto seulement) dit
    pourquoi le clip n'est pas en stream."""
    [(_, frame)] = list(frame_source(video, [start]))
    source_h, source_w = frame.shape[:2]
    geometry = _letterbox_geometry(source_w, source_h, settings)
    x, w, h = geometry["x"], geometry["w"], geometry["h"]
    out_w, out_h, letterbox_top = geometry["out_w"], geometry["out_h"], geometry["letterbox_top"]

    panels = [
        {
            "name": "background",
            "effect": "blur",
            "dest": {"x": 0, "y": 0, "w": out_w, "h": out_h},
            "rects": [{"start": start, "end": end, "x": 0, "y": 0, "w": source_w, "h": source_h}],
        },
        {
            "name": "main",
            "dest": {"x": 0, "y": letterbox_top, "w": out_w, "h": h},
            "rects": [{"start": start, "end": end, "x": x, "y": 0, "w": w, "h": source_h}],
        },
    ]
    plan = {
        "index": 0,
        "start": start,
        "end": end,
        "image": None,
        "llm": None,
        "layout": "letterbox",
        "reason": None,
        "faces": [],
        "panels": panels,
    }
    data = {
        "video_id": video_id,
        "clip_id": clip_id,
        "start": start,
        "end": end,
        "source": {"width": source_w, "height": source_h},
        "output": {"width": out_w, "height": out_h},
        "layout": "letterbox",
        "format": "letterbox",
        "text_zones": {
            name: {"x0": x0, "y0": y0, "x1": x1, "y1": y1} for name, (x0, y0, x1, y1) in geometry["zones"].items()
        },
        "plans": [plan],
    }
    if layout_reason is not None:
        data["layout_mode"] = settings["layout"]
        data["layout_reason"] = layout_reason
    _write_plan(out, data)
    return out


def _write_plan(out: Path, data: dict[str, Any]) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(out)


# --------------------------------------------------------------------------
# Format stream (SPEC-3a88) : facecam fixe agrandie en haut, jeu en bas.
# --------------------------------------------------------------------------


def _even(v: float) -> int:
    n = int(round(v))
    return n - n % 2


def _camera_size(settings: dict[str, Any]) -> tuple[int, int, int]:
    """(largeur, hauteur, haut) du panneau camera en pixels de sortie."""
    out_w, out_h = int(settings["output_width"]), int(settings["output_height"])
    return out_w, _even(out_h * float(settings["stream_camera_ratio"])), int(settings["stream_top"])


def _size_camera_rect(
    cx: float, cy: float, bw: float, bh: float, width: int, height: int, settings: dict[str, Any]
) -> tuple[tuple[int, int, int, int] | None, str | None]:
    """Rectangle centre sur (``cx``, ``cy``), agrandi au format du panneau
    camera pour contenir une zone ``bw`` x ``bh``, ramene dans l'image ;
    ``None`` et la raison s'il ne tient pas ou depasse ``facecam_max_area``
    de l'image."""
    cam_w, cam_h, _ = _camera_size(settings)
    aspect = cam_w / cam_h
    if bw / bh > aspect:
        bh = bw / aspect
    else:
        bw = bh * aspect
    w, h = _even(bw), _even(bh)
    max_area = float(settings["facecam_max_area"])
    if w > width or h > height or w * h >= max_area * width * height:
        return None, (
            f"zone de l'incrustation ({w}x{h} px au format du panneau camera) pas plus petite qu'un quart "
            f"(facecam_max_area = {max_area:g}) de l'image {width}x{height} : pas une incrustation"
        )
    x = min(max(round(cx - w / 2), 0), width - w)
    y = min(max(round(cy - h / 2), 0), height - h)
    return (x, y, w, h), None


def _facecam_rect_from_face(
    face: Box, width: int, height: int, settings: dict[str, Any]
) -> tuple[tuple[int, int, int, int] | None, str | None]:
    """Repli : rectangle source de la facecam au format du panneau camera,
    centre sur le seul visage stable (qui en occupe ``stream_face_height`` de
    la hauteur) -- utilise quand les bords reels de l'incrustation ne sont
    pas trouves (voir ``_incrustation_rect``)."""
    cx, cy = _center(face)
    bh = (face[3] - face[1]) / float(settings["stream_face_height"])
    cam_w, cam_h, _ = _camera_size(settings)
    return _size_camera_rect(cx, cy, bh * cam_w / cam_h, bh, width, height, settings)


def _edge_mask(image: np.ndarray, threshold: float) -> np.ndarray:
    """Pixels ou le gradient (Sobel) de l'image en niveaux de gris depasse
    ``threshold`` : une image cle a la fois (pas de pile en memoire, une
    video peut avoir des milliers d'images cles)."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(np.float64)
    gx = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
    return np.hypot(gx, gy) >= threshold


def _edge_position(
    counts: np.ndarray, n_frames: int, axis: str, lo: int, hi: int, start: int, step: int, limit: int, min_share: float
) -> int | None:
    """Premiere position, en s'eloignant de ``start`` par pas de ``step``
    jusqu'a ``limit`` (les deux inclus), ou la part des images cles ou le
    gradient depasse le seuil (``counts``, cumule par ``_edge_mask``), moyennee
    sur [``lo``, ``hi``) (colonne ``pos`` si ``axis`` == "x", ligne sinon),
    atteint ``min_share`` ; ``None`` si aucune position ne convient."""
    if hi <= lo or n_frames <= 0:
        return None
    pos = start
    while (step > 0 and pos <= limit) or (step < 0 and pos >= limit):
        band = counts[lo:hi, pos] if axis == "x" else counts[pos, lo:hi]
        if band.mean() / n_frames >= min_share - 1e-9:
            return pos
        pos += step
    return None


def _incrustation_rect(
    counts: np.ndarray, n_frames: int, face: Box, width: int, height: int, settings: dict[str, Any]
) -> tuple[Box | None, str | None]:
    """Bords reels de l'incrustation autour du visage stable ``face`` :
    premiere discontinuite forte et constante (``counts``, voir
    ``_edge_mask``) de part et d'autre de lui (voir CONFIG_DEFAULTS). Un ou
    deux bords non adjacents introuvables (un cote, ou un coin) alors que les
    autres sont nets sont ceux de l'image elle-meme : rien au-dela d'un bord
    d'image ne peut y creer de discontinuite, donc une incrustation qui y est
    collee n'en montre jamais (TASK-6519). ``None`` et la raison si plus de
    bords manquent, ou si les deux manquants sont sur le meme axe (aucun bord
    reel trouve pour donner la largeur ou la hauteur)."""
    gap_ratio = float(settings["facecam_edge_gap_ratio"])
    search_ratio = float(settings["facecam_edge_search_ratio"])
    min_share = float(settings["facecam_edge_min_share"])
    fx0, fy0, fx1, fy1 = face
    fw, fh = fx1 - fx0, fy1 - fy0
    gap_x, gap_y = max(1, round(fw * gap_ratio)), max(1, round(fh * gap_ratio))
    search_x, search_y = max(1, round(fw * search_ratio)), max(1, round(fh * search_ratio))
    y0i, y1i = max(0, round(fy0)), min(height, round(fy1))
    x0i, x1i = max(0, round(fx0)), min(width, round(fx1))

    left = _edge_position(
        counts, n_frames, "x", y0i, y1i, round(fx0) - gap_x, -1,
        max(0, round(fx0) - gap_x - search_x), min_share,
    )
    right = _edge_position(
        counts, n_frames, "x", y0i, y1i, round(fx1) + gap_x, 1,
        min(width - 1, round(fx1) + gap_x + search_x), min_share,
    )
    top = _edge_position(
        counts, n_frames, "y", x0i, x1i, round(fy0) - gap_y, -1,
        max(0, round(fy0) - gap_y - search_y), min_share,
    )
    bottom = _edge_position(
        counts, n_frames, "y", x0i, x1i, round(fy1) + gap_y, 1,
        min(height - 1, round(fy1) + gap_y + search_y), min_share,
    )

    borders = {"gauche": 0, "droit": width - 1, "haut": 0, "bas": height - 1}
    axis = {"gauche": "x", "droit": "x", "haut": "y", "bas": "y"}
    found = {"gauche": left, "droit": right, "haut": top, "bas": bottom}
    missing = [name for name, v in found.items() if v is None]
    same_axis = len(missing) == 2 and axis[missing[0]] == axis[missing[1]]
    if len(missing) > 2 or same_axis:
        return None, (
            f"bord(s) {', '.join(missing)} de l'incrustation introuvable(s) autour du visage stable "
            f"(gradient marque sur >= {min_share:.0%} des images cles, recherche jusqu'a "
            f"{search_x:g}x{search_y:g} px) : rectangle centre sur le visage conserve"
        )
    for name in missing:
        found[name] = borders[name]
    left, right, top, bottom = found["gauche"], found["droit"], found["haut"], found["bas"]
    assert left is not None and top is not None and right is not None and bottom is not None
    return (float(left), float(top), float(right + 1), float(bottom + 1)), None


def _facecam_rect(
    counts: np.ndarray, n_frames: int, face: Box, width: int, height: int, settings: dict[str, Any]
) -> tuple[tuple[int, int, int, int] | None, str | None, str | None]:
    """Rectangle source de la facecam, au format du panneau camera : cale sur
    les bords reels de l'incrustation quand ils sont trouves (voir
    ``_incrustation_rect``), sinon repli sur le seul visage stable
    (``_facecam_rect_from_face``), avec la raison du repli (TASK-6404).
    ``None`` et la raison si meme le repli ne tient pas dans l'image."""
    edge_box, edge_reason = _incrustation_rect(counts, n_frames, face, width, height, settings)
    if edge_box is not None:
        ex0, ey0, ex1, ey1 = edge_box
        rect, reason = _size_camera_rect(
            (ex0 + ex1) / 2, (ey0 + ey1) / 2, ex1 - ex0, ey1 - ey0, width, height, settings
        )
        if rect is not None:
            return rect, None, None
        edge_reason = reason
    rect, reason = _facecam_rect_from_face(face, width, height, settings)
    return rect, reason, edge_reason


def _stable_face(
    detections: list[list[Box]], tolerance: float
) -> tuple[Box | None, int]:
    """Visage a la meme position (centre a moins de ``tolerance`` px) sur le
    plus d'images : sa boite mediane et le nombre d'images ou il est."""
    best: tuple[int, list[Box]] | None = None
    for boxes in detections:
        for ref in boxes:
            rc = _center(ref)
            support = []
            for other in detections:
                near = [b for b in other if math.dist(_center(b), rc) <= tolerance]
                if near:
                    support.append(min(near, key=lambda b: math.dist(_center(b), rc)))
            if best is None or len(support) > best[0]:
                best = (len(support), support)
    if best is None:
        return None, 0
    count, support = best
    median = tuple(float(np.median([b[k] for b in support])) for k in range(4))
    return median, count  # type: ignore[return-value]


def _corner_boxes(width: int, height: int, size: float) -> list[tuple[int, int, int, int]]:
    """4 vignettes de coin (``size`` de la largeur/hauteur chacune)."""
    cw, ch = round(width * size), round(height * size)
    return [
        (0, 0, cw, ch),
        (width - cw, 0, width, ch),
        (0, height - ch, cw, height),
        (width - cw, height - ch, width, height),
    ]


def _detect_corners(
    detector: Any, image: np.ndarray, width: int, height: int, settings: dict[str, Any]
) -> list[Detection]:
    """Detections sur les 4 coins de l'image, recadres puis agrandis avant
    detection (une petite facecam en coin est trop reduite une fois l'image
    entiere passee au detecteur) ; coordonnees ramenees a l'image source."""
    size = float(settings["facecam_corner_size"])
    zoom = float(settings["facecam_corner_zoom"])
    found: list[Detection] = []
    for x0, y0, x1, y1 in _corner_boxes(width, height, size):
        crop = image[y0:y1, x0:x1]
        if crop.size == 0:
            continue
        enlarged = cv2.resize(crop, None, fx=zoom, fy=zoom, interpolation=cv2.INTER_LINEAR)
        for bx0, by0, bx1, by1, score in detector.detect(enlarged):
            found.append((x0 + bx0 / zoom, y0 + by0 / zoom, x0 + bx1 / zoom, y0 + by1 / zoom, score))
    return found


def _sample_keyframes(frames: list[dict[str, Any]], max_count: int) -> list[dict[str, Any]]:
    """Au plus ``max_count`` images cles (``frames``, triees par timecode), a
    intervalles reguliers (indices equirepartis, bornes comprises) : borne le
    nombre d'appels au detecteur sur une video a beaucoup d'images cles, sans
    perdre la couverture du debut et de la fin (TASK-493f184c4ce1)."""
    n = len(frames)
    if max_count <= 0 or n <= max_count:
        return frames
    if max_count == 1:
        return [frames[0]]
    step = (n - 1) / (max_count - 1)
    indices = sorted({round(i * step) for i in range(max_count)})
    return [frames[i] for i in indices]


def detect_facecam(
    video_id: str,
    workspace_dir: str | Path = "workspace",
    *,
    config: Any = None,
    force: bool = False,
    detector_factory: Callable[[dict[str, Any], Device], Any] | None = None,
    image_reader: Callable[[str], np.ndarray | None] = cv2.imread,
) -> Path:
    """Detection de la facecam, une fois par video (SPEC-8257 regle 1), sur
    les images cles de scenes.json ; resultat en cache dans
    workspace/<video_id>/facecam.json (pas refait sauf ``force``) :

        {"video_id", "source": {"width", "height"},
         "facecam": {"x", "y", "w", "h"} | null, "reason": null | pourquoi pas,
         "edge_reason": null | pourquoi le rectangle est centre sur le seul
             visage plutot que cale sur les bords reels de l'incrustation
             (TASK-6404, ADR-ad2e),
         "face": [x0, y0, x1, y1] | null, "share", "localize_min_share",
         "keyframes": [{"timecode", "path", "faces", "face_in_rect"}]}

    ``face_in_rect`` reste un indicateur informatif (visage detecte dans le
    rectangle sur cette image cle) : le choix du format par clip
    (``_clip_facecam``, SPEC-8257 regle 2) ne s'appuie plus dessus, seulement
    sur la presence et la vivacite du rectangle lui-meme.

    Detecteur de visages de reframe (``detector``), device via clipper.gpu,
    ferme avant de rendre la main (ADR-fb9b)."""
    video_dir = Path(workspace_dir) / video_id
    out = video_dir / "facecam.json"
    if out.exists() and not force:
        return out
    settings = _settings(config)
    scenes_file = video_dir / "scenes.json"
    if not scenes_file.exists():
        raise ReframeError(f"scenes.json absent : {scenes_file}")
    frames = sorted(json.loads(scenes_file.read_text(encoding="utf-8")).get("frames", []),
                    key=lambda f: f["timecode"])
    frames = _sample_keyframes(frames, int(settings["facecam_max_keyframes"]))
    if detector_factory is None:
        if settings["detector"] not in _DETECTORS:
            raise ReframeError(
                f"[reframe] detecteur inconnu {settings['detector']!r} (attendu : {' | '.join(_DETECTORS)})"
            )
        detector_factory = _DETECTORS[settings["detector"]]

    min_conf = float(settings["min_confidence"])
    dup_iou = float(settings["duplicate_iou"])
    edge_threshold = float(settings["facecam_edge_min_gradient"])
    detections: list[list[Box]] = []
    size: tuple[int, int] | None = None
    # Comptes de pixels a fort gradient, cumules image cle par image cle (pas
    # de pile d'images en memoire : une video peut en avoir des milliers).
    edge_counts: np.ndarray | None = None
    if frames:
        detector = detector_factory(settings, get_device())
        try:
            for frame_info in frames:
                path = video_dir / frame_info["path"]
                image = image_reader(str(path))
                if image is None:
                    raise ReframeError(f"image cle illisible : {path}")
                height, width = image.shape[:2]
                size = size or (width, height)
                found = [tuple(float(v) for v in d[:5]) for d in detector.detect(image)]
                found += _detect_corners(detector, image, width, height, settings)
                found = [d for d in found if d[4] >= min_conf]
                detections.append([d[:4] for d in _nms(found, dup_iou)])  # type: ignore[misc]
                mask = _edge_mask(image, edge_threshold)
                if edge_counts is None:
                    edge_counts = np.zeros((height, width), dtype=np.uint32)
                edge_counts += mask
        finally:
            detector.close()
            detector = None
            gc.collect()

    min_share = float(settings["facecam_localize_min_share"])
    tolerance = float(settings["facecam_tolerance"])
    rect: tuple[int, int, int, int] | None = None
    edge_reason: str | None = None
    face, count = _stable_face(detections, tolerance)
    share = count / len(frames) if frames else 0.0
    if not frames:
        reason = "aucune image cle dans scenes.json"
    elif face is None:
        reason = f"aucun visage detecte sur les {len(frames)} images cles"
    elif share < min_share - 1e-9:
        reason = (
            f"visage a la meme position (tolerance {tolerance:g} px) sur {share:.0%} des images cles "
            f"seulement (facecam_localize_min_share = {min_share:.0%})"
        )
    else:
        assert size is not None and edge_counts is not None
        rect, reason, edge_reason = _facecam_rect(edge_counts, len(frames), face, size[0], size[1], settings)

    keyframes = []
    for frame_info, boxes in zip(frames, detections):
        keyframes.append({
            "timecode": frame_info["timecode"],
            "path": frame_info["path"],
            "faces": [[round(v, 1) for v in b] for b in boxes],
            "face_in_rect": None if rect is None else any(_contains_point(
                (rect[0], rect[1], rect[0] + rect[2], rect[1] + rect[3]), _center(b)) for b in boxes),
        })
    data = {
        "video_id": video_id,
        "source": None if size is None else {"width": size[0], "height": size[1]},
        "facecam": None if rect is None else dict(zip("xywh", rect)),
        "reason": reason,
        "edge_reason": edge_reason,
        "face": None if face is None else [round(v, 1) for v in face],
        "share": share,
        "localize_min_share": min_share,
        "keyframes": keyframes,
    }
    if rect is None:
        log.warning("%s : pas de facecam, clips en letterbox (%s)", video_id, reason)
    elif edge_reason is not None:
        log.info(
            "%s : facecam %s, bords de l'incrustation non trouves (%s)", video_id, data["facecam"], edge_reason
        )
    else:
        log.info("%s : facecam %s (visage sur %.0f%% des images cles)", video_id, data["facecam"], share * 100)
    _write_plan(out, data)
    return out


def _rect_gray_crop(image: np.ndarray, rect: dict[str, int]) -> np.ndarray | None:
    """Recadrage en niveaux de gris du rectangle de la facecam dans
    ``image`` ; ``None`` si le rectangle ne recouvre pas l'image."""
    height, width = image.shape[:2]
    x, y, w, h = rect["x"], rect["y"], rect["w"], rect["h"]
    x0, y0, x1, y1 = max(0, x), max(0, y), min(width, x + w), min(height, y + h)
    if x1 <= x0 or y1 <= y0:
        return None
    crop = image[y0:y1, x0:x1]
    return cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY).astype(np.float64)


def _rect_is_black(gray: np.ndarray, settings: dict[str, Any]) -> bool:
    """Contenu trop sombre et trop uniforme pour etre une webcam active (ecran
    noir, camera coupee ou masquee) : luminosite ET texture toutes deux sous
    seuil (SPEC-8257 regle 2a)."""
    return (
        float(gray.mean()) < float(settings["facecam_black_min_mean"])
        and float(gray.std()) < float(settings["facecam_black_min_std"])
    )


def _rect_edges_found(image: np.ndarray, rect: dict[str, int], settings: dict[str, Any]) -> bool:
    """Bords marques par un gradient fort (meme methode que la localisation,
    ``_edge_mask``) sur au moins ``facecam_clip_edge_min_share`` d'une paire
    de cotes opposes (gauche/droit ou haut/bas) -- le rectangle n'est
    agrandi que sur un seul axe pour tenir le format du panneau camera
    (``_size_camera_rect``), l'autre garde le bord reel de l'incrustation,
    donc une seule paire nette suffit (SPEC-8257 regle 2b)."""
    threshold = float(settings["facecam_edge_min_gradient"])
    min_share = float(settings["facecam_clip_edge_min_share"])
    height, width = image.shape[:2]
    x, y, w, h = rect["x"], rect["y"], rect["w"], rect["h"]
    x0, x1 = max(0, x), min(width, x + w)
    y0, y1 = max(0, y), min(height, y + h)
    if x1 - x0 < 2 or y1 - y0 < 2:
        return False
    mask = _edge_mask(image, threshold)

    def share(*bands: np.ndarray) -> float:
        total = sum(band.size for band in bands)
        return sum(int(band.sum()) for band in bands) / total if total else 0.0

    left_right = share(mask[y0:y1, x0], mask[y0:y1, x1 - 1])
    top_bottom = share(mask[y0, x0:x1], mask[y1 - 1, x0:x1])
    return left_right >= min_share - 1e-9 or top_bottom >= min_share - 1e-9


def _rect_is_frozen(prev_gray: np.ndarray | None, gray: np.ndarray, settings: dict[str, Any]) -> bool:
    """Contenu identique a l'image cle precedente du meme clip : un ecran de
    pause ou un BRB ne bougent pas (SPEC-8257 regle 2c). La part de pixels
    qui change reellement (au-dela de ``facecam_frozen_min_diff``, un bruit
    de capteur ne compte pas) est comparee a ``facecam_frozen_min_pixel_share``
    plutot que la moyenne : le rectangle est bien plus grand que la personne
    qui y bouge (marge de ``stream_face_height``), une moyenne globale
    diluerait un mouvement localise mais reel. La premiere image cle du clip
    n'a rien a comparer : jamais consideree figee."""
    if prev_gray is None or prev_gray.shape != gray.shape:
        return False
    changed = np.abs(gray - prev_gray) >= float(settings["facecam_frozen_min_diff"])
    return float(changed.mean()) < float(settings["facecam_frozen_min_pixel_share"])


def _clip_facecam(
    facecam: dict[str, Any],
    start: float,
    end: float,
    settings: dict[str, Any],
    video_dir: Path,
    image_reader: Callable[[str], np.ndarray | None] = cv2.imread,
) -> tuple[dict[str, int] | None, str | None]:
    """Choix du clip, tout ou rien (SPEC-8257 regle 2) : le rectangle de la
    facecam (deja localise) s'il y est present et vivant -- contenu non noir,
    bords retrouves, non fige (voir CONFIG_DEFAULTS) -- sur au moins
    ``facecam_clip_min_share`` de ses images cles, sans exiger qu'un visage y
    soit detecte ; sinon ``None`` et la raison (ADR-ad2e : jamais un repli
    silencieux)."""
    if facecam["facecam"] is None:
        return None, f"pas de facecam dans la video : {facecam['reason']}"
    rect = facecam["facecam"]
    keys = [k for k in facecam["keyframes"] if start - 1e-6 <= k["timecode"] <= end + 1e-6]
    if not keys:
        return None, f"aucune image cle de scenes.json dans le clip [{start}, {end}]"
    # La localisation n'a pas toujours de bords reels a retrouver : quand
    # elle est repliee sur le seul visage stable (``edge_reason`` non nul,
    # voir detect_facecam), le rectangle n'a jamais ete cale sur une
    # incrustation reelle -- rien de comparable a chercher par image cle,
    # la regle (b) ne s'applique donc pas (elle ne ferait jamais que
    # rejeter, quel que soit le contenu).
    skip_edge_check = facecam.get("edge_reason") is not None

    alive = 0
    prev_gray: np.ndarray | None = None
    for k in keys:
        path = video_dir / k["path"]
        image = image_reader(str(path))
        if image is None:
            raise ReframeError(f"image cle illisible : {path}")
        gray = _rect_gray_crop(image, rect)
        live = (
            gray is not None
            and not _rect_is_black(gray, settings)
            and (skip_edge_check or _rect_edges_found(image, rect, settings))
            and not _rect_is_frozen(prev_gray, gray, settings)
        )
        if live:
            alive += 1
        prev_gray = gray

    share = alive / len(keys)
    min_share = float(settings["facecam_clip_min_share"])
    if share < min_share - 1e-9:
        return None, (
            f"webcam absente, noire ou figee sur {1 - share:.0%} des images cles du clip "
            f"({alive}/{len(keys)} vivante(s) seulement, facecam_clip_min_share = {min_share:.0%})"
        )
    return rect, None


def _game_window(
    width: int, height: int, aspect: float, exclude: tuple[int, int, int, int]
) -> tuple[int, int, int, int]:
    """Plus grande fenetre de rapport ``aspect`` qui evite ``exclude`` (x0,
    y0, x1, y1) : entierement a gauche, a droite, au-dessus ou au-dessous ;
    a surface egale, la plus proche du centre de l'image."""
    ex0, ey0, ex1, ey1 = exclude
    regions = [(0, 0, ex0, height), (ex1, 0, width, height), (0, 0, width, ey0), (0, ey1, width, height)]
    best: tuple[float, float, tuple[int, int, int, int]] | None = None
    for rx0, ry0, rx1, ry1 in regions:
        if rx1 - rx0 < 2 or ry1 - ry0 < 2:
            continue
        ww, wh = _window(rx1 - rx0, ry1 - ry0, aspect)
        ww, wh = ww - ww % 2, wh - wh % 2
        x = min(max(round(width / 2 - ww / 2), rx0), rx1 - ww)
        y = min(max(round(height / 2 - wh / 2), ry0), ry1 - wh)
        key = (ww * wh, -math.dist((x + ww / 2, y + wh / 2), (width / 2, height / 2)))
        if best is None or key > best[:2]:
            best = (*key, (x, y, ww, wh))
    if best is None:
        raise ReframeError(f"aucune place pour le jeu hors de la facecam {exclude} dans {width}x{height}")
    return best[2]


def _reframe_stream(
    video_id: str,
    clip_id: str,
    start: float,
    end: float,
    out: Path,
    facecam: dict[str, Any],
    rect: dict[str, int],
    settings: dict[str, Any],
) -> Path:
    """Un seul plan, rectangles figes sur tout le clip : fond flou, camera
    (rectangle de la facecam) en haut, jeu en bas ; aucun suivi ni zoom
    (SPEC-3a88 regle 3)."""
    source_w, source_h = facecam["source"]["width"], facecam["source"]["height"]
    out_w, out_h = int(settings["output_width"]), int(settings["output_height"])
    cam_w, cam_h, top = _camera_size(settings)
    if abs(rect["w"] / rect["h"] - cam_w / cam_h) > 0.02 * cam_w / cam_h:
        raise ReframeError(
            f"facecam.json ({rect['w']}x{rect['h']}) calcule pour un autre panneau camera ({cam_w}x{cam_h}) : "
            "relancer reframe --force"
        )
    game_top = top + cam_h
    game_h = out_h - game_top
    if top < 0 or game_h <= 0:
        raise ReframeError(f"[reframe] stream_top/stream_camera_ratio : panneau camera hors de {out_w}x{out_h}")
    margin = int(settings["stream_exclude_margin"])
    exclude = (
        max(0, rect["x"] - margin), max(0, rect["y"] - margin),
        min(source_w, rect["x"] + rect["w"] + margin), min(source_h, rect["y"] + rect["h"] + margin),
    )
    gx, gy, gw, gh = _game_window(source_w, source_h, out_w / game_h, exclude)

    camera_dest = (0, top, out_w, game_top)
    safe_left, safe_right = int(settings["safe_left"]), int(settings["safe_right"])
    safe_top, safe_bottom = int(settings["safe_top"]), int(settings["safe_bottom"])
    text_gap, part_height = int(settings["text_gap"]), int(settings["part_height"])
    zones = {
        "title": (safe_left, safe_top, safe_right, top - text_gap),
        "subtitles": (safe_left, game_top + text_gap, safe_right, safe_bottom - part_height - text_gap),
        "part": (safe_left, safe_bottom - part_height, safe_right, safe_bottom),
    }
    for name, (x0, y0, x1, y1) in zones.items():
        if x1 <= x0 or y1 <= y0 or x0 < 0 or y0 < 0 or x1 > out_w or y1 > out_h:
            raise ReframeError(f"[reframe] zone {name} du format stream vide ou hors cadre : ({x0},{y0})-({x1},{y1})")
        if _rects_overlap(camera_dest, (x0, y0, x1, y1)):
            raise ReframeError(f"[reframe] zone {name} du format stream recouvre la facecam : ({x0},{y0})-({x1},{y1})")

    def panel(name: str, x: int, y: int, w: int, h: int, dest: tuple[int, int, int, int]) -> dict[str, Any]:
        return {
            "name": name,
            "dest": {"x": dest[0], "y": dest[1], "w": dest[2], "h": dest[3]},
            "rects": [{"start": start, "end": end, "x": x, "y": y, "w": w, "h": h}],
        }

    background = panel("background", 0, 0, source_w, source_h, (0, 0, out_w, out_h))
    panels = [
        {"name": "background", "effect": "blur", "dest": background["dest"], "rects": background["rects"]},
        panel("camera", rect["x"], rect["y"], rect["w"], rect["h"], (0, top, out_w, cam_h)),
        panel("gameplay", gx, gy, gw, gh, (0, game_top, out_w, game_h)),
    ]
    data = {
        "video_id": video_id,
        "clip_id": clip_id,
        "start": start,
        "end": end,
        "source": {"width": source_w, "height": source_h},
        "output": {"width": out_w, "height": out_h},
        "layout": "stream",
        "format": "letterbox",
        "layout_mode": settings["layout"],
        "layout_reason": None,
        "facecam": dict(rect),
        "text_zones": {
            name: {"x0": x0, "y0": y0, "x1": x1, "y1": y1} for name, (x0, y0, x1, y1) in zones.items()
        },
        "plans": [{
            "index": 0,
            "start": start,
            "end": end,
            "image": None,
            "llm": None,
            "layout": "stream",
            "reason": None,
            "faces": [],
            "panels": panels,
        }],
    }
    log.info("reframe %s/%s : stream, facecam %s", video_id, clip_id, rect)
    _write_plan(out, data)
    return out


# --------------------------------------------------------------------------
# Agencement stream split (SPEC-76dc) : webcam en haut, jeu en bas, tous
# deux recadres (jamais etires) au ratio de leur rectangle dest.
# --------------------------------------------------------------------------


def _crop_to_ratio(box: Box, aspect: float) -> Box:
    """``box`` rogne symetriquement autour de son centre pour atteindre
    ``aspect`` (largeur/hauteur) : jamais etire, jamais agrandi."""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    if w / h > aspect:
        new_w = h * aspect
        dx = (w - new_w) / 2
        return x0 + dx, y0, x1 - dx, y1
    new_h = w / aspect
    dy = (h - new_h) / 2
    return x0, y0 + dy, x1, y1 - dy


def _split_webcam_rect(facecam_rect: dict[str, int], dest: dict[str, Any]) -> dict[str, int]:
    """Rectangle source de la webcam : le rectangle deja localise
    (``facecam_rect``), rogne au ratio de ``dest`` en le centrant sur lui
    (SPEC-76dc, agencement split)."""
    box = (
        float(facecam_rect["x"]), float(facecam_rect["y"]),
        float(facecam_rect["x"] + facecam_rect["w"]), float(facecam_rect["y"] + facecam_rect["h"]),
    )
    x0, y0, x1, y1 = _crop_to_ratio(box, float(dest["w"]) / float(dest["h"]))
    x0, y0, x1, y1 = round(x0), round(y0), round(x1), round(y1)
    return {"x": x0, "y": y0, "w": max(1, x1 - x0), "h": max(1, y1 - y0)}


def _split_gameplay_rect(
    source_w: int, source_h: int, dest: dict[str, Any], webcam_source: dict[str, int]
) -> tuple[dict[str, int], str | None]:
    """Rectangle source du jeu : la plus grande fenetre au ratio de ``dest``
    (pleine hauteur en general), centree dans la largeur qui reste une fois
    la colonne de la webcam exclue quand c'est possible ; sinon centree dans
    l'image entiere, avec une note (repli silencieux accepte, SPEC-76dc)."""
    ww, wh = _window(source_w, source_h, float(dest["w"]) / float(dest["h"]))
    ex0, ex1 = webcam_source["x"], webcam_source["x"] + webcam_source["w"]
    left_w, right_w = ex0, source_w - ex1
    note = None
    if left_w >= ww and left_w >= right_w:
        x = round((left_w - ww) / 2)
    elif right_w >= ww:
        x = ex1 + round((right_w - ww) / 2)
    else:
        x = round((source_w - ww) / 2)
        note = (
            f"jeu recadre au centre ({ww}x{wh}) : la zone webcam ({webcam_source}) ne laisse pas assez de "
            f"largeur pour l'exclure (gauche {left_w}px, droite {right_w}px, {ww}px requis)"
        )
    y = round((source_h - wh) / 2)
    return {"x": x, "y": y, "w": ww, "h": wh}, note


def _reframe_stream_split(
    video_id: str,
    clip_id: str,
    start: float,
    end: float,
    out: Path,
    facecam: dict[str, Any],
    rect: dict[str, int],
    settings: dict[str, Any],
) -> Path:
    """Un seul plan, rectangles figes sur tout le clip : webcam en haut,
    jeu en bas, tous deux recadres (jamais etires) au ratio de leur
    rectangle dest (SPEC-76dc) ; aucun suivi ni zoom, comme le format stream
    'top' (SPEC-3a88 regle 3)."""
    source_w, source_h = facecam["source"]["width"], facecam["source"]["height"]
    out_w, out_h = int(settings["output_width"]), int(settings["output_height"])
    webcam_dest = settings["split_webcam_dest"]
    gameplay_dest = settings["split_gameplay_dest"]
    webcam_source = _split_webcam_rect(rect, webcam_dest)
    gameplay_source, note = _split_gameplay_rect(source_w, source_h, gameplay_dest, webcam_source)

    def panel(name: str, src: dict[str, int], dest: dict[str, Any]) -> dict[str, Any]:
        return {
            "name": name,
            "dest": {"x": dest["x"], "y": dest["y"], "w": dest["w"], "h": dest["h"]},
            "rects": [{"start": start, "end": end, **src}],
        }

    panels = [panel("webcam", webcam_source, webcam_dest), panel("gameplay", gameplay_source, gameplay_dest)]

    safe_left, safe_right = int(settings["safe_left"]), int(settings["safe_right"])
    safe_top, safe_bottom = int(settings["safe_top"]), int(settings["safe_bottom"])
    text_gap, part_height = int(settings["text_gap"]), int(settings["part_height"])
    badge_dest = settings["badge_dest"]
    subtitle_dest = settings["split_subtitle_dest"]
    zones: dict[str, tuple[int, int, int, int]] = {
        "badge": (badge_dest["x"], badge_dest["y"], badge_dest["x"] + badge_dest["w"], badge_dest["y"] + badge_dest["h"]),
        "subtitles": (
            subtitle_dest["x"], subtitle_dest["y"],
            subtitle_dest["x"] + subtitle_dest["w"], subtitle_dest["y"] + subtitle_dest["h"],
        ),
        "part": (safe_left, safe_bottom - part_height, safe_right, safe_bottom),
    }
    # Zone titre : reframe ignore [render] title_enabled (une etape ne lit
    # jamais la config d'une autre, ADR-b16b) ; elle fournit la zone quand la
    # geometrie le permet (place au-dessus de la webcam), l'omet sinon --
    # render.py exige alors une erreur explicite s'il doit malgre tout
    # dessiner un titre (ADR-ad2e).
    title_bottom = int(webcam_dest["y"]) - text_gap
    if title_bottom > safe_top:
        zones["title"] = (safe_left, safe_top, safe_right, title_bottom)
    for name, (x0, y0, x1, y1) in zones.items():
        if x0 < 0 or y0 < 0 or x1 > out_w or y1 > out_h:
            raise ReframeError(f"[reframe] zone {name} de l'agencement split hors cadre : ({x0},{y0})-({x1},{y1})")

    data = {
        "video_id": video_id,
        "clip_id": clip_id,
        "start": start,
        "end": end,
        "source": {"width": source_w, "height": source_h},
        "output": {"width": out_w, "height": out_h},
        "layout": "stream_split",
        "format": "letterbox",
        "layout_mode": settings["layout"],
        "layout_reason": None,
        "facecam": dict(rect),
        "text_zones": {
            name: {"x0": x0, "y0": y0, "x1": x1, "y1": y1} for name, (x0, y0, x1, y1) in zones.items()
        },
        "plans": [{
            "index": 0,
            "start": start,
            "end": end,
            "image": None,
            "llm": None,
            "layout": "stream_split",
            "reason": note,
            "faces": [],
            "panels": panels,
        }],
    }
    log.info(
        "reframe %s/%s : stream_split, webcam %s, jeu %s", video_id, clip_id, webcam_source, gameplay_source
    )
    _write_plan(out, data)
    return out


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
            "- #{id} : environ x={x:.2f}, y={y:.2f} (normalise), present {p}/{n} images, {r}".format(
                id=tr.id,
                x=_center(tr.mean_box())[0] / width,
                y=_center(tr.mean_box())[1] / height,
                p=len(tr.present()),
                n=len(plan.times),
                r="retenu" if tr.retained else "non retenu (trop petit, trop bref ou intermittent)",
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
        "- single : un plan filme classique. face = numero d'un visage retenu a suivre (la "
        "personne qui parle ou le sujet principal), null s'il n'y a aucun visage retenu ; "
        "camera = null. Un visage non retenu ne peut pas etre suivi.\n"
        "ignore : numeros des detections qui ne sont pas des visages (main, objet, "
        "motif...) ; elles ne seront pas protegees par le cadrage. [] si toutes sont des "
        "visages.\n"
        "reason : une phrase de justification (dire ce que sont les detections ignorees)."
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
    ids = [tr.id for tr in plan.tracks]
    ignore = answer.get("ignore", [])
    unknown = [i for i in ignore if i not in ids]
    if unknown:
        raise llm.SchemaError(f"ignore : visage(s) {unknown} inconnu(s) (visages du plan : {ids})")
    if answer["layout"] != "facecam_gameplay" and ids:
        # Sans visage detecte (ids vide), la question posee au modele n'a
        # aucune reponse valable possible (single() ignore de toute facon
        # ``face`` quand plan.tracks est vide, aucun id ne peut y correspondre) :
        # ce n'est pas une valeur de secours (ADR-ad2e), juste une contrainte
        # qui ne s'applique qu'en presence d'au moins un visage a choisir.
        face = answer["face"]
        if face is not None and face not in ids:
            raise llm.SchemaError(f"visage #{face} inconnu (visages du plan : {ids})")
        if face in ignore:
            raise llm.SchemaError(f"visage #{face} a la fois suivi et ignore")
        retained = [tr.id for tr in plan.tracks if tr.retained]
        if face is not None and face not in retained:
            raise llm.SchemaError(f"visage #{face} non retenu : seul un visage retenu {retained} peut etre suivi")


# --------------------------------------------------------------------------
# Entree de l'etape
# --------------------------------------------------------------------------


def _settings(config: Any) -> dict[str, Any]:
    if config is None:
        from clipper.config import load_config

        config = load_config()
    settings = {**CONFIG_DEFAULTS, **config.section("reframe")}
    if settings["format"] not in _FORMATS:
        raise ReframeError(f"[reframe] format inconnu {settings['format']!r} (attendu : {' | '.join(_FORMATS)})")
    if settings["layout"] not in _LAYOUT_MODES:
        raise ReframeError(
            f"[reframe] layout inconnu {settings['layout']!r} (attendu : {' | '.join(_LAYOUT_MODES)})"
        )
    if settings["layout"] != "letterbox" and settings["format"] != "letterbox":
        raise ReframeError(
            f"[reframe] layout = {settings['layout']!r} demande format = \"letterbox\" "
            f"(le format {settings['format']!r} est fige)"
        )
    if not all(isinstance(m, (int, float)) and m >= 0 for m in settings["fit_margins"]):
        raise ReframeError(f"[reframe] fit_margins invalide {settings['fit_margins']!r} (liste de marges >= 0)")
    if settings["fallback"] not in _FALLBACKS:
        raise ReframeError(f"[reframe] fallback invalide {settings['fallback']!r} (attendu : {' | '.join(_FALLBACKS)})")
    if settings["stream_variant"] not in _STREAM_VARIANTS:
        raise ReframeError(
            f"[reframe] stream_variant inconnu {settings['stream_variant']!r} "
            f"(attendu : {' | '.join(_STREAM_VARIANTS)})"
        )
    if settings["stream_variant"] == "split":
        _validate_split_geometry(settings)
    return settings


def _dest_box(name: str, dest: Any) -> tuple[int, int, int, int]:
    if not isinstance(dest, dict) or set(dest) != {"x", "y", "w", "h"}:
        raise ReframeError(f"[reframe] {name} invalide {dest!r} (attendu un rectangle {{x, y, w, h}})")
    x, y, w, h = dest["x"], dest["y"], dest["w"], dest["h"]
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (x, y, w, h)) or w <= 0 or h <= 0:
        raise ReframeError(f"[reframe] {name} invalide {dest!r} (attendu x, y, w, h numeriques, w > 0, h > 0)")
    return x, y, x + w, y + h


def _validate_split_geometry(settings: dict[str, Any]) -> None:
    """Geometrie de l'agencement split (SPEC-76dc), verifiee des le
    chargement de la config (ne depend que d'elle, jamais de la source) :
    webcam/jeu dans le canevas sans se chevaucher, badge/sous-titres dans la
    zone sure TikTok sans se chevaucher entre eux (ADR-ad2e : jamais un
    rendu tronque ou chevauchant en silence)."""
    out_w, out_h = int(settings["output_width"]), int(settings["output_height"])
    webcam = _dest_box("split_webcam_dest", settings["split_webcam_dest"])
    gameplay = _dest_box("split_gameplay_dest", settings["split_gameplay_dest"])
    badge = _dest_box("badge_dest", settings["badge_dest"])
    subtitles = _dest_box("split_subtitle_dest", settings["split_subtitle_dest"])

    for name, (x0, y0, x1, y1) in (
        ("split_webcam_dest", webcam), ("split_gameplay_dest", gameplay),
        ("badge_dest", badge), ("split_subtitle_dest", subtitles),
    ):
        if x0 < 0 or y0 < 0 or x1 > out_w or y1 > out_h:
            raise ReframeError(f"[reframe] {name} deborde du canevas {out_w}x{out_h} : ({x0},{y0})-({x1},{y1})")

    if _rects_overlap(webcam, gameplay):
        raise ReframeError(
            f"[reframe] split_webcam_dest {settings['split_webcam_dest']!r} et split_gameplay_dest "
            f"{settings['split_gameplay_dest']!r} se chevauchent"
        )

    safe_left, safe_right = int(settings["safe_left"]), int(settings["safe_right"])
    safe_top, safe_bottom = int(settings["safe_top"]), int(settings["safe_bottom"])
    for name, (x0, y0, x1, y1) in (("badge_dest", badge), ("split_subtitle_dest", subtitles)):
        if x0 < safe_left or y0 < safe_top or x1 > safe_right or y1 > safe_bottom:
            raise ReframeError(
                f"[reframe] {name} hors de la zone sure TikTok "
                f"(x {safe_left}-{safe_right}, y {safe_top}-{safe_bottom}) : ({x0},{y0})-({x1},{y1})"
            )
    if _rects_overlap(badge, subtitles):
        raise ReframeError(
            f"[reframe] badge_dest {settings['badge_dest']!r} et split_subtitle_dest "
            f"{settings['split_subtitle_dest']!r} se chevauchent"
        )


def _plans(scenes_file: Path, start: float, end: float, fps: float, min_seconds: float) -> list[_Plan]:
    """Plans du clip : scenes.json coupe a [start, end], chaque plan de moins
    de ``min_seconds`` fusionne au plan precedent (au suivant s'il est le
    premier)."""
    if not scenes_file.exists():
        raise ReframeError(f"scenes.json absent : {scenes_file}")
    scenes = json.loads(scenes_file.read_text(encoding="utf-8"))["scenes"]
    spans: list[list[float]] = []
    for scene in scenes:
        s, e = max(start, scene["start"]), min(end, scene["end"])
        if e - s > 1e-3:
            spans.append([s, e])
    if not spans:
        raise ReframeError(f"aucun plan de scenes.json ne recouvre le clip [{start}, {end}]")
    while len(spans) > 1:
        short = [i for i, (s, e) in enumerate(spans) if e - s < min_seconds]
        if not short:
            break
        i = short[0]
        if i == 0:
            spans[1][0] = spans[0][0]
        else:
            spans[i - 1][1] = spans[i][1]
        del spans[i]
    return [_Plan(index=k, start=s, end=e, times=_sample_times(s, e, fps)) for k, (s, e) in enumerate(spans)]


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
    settings = _settings(config)
    if out.exists() and not force:
        existing = json.loads(out.read_text(encoding="utf-8"))
        existing_format = existing.get("format", "crop")
        if existing_format != settings["format"]:
            raise ReframeError(
                f"reframe/{clip_id}.json existant au format {existing_format!r}, config [reframe] "
                f"demande {settings['format']!r} : --force pour le recalculer"
            )
        existing_mode = existing.get("layout_mode", "letterbox")
        if existing_format == "letterbox" and existing_mode != settings["layout"]:
            raise ReframeError(
                f"reframe/{clip_id}.json existant calcule avec layout = {existing_mode!r}, config [reframe] "
                f"demande {settings['layout']!r} : --force pour le recalculer"
            )
        existing_layout = existing.get("layout")
        if existing_layout in ("stream", "stream_split"):
            existing_variant = "split" if existing_layout == "stream_split" else "top"
            if existing_variant != settings["stream_variant"]:
                raise ReframeError(
                    f"reframe/{clip_id}.json existant calcule avec stream_variant = {existing_variant!r}, "
                    f"config [reframe] demande {settings['stream_variant']!r} : --force pour le recalculer"
                )
        return out

    video = video_dir / f"{video_id}.mp4"
    if not video.exists():
        raise ReframeError(f"video absente : {video}")

    if settings["format"] == "letterbox" and settings["layout"] == "stream_auto":
        facecam = json.loads(
            detect_facecam(video_id, workspace_dir, config=config, detector_factory=detector_factory)
            .read_text(encoding="utf-8")
        )
        rect, reason = _clip_facecam(facecam, start, end, settings, video_dir)
        if rect is not None:
            if settings["stream_variant"] == "split":
                return _reframe_stream_split(video_id, clip_id, start, end, out, facecam, rect, settings)
            return _reframe_stream(video_id, clip_id, start, end, out, facecam, rect, settings)
        log.info("reframe %s/%s : letterbox, pas de stream (%s)", video_id, clip_id, reason)
        return _reframe_letterbox(
            video_id, clip_id, start, end, out, video, settings, frame_source, layout_reason=reason
        )
    if settings["format"] == "letterbox":
        return _reframe_letterbox(video_id, clip_id, start, end, out, video, settings, frame_source)

    if detector_factory is None:
        if settings["detector"] not in _DETECTORS:
            raise ReframeError(
                f"[reframe] detecteur inconnu {settings['detector']!r} (attendu : {' | '.join(_DETECTORS)})"
            )
        detector_factory = _DETECTORS[settings["detector"]]
    fps = float(settings["sample_fps"])
    plans = _plans(video_dir / "scenes.json", start, end, fps, float(settings["min_plan_seconds"]))

    width, height = _detect(plans, video, settings, detector_factory, frame_source)
    geometry = _Geometry(width, height, settings)
    for plan in plans:
        plan.tracks = _build_tracks(plan.detections, fps, settings)
        _retain(plan.tracks, fps, height, settings)

    results = []
    for plan in plans:
        image = out_dir / clip_id / f"plan_{plan.index:03d}.jpg"
        _annotate(plan, image, int(settings["jpeg_quality"]))
        answer = llm.ask("layout", _prompt(plan, width, height), [image], LAYOUT_SCHEMA, config=config)
        _check_answer(answer, plan)
        for tr in plan.tracks:
            if tr.id in answer.get("ignore", []):
                tr.retained = False

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
                split_min = float(settings["split_min_seconds"])
                try:
                    if plan.end - plan.start < split_min:
                        raise _Infeasible(
                            f"plan de {plan.end - plan.start:.2f}s, moins que split_min_seconds ({split_min:g}s)"
                        )
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
