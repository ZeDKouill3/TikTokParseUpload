"""Etape transcribe : faster-whisper mot par mot, vocabulaire et correction
des noms propres par clipper.llm.

Entrees : workspace/<video_id>/<video_id>.mp4 et meta.json (etape download).
Sortie  : workspace/<video_id>/transcript.json (et un intermediaire,
transcript_raw.json, garde avant la correction)

    {"video_id", "language", "language_probability", "duration", "model",
     "vocab": [...],
     "segments": [{"id", "start", "end", "text",
                   "words": [{"word", "start", "end", "probability"}]}]}

Deroulement :
1. usage ``vocab`` : noms propres tires du titre et de la description,
   passes a whisper en initial_prompt et hotwords (avant de charger le
   modele : jamais un LLM local et whisper en meme temps, ADR-fb9b) ;
2. extraction de l'audio (ffmpeg, wav 16 kHz mono), transcription, puis
   liberation du modele ; le resultat brut est ecrit dans
   transcript_raw.json avant la correction ;
3. usage ``transcript_fix`` par tranches de ``fix_chunk_words`` mots,
   jusqu'a ``fix_parallel`` tranches en meme temps (threads : les appels
   clipper.llm sont des sous-processus) : la reponse ne liste que des
   corrections {i, word} par index de mot, donc ni le nombre de mots ni
   leurs timecodes ne peuvent changer.

Si transcript_raw.json existe deja (retour apres un echec de la correction),
il est reutilise et whisper n'est pas relance, sauf ``force``.

Claude indisponible : l'erreur remonte, rien n'est ecrit (ADR-ad2e). Seul
``vocab = false`` / ``transcript_fix = false`` dans [transcribe] saute ces
appels.
"""

from __future__ import annotations

import gc
import json
import os
import subprocess
import sys
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from importlib.util import find_spec
from pathlib import Path
from typing import Any

from clipper import llm
from clipper.gpu import get_device

CONFIG_DEFAULTS: dict[str, object] = {
    # Taille du modele faster-whisper (tiny, base, small, medium, large-v3...).
    "model": "small",
    # Langue forcee ("fr", "en"...) ; absente = detection automatique.
    "language": None,
    "beam_size": 5,
    "vad_filter": True,
    # Vocabulaire de noms propres demande a clipper.llm (usage vocab).
    "vocab": True,
    # Correction des mots par clipper.llm (usage transcript_fix).
    "transcript_fix": True,
    # Nombre de mots vises par tranche de correction (une tranche ne coupe
    # jamais un segment).
    "fix_chunk_words": 3000,
    # Nombre de tranches de correction traitees en meme temps (appels
    # clipper.llm en sous-processus, pas de cout CPU Python).
    "fix_parallel": 4,
}

VOCAB_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "words": {"type": "array", "items": {"type": "string", "minLength": 1}, "maxItems": 100},
    },
    "required": ["words"],
    "additionalProperties": False,
}


class TranscribeError(Exception):
    """Entree manquante, ffmpeg en echec ou correction inapplicable."""


def extract_audio(video_path: str | Path, audio_path: str | Path) -> None:
    """Extrait la piste audio de la video en wav PCM 16 kHz mono."""
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error", "-i", str(video_path),
        "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(audio_path),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise TranscribeError("ffmpeg introuvable dans le PATH") from exc
    except subprocess.CalledProcessError as exc:
        raise TranscribeError(f"ffmpeg a echoue sur {video_path} : {exc.stderr.strip()}") from exc


def _whisper_model(name: str, device: str, compute_type: str) -> Any:
    from faster_whisper import WhisperModel

    return WhisperModel(name, device=device, compute_type=compute_type)


def _cuda_dll_dirs() -> list[Path]:
    """Dossiers bin des paquets pip nvidia (nvidia-cublas-cu12,
    nvidia-cudnn-cu12...) installes dans l'environnement courant, absents si
    ces paquets ne sont pas installes."""
    spec = find_spec("nvidia")
    if spec is None or not spec.submodule_search_locations:
        return []
    dirs = []
    for base in spec.submodule_search_locations:
        for bin_dir in Path(base).glob("*/bin"):
            if bin_dir.is_dir():
                dirs.append(bin_dir)
    return dirs


