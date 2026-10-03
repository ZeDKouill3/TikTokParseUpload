"""« clipper models prefetch » (SPEC-38f7 R5) : telecharge dans leurs caches
habituels le modele mediapipe de clipper.reframe et le modele faster-whisper
configure (``[transcribe] model``), pour qu'un premier clip n'attende pas un
telechargement ni n'echoue a mi-pipeline.

Module utilitaire (ADR-b16b) : n'importe aucune etape du pipeline ni
clipper.web. Le cablage des vraies fabriques (celles de clipper.transcribe et
clipper.reframe) se fait dans clipper/__main__.py sous « clipper models
prefetch », jamais ici.

Contrat d'une fabrique : ``factory(local_files_only: bool) -> Any`` (le
whisper_factory recoit aussi le nom du modele en premier argument), au sens
de ``faster_whisper.utils.download_model(..., local_files_only=...)``.
``prefetch`` l'appelle d'abord avec ``local_files_only=True`` (sonde locale,
sans reseau) ; si elle echoue (modele absent du cache), elle est rappelee une
seule fois avec ``local_files_only=False`` pour le telecharger reellement.
Deja present : jamais rappelee une seconde fois. Toute erreur du
telechargement reel remonte en ``ModelsError``, jamais de repli silencieux
(ADR-ad2e).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

# Convention documentee (SPEC-38f7 R5, docstring de clipper.reframe) : chemin
# par defaut du modele mediapipe. Dupliquee ici a l'identique (jamais
# clipper.reframe importe, ADR-b16b) pour que ce module et clipper.doctor
# sondent le meme fichier sans jamais charger l'etape.
DEFAULT_MEDIAPIPE_MODEL_PATH = Path.home() / ".cache" / "clipper" / "blaze_face_short_range.tflite"

# Convention documentee (CONFIG_DEFAULTS de clipper.transcribe). Meme raison.
DEFAULT_WHISPER_MODEL = "small"


class ModelsError(Exception):
    """Un modele n'a pas pu etre telecharge (la raison est dans le message)."""


def _section(config: Any, name: str) -> dict[str, Any]:
    """Table ``[name]`` brute de ``config.toml`` (sans les defauts du module
    de l'etape, jamais importe ici, ADR-b16b) ; ``{}`` si absente ou si
    ``config`` est ``None``."""
    if config is None:
        return {}
    return dict(getattr(config, "_sections", {}).get(name, {}))


def mediapipe_model_path(config: Any = None) -> Path:
    """Chemin du modele mediapipe attendu : ``[reframe] model_path`` s'il est
    regle, sinon ``DEFAULT_MEDIAPIPE_MODEL_PATH``."""
    configured = str(_section(config, "reframe").get("model_path") or "").strip()
    return Path(configured).expanduser() if configured else DEFAULT_MEDIAPIPE_MODEL_PATH


def whisper_model_name(config: Any = None) -> str:
    """Nom du modele whisper configure (``[transcribe] model``), par defaut
    ``DEFAULT_WHISPER_MODEL``."""
    configured = _section(config, "transcribe").get("model")
    return str(configured) if configured else DEFAULT_WHISPER_MODEL


@dataclass(frozen=True)
class PrefetchResult:
    name: str
    already_present: bool


def _fetch(label: str, call: Callable[[bool], Any]) -> PrefetchResult:
    try:
        call(True)
    except Exception:
        try:
            call(False)
        except Exception as exc:
            raise ModelsError(f"{label} : telechargement impossible ({exc})") from exc
        return PrefetchResult(name=label, already_present=False)
    return PrefetchResult(name=label, already_present=True)


def prefetch(
    config: Any,
    whisper_factory: Callable[[str, bool], Any],
    face_model_fetch: Callable[[bool], Any],
) -> list[PrefetchResult]:
    """Telecharge (si besoin) le modele whisper configure et le modele
    mediapipe, dans leurs caches habituels. Chaque resultat dit si le modele
    etait deja present. Toute erreur remonte en ``ModelsError``, jamais de
    repli silencieux (ADR-ad2e)."""
    name = whisper_model_name(config)
    whisper_result = _fetch(
        f"whisper:{name}", lambda local_files_only: whisper_factory(name, local_files_only)
    )
    mediapipe_result = _fetch("mediapipe", face_model_fetch)
    return [whisper_result, mediapipe_result]
