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
   passes a whisper en initial_prompt (avant de charger le modele : jamais
   un LLM local et whisper en meme temps, ADR-fb9b), raccourcis a
   ``vocab_max_tokens`` tokens pour tenir dans la fenetre du decodeur
   (journalise ; transcript.json et la correction gardent tout) ;
2. extraction de l'audio (ffmpeg, wav 16 kHz mono), transcription via
   ``BatchedInferencePipeline`` (``batch_size`` de la config, defaut 8 ;
   ~4,9x plus rapide qu'un ``WhisperModel.transcribe`` sequentiel sur une
   video reelle, sans perte de mots mais ponctuation/majuscules internes
   moins riches, banc docs/bench-whisper-vitesse.md), ou sequentiel si
   ``batch_size <= 1`` ; puis liberation du modele et ecriture du resultat
   brut dans transcript_raw.json avant la correction ;
3. usage ``transcript_fix`` par tranches de ``fix_chunk_words`` mots,
   jusqu'a ``fix_parallel`` tranches en meme temps (threads : les appels
   clipper.llm sont des sous-processus) : la reponse ne liste que des
   corrections {i, old, word} par index de mot (ancien texte, nouveau texte),
   donc ni le nombre de mots ni leurs timecodes ne peuvent changer. Une
   correction dont ``old`` ne correspond pas au mot reellement present a cet
   index est refusee et journalisee dans llm_refusals.jsonl (ADR-ad2e),
   jamais appliquee en silence.

Si transcript_raw.json existe deja (retour apres un echec de la correction),
il est reutilise et whisper n'est pas relance, sauf ``force``.