def _make_cuda_dlls_discoverable() -> None:
    """Sous Windows, CTranslate2 (utilise par faster-whisper) resout cuBLAS
    et cuDNN via le PATH du processus, pas via os.add_dll_directory (mesure :
    TASK-f6c8, add_dll_directory seul laisse 'cublas64_12.dll is not found or
    cannot be loaded'). Sans reglage manuel du PATH par l'utilisateur, il
    faut donc y prefixer les dossiers bin des paquets pip nvidia avant de
    charger le modele. Si ces paquets sont absents, le PATH n'est pas touche
    et l'echec de CTranslate2 remonte normalement (ADR-ad2e : pas de repli
    silencieux)."""
    if sys.platform != "win32":
        return
    dirs = [str(d) for d in _cuda_dll_dirs()]
    if not dirs:
        return
    current = os.environ.get("PATH", "")
    existing = current.split(os.pathsep) if current else []
    missing = [d for d in dirs if d not in existing]
    if not missing:
        return
    os.environ["PATH"] = os.pathsep.join(missing + existing)


def _settings(config: Any) -> dict[str, Any]:
    if config is None:
        from clipper.config import load_config

        config = load_config()
    return {**CONFIG_DEFAULTS, **config.section("transcribe")}


def _ask_vocab(meta: dict[str, Any], config: Any) -> list[str]:
    prompt = (
        "Voici le titre et la description d'une video YouTube qui va etre "
        "transcrite automatiquement par Whisper. Donne la liste des noms "
        "propres, marques, titres de jeux, pseudos et termes rares que Whisper "
        "risque de mal orthographier, ecrits exactement comme il faut.\n\n"
        f"Titre : {meta.get('title') or ''}\n\n"
        f"Description :\n{meta.get('description') or ''}"
    )
    answer = llm.ask("vocab", prompt, [], VOCAB_SCHEMA, config=config)
    return [w.strip() for w in answer["words"] if w.strip()]


