"""Etape scenes : detection des changements de plan et images cles.

Le decodage passe par ffmpeg en sous-processus (TASK-1f16) : l'analyse porte
sur des images reduites (``analysis_width`` pixels de large, au plus
``analysis_max_fps`` images/s), les images cles sont extraites en pleine
resolution. Le FFmpeg embarque par OpenCV ne decode l'AV1 qu'avec libaom
(~45 img/s en 1080p60 sur CPU charge) ; ffmpeg prend libdav1d (~700 img/s).
``decoder`` force un decodeur (``-c:v``) ; vide, ffmpeg prend celui qu'il
associe au codec. Un decodeur qui echoue fait echouer l'etape : aucun repli
vers un autre decodeur (ADR-ad2e). Aucun decodage materiel : rien ne passe
par le GPU ici (ADR-fb9b).

TASK-22a9 : un moment ne peut venir que d'une ligne de la transcription
(clipper.moments, regle de decoupe 1 : start/end = debut/fin d'une ligne), et
reframe coupe les plans de scenes.json exactement a [start, end] du moment ;
decoder toute la video (jusqu'a 1 h 52 de silence sur une VOD de 3 h) est donc
du temps perdu. ``detect_scenes`` ne decode que l'union des plages de parole
de transcript.json (segments), elargies de ``speech_margin_seconds`` (ponts
les silences courts entre deux lignes d'un meme moment), plus, si audio.json
existe deja (l'etape audio tourne apres scenes dans clipper.pipeline.STEPS :
le cas normal ne le voit jamais, seulement un ``--force`` rejoue apres coup),
une fenetre de la meme marge autour de chaque pic hors parole. transcript.json
est une entree obligatoire (comme scenes.json pour clipper.reframe) : absent,
ou sans aucun segment de parole, l'etape echoue plutot que de decoder toute
la video en silence (ADR-ad2e).
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from scenedetect import FrameTimecode
from scenedetect.detectors import ContentDetector
from scenedetect.scene_manager import get_scenes_from_cuts

CONFIG_DEFAULTS: dict[str, object] = {
    "threshold": 27.0,
    "keyframe_interval_seconds": 5.0,
    "jpeg_quality": 95,
    # Largeur (px) des images analysees ; PySceneDetect reduisait deja a ~256 px.
    "analysis_width": 256,
    # Cadence maximale d'analyse (img/s) ; une source plus lente garde la sienne.
    "analysis_max_fps": 30.0,
    # Decodeur ffmpeg force (-c:v) ; "" = celui que ffmpeg associe au codec.
    "decoder": "",
    # Processus ffmpeg d'extraction d'images cles lances en parallele au plus.
    "extract_parallel": 4,
    # Marge (s) ajoutee avant/apres chaque plage de parole avant decodage.
    "speech_margin_seconds": 5.0,
}


class ScenesError(Exception):
    """Scene detection or frame extraction failed."""


def _run(cmd: list[str], what: str) -> bytes:
    try:
        proc = subprocess.run(cmd, capture_output=True)
    except FileNotFoundError as exc:
        raise ScenesError(f"{cmd[0]} introuvable ({what})") from exc
    if proc.returncode != 0:
        raise ScenesError(
            f"{what} : {cmd[0]} a echoue (code {proc.returncode}) : "
            f"{proc.stderr.decode(errors='replace').strip()}"
        )
    return proc.stdout


def _decoder_args(decoder: str) -> list[str]:
    return ["-c:v", decoder] if decoder else []


def _decoder_name(decoder: str) -> str:
    return f"decodeur {decoder}" if decoder else "decodeur par defaut de ffmpeg"


def _probe(video_path: Path, ffprobe_bin: str) -> tuple[int, int, Fraction]:
    out = _run(
        [
            ffprobe_bin, "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height,avg_frame_rate,r_frame_rate",
            "-of", "json", str(video_path),
        ],
        f"lecture des proprietes de {video_path}",
    )
    streams = json.loads(out or b"{}").get("streams") or []
    if not streams:
        raise ScenesError(f"aucune piste video dans {video_path}")
    stream = streams[0]
    for key in ("avg_frame_rate", "r_frame_rate"):
        num, _, den = str(stream.get(key, "0/0")).partition("/")
        if int(num or 0) > 0 and int(den or 1) > 0:
            return int(stream["width"]), int(stream["height"]), Fraction(int(num), int(den or 1))
    raise ScenesError(f"cadence d'images inconnue pour {video_path}")


def _read_json(path: Path) -> Any:
    if not path.exists():
        raise ScenesError(f"entree absente : {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _read_json_optional(path: Path) -> Any:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _merge_windows(windows: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Sorted, overlapping or touching windows collapsed into one each."""
    if not windows:
        return []
    ordered = sorted(windows)
    merged = [list(ordered[0])]
    for start, end in ordered[1:]:
        if start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(start, end) for start, end in merged]


