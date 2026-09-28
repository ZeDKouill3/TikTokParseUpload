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

Format letterbox (SPEC-6127, ``layout = "letterbox"`` a la racine de
reframe/<clip_id>.json) : render lit ``text_zones`` (zones title/subtitles/
part en pixels de sortie, calculees par reframe) et
- dessine ``screen_title`` (captions.json) pendant tout le clip : texte noir
  Poppins ExtraBold et emoji en couleur sur un encadre blanc a coins
  arrondis, centre dans la zone title et colle en bas de celle-ci. Le texte
  est coupe en segments texte / emoji par classe Unicode
  (Extended_Pictographic), passe a la ligne (2 lignes au plus) puis baisse
  de taille par paliers jusqu'a ce que l'encadre tienne ; sinon RenderError
  (jamais tronque ni debordant). Le titre est rasterise en PNG transparent
  (Pillow, taille de la zone title) puis incruste par ffmpeg (deuxieme
  entree, ``overlay`` sur toute la duree) ;
- n'affiche pas d'accroche de 2 s ;
- centre « Partie N » dans la zone part si parts_total > 1 (drawtext, taille
  en em comme Pillow, mesuree avec la vraie police, sinon RenderError) ;
- ecrit ``video_rect`` (le panneau main en pixels de sortie) dans le JSON.

