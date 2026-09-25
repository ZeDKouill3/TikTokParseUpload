"""Etape qa : controle qualite de chaque clip rendu (SPEC-350f), avis de
clipper.llm (usage ``qa``) complete de verifications mecaniques locales.

Entrees : output/<video_id>/<clip_id>.mp4 et output/<video_id>/<clip_id>.json
tels qu'ecrits par l'etape render (lus sur disque, jamais en important
render - ADR-b16b).

Pour chaque clip :
- images fixes extraites du .mp4 par OpenCV (debut, milieu, fin, et une juste
  apres chaque changement de plan, detecte par ecart d'histogramme HSV entre
  images successives), ecrites en JPEG sous workspace/<video_id>/qa/<clip_id>/ ;
- l'IA recoit ces images (jamais la video ni l'audio - ADR-b1c1), le texte
  d'accroche et la transcription du clip (champ ``transcript`` du JSON), et
  liste les defauts parmi : visage coupe (face_cut), sous-titre sur un visage
  (subtitle_on_face), debut en milieu de phrase (starts_mid_sentence),
  accroche faible (weak_hook), ecran noir (black_screen) ;
- verifications locales par ffprobe/ffmpeg : duree reelle vs ``duration`` du
  JSON, resolution attendue (1080x1920), silence initial superieur au seuil
  (1 s par defaut ; pas de piste audio = silence).

Sortie : le JSON du clip est mis a jour en place :

    "qa": {"status": "passed" | "rejected",
           "issues": [{"type", "detail", "source": "llm" | "local"}]},
    "ready": true | false

``rejected`` des qu'il y a un defaut, d'ou qu'il vienne ; ``ready`` n'est
vrai que pour un clip ``passed`` (voir ``is_ready``, a utiliser par tout
consommateur). Reponse invalide ou Claude indisponible : l'erreur remonte et
le JSON n'est pas touche, aucun verdict de secours (ADR-ad2e). Un clip deja
controle (passed/rejected) n'est pas recontrole, sauf ``force``.
"""

from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from clipper import llm

CONFIG_DEFAULTS: dict[str, object] = {
    "expected_width": 1080,
    "expected_height": 1920,
    # Ecart tolere (s) entre la duree reelle du .mp4 et ``duration`` du JSON.
    "duration_tolerance": 0.5,
    # Silence initial (s) au-dela duquel le clip est rejete.
    "max_leading_silence": 1.0,
    # Niveau (dBFS, RMS par fenetre) sous lequel l'audio compte comme silence.
    "silence_threshold_db": -45.0,
    "silence_window": 0.02,
    # Correlation d'histogramme HSV sous laquelle deux images successives
    # appartiennent a deux plans differents.
    "shot_change_threshold": 0.5,
    # Decalage (s) des images prises apres le debut du clip et apres une coupe.
    "frame_offset": 0.1,
    # Deux images plus proches que cet ecart (s) sont fusionnees.
    "frame_min_gap": 0.3,
    # Au-dela, les changements de plan retenus sont repartis uniformement.
    "max_shot_frames": 10,
    "frame_width": 540,
    "jpeg_quality": 85,
}

DEFECTS: dict[str, str] = {
    "face_cut": "un visage est coupe par le bord du cadre",
    "subtitle_on_face": "un sous-titre ou un texte incruste recouvre un visage",
    "starts_mid_sentence": "le clip commence au milieu d'une phrase",
    "weak_hook": "l'accroche (texte affiche et premiers mots) ne donne pas envie de rester",
    "black_screen": "une image est noire ou vide",
}

_CHECKED = ("passed", "rejected")


class QAError(Exception):
    """Clip rendu absent ou illisible, ou echec de ffmpeg/ffprobe/OpenCV."""


# --------------------------------------------------------------------------
# Lecture de l'etat
# --------------------------------------------------------------------------


def is_ready(clip: dict[str, Any]) -> bool:
    """Un clip n'est pret a publier que s'il a passe le controle qualite
    (SPEC-350f : un clip rejete ne l'est jamais, quel que soit ``ready``)."""
    return clip.get("qa", {}).get("status") == "passed" and clip.get("ready") is True