def _free_memory() -> None:
    """Rend la memoire d'un modele dont l'appelant a lache les references
    (ADR-fb9b)."""
    gc.collect()
    try:
        import torch
    except ImportError:
        return
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def _run_whisper(
    model_factory: Callable[[str, str, str], Any],
    audio_path: Path,
    settings: dict[str, Any],
    vocab: list[str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    device = get_device()
    options: dict[str, Any] = {
        "word_timestamps": True,
        "beam_size": settings["beam_size"],
        "vad_filter": settings["vad_filter"],
        "language": settings["language"],
    }
    if vocab:
        options["initial_prompt"] = ", ".join(vocab)
        options["hotwords"] = " ".join(vocab)

    if device.type == "cuda":
        _make_cuda_dlls_discoverable()
    model = model_factory(settings["model"], device.type, device.compute_type)
    try:
        raw_segments, info = model.transcribe(str(audio_path), **options)
        segments = [_segment_dict(seg) for seg in raw_segments]
        header = {
            "language": info.language,
            "language_probability": info.language_probability,
            "duration": info.duration,
        }
    finally:
        raw_segments = model = None
        _free_memory()
    return segments, header


def _segment_dict(seg: Any) -> dict[str, Any]:
    words = [
        {"word": w.word, "start": w.start, "end": w.end, "probability": w.probability}
        for w in (seg.words or [])
    ]
    return {"id": seg.id, "start": seg.start, "end": seg.end, "text": seg.text, "words": words}


def _chunks(segments: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    """Regroupe les segments en tranches d'environ ``size`` mots."""
    chunks: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    count = 0
    for seg in segments:
        n = len(seg["words"])
        if current and count + n > size:
            chunks.append(current)
            current, count = [], 0
        current.append(seg)
        count += n
    if current:
        chunks.append(current)
    return chunks


def _fix_schema(n_words: int) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "corrections": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "i": {"type": "integer", "minimum": 0, "maximum": n_words - 1},
                        "word": {"type": "string", "minLength": 1},
                    },
                    "required": ["i", "word"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["corrections"],
        "additionalProperties": False,
    }


def _fix_chunk(chunk: list[dict[str, Any]], vocab: list[str], config: Any) -> None:
    words = [w for seg in chunk for w in seg["words"]]
    if not words:
        return
    lines = "\n".join(f"{i}\t{w['word'].strip()}" for i, w in enumerate(words))
    prompt = (
        "Voici un extrait de transcription automatique, un mot par ligne, "
        "precede de son index. Corrige uniquement l'orthographe des mots mal "
        "reconnus (surtout les noms propres). Ne fusionne, ne coupe, n'ajoute "
        "et ne supprime aucun mot : une correction remplace exactement un mot "
        "par un seul mot, sans espace. Ne liste que les mots a changer.\n\n"
        f"Vocabulaire attendu : {', '.join(vocab) if vocab else '(aucun)'}\n\n"
        f"{lines}"
    )
    answer = llm.ask("transcript_fix", prompt, [], _fix_schema(len(words)), config=config)
    for correction in answer["corrections"]:
        text = correction["word"].strip()
        if not text or any(c.isspace() for c in text):
            raise TranscribeError(
                f"correction refusee pour le mot {correction['i']} : {correction['word']!r} "
                "(un mot doit rester un seul mot)"
            )
        word = words[correction["i"]]
        original = word["word"]
        word["word"] = original[: len(original) - len(original.lstrip())] + text
    for seg in chunk:
        if seg["words"]:
            seg["text"] = "".join(w["word"] for w in seg["words"])


def _fix_chunks(
    chunks: list[list[dict[str, Any]]], vocab: list[str], config: Any, parallel: int
) -> None:
    """Corrige jusqu'a ``parallel`` tranches en meme temps (threads : les
    appels clipper.llm sont des sous-processus, pas du calcul CPU Python).
    Chaque tranche porte des segments distincts, donc les threads n'ecrivent
    jamais dans la meme structure. Une tranche en echec fait echouer l'etape
    avec sa raison (ADR-ad2e) ; les autres deja lancees terminent avant que
    l'exception ne remonte."""
    if not chunks:
        return
    with ThreadPoolExecutor(max_workers=max(1, parallel)) as executor:
        futures = [executor.submit(_fix_chunk, chunk, vocab, config) for chunk in chunks]
        for future in futures:
            future.result()


def transcribe(
    video_id: str,
    workspace_dir: str | Path = "workspace",
    *,
    config: Any = None,
    force: bool = False,
    model_factory: Callable[[str, str, str], Any] = _whisper_model,
    audio_extractor: Callable[[Path, Path], None] = extract_audio,
) -> Path:
    """Transcrit workspace/<video_id>/<video_id>.mp4 dans transcript.json et
    renvoie ce chemin. Un transcript deja present n'est pas refait, sauf
    ``force``. Le resultat brut de whisper est garde dans
    transcript_raw.json avant la correction : une relance apres un echec de
    la correction reutilise ce fichier au lieu de refaire whisper."""
    video_dir = Path(workspace_dir) / video_id
    out = video_dir / "transcript.json"
    if out.exists() and not force:
        return out

    settings = _settings(config)
    raw_path = video_dir / "transcript_raw.json"

    if raw_path.exists() and not force:
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
        header = {k: raw[k] for k in ("language", "language_probability", "duration")}
        model_name = raw["model"]
        vocab = raw["vocab"]
        segments = raw["segments"]
    else:
        video = video_dir / f"{video_id}.mp4"
        meta_file = video_dir / "meta.json"
        if not video.exists():
            raise TranscribeError(f"video absente : {video}")
        if not meta_file.exists():
            raise TranscribeError(f"meta.json absent : {meta_file}")
        meta = json.loads(meta_file.read_text(encoding="utf-8"))

        vocab = _ask_vocab(meta, config) if settings["vocab"] else []

        audio = video_dir / "transcribe_audio.wav"
        try:
            audio_extractor(video, audio)
            segments, header = _run_whisper(model_factory, audio, settings, vocab)
        finally:
            audio.unlink(missing_ok=True)

        model_name = settings["model"]
        raw = {"video_id": video_id, **header, "model": model_name, "vocab": vocab, "segments": segments}
        tmp_raw = raw_path.with_suffix(".json.tmp")
        tmp_raw.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_raw.replace(raw_path)

    if settings["transcript_fix"]:
        chunks = _chunks(segments, int(settings["fix_chunk_words"]))
        _fix_chunks(chunks, vocab, config, int(settings["fix_parallel"]))

    transcript = {
        "video_id": video_id,
        **header,
        "model": model_name,
        "vocab": vocab,
        "segments": segments,
    }
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(transcript, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(out)
    return out