Police emoji (``emoji_font``, vide = resolue par plateforme, voir
resolve_emoji_font) : Windows ``C:/Windows/Fonts/seguiemj.ttf`` ; Linux
``NotoColorEmoji.ttf`` (paquet fonts-noto-color-emoji), police bitmap qui ne
s'ouvre qu'a la taille 109 : chaque emoji est donc rasterise a
``emoji_raster_size`` (109) puis reduit a la taille du texte, sur toutes
les plateformes. Police absente = RenderError.
"""

from __future__ import annotations

import bisect
import functools
import json
import math
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont

from clipper.gpu import get_device

CONFIG_DEFAULTS: dict[str, object] = {
    # Cadence de sortie (SPEC-350f) : imposee, quelle que soit la cadence source.
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
    # Le fond flou (fallback_blur) est calcule sur une image reduite d'un
    # facteur blur_downscale puis remis a la taille de dest : boxblur sur
    # 1080x1920 en plein cadre est le cout dominant d'un rendu fallback_blur
    # (constat essai reel 2026-09-25, ~1200s CPU pour 40s de clip).
    "blur_downscale": 4,
    # Ecart tolere (s) entre les bornes de captions.json et celles du plan
    # reframe : au-dela, les entrees sont jugees incoherentes.
    "start_end_tolerance": 0.15,
    # Format letterbox (SPEC-6127) : titre d'ecran sur encadre blanc. Tailles
    # en pixels par em (meme unite pour Pillow et drawtext).
    "title_font_size": 64,
    "title_font_size_min": 36,
    "title_font_size_step": 4,
    "title_line_height": 1.25,  # interligne, en em
    "title_emoji_scale": 0.9,  # hauteur de l'emoji, en em
    # Espace ajoute entre un segment texte et un emoji qui se suivent, en em
    # (compte dans la largeur mesuree de l'encadre).
    "title_emoji_gap": 0.25,
    "title_pad_x": 28,
    "title_pad_y": 16,
    "title_radius": 22,
    # Police emoji couleur : "" = resolue par plateforme (resolve_emoji_font).
    "emoji_font": "",
    # Taille de rasterisation des emojis, reduits ensuite : NotoColorEmoji
    # (Linux) ne s'ouvre qu'a 109.
    "emoji_raster_size": 109,
    # « Partie N » en letterbox (taille : part_font_size, couleur : part_font_color).
    "part_border": 4,
}

FONTS_DIR = Path(__file__).resolve().parent / "assets" / "fonts"
FONT_FILE = FONTS_DIR / "Poppins-ExtraBold.ttf"

# Polices emoji couleur cherchees quand [render] emoji_font est vide.
EMOJI_FONT_CANDIDATES: dict[str, tuple[str, ...]] = {
    "win32": ("C:/Windows/Fonts/seguiemj.ttf",),
    "linux": (
        "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
        "/usr/share/fonts/noto/NotoColorEmoji.ttf",
        "/usr/share/fonts/google-noto-emoji/NotoColorEmoji.ttf",
        "/usr/share/fonts/noto-emoji/NotoColorEmoji.ttf",
    ),
}

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
# Letterbox : titre d'ecran (texte + emoji) rasterise par Pillow
# --------------------------------------------------------------------------

# Extended_Pictographic (Unicode emoji-data.txt), en intervalles fermes tries.
_PICTO_RANGES: tuple[tuple[int, int], ...] = (
    (0x00A9, 0x00A9), (0x00AE, 0x00AE), (0x203C, 0x203C), (0x2049, 0x2049), (0x2122, 0x2122),
    (0x2139, 0x2139), (0x2194, 0x2199), (0x21A9, 0x21AA), (0x231A, 0x231B), (0x2328, 0x2328),
    (0x2388, 0x2388), (0x23CF, 0x23CF), (0x23E9, 0x23F3), (0x23F8, 0x23FA), (0x24C2, 0x24C2),
    (0x25AA, 0x25AB), (0x25B6, 0x25B6), (0x25C0, 0x25C0), (0x25FB, 0x25FE), (0x2600, 0x2605),
    (0x2607, 0x2612), (0x2614, 0x2685), (0x2690, 0x2705), (0x2708, 0x2712), (0x2714, 0x2714),
    (0x2716, 0x2716), (0x271D, 0x271D), (0x2721, 0x2721), (0x2728, 0x2728), (0x2733, 0x2734),
    (0x2744, 0x2744), (0x2747, 0x2747), (0x274C, 0x274C), (0x274E, 0x274E), (0x2753, 0x2755),
    (0x2757, 0x2757), (0x2763, 0x2767), (0x2795, 0x2797), (0x27A1, 0x27A1), (0x27B0, 0x27B0),
    (0x27BF, 0x27BF), (0x2934, 0x2935), (0x2B05, 0x2B07), (0x2B1B, 0x2B1C), (0x2B50, 0x2B50),
    (0x2B55, 0x2B55), (0x3030, 0x3030), (0x303D, 0x303D), (0x3297, 0x3297), (0x3299, 0x3299),
    (0x1F000, 0x1F0FF), (0x1F10D, 0x1F10F), (0x1F12F, 0x1F12F), (0x1F16C, 0x1F171),
    (0x1F17E, 0x1F17F), (0x1F18E, 0x1F18E), (0x1F191, 0x1F19A), (0x1F1AD, 0x1F1E5),
    (0x1F201, 0x1F20F), (0x1F21A, 0x1F21A), (0x1F22F, 0x1F22F), (0x1F232, 0x1F23A),
    (0x1F23C, 0x1F23F), (0x1F249, 0x1F3FA), (0x1F400, 0x1F53D), (0x1F546, 0x1F64F),
    (0x1F680, 0x1F6FF), (0x1F774, 0x1F77F), (0x1F7D5, 0x1F7FF), (0x1F80C, 0x1F80F),
    (0x1F848, 0x1F84F), (0x1F85A, 0x1F85F), (0x1F888, 0x1F88F), (0x1F8AE, 0x1F8FF),
    (0x1F90C, 0x1F93A), (0x1F93C, 0x1F945), (0x1F947, 0x1FAFF), (0x1FC00, 0x1FFFD),
)
_PICTO_STARTS = [lo for lo, _hi in _PICTO_RANGES]
_ZWJ = 0x200D


def _is_pictographic(cp: int) -> bool:
    i = bisect.bisect_right(_PICTO_STARTS, cp) - 1
    return i >= 0 and cp <= _PICTO_RANGES[i][1]


def _is_regional_indicator(cp: int) -> bool:
    return 0x1F1E6 <= cp <= 0x1F1FF


def _is_emoji_extender(cp: int) -> bool:
    """VS16, keycap, modificateur de teint, etiquettes (drapeaux de region)."""
    return cp in (0xFE0F, 0x20E3) or 0x1F3FB <= cp <= 0x1F3FF or 0xE0020 <= cp <= 0xE007F


def _emoji_start(cp: int) -> bool:
    return _is_pictographic(cp) or _is_regional_indicator(cp)


def split_segments(text: str) -> list[tuple[str, str]]:
    """Decoupe ``text`` en segments ``("text", ...)`` / ``("emoji", ...)`` par
    classe Unicode : un emoji est un point de code Extended_Pictographic (ou
    une paire d'indicateurs regionaux) suivi de ses extensions (VS16, teint,
    keycap, ZWJ + pictogramme)."""
    segments: list[tuple[str, str]] = []
    i, n = 0, len(text)
    while i < n:
        cp = ord(text[i])
        j = i + 1
        if _emoji_start(cp):
            if _is_regional_indicator(cp) and j < n and _is_regional_indicator(ord(text[j])):
                j += 1
            while j < n:
                c = ord(text[j])
                if _is_emoji_extender(c):
                    j += 1
                elif c == _ZWJ and j + 1 < n and _emoji_start(ord(text[j + 1])):
                    j += 2
                else:
                    break
            segments.append(("emoji", text[i:j]))
        else:
            while j < n and not _emoji_start(ord(text[j])):
                j += 1
            segments.append(("text", text[i:j]))
        i = j
    return segments


def resolve_emoji_font(settings: dict[str, Any]) -> Path:
    """Police emoji couleur : ``emoji_font`` si renseigne, sinon la premiere
    police connue presente pour la plateforme (EMOJI_FONT_CANDIDATES).
    Absente = RenderError (jamais d'emoji en noir et blanc en silence)."""
    configured = str(settings.get("emoji_font") or "")
    if configured:
        path = Path(configured)
        if not path.is_file():
            raise RenderError(f"police emoji absente : {path} (reglage [render] emoji_font)")
        return path
    platform = "linux" if sys.platform.startswith("linux") else sys.platform
    candidates = EMOJI_FONT_CANDIDATES.get(platform, ())
    for candidate in candidates:
        if Path(candidate).is_file():
            return Path(candidate)
    raise RenderError(
        f"police emoji couleur introuvable sur {sys.platform} (cherchee : {', '.join(candidates) or 'aucune connue'}) : "
        "installer NotoColorEmoji (Linux : paquet fonts-noto-color-emoji) ou renseigner [render] emoji_font"
    )


@functools.lru_cache(maxsize=None)
def _cmap(font_path: str) -> frozenset[int]:
    font = TTFont(font_path, lazy=True, fontNumber=0)
    try:
        return frozenset(font.getBestCmap() or {})
    finally:
        font.close()


@functools.lru_cache(maxsize=None)
def _text_font(size: int) -> ImageFont.FreeTypeFont:
    if not FONT_FILE.is_file():
        raise RenderError(f"police absente : {FONT_FILE}")
    return ImageFont.truetype(str(FONT_FILE), size)


@functools.lru_cache(maxsize=None)
def _emoji_raster(cluster: str, font_path: str, raster_size: int) -> Image.Image:
    """L'emoji ``cluster`` rasterise en couleur a ``raster_size`` et recadre
    sur ses pixels visibles."""
    cmap = _cmap(font_path)
    missing = [c for c in cluster if ord(c) not in cmap and ord(c) not in (0xFE0F, _ZWJ)]
    if missing:
        raise RenderError(f"emoji {cluster!r} absent de la police emoji {font_path}")
    try:
        font = ImageFont.truetype(font_path, raster_size)
    except OSError as exc:
        raise RenderError(f"police emoji illisible a la taille {raster_size} : {font_path} ({exc})") from exc
    canvas = Image.new("RGBA", (raster_size * 4, raster_size * 2), (0, 0, 0, 0))
    ImageDraw.Draw(canvas).text(
        (raster_size // 2, raster_size * 3 // 2), cluster, font=font, embedded_color=True, anchor="ls"
    )
    bbox = canvas.getbbox()
    if bbox is None:
        raise RenderError(f"emoji {cluster!r} sans rendu avec {font_path}")
    return canvas.crop(bbox)


@dataclass
class TitleLayout:
    """Mise en page du titre d'ecran, en pixels de sortie."""

    font_size: int
    lines: list[str]
    box: tuple[int, int, int, int]  # encadre blanc (x0, y0, x1, y1)
    emoji_boxes: list[tuple[int, int, int, int]] = field(default_factory=list)
    # (kind, contenu, x, y) : texte ancre sur sa ligne de base, emoji par son coin haut-gauche.
    items: list[tuple[str, str, int, int]] = field(default_factory=list)


def _zone(zone: dict[str, Any]) -> tuple[int, int, int, int]:
    return int(zone["x0"]), int(zone["y0"]), int(zone["x1"]), int(zone["y1"])


def _font_sizes(settings: dict[str, Any]) -> list[int]:
    start, low = int(settings["title_font_size"]), int(settings["title_font_size_min"])
    step = max(1, int(settings["title_font_size_step"]))
    sizes = list(range(start, low - 1, -step))
    if not sizes or sizes[-1] != low:
        sizes.append(low)
    return sizes


def layout_title(text: str, zone: dict[str, Any], settings: dict[str, Any]) -> TitleLayout:
    """Mesure ``text`` avec les vraies polices et place l'encadre blanc dans
    ``zone`` : centre horizontalement, colle en bas. Une ligne, puis deux,
    puis une taille plus petite par paliers ; RenderError s'il ne tient pas a
    la taille minimale."""
    words = text.split()
    if not words:
        raise RenderError("titre d'ecran vide")
    segments_by_word = [split_segments(w) for w in words]
    if not FONT_FILE.is_file():
        raise RenderError(f"police absente : {FONT_FILE}")
    text_cmap = _cmap(str(FONT_FILE))
    for kind, seg in (s for segs in segments_by_word for s in segs):
        if kind == "text":
            missing = sorted({c for c in seg if ord(c) not in text_cmap})
            if missing:
                raise RenderError(f"caractere(s) {''.join(missing)!r} du titre absent(s) de Poppins ExtraBold : {text!r}")
    emoji_font = None
    if any(kind == "emoji" for segs in segments_by_word for kind, _ in segs):
        emoji_font = str(resolve_emoji_font(settings))
    raster_size = int(settings["emoji_raster_size"])

    zx0, zy0, zx1, zy1 = _zone(zone)
    zone_w, zone_h = zx1 - zx0, zy1 - zy0
    pad_x, pad_y = int(settings["title_pad_x"]), int(settings["title_pad_y"])

    for size in _font_sizes(settings):
        font = _text_font(size)
        emoji_h = max(1, round(size * float(settings["title_emoji_scale"])))

        def emoji_w(cluster: str) -> int:
            img = _emoji_raster(cluster, emoji_font, raster_size)
            return max(1, round(img.width * emoji_h / img.height))

        def line_segments(line_words: list[list[tuple[str, str]]]) -> list[tuple[str, str]]:
            segs: list[tuple[str, str]] = []
            for k, word_segs in enumerate(line_words):
                if k:
                    segs.append(("text", " "))
                segs.extend(word_segs)
            return segs

        gap = round(size * float(settings["title_emoji_gap"]))

        def transitions(segs: list[tuple[str, str]]) -> int:
            return sum(1 for (k1, _), (k2, _) in zip(segs, segs[1:]) if k1 != k2)

        def width(segs: list[tuple[str, str]]) -> float:
            return sum(font.getlength(s) if kind == "text" else emoji_w(s) for kind, s in segs) + gap * transitions(segs)

        def span_width(a: int, b: int) -> float:
            return width(line_segments(segments_by_word[a:b]))

        # Une ligne, puis la coupure en deux lignes la plus equilibree.
        n = len(words)
        candidates = [[(0, n)]]
        if n > 1:
            k = min(range(1, n), key=lambda k: max(span_width(0, k), span_width(k, n)))
            candidates.append([(0, k), (k, n)])
        line_h = round(size * float(settings["title_line_height"]))
        for spans in candidates:
            segs_per_line = [line_segments(segments_by_word[a:b]) for a, b in spans]
            widths = [width(s) for s in segs_per_line]
            box_w = math.ceil(max(widths)) + 2 * pad_x
            box_h = len(spans) * line_h + 2 * pad_y
            if box_w > zone_w or box_h > zone_h:
                continue
            bx0 = zx0 + (zone_w - box_w) // 2
            by0 = zy1 - box_h
            cap = -font.getbbox("H", anchor="ls")[1]
            layout = TitleLayout(
                font_size=size,
                lines=[" ".join(words[a:b]) for a, b in spans],
                box=(bx0, by0, bx0 + box_w, by0 + box_h),
            )
            for i, segs in enumerate(segs_per_line):
                baseline = by0 + pad_y + i * line_h + round((line_h + cap) / 2)
                x = bx0 + (box_w - widths[i]) / 2
                for j, (kind, seg) in enumerate(segs):
                    if j and segs[j - 1][0] != kind:
                        x += gap
                    if kind == "text":
                        layout.items.append(("text", seg, round(x), baseline))
                        x += font.getlength(seg)
                    else:
                        w = emoji_w(seg)
                        top = round(baseline - cap / 2 - emoji_h / 2)
                        layout.items.append(("emoji", seg, round(x), top))
                        layout.emoji_boxes.append((round(x), top, round(x) + w, top + emoji_h))
                        x += w
            return layout
    raise RenderError(
        f"titre d'ecran trop long pour sa zone ({zone_w}x{zone_h} px) meme a la taille "
        f"{settings['title_font_size_min']} sur 2 lignes : {text!r}"
    )


def title_png(text: str, zone: dict[str, Any], settings: dict[str, Any], path: Path) -> TitleLayout:
    """Ecrit dans ``path`` le titre d'ecran en PNG transparent de la taille
    de ``zone`` (a incruster en (x0, y0) de la zone) ; renvoie sa mise en page."""
    layout = layout_title(text, zone, settings)
    zx0, zy0, zx1, zy1 = _zone(zone)
    img = Image.new("RGBA", (zx1 - zx0, zy1 - zy0), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    bx0, by0, bx1, by1 = layout.box
    draw.rounded_rectangle(
        (bx0 - zx0, by0 - zy0, bx1 - zx0 - 1, by1 - zy0 - 1), radius=int(settings["title_radius"]), fill="white"
    )
    font = _text_font(layout.font_size)
    emojis = [item for item in layout.items if item[0] == "emoji"]
    if emojis:
        emoji_font = str(resolve_emoji_font(settings))
    for (_kind, content, x, y), box in zip(emojis, layout.emoji_boxes):
        raster = _emoji_raster(content, emoji_font, int(settings["emoji_raster_size"]))
        scaled = raster.resize((box[2] - box[0], box[3] - box[1]), Image.LANCZOS)
        img.alpha_composite(scaled, (x - zx0, y - zy0))
    for kind, content, x, y in layout.items:
        if kind == "text":
            draw.text((x - zx0, y - zy0), content, font=font, fill="black", anchor="ls")
    img.save(path, format="PNG")
    return layout


def _part_placement(text: str, zone: dict[str, Any], settings: dict[str, Any]) -> int:
    """Ligne de base (y, pixels de sortie) qui centre verticalement ``text``
    (encre + bordure, mesuree avec Poppins a part_font_size) dans ``zone`` ;
    RenderError s'il n'y tient pas."""
    zx0, zy0, zx1, zy1 = _zone(zone)
    size, border = int(settings["part_font_size"]), int(settings["part_border"])
    font = _text_font(size)
    left, top, right, bottom = font.getbbox(text, anchor="ls", stroke_width=border)
    advance = font.getlength(text) + 2 * border
    if max(right - left, advance) > zx1 - zx0 or bottom - top > zy1 - zy0:
        raise RenderError(
            f"« {text} » ne tient pas dans sa zone ({zx1 - zx0}x{zy1 - zy0} px) a la taille {size} "
            "(reglage [render] part_font_size)"
        )
    return zy0 + ((zy1 - zy0) - (bottom - top)) // 2 - top


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
        factor = settings["blur_downscale"]
        lines.append(f"[{cur}]scale=iw/{factor}:ih/{factor}[{label}r]")
        cur = f"{label}r"
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
    hook_path: Path | None,
    part_path: Path | None,
    scratch_dir: Path,
    settings: dict[str, Any],
    *,
    title_input: int | None = None,
) -> tuple[str, str]:
    """Graphe ffmpeg du clip. En letterbox (``layout`` = letterbox a la racine
    de reframe_data), ``title_input`` est l'index de l'entree ffmpeg du PNG
    de titre, incruste en haut-gauche de la zone title pour tout le clip ;
    pas d'accroche ; « Partie N » (``part_path``) centre dans la zone part."""
    letterbox = reframe_data.get("layout") == "letterbox"
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
    font_rel = _filter_path(FONT_FILE, scratch_dir)

    if letterbox:
        zones = reframe_data["text_zones"]
        if title_input is None:
            raise RenderError("letterbox : le PNG du titre d'ecran n'est pas fourni a ffmpeg")
        tx0, ty0, _tx1, _ty1 = _zone(zones["title"])
        lines.append(f"[{cur}][{title_input}:v]overlay=x={tx0}:y={ty0}:eof_action=repeat[vtitle]")
        cur = "vtitle"
        if part_path is not None:
            px0, _py0, px1, _py1 = _zone(zones["part"])
            baseline = _part_placement(part_path.read_text(encoding="utf-8"), zones["part"], settings)
            part_rel = _filter_path(part_path, scratch_dir)
            lines.append(
                f"[{cur}]drawtext=textfile='{part_rel}':fontfile='{font_rel}':"
                f"fontsize={settings['part_font_size']}:fontcolor={settings['part_font_color']}:"
                f"borderw={settings['part_border']}:bordercolor=black:"
                f"x={px0}+({px1 - px0}-text_w)/2:y={baseline}:y_align=baseline[vpart]"
            )
            cur = "vpart"
        lines.append(_audio_filter(clip_start, clip_end, settings))
        return ";".join(lines), cur

    if hook_path is None:
        raise RenderError("texte d'accroche absent pour un rendu hors letterbox")
    hook_rel = _filter_path(hook_path, scratch_dir)
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

    lines.append(_audio_filter(clip_start, clip_end, settings))
    return ";".join(lines), cur


def _audio_filter(clip_start: float, clip_end: float, settings: dict[str, Any]) -> str:
    return (
        f"[0:a]atrim=start={clip_start:.6f}:end={clip_end:.6f},asetpts=PTS-STARTPTS,"
        f"loudnorm=I={settings['loudnorm_i']}:TP={settings['loudnorm_tp']}:LRA={settings['loudnorm_lra']}[aout]"
    )


# --------------------------------------------------------------------------
# ffmpeg / ffprobe
# --------------------------------------------------------------------------


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
    extra_inputs: tuple[Path, ...] = (),
) -> None:
    cmd = [
        ffmpeg_bin, "-y", "-loglevel", "error",
        "-i", str(source.resolve()),
        *(arg for extra in extra_inputs for arg in ("-i", str(extra.resolve()))),
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
    _exec_ffmpeg(cmd, scratch_dir, out_path)


def _exec_ffmpeg(cmd: list[str], cwd: Path, out_path: Path) -> None:
    try:
        proc = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError as exc:
        raise RenderError(f"ffmpeg introuvable ({cmd[0]})") from exc
    if proc.returncode != 0:
        raise RenderError(f"ffmpeg a echoue pour {out_path} : {proc.stderr.decode(errors='replace').strip()}")


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

    screen_title = clip.get("screen_title")
    if not isinstance(screen_title, str) or not screen_title.strip():
        raise RenderError(
            f"screen_title absent de captions.json pour {clip_id} : relancer captions --force"
        )

    letterbox = reframe_data.get("layout") == "letterbox"
    video_rect: dict[str, int] | None = None
    if letterbox:
        zones = reframe_data.get("text_zones")
        if not isinstance(zones, dict) or not {"title", "subtitles", "part"} <= set(zones):
            raise RenderError(
                f"reframe/{clip_id}.json est en letterbox sans text_zones (title, subtitles, part) : "
                "relancer reframe --force"
            )
        main = [p for p in reframe_data["plans"][0]["panels"] if p.get("name") == "main"]
        if not main:
            raise RenderError(f"reframe/{clip_id}.json est en letterbox sans panneau main : relancer reframe --force")
        video_rect = {k: int(main[0]["dest"][k]) for k in ("x", "y", "w", "h")}

    scratch_dir = video_dir / "render" / clip_id
    scratch_dir.mkdir(parents=True, exist_ok=True)
    try:
        hook_path: Path | None = None
        part_path: Path | None = None
        extra_inputs: tuple[Path, ...] = ()
        if letterbox:
            # Titre d'ecran pendant tout le clip, pas d'accroche de 2 s (SPEC-6127).
            png = scratch_dir / "title.png"
            title_png(screen_title, reframe_data["text_zones"]["title"], settings, png)
            extra_inputs = (png,)
            if clip["parts_total"] > 1:
                part_path = scratch_dir / "part.txt"
                part_path.write_text(f"Partie {clip['part']}", encoding="utf-8")
        else:
            hook_path = scratch_dir / "hook.txt"
            hook_path.write_text(clip["hook_text"], encoding="utf-8")
            if clip["parts_total"] > 1:
                part_path = scratch_dir / "part.txt"
                part_path.write_text(f"Part {clip['part']}/{clip['parts_total']}", encoding="utf-8")

        filter_complex, vout_label = _build_filter_complex(
            reframe_data, clip["start"], clip["end"], ass_path, hook_path, part_path, scratch_dir, settings,
            title_input=1 if letterbox else None,
        )

        target_fps = float(settings["max_fps"])

        device = get_device()

        tmp_out = mp4_out.with_suffix(".mp4.tmp")
        out_dir.mkdir(parents=True, exist_ok=True)
        _run_ffmpeg(
            ffmpeg_bin, source, filter_complex, vout_label, target_fps, device.type, settings, scratch_dir, tmp_out,
            extra_inputs,
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
        "screen_title": screen_title,
        "title": clip["title"],
        "caption": clip["caption"],
        "hashtags": clip["hashtags"],
        "transcript": _clip_transcript(transcript, clip["start"], clip["end"]),
        "layout": reframe_data["layout"],
        "qa": dict(_QA_DEFAULT),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if video_rect is not None:
        data["video_rect"] = video_rect  # le panneau main, pour la qa (SPEC-6127)
    tmp_json = json_out.with_suffix(".json.tmp")
    tmp_json.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_json.replace(json_out)

    return mp4_out