Claude indisponible : l'erreur remonte, rien n'est ecrit (ADR-ad2e). Seul
``vocab = false`` / ``transcript_fix = false`` dans [transcribe] saute ces
appels.
"""

from __future__ import annotations

import gc
import json
import logging
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
    # Taille de lot BatchedInferencePipeline (banc TASK-be65 : ~4,9x plus
    # rapide que le sequentiel sur une video reelle, sans perte de mots,
    # docs/bench-whisper-vitesse.md). <= 1 = sequentiel (WhisperModel.transcribe
    # direct, comportement d'avant ce reglage).
    "batch_size": 8,
    # Vocabulaire de noms propres demande a clipper.llm (usage vocab).
    "vocab": True,
    # Tokens maximum du vocabulaire passe a whisper en initial_prompt :
    # au-dela, les dernieres entrees sont ecartees et c'est journalise. Le
    # decodeur a 448 positions, que faster-whisper remplit avec 1 (sot_prev)
    # + 223 tokens de contexte (initial_prompt) + tokens speciaux : la borne
    # est refusee au-dela de _VOCAB_TOKENS_CEILING (100 positions laissees a
    # la transcription de chaque fenetre).
    "vocab_max_tokens": 100,
    # Correction des mots par clipper.llm (usage transcript_fix).
    "transcript_fix": True,
    # Nombre de mots vises par tranche de correction (une tranche ne coupe
    # jamais un segment).
    "fix_chunk_words": 3000,
    # Nombre de tranches de correction traitees en meme temps (appels
    # clipper.llm en sous-processus, pas de cout CPU Python).
    "fix_parallel": 4,
}

log = logging.getLogger(__name__)

# Fenetre du decodeur Whisper et prompt construit par faster-whisper
# (WhisperModel.get_prompt, 1.2.1) : [sot_prev] + texte precedent
# (initial_prompt puis transcription deja faite, 223 derniers tokens) +
# sot, langue, tache (+ no_timestamps). TASK-b20f (avant le retrait de
# hotwords, TASK-913b) : sans borne, un vocabulaire long donnait 1 + 223
# (hotwords) + 223 (initial_prompt) + 3 = 450 > 448.
_WHISPER_POSITIONS = 448
_WHISPER_CONTEXT_TOKENS = _WHISPER_POSITIONS // 2 - 1
_WHISPER_SPECIAL_TOKENS = 5
_MIN_GENERATION_TOKENS = 100
_VOCAB_TOKENS_CEILING = (
    _WHISPER_POSITIONS - _WHISPER_SPECIAL_TOKENS - _WHISPER_CONTEXT_TOKENS - _MIN_GENERATION_TOKENS
)

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


def _batched_pipeline(model: Any) -> Any:
    from faster_whisper import BatchedInferencePipeline

    return BatchedInferencePipeline(model)


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


def _check_vocab_max_tokens(settings: dict[str, Any]) -> None:
    bound = settings["vocab_max_tokens"]
    if not isinstance(bound, int) or isinstance(bound, bool) or not 1 <= bound <= _VOCAB_TOKENS_CEILING:
        raise TranscribeError(
            f"[transcribe] vocab_max_tokens = {bound!r} : attendu un entier entre 1 et "
            f"{_VOCAB_TOKENS_CEILING} (fenetre de {_WHISPER_POSITIONS} positions du decodeur "
            f"Whisper, dont {_WHISPER_CONTEXT_TOKENS} de contexte et {_MIN_GENERATION_TOKENS} "
            "gardees pour la transcription) ; pour ne pas passer de vocabulaire : vocab = false"
        )


def _whisper_vocab(model: Any, vocab: list[str], max_tokens: int) -> list[str]:
    """Plus longue tete du vocabulaire (entrees entieres, dans l'ordre) dont
    initial_prompt tient dans ``max_tokens`` tokens du tokenizer du modele,
    comptes comme faster-whisper les encode. Un modele sans ``hf_tokenizer``
    (WhisperModel en a toujours un) est borne par le nombre d'octets UTF-8,
    qui majore les tokens d'un BPE sur octets ; c'est journalise. Les
    entrees ecartees sont journalisees (ADR-ad2e)."""
    hf_tokenizer = getattr(model, "hf_tokenizer", None)

    def tokens(text: str) -> int:
        if hf_tokenizer is None:
            return len((" " + text).encode("utf-8"))
        return len(hf_tokenizer.encode(" " + text, add_special_tokens=False).ids)

    if vocab and hf_tokenizer is None:
        log.warning(
            "modele whisper sans hf_tokenizer : tokens du vocabulaire majores par ses octets UTF-8"
        )

    kept = len(vocab)
    while kept and tokens(", ".join(vocab[:kept])) > max_tokens:
        kept -= 1
    if kept < len(vocab):
        log.warning(
            "vocabulaire whisper raccourci a %d/%d entrees (vocab_max_tokens = %d, fenetre du "
            "decodeur) ; ecartees : %s",
            kept, len(vocab), max_tokens, ", ".join(vocab[kept:]),
        )
    return vocab[:kept]


def _run_whisper(
    model_factory: Callable[[str, str, str], Any],
    audio_path: Path,
    settings: dict[str, Any],
    vocab: list[str],
    pipeline_factory: Callable[[Any], Any] = _batched_pipeline,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    device = get_device()
    options: dict[str, Any] = {
        "word_timestamps": True,
        "beam_size": settings["beam_size"],
        "vad_filter": settings["vad_filter"],
        "language": settings["language"],
    }
    if device.type == "cuda":
        _make_cuda_dlls_discoverable()
    model = model_factory(settings["model"], device.type, device.compute_type)
    try:
        prompt_vocab = _whisper_vocab(model, vocab, int(settings["vocab_max_tokens"]))
        if prompt_vocab:
            options["initial_prompt"] = ", ".join(prompt_vocab)
        batch_size = int(settings["batch_size"])
        if batch_size > 1:
            runner = pipeline_factory(model)
            raw_segments, info = runner.transcribe(str(audio_path), batch_size=batch_size, **options)
        else:
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
                        "old": {"type": "string", "minLength": 1},
                        "word": {"type": "string", "minLength": 1},
                    },
                    "required": ["i", "old", "word"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["corrections"],
        "additionalProperties": False,
    }


def _check_corrections(words: list[dict[str, Any]]) -> Callable[[Any], None]:
    """Controle passe a llm.ask (comme clipper.captions) : une correction
    dont ``old`` ne correspond pas au mot reellement present a cet index (LLM
    decale, index hallucine...) ne correspond pas au texte et est renvoyee au
    modele pour correction, comme une reponse hors schema ; si elle est
    encore refusee apres les tentatives de reparation, l'echec est journalise
    dans llm_refusals.jsonl (ADR-ad2e) et remonte, jamais applique en
    silence. Un mot corrige ne peut pas non plus contenir d'espace interne :
    il deviendrait deux mots pour les sous-titres, sans timecode propre."""

    def check(answer: dict[str, Any]) -> None:
        for correction in answer["corrections"]:
            i = correction["i"]
            old = correction["old"].strip()
            actual = words[i]["word"].strip()
            if old != actual:
                raise llm.SchemaError(
                    f"correction refusee pour le mot {i} : le modele visait {old!r}, "
                    f"le texte a cet index est {actual!r}"
                )
            new = correction["word"].strip()
            if not new or any(c.isspace() for c in new):
                raise llm.SchemaError(
                    f"correction refusee pour le mot {i} : {correction['word']!r} "
                    "(un mot doit rester un seul mot)"
                )

    return check


def _fix_chunk(chunk: list[dict[str, Any]], vocab: list[str], config: Any, log_path: Path) -> None:
    words = [w for seg in chunk for w in seg["words"]]
    if not words:
        return
    lines = "\n".join(f"{i}\t{w['word'].strip()}" for i, w in enumerate(words))
    prompt = (
        "Voici un extrait de transcription automatique, un mot par ligne, "
        "precede de son index. Corrige uniquement l'orthographe des mots mal "
        "reconnus (surtout les noms propres). Ne fusionne, ne coupe, n'ajoute "
        "et ne supprime aucun mot : une correction remplace exactement un mot "
        "par un seul mot, sans espace. Ne liste que les mots a changer, "
        "chacun avec son index, le mot original exact (old) et le mot "
        "corrige (word).\n\n"
        f"Vocabulaire attendu : {', '.join(vocab) if vocab else '(aucun)'}\n\n"
        f"{lines}"
    )
    answer = llm.ask(
        "transcript_fix", prompt, [], _fix_schema(len(words)),
        config=config, check=_check_corrections(words), log_path=log_path,
    )
    for correction in answer["corrections"]:
        word = words[correction["i"]]
        original = word["word"]
        new = correction["word"].strip()
        word["word"] = original[: len(original) - len(original.lstrip())] + new
    for seg in chunk:
        if seg["words"]:
            seg["text"] = "".join(w["word"] for w in seg["words"])


def _fix_chunks(
    chunks: list[list[dict[str, Any]]], vocab: list[str], config: Any, parallel: int, log_path: Path
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
        futures = [executor.submit(_fix_chunk, chunk, vocab, config, log_path) for chunk in chunks]
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
    pipeline_factory: Callable[[Any], Any] = _batched_pipeline,
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
    _check_vocab_max_tokens(settings)
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
            segments, header = _run_whisper(model_factory, audio, settings, vocab, pipeline_factory)
        finally:
            audio.unlink(missing_ok=True)

        model_name = settings["model"]
        raw = {"video_id": video_id, **header, "model": model_name, "vocab": vocab, "segments": segments}
        tmp_raw = raw_path.with_suffix(".json.tmp")
        tmp_raw.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_raw.replace(raw_path)

    if settings["transcript_fix"]:
        chunks = _chunks(segments, int(settings["fix_chunk_words"]))
        log_path = video_dir / "llm_refusals.jsonl"
        _fix_chunks(chunks, vocab, config, int(settings["fix_parallel"]), log_path)

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