def _speech_windows(
    transcript: dict[str, Any], audio: dict[str, Any], margin: float
) -> list[tuple[float, float]]:
    """Union of transcript.json speech segments, plus audio.json's out-of-speech
    peaks when that file already exists, each widened by ``margin``."""
    windows: list[tuple[float, float]] = []
    for segment in transcript.get("segments") or []:
        windows.append((max(0.0, segment["start"] - margin), segment["end"] + margin))
    for peak in audio.get("peaks") or []:
        timecode = peak["timecode"]
        windows.append((max(0.0, timecode - margin), timecode + margin))
    return _merge_windows(windows)


def _analysis_size(width: int, height: int, analysis_width: int) -> tuple[int, int]:
    """Reduced size with even dimensions, never larger than the source."""
    out_w = min(int(analysis_width), width)
    out_h = round(height * out_w / width)
    return max(2, out_w - out_w % 2), max(2, out_h - out_h % 2)


def _decode_window_cuts(
    video_path: Path,
    window_start: float,
    window_end: float,
    threshold: float,
    decoder: str,
    ffmpeg_bin: str,
    fps: float,
    rate: Fraction,
    out_w: int,
    out_h: int,
) -> list[tuple[float, float]]:
    """Scene cuts within one [window_start, window_end) window, as times
    relative to the window's own start. Input-side seek (``-ss`` before
    ``-i``) skips decoding everything before ``window_start``."""
    frame_bytes = out_w * out_h * 3
    cmd = [
        ffmpeg_bin, "-v", "error", "-nostdin", "-noautorotate",
        "-ss", f"{window_start:.3f}",
        *_decoder_args(decoder), "-i", str(video_path),
        "-t", f"{window_end - window_start:.3f}",
        "-map", "0:v:0", "-an", "-sn",
        "-vf", f"fps={rate.numerator}/{rate.denominator},scale={out_w}:{out_h}",
        "-pix_fmt", "bgr24", "-f", "rawvideo", "-",
    ]
    detector = ContentDetector(threshold=threshold)
    cuts: list[FrameTimecode] = []
    count = 0
    with tempfile.TemporaryFile() as stderr:
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=stderr)
        except FileNotFoundError as exc:
            raise ScenesError(f"{ffmpeg_bin} introuvable (analyse de {video_path})") from exc
        assert proc.stdout is not None
        try:
            while len(buf := proc.stdout.read(frame_bytes)) == frame_bytes:
                frame = np.frombuffer(buf, np.uint8).reshape(out_h, out_w, 3)
                cuts += detector.process_frame(FrameTimecode(count, fps), frame)
                count += 1
        finally:
            proc.stdout.close()
            returncode = proc.wait()
        stderr.seek(0)
        message = stderr.read().decode(errors="replace").strip()

    if returncode != 0:
        raise ScenesError(
            f"decodage de {video_path} echoue ({_decoder_name(decoder)}, "
            f"code {returncode}) : {message}"
        )
    if count == 0:
        raise ScenesError(
            f"aucune image decodee dans {video_path} entre {window_start:.3f}s et "
            f"{window_end:.3f}s ({_decoder_name(decoder)}) : {message}"
        )

    end = FrameTimecode(count, fps)
    cuts += detector.post_process(end)
    scene_list = get_scenes_from_cuts(
        cut_list=sorted(set(cuts)), start_pos=FrameTimecode(0, fps), end_pos=end
    )
    return [(start.seconds, stop.seconds) for start, stop in scene_list]


def _detect_scene_list(
    video_path: Path,
    threshold: float,
    analysis_width: int,
    analysis_max_fps: float,
    decoder: str,
    windows: list[tuple[float, float]],
    ffmpeg_bin: str,
    ffprobe_bin: str,
) -> list[tuple[float, float]]:
    width, height, source_rate = _probe(video_path, ffprobe_bin)
    rate = min(source_rate, Fraction(analysis_max_fps).limit_denominator(1001))
    fps = float(rate)
    out_w, out_h = _analysis_size(width, height, analysis_width)

    scene_list: list[tuple[float, float]] = []
    for window_start, window_end in windows:
        window_scenes = _decode_window_cuts(
            video_path, window_start, window_end, threshold, decoder, ffmpeg_bin, fps, rate, out_w, out_h
        )
        scene_list += [(window_start + start, window_start + stop) for start, stop in window_scenes]
    return scene_list