# --------------------------------------------------------------------------
# ffprobe / ffmpeg
# --------------------------------------------------------------------------


def _probe(mp4: Path, ffprobe_bin: str) -> dict[str, Any]:
    cmd = [
        ffprobe_bin, "-v", "error", "-show_entries", "stream=codec_type,width,height",
        "-show_entries", "format=duration", "-of", "json", str(mp4),
    ]
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError as exc:
        raise QAError(f"ffprobe introuvable ({ffprobe_bin})") from exc
    if proc.returncode != 0:
        raise QAError(f"ffprobe a echoue sur {mp4} : {proc.stderr.decode(errors='replace').strip()}")
    return json.loads(proc.stdout)


def _leading_silence(mp4: Path, settings: dict[str, Any], ffmpeg_bin: str) -> float:
    """Secondes de silence au debut de la piste audio (decodee en mono
    16 kHz sur les premieres secondes seulement)."""
    limit = float(settings["max_leading_silence"]) + 1.0
    rate = 16000
    cmd = [
        ffmpeg_bin, "-v", "error", "-t", f"{limit:.3f}", "-i", str(mp4),
        "-vn", "-ac", "1", "-ar", str(rate), "-f", "s16le", "-",
    ]
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError as exc:
        raise QAError(f"ffmpeg introuvable ({ffmpeg_bin})") from exc
    if proc.returncode != 0:
        raise QAError(f"ffmpeg a echoue sur {mp4} : {proc.stderr.decode(errors='replace').strip()}")
    samples = np.frombuffer(proc.stdout, dtype=np.int16).astype(np.float64) / 32768.0
    win = max(1, int(rate * float(settings["silence_window"])))
    threshold = 10 ** (float(settings["silence_threshold_db"]) / 20)
    for i in range(0, len(samples) - win + 1, win):
        rms = math.sqrt(float(np.mean(samples[i:i + win] ** 2)))
        if rms > threshold:
            return i / rate
    return len(samples) / rate


def _local_issues(mp4: Path, clip: dict[str, Any], settings: dict[str, Any], ffmpeg_bin: str, ffprobe_bin: str) -> list[dict[str, Any]]:
    info = _probe(mp4, ffprobe_bin)
    streams = info.get("streams", [])
    issues: list[dict[str, Any]] = []

    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    want_w, want_h = int(settings["expected_width"]), int(settings["expected_height"])
    if video is None:
        issues.append({"type": "resolution", "detail": "aucune piste video", "source": "local"})
    elif (video.get("width"), video.get("height")) != (want_w, want_h):
        issues.append({
            "type": "resolution",
            "detail": f"{video.get('width')}x{video.get('height')} au lieu de {want_w}x{want_h}",
            "source": "local",
        })

    actual = float(info.get("format", {}).get("duration", 0.0))
    expected = float(clip["duration"])
    if abs(actual - expected) > float(settings["duration_tolerance"]):
        issues.append({
            "type": "duration",
            "detail": f"duree reelle {actual:.2f} s, {expected:.2f} s annoncee dans le JSON",
            "source": "local",
        })

    max_silence = float(settings["max_leading_silence"])
    if not any(s.get("codec_type") == "audio" for s in streams):
        issues.append({"type": "leading_silence", "detail": "aucune piste audio", "source": "local"})
    else:
        silence = _leading_silence(mp4, settings, ffmpeg_bin)
        if silence > max_silence:
            issues.append({
                "type": "leading_silence",
                "detail": f"{silence:.2f} s de silence au debut (max {max_silence:.2f} s)",
                "source": "local",
            })
    return issues


# --------------------------------------------------------------------------
# Images fixes : debut, milieu, fin, une par changement de plan
# --------------------------------------------------------------------------


def _hist(frame: np.ndarray) -> np.ndarray:
    small = cv2.resize(frame, (64, 64))
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], None, [30, 32], [0, 180, 0, 256])
    return cv2.normalize(hist, hist)


