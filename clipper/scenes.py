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
les silences courts entre deux lignes d'un meme moment), plus, avec
``peak_windows=True``, une fenetre de la meme marge autour de chaque pic hors
parole d'audio.json (SPEC-b0f3 R4bis, ADR-4e57 : l'etape audio tourne AVANT
scenes dans clipper.pipeline.STEPS, qui positionne seul ``peak_windows`` d'apres
``[action] enabled`` ; scenes ne lit la config d'aucune autre etape). A False
(defaut), audio.json est ignore meme present et scenes.json est identique
octet pour octet a celui d'avant. A True, audio.json est une entree
obligatoire (ScenesError s'il manque) et scenes.json porte
``"peak_windows": true``. transcript.json
est une entree obligatoire (comme scenes.json pour clipper.reframe) : absent,
ou sans aucun segment de parole, l'etape echoue plutot que de decoder toute
la video en silence (ADR-ad2e).
"""

from __future__ import annotations

import json
import logging
import subprocess
import tempfile
import threading
import time
from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait
from fractions import Fraction
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from scenedetect import FrameTimecode
from scenedetect.detectors import ContentDetector as _StockContentDetector
from scenedetect.scene_manager import get_scenes_from_cuts

from clipper.channel import atomic_write_json

logger = logging.getLogger(__name__)

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
    # Processus ffmpeg de detection (fenetres ou morceaux) lances en parallele au plus.
    "detect_parallel": 4,
    # Duree (s) au-dela de laquelle une fenetre est decoupee en morceaux contigus
    # detectes en parallele puis recolles.
    "detect_chunk_seconds": 600.0,
    # -skip_loop_filter all a l entree de la detection seulement (jamais pour
    # l extraction des images cles, qui restent pleine qualite).
    "analysis_skip_loop_filter": True,
    # Marge (s) ajoutee avant/apres chaque plage de parole avant decodage.
    "speech_margin_seconds": 5.0,
    # Images cles extraites par processus ffmpeg (une entree -ss par image,
    # un seul demarrage et une seule ouverture du fichier par lot) ; 1 = un
    # processus par image.
    "extract_batch": 8,
    # Fils de decodage de chaque ffmpeg d'extraction (0 = defaut de ffmpeg :
    # tous les coeurs, que extract_parallel processus se disputent). Le
    # decodage h264 est deterministe : memes pixels quel que soit le nombre.
    "extract_threads": 2,
}


# Un dernier morceau plus court est recolle au precedent (pas de decodage vide).
MIN_TAIL_SECONDS = 2.0

# Images d'analyse lues d'un coup sur le tube de ffmpeg.
READ_BLOCK_FRAMES = 32


class ScenesError(Exception):
    """Scene detection or frame extraction failed."""


class ContentDetector(_StockContentDetector):
    """PySceneDetect's ContentDetector with the same score, computed faster:
    the three HSV channels are compared in one ``cv2.absdiff`` and one
    ``cv2.sumElems`` (exact integer sums) instead of a split and three int32
    numpy passes. Same operations in the same order on the same integers, so
    every score, hence every cut, is identical float for float. Only the
    default weights (hue, saturation, luma at 1, edges at 0) are supported:
    that is all this step uses."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if tuple(self._weights) != (1.0, 1.0, 1.0, 0.0):
            raise ScenesError("ContentDetector rapide : poids par defaut uniquement")
        self._last_hsv: np.ndarray | None = None

    def _calculate_frame_score(self, timecode: FrameTimecode, frame_img: np.ndarray) -> float:
        hsv = cv2.cvtColor(frame_img, cv2.COLOR_BGR2HSV)
        last, self._last_hsv = self._last_hsv, hsv
        if last is None:
            return 0.0
        hue, sat, lum, _ = cv2.sumElems(cv2.absdiff(hsv, last))
        pixels = float(hsv.shape[0] * hsv.shape[1])
        # sum() de PySceneDetect : 0 + h*1 + s*1 + l*1 + 0.0*0, puis / 3.0.
        return (hue / pixels + sat / pixels + lum / pixels) / 3.0


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


def _duration(video_path: Path, ffprobe_bin: str) -> float:
    out = _run(
        [
            ffprobe_bin, "-v", "error", "-show_entries", "format=duration",
            "-of", "json", str(video_path),
        ],
        f"lecture de la duree de {video_path}",
    )
    try:
        return float((json.loads(out or b"{}").get("format") or {})["duration"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ScenesError(f"duree inconnue pour {video_path}") from exc


def _read_json(path: Path) -> Any:
    if not path.exists():
        raise ScenesError(f"entree absente : {path}")
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
    peaks (``audio`` is empty unless peak windows are on), each widened by
    ``margin``."""
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
    skip_loop_filter: bool = False,
    running: set[subprocess.Popen] | None = None,
    running_lock: threading.Lock | None = None,
) -> list[tuple[float, float]]:
    """Scene cuts within one [window_start, window_end) window, as times
    relative to the window's own start. Input-side seek (``-ss`` before
    ``-i``) skips decoding everything before ``window_start``."""
    frame_bytes = out_w * out_h * 3
    cmd = [
        ffmpeg_bin, "-v", "error", "-nostdin", "-noautorotate",
        "-ss", f"{window_start:.3f}",
        *(["-skip_loop_filter", "all"] if skip_loop_filter else []),
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
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=stderr,
                bufsize=frame_bytes * READ_BLOCK_FRAMES,
            )
        except FileNotFoundError as exc:
            raise ScenesError(f"{ffmpeg_bin} introuvable (analyse de {video_path})") from exc
        assert proc.stdout is not None
        if running is not None and running_lock is not None:
            with running_lock:
                running.add(proc)
        try:
            # Lecture par blocs d'images : un seul appel systeme pour
            # READ_BLOCK_FRAMES images ; une image incomplete en fin de flux
            # est ignoree comme avant.
            while block := proc.stdout.read(frame_bytes * READ_BLOCK_FRAMES):
                view = np.frombuffer(block, np.uint8)
                for offset in range(0, len(block) - frame_bytes + 1, frame_bytes):
                    frame = view[offset:offset + frame_bytes].reshape(out_h, out_w, 3)
                    cuts += detector.process_frame(FrameTimecode(count, fps), frame)
                    count += 1
                if len(block) < frame_bytes * READ_BLOCK_FRAMES:
                    break
        finally:
            proc.stdout.close()
            returncode = proc.wait()
            if running is not None and running_lock is not None:
                with running_lock:
                    running.discard(proc)
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


def _split_window(
    start: float, end: float, chunk_seconds: float, rate: Fraction
) -> list[tuple[float, float]]:
    """Contiguous chunks of ``chunk_seconds`` (rounded to a whole number of
    analysed frames, so every chunk samples the same frame grid as one
    sequential decode of the window); a window not longer than that stays whole."""
    if end - start <= chunk_seconds:
        return [(start, end)]
    frames = max(1, round(chunk_seconds * float(rate)))
    step = float(Fraction(frames) / rate)
    chunks: list[tuple[float, float]] = []
    chunk_start = start
    while end - chunk_start > step:
        chunks.append((chunk_start, chunk_start + step))
        chunk_start += step
    if chunks and end - chunk_start < MIN_TAIL_SECONDS:
        chunk_start = chunks.pop()[0]
    chunks.append((chunk_start, end))
    return chunks


def _join_chunks(chunk_scenes: list[list[tuple[float, float]]]) -> list[tuple[float, float]]:
    """Absolute scenes of consecutive chunks of one window, recollees : the
    scene touching a seam is merged with its neighbour (a cut is never
    invented at a seam)."""
    joined: list[tuple[float, float]] = []
    for scenes in chunk_scenes:
        for index, (start, stop) in enumerate(scenes):
            if index == 0 and joined:
                joined[-1] = (joined[-1][0], stop)
            else:
                joined.append((start, stop))
    return joined


def _detect_scene_list(
    video_path: Path,
    threshold: float,
    analysis_width: int,
    analysis_max_fps: float,
    decoder: str,
    windows: list[tuple[float, float]],
    ffmpeg_bin: str,
    ffprobe_bin: str,
    detect_parallel: int = 1,
    detect_chunk_seconds: float = 600.0,
    skip_loop_filter: bool = False,
) -> list[tuple[float, float]]:
    width, height, source_rate = _probe(video_path, ffprobe_bin)
    rate = min(source_rate, Fraction(analysis_max_fps).limit_denominator(1001))
    fps = float(rate)
    out_w, out_h = _analysis_size(width, height, analysis_width)

    # Les fenetres depassent souvent la fin de la video (fin de parole + marge) :
    # le decoupage ne porte que sur la partie reelle, ffmpeg s arrete seul a la fin.
    duration = _duration(video_path, ffprobe_bin)
    chunks = []
    for start, end in windows:
        real_end = min(end, duration)
        if real_end <= start:
            chunks.append([(start, end)])
            continue
        window_chunks = _split_window(start, real_end, detect_chunk_seconds, rate)
        window_chunks[-1] = (window_chunks[-1][0], end)
        chunks.append(window_chunks)
    jobs = [(w, c, cs, ce) for w, window in enumerate(chunks) for c, (cs, ce) in enumerate(window)]
    logger.info(
        "detection : %d fenetre(s) en %d morceau(x), parallelisme %d",
        len(windows), len(jobs), detect_parallel,
    )

    running: set[subprocess.Popen] = set()
    running_lock = threading.Lock()
    failed = threading.Event()

    def detect(job: tuple[int, int, float, float]) -> list[tuple[float, float]]:
        _, _, chunk_start, chunk_end = job
        if failed.is_set():
            raise ScenesError("annule : un autre morceau a echoue")
        try:
            return _decode_window_cuts(
                video_path, chunk_start, chunk_end, threshold, decoder, ffmpeg_bin,
                fps, rate, out_w, out_h, skip_loop_filter, running, running_lock,
            )
        except ScenesError as exc:
            if failed.is_set():
                raise
            raise ScenesError(
                f"fenetre {windows[job[0]][0]:.3f}s-{windows[job[0]][1]:.3f}s "
                f"(morceau {chunk_start:.3f}s-{chunk_end:.3f}s) : {exc}"
            ) from exc

    started = time.monotonic()
    executor = ThreadPoolExecutor(max_workers=detect_parallel)
    futures = [executor.submit(detect, job) for job in jobs]
    try:
        wait(futures, return_when=FIRST_EXCEPTION)
        errors = [f.exception() for f in futures if f.done() and f.exception() is not None]
        if errors:
            failed.set()
            with running_lock:
                for proc in running:
                    proc.kill()
            raise errors[0]
        results = [f.result() for f in futures]
    finally:
        failed.set()
        executor.shutdown(wait=True, cancel_futures=True)
    logger.info("detection : %.1f s", time.monotonic() - started)

    scene_list: list[tuple[float, float]] = []
    for w, (window_start, _) in enumerate(windows):
        relative = [
            [(chunk_start - window_start + s, chunk_start - window_start + e) for s, e in rel]
            for (jw, _c, chunk_start, _e), rel in zip(jobs, results)
            if jw == w
        ]
        scene_list += [
            (window_start + s, window_start + e) for s, e in _join_chunks(relative)
        ]
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


def _thread_args(threads: int) -> list[str]:
    return ["-threads", str(threads)] if threads > 0 else []


def _extract_frame(
    video_path: Path, timecode: float, decoder: str, ffmpeg_bin: str, threads: int = 0
):
    """Full-resolution image at ``timecode`` (accurate input seek; BMP on a
    pipe, so the size never has to be guessed)."""
    data = _run(
        [
            ffmpeg_bin, "-v", "error", "-nostdin", "-ss", f"{timecode:.3f}",
            *_thread_args(threads), *_decoder_args(decoder), "-i", str(video_path),
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


def _extract_frames(
    video_path: Path, timecodes: list[float], decoder: str, ffmpeg_bin: str, threads: int = 0
) -> list[Any]:
    """Full-resolution images at ``timecodes`` from one ffmpeg process: one
    accurate input seek (``-ss`` before ``-i``) per image, each written as a
    BMP -- the same decode, hence the same pixels, as ``_extract_frame`` -- but
    with a single process start for the whole batch."""
    if len(timecodes) == 1:
        return [_extract_frame(video_path, timecodes[0], decoder, ffmpeg_bin, threads)]
    cmd = [ffmpeg_bin, "-v", "error", "-nostdin"]
    for timecode in timecodes:
        cmd += [
            "-ss", f"{timecode:.3f}", *_thread_args(threads), *_decoder_args(decoder),
            "-i", str(video_path),
        ]
    with tempfile.TemporaryDirectory(prefix="clipper-frames-") as tmp:
        for index in range(len(timecodes)):
            cmd += ["-map", f"{index}:v:0", "-frames:v", "1", "-c:v", "bmp", f"{tmp}/{index}.bmp"]
        _run(
            cmd,
            f"extraction de {len(timecodes)} images de {video_path} "
            f"({_decoder_name(decoder)}) a partir de {timecodes[0]:.3f}s",
        )
        frames = []
        for index, timecode in enumerate(timecodes):
            frame = cv2.imread(f"{tmp}/{index}.bmp", cv2.IMREAD_COLOR)
            if frame is None:
                raise ScenesError(
                    f"impossible d'extraire l'image a {timecode:.3f}s ({_decoder_name(decoder)})"
                )
            frames.append(frame)
    return frames


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
    extract_batch: int = 8,
    extract_threads: int = 2,
    speech_margin_seconds: float = 5.0,
    detect_parallel: int = 4,
    detect_chunk_seconds: float = 600.0,
    analysis_skip_loop_filter: bool = True,
    peak_windows: bool = False,
    ffmpeg_bin: str = "ffmpeg",
    ffprobe_bin: str = "ffprobe",
    force: bool = False,
) -> dict[str, Any]:
    """Detect plan changes with PySceneDetect and extract keyframes (ADR-b16b:
    a step reads its inputs and writes workspace/<video_id>/ itself).

    A video already analysed (scenes.json present) is not re-analysed unless
    ``force`` is set. Keyframes are extracted with at most ``extract_parallel``
    ffmpeg processes running at once (1 = sequential). Detection windows run
    in at most ``detect_parallel`` ffmpeg processes; a window longer than
    ``detect_chunk_seconds`` is split into contiguous chunks detected in
    parallel then joined (the scene across a seam is merged, no cut invented).
    Keyframes are extracted ``extract_batch`` per ffmpeg process, each decoding
    on ``extract_threads`` threads.
    ``analysis_skip_loop_filter`` adds ``-skip_loop_filter all`` to the
    detection input only. One failing ffmpeg fails the step (ScenesError naming
    the window) and the others are killed.

    Only the union of transcript.json's speech segments (widened by
    ``speech_margin_seconds``) is decoded -- a moment can only come from a
    transcript line (clipper.moments), so nothing outside speech can ever be
    cut into. With ``peak_windows`` (set by clipper.pipeline alone, from
    ``[action] enabled``), audio.json's out-of-speech peaks are included too:
    audio runs before scenes and the file is then a required input (SPEC-b0f3
    R4bis); without it audio.json is ignored even when present and scenes.json
    is unchanged byte for byte. transcript.json is a required input, like scenes.json is
    for clipper.reframe: missing, or with no speech segment at all, the step
    fails rather than silently decoding the whole video (ADR-ad2e).
    """
    if extract_parallel < 1:
        raise ScenesError(
            f"extract_parallel doit etre >= 1 (recu {extract_parallel})"
        )
    if extract_batch < 1:
        raise ScenesError(
            f"extract_batch doit etre >= 1 (recu {extract_batch})"
        )
    if extract_threads < 0:
        raise ScenesError(
            f"extract_threads doit etre >= 0 (recu {extract_threads})"
        )
    if detect_parallel < 1:
        raise ScenesError(
            f"detect_parallel doit etre >= 1 (recu {detect_parallel})"
        )
    if detect_chunk_seconds <= 0:
        raise ScenesError(
            f"detect_chunk_seconds doit etre > 0 (recu {detect_chunk_seconds})"
        )
    video_path = Path(video_path)
    video_dir = Path(workspace_dir) / video_id
    scenes_file = video_dir / "scenes.json"
    frames_dir = video_dir / "frames"

    if scenes_file.exists() and not force:
        try:
            return json.loads(scenes_file.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise ScenesError(
                f"{scenes_file} est illisible ({exc}) : refais l'etape scenes avec --force"
            ) from exc

    transcript = _read_json(video_dir / "transcript.json")
    audio = _read_json(video_dir / "audio.json") if peak_windows else {}
    windows = _speech_windows(transcript, audio, speech_margin_seconds)
    if not windows:
        raise ScenesError(
            f"aucun segment de parole dans {video_dir / 'transcript.json'} : "
            "rien a decoder"
        )

    scene_list = _detect_scene_list(
        video_path, threshold, analysis_width, analysis_max_fps, decoder, windows, ffmpeg_bin, ffprobe_bin,
        detect_parallel, detect_chunk_seconds, analysis_skip_loop_filter,
    )
    detected = time.monotonic()

    frames_dir.mkdir(parents=True, exist_ok=True)
    tasks: list[tuple[int, float, str]] = []
    for scene_index, (start, end) in enumerate(scene_list):
        timecodes = _keyframe_timecodes(start, end, keyframe_interval_seconds)
        for seq, timecode in enumerate(timecodes):
            filename = f"scene{scene_index:04d}_{seq:03d}.jpg"
            tasks.append((scene_index, timecode, filename))

    frames: list[dict[str, Any]] = []
    batches = [tasks[i:i + extract_batch] for i in range(0, len(tasks), extract_batch)]
    with ThreadPoolExecutor(max_workers=extract_parallel) as executor:
        extracted = executor.map(
            lambda batch: _extract_frames(
                video_path, [t[1] for t in batch], decoder, ffmpeg_bin, extract_threads
            ),
            batches,
        )
        for batch, images in zip(batches, extracted):
            for (scene_index, timecode, filename), frame in zip(batch, images):
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

    logger.info("extraction : %d image(s) en %.1f s", len(frames), time.monotonic() - detected)

    result: dict[str, Any] = {
        "scenes": [{"start": start, "end": end} for start, end in scene_list],
        "frames": frames,
    }
    if peak_windows:
        result["peak_windows"] = True
    atomic_write_json(scenes_file, result)
    return result
