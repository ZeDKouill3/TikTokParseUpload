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


def _analysis_size(width: int, height: int, analysis_width: int) -> tuple[int, int]:
    """Reduced size with even dimensions, never larger than the source."""
    out_w = min(int(analysis_width), width)
    out_h = round(height * out_w / width)
    return max(2, out_w - out_w % 2), max(2, out_h - out_h % 2)


def _detect_scene_list(
    video_path: Path,
    threshold: float,
    analysis_width: int,
    analysis_max_fps: float,
    decoder: str,
    ffmpeg_bin: str,
    ffprobe_bin: str,
) -> list[tuple[float, float]]:
    width, height, source_rate = _probe(video_path, ffprobe_bin)
    rate = min(source_rate, Fraction(analysis_max_fps).limit_denominator(1001))
    fps = float(rate)
    out_w, out_h = _analysis_size(width, height, analysis_width)
    frame_bytes = out_w * out_h * 3

    cmd = [
        ffmpeg_bin, "-v", "error", "-nostdin", "-noautorotate",
        *_decoder_args(decoder), "-i", str(video_path),
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
            f"aucune image decodee dans {video_path} ({_decoder_name(decoder)}) : {message}"
        )

    end = FrameTimecode(count, fps)
    cuts += detector.post_process(end)
    scene_list = get_scenes_from_cuts(
        cut_list=sorted(set(cuts)), start_pos=FrameTimecode(0, fps), end_pos=end
    )
    return [(start.seconds, stop.seconds) for start, stop in scene_list]


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
    ffmpeg_bin: str = "ffmpeg",
    ffprobe_bin: str = "ffprobe",
    force: bool = False,
) -> dict[str, Any]:
    """Detect plan changes with PySceneDetect and extract keyframes (ADR-b16b:
    a step reads its inputs and writes workspace/<video_id>/ itself).

    A video already analysed (scenes.json present) is not re-analysed unless
    ``force`` is set. Keyframes are extracted with at most ``extract_parallel``
    ffmpeg processes running at once (1 = sequential).
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

    scene_list = _detect_scene_list(
        video_path, threshold, analysis_width, analysis_max_fps, decoder, ffmpeg_bin, ffprobe_bin
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