def _keyframe_timecodes(start: float, end: float, interval: float) -> list[float]:
    """One keyframe in the middle of the plan, plus one every ``interval``
    seconds for plans longer than ``interval`` (see TASK-e374's
    done_criteria)."""
    timecodes = [start + (end - start) / 2]
    if interval > 0 and (end - start) > interval:
        t = start + interval
        while t < end:
            timecodes.append(t)
            t += interval
    return timecodes


def _extract_frame(video_path: Path, timecode: float, decoder: str, ffmpeg_bin: str):
    """Full-resolution image at ``timecode`` (accurate input seek; BMP on a
    pipe, so the size never has to be guessed)."""
    data = _run(
        [
            ffmpeg_bin, "-v", "error", "-nostdin", "-ss", f"{timecode:.3f}",
            *_decoder_args(decoder), "-i", str(video_path),
            "-map", "0:v:0", "-frames:v", "1", "-f", "image2pipe", "-c:v", "bmp", "-",
        ],
        f"extraction de l'image a {timecode:.3f}s de {video_path} ({_decoder_name(decoder)})",
    )
    frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR) if data else None
    if frame is None:
        raise ScenesError(
            f"impossible d'extraire l'image a {timecode:.3f}s ({_decoder_name(decoder)})"
        )
    return frame


def detect_scenes(
    video_path: str | Path,
    workspace_dir: str | Path,
    video_id: str,
    *,
    threshold: float = 27.0,
    keyframe_interval_seconds: float = 5.0,
    jpeg_quality: int = 95,
    analysis_width: int = 256,
    analysis_max_fps: float = 30.0,
    decoder: str = "",
    extract_parallel: int = 4,
    speech_margin_seconds: float = 5.0,
    ffmpeg_bin: str = "ffmpeg",
    ffprobe_bin: str = "ffprobe",
    force: bool = False,
) -> dict[str, Any]:
    """Detect plan changes with PySceneDetect and extract keyframes (ADR-b16b:
    a step reads its inputs and writes workspace/<video_id>/ itself).

    A video already analysed (scenes.json present) is not re-analysed unless
    ``force`` is set. Keyframes are extracted with at most ``extract_parallel``
    ffmpeg processes running at once (1 = sequential).

    Only the union of transcript.json's speech segments (widened by
    ``speech_margin_seconds``) is decoded -- a moment can only come from a
    transcript line (clipper.moments), so nothing outside speech can ever be
    cut into. audio.json's out-of-speech peaks are included too when that
    file already exists (it normally does not: clipper.pipeline runs audio
    after scenes). transcript.json is a required input, like scenes.json is
    for clipper.reframe: missing, or with no speech segment at all, the step
    fails rather than silently decoding the whole video (ADR-ad2e).
    """
    if extract_parallel < 1:
        raise ScenesError(
            f"extract_parallel doit etre >= 1 (recu {extract_parallel})"
        )
    video_path = Path(video_path)
    video_dir = Path(workspace_dir) / video_id
    scenes_file = video_dir / "scenes.json"
    frames_dir = video_dir / "frames"

    if scenes_file.exists() and not force:
        return json.loads(scenes_file.read_text(encoding="utf-8"))

    transcript = _read_json(video_dir / "transcript.json")
    audio = _read_json_optional(video_dir / "audio.json")
    windows = _speech_windows(transcript, audio, speech_margin_seconds)
    if not windows:
        raise ScenesError(
            f"aucun segment de parole dans {video_dir / 'transcript.json'} : "
            "rien a decoder"
        )

    scene_list = _detect_scene_list(
        video_path, threshold, analysis_width, analysis_max_fps, decoder, windows, ffmpeg_bin, ffprobe_bin
    )

    frames_dir.mkdir(parents=True, exist_ok=True)
    tasks: list[tuple[int, float, str]] = []
    for scene_index, (start, end) in enumerate(scene_list):
        timecodes = _keyframe_timecodes(start, end, keyframe_interval_seconds)
        for seq, timecode in enumerate(timecodes):
            filename = f"scene{scene_index:04d}_{seq:03d}.jpg"
            tasks.append((scene_index, timecode, filename))

    frames: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=extract_parallel) as executor:
        extracted = executor.map(
            lambda task: _extract_frame(video_path, task[1], decoder, ffmpeg_bin), tasks
        )
        for (scene_index, timecode, filename), frame in zip(tasks, extracted):
            cv2.imwrite(
                str(frames_dir / filename),
                frame,
                [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality],
            )
            frames.append(
                {
                    "path": f"frames/{filename}",
                    "timecode": timecode,
                    "scene": scene_index,
                }
            )

    result: dict[str, Any] = {
        "scenes": [{"start": start, "end": end} for start, end in scene_list],
        "frames": frames,
    }
    scenes_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