def _open(mp4: Path) -> cv2.VideoCapture:
    capture = cv2.VideoCapture(str(mp4))
    if not capture.isOpened():
        raise QAError(f"OpenCV ne peut pas lire {mp4}")
    return capture


def _scan(mp4: Path, threshold: float) -> tuple[int, float, list[int]]:
    """(nombre d'images, fps, indices des premieres images de chaque nouveau plan)."""
    capture = _open(mp4)
    try:
        fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
        cuts: list[int] = []
        prev = None
        n = 0
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            hist = _hist(frame)
            if prev is not None and cv2.compareHist(prev, hist, cv2.HISTCMP_CORREL) < threshold:
                cuts.append(n)
            prev = hist
            n += 1
    finally:
        capture.release()
    if n == 0:
        raise QAError(f"aucune image lisible dans {mp4}")
    return n, fps, cuts


def _spread(items: list[int], k: int) -> list[int]:
    """Au plus ``k`` elements de ``items``, repartis uniformement."""
    if len(items) <= k:
        return items
    step = len(items) / k
    return [items[int(i * step)] for i in range(k)]


def _targets(n: int, fps: float, cuts: list[int], settings: dict[str, Any]) -> list[tuple[int, list[str]]]:
    """Indices d'images a extraire, tries, avec leurs etiquettes ; deux
    cibles trop proches sont fusionnees."""
    offset = int(round(float(settings["frame_offset"]) * fps))
    raw: list[tuple[int, str]] = [(min(offset, n - 1), "debut"), (n // 2, "milieu"), (n - 1, "fin")]
    for cut in _spread(cuts, int(settings["max_shot_frames"])):
        raw.append((min(cut + offset, n - 1), "changement de plan"))
    raw.sort()
    gap = float(settings["frame_min_gap"]) * fps
    merged: list[tuple[int, list[str]]] = []
    for index, label in raw:
        if merged and index - merged[-1][0] < gap:
            if label not in merged[-1][1]:
                merged[-1][1].append(label)
            continue
        merged.append((index, [label]))
    return merged


def _extract_frames(mp4: Path, dest: Path, settings: dict[str, Any]) -> list[tuple[Path, float, list[str]]]:
    n, fps, cuts = _scan(mp4, float(settings["shot_change_threshold"]))
    targets = dict(_targets(n, fps, cuts, settings))
    dest.mkdir(parents=True, exist_ok=True)
    for old in dest.glob("*.jpg"):
        old.unlink()
    width = int(settings["frame_width"])
    frames: list[tuple[Path, float, list[str]]] = []
    capture = _open(mp4)
    try:
        index = 0
        while len(frames) < len(targets):
            ok, frame = capture.read()
            if not ok:
                break
            if index in targets:
                h, w = frame.shape[:2]
                if w > width:
                    frame = cv2.resize(frame, (width, round(h * width / w)))
                path = dest / f"{len(frames) + 1:02d}.jpg"
                if not cv2.imwrite(str(path), frame, [cv2.IMWRITE_JPEG_QUALITY, int(settings["jpeg_quality"])]):
                    raise QAError(f"ecriture de {path} impossible")
                frames.append((path, index / fps, targets[index]))
            index += 1
    finally:
        capture.release()
    if len(frames) < len(targets):
        raise QAError(f"{mp4} : {len(frames)} images lues sur {len(targets)} attendues")
    return frames


# --------------------------------------------------------------------------
# Schema et prompt
# --------------------------------------------------------------------------


def response_schema() -> dict[str, Any]:
    """Ce que le LLM renvoie pour un clip : la liste de ses defauts (vide si
    le clip est bon)."""
    return {
        "type": "object",
        "properties": {
            "issues": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "enum": list(DEFECTS)},
                        "detail": {
                            "type": "string", "minLength": 1,
                            "description": "Ce qui est vu, et sur quelle image.",
                        },
                    },
                    "required": ["type", "detail"],
                    "additionalProperties": False,
                },
                "description": "Defauts constates ; liste vide si le clip est publiable.",
            },
        },
        "required": ["issues"],
        "additionalProperties": False,
    }


