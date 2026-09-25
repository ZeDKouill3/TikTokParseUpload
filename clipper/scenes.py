from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import cv2
from scenedetect import SceneManager, open_video
from scenedetect.detectors import ContentDetector

CONFIG_DEFAULTS: dict[str, object] = {
    "threshold": 27.0,
    "keyframe_interval_seconds": 5.0,
    "jpeg_quality": 95,
}


class ScenesError(Exception):
    """Scene detection or frame extraction failed."""


def _detect_scene_list(video_path: Path, threshold: float) -> list[tuple[float, float]]:
    video = open_video(str(video_path))
    scene_manager = SceneManager()
    scene_manager.add_detector(ContentDetector(threshold=threshold))
    scene_manager.detect_scenes(video=video)
    scene_list = scene_manager.get_scene_list()

    if not scene_list:
        return [(0.0, video.duration.seconds)]
    return [(start.seconds, end.seconds) for start, end in scene_list]


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


def _extract_frame(capture: cv2.VideoCapture, timecode: float):
    capture.set(cv2.CAP_PROP_POS_MSEC, timecode * 1000)
    ok, frame = capture.read()
    if not ok:
        raise ScenesError(f"impossible d'extraire l'image a {timecode:.3f}s")
    return frame


def detect_scenes(
    video_path: str | Path,
    workspace_dir: str | Path,
    video_id: str,
    *,
    threshold: float = 27.0,
    keyframe_interval_seconds: float = 5.0,
    jpeg_quality: int = 95,
    force: bool = False,
) -> dict[str, Any]:
    """Detect plan changes with PySceneDetect and extract keyframes (ADR-b16b:
    a step reads its inputs and writes workspace/<video_id>/ itself).

    A video already analysed (scenes.json present) is not re-analysed unless
    ``force`` is set.
    """
    video_path = Path(video_path)
    video_dir = Path(workspace_dir) / video_id
    scenes_file = video_dir / "scenes.json"
    frames_dir = video_dir / "frames"

    if scenes_file.exists() and not force:
        return json.loads(scenes_file.read_text(encoding="utf-8"))

    scene_list = _detect_scene_list(video_path, threshold)

    frames_dir.mkdir(parents=True, exist_ok=True)
    capture = cv2.VideoCapture(str(video_path))
    try:
        frames: list[dict[str, Any]] = []
        for scene_index, (start, end) in enumerate(scene_list):
            timecodes = _keyframe_timecodes(start, end, keyframe_interval_seconds)
            for seq, timecode in enumerate(timecodes):
                frame = _extract_frame(capture, timecode)
                filename = f"scene{scene_index:04d}_{seq:03d}.jpg"
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
    finally:
        capture.release()

    result: dict[str, Any] = {
        "scenes": [{"start": start, "end": end} for start, end in scene_list],
        "frames": frames,
    }
    scenes_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
