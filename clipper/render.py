"""Etape render : assemble le clip final par ffmpeg (SPEC-350f).

Entrees (workspace/<video_id>/, lues en JSON/.ass, jamais en important les
autres etapes - ADR-b16b) :
- <video_id>.mp4 : la video source ;
- captions.json (captions) : titre, legende, hashtags, accroche, start/end/
  duration/part/parts_total/language/moment_id de chaque clip ;
- moments.json (moments) : score, notes par critere et justification, par
  moment_id ;
- reframe/<clip_id>.json (reframe) : le plan de recadrage (plans, panneaux,
  rectangles source par intervalle de temps, layout) ;
- subtitles/<clip_id>.ass (subtitles) : les sous-titres deja positionnes
  (SPEC-350f : jamais sur un visage, decide par l'etape subtitles) ;
- transcript.json (transcribe) : le texte prononce dans le clip ;
- meta.json (download), facultatif : titre de la video source.

Sortie : output/<video_id>/<clip_id>.mp4 et output/<video_id>/<clip_id>.json
conformes a SPEC-350f. Le champ ``qa`` part a ``{"status": "skipped",
"issues": []}`` : l'etape qa (SPEC-350f) le remplace apres coup.

ffmpeg construit chaque clip plan par plan : trim du plan sur la source,
canevas noir 1080x1920 (ou la taille de sortie de reframe), un panneau par
``crop`` (positions figees par intervalle, une expression ``if(lt(t,...))``
quand elles varient) eventuellement flou (fond, ``fallback_blur``) puis
``scale``, empile par ``overlay`` ; les plans sont mis bout a bout par
``concat``. Les sous-titres sont incrustes via le filtre ``ass`` (police
Poppins ExtraBold chargee depuis clipper/assets/fonts via ``fontsdir``,
chemin relatif au paquet - jamais code en dur pour une machine). L'accroche
et « Part N/M » sont incrustes par ``drawtext`` (texte lu depuis un fichier
temporaire, pour eviter tout souci d'echappement UTF-8). L'audio est
recadre puis normalise a -14 LUFS integres (``loudnorm``). L'encodeur video
est resolu via clipper.gpu (ADR-fb9b) : h264_nvenc si un GPU CUDA est
detecte, sinon libx264.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from clipper.gpu import get_device

CONFIG_DEFAULTS: dict[str, object] = {
    # Plafond d'images/s de sortie ; en-deca, la cadence source est gardee.
    "max_fps": 30,
    "crf": 20,
    "x264_preset": "medium",
    "nvenc_preset": "p5",
    "audio_bitrate": "192k",
    "loudnorm_i": -14.0,
    "loudnorm_tp": -1.5,
    "loudnorm_lra": 11.0,
    "hook_seconds": 2.0,
    "hook_font_size": 64,
    "hook_font_color": "white",
    "hook_margin_top": 100,
    "part_font_size": 48,
    "part_font_color": "white",
    "part_margin": 40,
    "blur_radius": 20,
    "blur_power": 2,
    # Ecart tolere (s) entre les bornes de captions.json et celles du plan
    # reframe : au-dela, les entrees sont jugees incoherentes.
    "start_end_tolerance": 0.15,
}

FONTS_DIR = Path(__file__).resolve().parent / "assets" / "fonts"
FONT_FILE = FONTS_DIR / "Poppins-ExtraBold.ttf"

_QA_DEFAULT: dict[str, Any] = {"status": "skipped", "issues": []}
_EDGE = 0.1
_EPS = 1e-6


class RenderError(Exception):
    """Entree manquante ou incoherente, ou echec de ffmpeg/ffprobe."""


# --------------------------------------------------------------------------
# Entrees
# --------------------------------------------------------------------------


def _settings(config: Any) -> dict[str, Any]:
    if config is None:
        from clipper.config import load_config

        config = load_config()
    return {**CONFIG_DEFAULTS, **config.section("render")}


def _read_json(path: Path, optional: bool = False) -> Any:
    if not path.exists():
        if optional:
            return None
        raise RenderError(f"entree absente : {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _find(items: list[dict[str, Any]], key: str, value: Any, where: str) -> dict[str, Any]:
    for item in items:
        if item[key] == value:
            return item
    raise RenderError(f"{key}={value!r} absent de {where}")


def _clip_transcript(transcript: dict[str, Any], start: float, end: float) -> str:
    words = [
        w
        for seg in transcript.get("segments", [])
        for w in (seg.get("words") or [])
        if w["start"] >= start - _EDGE - _EPS and w["end"] <= end + _EDGE + _EPS
    ]
    return "".join(w["word"] for w in words).strip()


# --------------------------------------------------------------------------
# Chemins dans le filtre ffmpeg (jamais un ':' de lettre de lecteur nu)
# --------------------------------------------------------------------------


def _filter_path(target: Path, cwd: Path) -> str:
    try:
        rel = os.path.relpath(target, cwd)
    except ValueError:
        return target.resolve().as_posix().replace(":", "\\:")
    return Path(rel).as_posix()


# --------------------------------------------------------------------------
# Filtergraph : un plan de recadrage a la fois
# --------------------------------------------------------------------------


def _fmt_num(value: Any) -> str:
    return f"{value:.6f}" if isinstance(value, float) else str(value)


def _time_expr(rects: list[dict[str, Any]], plan_start: float, key: str) -> str:
    """Expression ffmpeg (en ``t``, secondes depuis le debut du plan) pour
    ``key`` (x/y/w/h) : une constante s'il n'y a qu'un rectangle, sinon une
    chaine de ``if(lt(t, fin_relative), valeur, ...)``."""
    if len(rects) == 1:
        return _fmt_num(rects[0][key])
    expr = _fmt_num(rects[-1][key])
    for rect in reversed(rects[:-1]):
        rel_end = rect["end"] - plan_start
        expr = f"if(lt(t,{rel_end:.6f}),{_fmt_num(rect[key])},{expr})"
    return expr


def _panel_filters(
    panel: dict[str, Any], base_ref: str, plan_start: float, label: str, settings: dict[str, Any]
) -> tuple[list[str], str, dict[str, int]]:
    rects = panel["rects"]
    x = _time_expr(rects, plan_start, "x")
    y = _time_expr(rects, plan_start, "y")
    w = _time_expr(rects, plan_start, "w")
    h = _time_expr(rects, plan_start, "h")
    lines = [f"[{base_ref}]crop=w='{w}':h='{h}':x='{x}':y='{y}'[{label}c]"]
    cur = f"{label}c"
    if panel.get("effect") == "blur":
        lines.append(f"[{cur}]boxblur={settings['blur_radius']}:{settings['blur_power']}[{label}b]")
        cur = f"{label}b"
    dest = panel["dest"]
    lines.append(f"[{cur}]scale={dest['w']}:{dest['h']}[{label}s]")
    return lines, f"{label}s", dest


def _plan_filters(plan: dict[str, Any], index: int, out_w: int, out_h: int, settings: dict[str, Any]) -> tuple[list[str], str]:
    label = f"p{index}"
    duration = plan["end"] - plan["start"]
    lines = [
        f"[0:v]trim=start={plan['start']:.6f}:end={plan['end']:.6f},setpts=PTS-STARTPTS[{label}base]"
    ]
    panels = plan["panels"]
    n = len(panels)
    if n > 1:
        lines.append(f"[{label}base]split={n}" + "".join(f"[{label}base{i}]" for i in range(n)))
        bases = [f"{label}base{i}" for i in range(n)]
    else:
        bases = [f"{label}base"]

    lines.append(f"color=c=black:s={out_w}x{out_h}:d={duration:.6f}[{label}canvas]")
    cur = f"{label}canvas"
    for i, panel in enumerate(panels):
        panel_lines, scaled, dest = _panel_filters(panel, bases[i], plan["start"], f"{label}_{i}", settings)
        lines.extend(panel_lines)
        nxt = f"{label}ov{i}"
        lines.append(f"[{cur}][{scaled}]overlay=x={dest['x']}:y={dest['y']}[{nxt}]")
        cur = nxt
    return lines, cur


def _build_filter_complex(
    reframe_data: dict[str, Any],
    clip_start: float,
    clip_end: float,
    ass_path: Path,
    hook_path: Path,
    part_path: Path | None,
    scratch_dir: Path,
    settings: dict[str, Any],
) -> tuple[str, str]:
    out_w = reframe_data["output"]["width"]
    out_h = reframe_data["output"]["height"]

    lines: list[str] = []
    plan_labels: list[str] = []
    for i, plan in enumerate(reframe_data["plans"]):
        plan_lines, final_label = _plan_filters(plan, i, out_w, out_h, settings)
        lines.extend(plan_lines)
        plan_labels.append(final_label)

    if len(plan_labels) > 1:
        lines.append(
            "".join(f"[{lbl}]" for lbl in plan_labels) + f"concat=n={len(plan_labels)}:v=1:a=0[vraw]"
        )
        cur = "vraw"
    else:
        cur = plan_labels[0]

    ass_rel = _filter_path(ass_path, scratch_dir)
    fonts_rel = _filter_path(FONTS_DIR, scratch_dir)
    lines.append(f"[{cur}]ass='{ass_rel}':fontsdir='{fonts_rel}'[vsub]")
    cur = "vsub"

    hook_rel = _filter_path(hook_path, scratch_dir)
    font_rel = _filter_path(FONT_FILE, scratch_dir)
    lines.append(
        f"[{cur}]drawtext=textfile='{hook_rel}':fontfile='{font_rel}':"
        f"fontsize={settings['hook_font_size']}:fontcolor={settings['hook_font_color']}:"
        f"x=(w-text_w)/2:y={settings['hook_margin_top']}:"
        f"enable='lt(t,{settings['hook_seconds']})'[vhook]"
    )
    cur = "vhook"

    if part_path is not None:
        part_rel = _filter_path(part_path, scratch_dir)
        lines.append(
            f"[{cur}]drawtext=textfile='{part_rel}':fontfile='{font_rel}':"
            f"fontsize={settings['part_font_size']}:fontcolor={settings['part_font_color']}:"
            f"x=w-text_w-{settings['part_margin']}:y={settings['part_margin']}[vpart]"
        )
        cur = "vpart"

    lines.append(
        f"[0:a]atrim=start={clip_start:.6f}:end={clip_end:.6f},asetpts=PTS-STARTPTS,"
        f"loudnorm=I={settings['loudnorm_i']}:TP={settings['loudnorm_tp']}:LRA={settings['loudnorm_lra']}[aout]"
    )

    return ";".join(lines), cur


# --------------------------------------------------------------------------
# ffmpeg / ffprobe
# --------------------------------------------------------------------------


def _probe_fps(video_path: Path, ffprobe_bin: str) -> float:
    cmd = [
        ffprobe_bin, "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=r_frame_rate", "-of", "csv=p=0", str(video_path),
    ]
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError as exc:
        raise RenderError(f"ffprobe introuvable ({ffprobe_bin})") from exc
    if proc.returncode != 0:
        raise RenderError(
            f"ffprobe a echoue sur {video_path} : {proc.stderr.decode(errors='replace').strip()}"
        )
    text = proc.stdout.decode().strip()
    num, _, den = text.partition("/")
    try:
        return float(num) / float(den or 1)
    except (ValueError, ZeroDivisionError) as exc:
        raise RenderError(f"fps illisible depuis ffprobe ({text!r})") from exc


def _encoder(device_type: str, settings: dict[str, Any]) -> list[str]:
    if device_type == "cuda":
        return ["-c:v", "h264_nvenc", "-preset", str(settings["nvenc_preset"]), "-cq", str(settings["crf"])]
    return ["-c:v", "libx264", "-preset", str(settings["x264_preset"]), "-crf", str(settings["crf"])]


def _run_ffmpeg(
    ffmpeg_bin: str,
    source: Path,
    filter_complex: str,
    vout_label: str,
    target_fps: float,
    device_type: str,
    settings: dict[str, Any],
    scratch_dir: Path,
    out_path: Path,
) -> None:
    cmd = [
        ffmpeg_bin, "-y", "-loglevel", "error",
        "-i", str(source.resolve()),
        "-filter_complex", filter_complex,
        "-map", f"[{vout_label}]", "-map", "[aout]",
        "-r", str(target_fps),
        *_encoder(device_type, settings),
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", str(settings["audio_bitrate"]), "-ar", "48000",
        "-movflags", "+faststart",
        "-f", "mp4",
        str(out_path.resolve()),
    ]
    try:
        proc = subprocess.run(cmd, cwd=scratch_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError as exc:
        raise RenderError(f"ffmpeg introuvable ({ffmpeg_bin})") from exc
    if proc.returncode != 0:
        raise RenderError(f"ffmpeg a echoue sur {source} : {proc.stderr.decode(errors='replace').strip()}")


# --------------------------------------------------------------------------
# Etape
# --------------------------------------------------------------------------


def render(
    video_id: str,
    clip_id: str,
    workspace_dir: str | Path = "workspace",
    output_dir: str | Path = "output",
    *,
    config: Any = None,
    force: bool = False,
    ffmpeg_bin: str = "ffmpeg",
    ffprobe_bin: str = "ffprobe",
) -> Path:
    """Rend le clip ``clip_id`` de ``video_id`` : ecrit
    output/<video_id>/<clip_id>.mp4 et .json (SPEC-350f), renvoie le chemin
    du .mp4. Une paire deja presente n'est pas refaite, sauf ``force``."""
    video_dir = Path(workspace_dir) / video_id
    out_dir = Path(output_dir) / video_id
    mp4_out = out_dir / f"{clip_id}.mp4"
    json_out = out_dir / f"{clip_id}.json"
    if mp4_out.exists() and json_out.exists() and not force:
        return mp4_out

    settings = _settings(config)

    source = video_dir / f"{video_id}.mp4"
    if not source.exists():
        raise RenderError(f"video absente : {source}")

    captions = _read_json(video_dir / "captions.json")
    clip = _find(captions["clips"], "id", clip_id, "captions.json")

    moments = _read_json(video_dir / "moments.json")
    moment = _find(moments["moments"], "id", clip["moment_id"], "moments.json")

    transcript = _read_json(video_dir / "transcript.json")
    meta = _read_json(video_dir / "meta.json", optional=True) or {}
    reframe_data = _read_json(video_dir / "reframe" / f"{clip_id}.json")
    ass_path = video_dir / "subtitles" / f"{clip_id}.ass"
    if not ass_path.exists():
        raise RenderError(f"sous-titres absents : {ass_path}")

    tol = float(settings["start_end_tolerance"])
    if abs(reframe_data["start"] - clip["start"]) > tol or abs(reframe_data["end"] - clip["end"]) > tol:
        raise RenderError(
            f"bornes incoherentes pour {clip_id} : captions.json [{clip['start']}, {clip['end']}] "
            f"vs reframe.json [{reframe_data['start']}, {reframe_data['end']}]"
        )
    if not reframe_data["plans"]:
        raise RenderError(f"reframe.json de {clip_id} n'a aucun plan")

    scratch_dir = video_dir / "render" / clip_id
    scratch_dir.mkdir(parents=True, exist_ok=True)
    try:
        hook_path = scratch_dir / "hook.txt"
        hook_path.write_text(clip["hook_text"], encoding="utf-8")
        part_path: Path | None = None
        if clip["parts_total"] > 1:
            part_path = scratch_dir / "part.txt"
            part_path.write_text(f"Part {clip['part']}/{clip['parts_total']}", encoding="utf-8")

        filter_complex, vout_label = _build_filter_complex(
            reframe_data, clip["start"], clip["end"], ass_path, hook_path, part_path, scratch_dir, settings
        )

        source_fps = _probe_fps(source, ffprobe_bin)
        target_fps = min(source_fps, float(settings["max_fps"]))

        device = get_device()

        tmp_out = mp4_out.with_suffix(".mp4.tmp")
        out_dir.mkdir(parents=True, exist_ok=True)
        _run_ffmpeg(
            ffmpeg_bin, source, filter_complex, vout_label, target_fps, device.type, settings, scratch_dir, tmp_out
        )
        tmp_out.replace(mp4_out)
    finally:
        shutil.rmtree(scratch_dir, ignore_errors=True)

    data = {
        "video_id": video_id,
        # meta.json (download) ne garde pas l'URL d'origine, seulement video_id.
        "source_url": f"https://www.youtube.com/watch?v={video_id}",
        "source_title": meta.get("title") or "",
        "clip_id": clip_id,
        "part": clip["part"],
        "parts_total": clip["parts_total"],
        "start": clip["start"],
        "end": clip["end"],
        "duration": clip["duration"],
        "language": clip["language"],
        "score": moment["final_score"],
        "scores": moment["scores"],
        "reason": moment["justification"],
        "hook_text": clip["hook_text"],
        "title": clip["title"],
        "caption": clip["caption"],
        "hashtags": clip["hashtags"],
        "transcript": _clip_transcript(transcript, clip["start"], clip["end"]),
        "layout": reframe_data["layout"],
        "qa": dict(_QA_DEFAULT),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    tmp_json = json_out.with_suffix(".json.tmp")
    tmp_json.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_json.replace(json_out)

    return mp4_out