def _prompt(clip: dict[str, Any], frames: list[tuple[Path, float, list[str]]]) -> str:
    defects = "\n".join(f"- {key} : {text}" for key, text in DEFECTS.items())
    images = "\n".join(
        f"Image {k} : t={t:.2f} s ({', '.join(labels)})" for k, (_, t, labels) in enumerate(frames, 1)
    )
    return (
        "Tu fais le controle qualite d'un clip vertical TikTok deja rendu, avant publication.\n"
        "Tu vois des images fixes extraites du clip et sa transcription ; signale uniquement "
        "les defauts reellement visibles ou lisibles, parmi :\n"
        f"{defects}\n\n"
        "Un clip sans defaut rend une liste vide. En cas de doute franc, signale le defaut.\n\n"
        "## Clip\n"
        f"Duree : {float(clip['duration']):.1f} s ; langue : {clip.get('language') or '?'}\n"
        f"Texte d'accroche affiche les 2 premieres secondes : {clip.get('hook_text', '')}\n"
        f"Titre : {clip.get('title', '')}\n\n"
        "## Images jointes, dans cet ordre\n"
        f"{images}\n\n"
        "## Transcription du clip\n"
        f"{clip.get('transcript', '')}\n"
    )


# --------------------------------------------------------------------------
# Etape
# --------------------------------------------------------------------------


def _settings(config: Any) -> dict[str, Any]:
    if config is None:
        from clipper.config import load_config

        config = load_config()
    return {**CONFIG_DEFAULTS, **config.section("qa")}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def check_clip(
    json_path: Path,
    frames_dir: Path,
    settings: dict[str, Any],
    *,
    config: Any = None,
    ffmpeg_bin: str = "ffmpeg",
    ffprobe_bin: str = "ffprobe",
) -> dict[str, Any]:
    """Controle un clip rendu et reecrit son JSON avec ``qa`` et ``ready`` ;
    renvoie le champ ``qa``."""
    clip = json.loads(json_path.read_text(encoding="utf-8"))
    mp4 = json_path.with_suffix(".mp4")
    if not mp4.exists():
        raise QAError(f"video du clip absente : {mp4}")

    issues = _local_issues(mp4, clip, settings, ffmpeg_bin, ffprobe_bin)
    frames = _extract_frames(mp4, frames_dir, settings)
    answer = llm.ask("qa", _prompt(clip, frames), [p for p, _, _ in frames], response_schema(), config=config)
    issues = [{**issue, "source": "llm"} for issue in answer["issues"]] + issues

    status = "rejected" if issues else "passed"
    clip["qa"] = {"status": status, "issues": issues}
    clip["ready"] = status == "passed"
    _write_json(json_path, clip)
    return clip["qa"]


def run(
    video_id: str,
    workspace_dir: str | Path = "workspace",
    output_dir: str | Path = "output",
    *,
    config: Any = None,
    force: bool = False,
    ffmpeg_bin: str = "ffmpeg",
    ffprobe_bin: str = "ffprobe",
) -> Path:
    """Controle chaque clip rendu de output/<video_id>/ et met a jour son
    JSON ; renvoie ce dossier. Un clip deja controle n'est pas refait, sauf
    ``force``."""
    out_dir = Path(output_dir) / video_id
    clips = sorted(out_dir.glob("*.json")) if out_dir.is_dir() else []
    if not clips:
        raise QAError(f"aucun clip rendu dans {out_dir}")
    settings = _settings(config)
    frames_root = Path(workspace_dir) / video_id / "qa"
    for json_path in clips:
        clip = json.loads(json_path.read_text(encoding="utf-8"))
        if not force and clip.get("qa", {}).get("status") in _CHECKED:
            continue
        check_clip(
            json_path, frames_root / json_path.stem, settings,
            config=config, ffmpeg_bin=ffmpeg_bin, ffprobe_bin=ffprobe_bin,
        )
    return out_dir
