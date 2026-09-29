"""Backend ``claude-cli`` : Claude Code en mode non interactif.

Commande construite :

    claude -p --model <modele> --output-format <json|stream-json>
           [--input-format stream-json --verbose]  # avec images
           --tools ""
           [--json-schema <schema JSON compact>]
           --system-prompt <court> --setting-sources "" --no-session-persistence

Le prompt passe par stdin, pas par argv : une transcription de 2-3 h depasse
la limite de ligne de commande de Windows (32 767 caracteres).

Images. ``claude -p`` n'a aucune option pour joindre une image (verifie sur
Claude Code 2.1.282 : ni --image ni equivalent dans ``claude --help``). Deux
voies existent :
- ``--input-format stream-json`` avec un bloc image base64 sur stdin, mais
  cela impose ``--output-format stream-json`` ;
- donner a Claude le chemin du fichier et l'outil Read, qui lit les images
  et les presente visuellement, en 2 tours agentiques (lecture puis reponse).
La seconde a ete mesuree (TASK-b0fa, ivl0nxa3C7o) : chaque tour relit tout le
contexte, ~90k tokens de cache par appel vision sur la duree d'une video, un
cout qui ne baisse pas avec une planche unique d'images. On prend donc la
premiere : les images partent en blocs base64 dans le message utilisateur
(stdin, stream-json), sans outil (``--tools ""``), reponse en un seul tour.
Sans image, le prompt reste du texte brut sur stdin (``--output-format
json``, comportement inchange).

``--system-prompt`` remplace le prompt systeme de Claude Code (~170k tokens
de contexte mis en cache par appel sinon) et ``--setting-sources ""`` ignore
CLAUDE.md, hooks et reglages de l'utilisateur : le quota est partage avec ses
sessions Claude Code (ADR-b1c1).

Schema. Donne seulement dans le prompt, il n'est qu'une consigne : essai
reel du 2026-09-25 (etape vision, 8 images) -> images bien decrites mais
``{"0": {...}, ...}`` au lieu de ``{"frames": [...]}``. ``--json-schema``
l'impose au CLI (sortie structuree). Il n'accepte que du JSON litteral (ni
chemin ni ``@fichier``, verifie sur 2.1.281) : le schema passe donc par argv,
en JSON compact, et une ligne de commande qui depasserait la limite Windows
est un echec explicite plutot qu'un envoi sans schema.

Cache de prompt (TASK-2cbb). Le cache de contexte d'Anthropic marque des
BLOCS de contenu (``cache_control``), pas un prefixe de caracteres a
l'interieur d'un bloc unique : un prompt texte identique octet pour octet
entre deux appels ne produit aucune relecture de cache tant qu'il n'est
qu'une seule chaine sur stdin, faute de frontiere de bloc ou poser ce
marqueur (mesure reelle, cache_read quasi nul malgre un prefixe deja partage
depuis TASK-b0fa). Quand ``LLMRequest.cache_prefix`` est donne, le prompt
part donc en (au moins) 2 blocs de texte, meme sans image (``--input-format
stream-json`` comme pour les images) : le premier (``cache_prefix``) porte
``cache_control: {"type": "ephemeral", "ttl": "1h"}``, le reste (role du juge
compris) n'en porte pas. Des juges d'un meme modele (clipper.jury) partagent
alors un bloc identique que le fournisseur peut relire au lieu de le
refacturer. ``ttl: "1h"`` est obligatoire : Claude Code pose deja son propre
cache_control ttl=1h sur le systeme (interne, hors controle), et l'API
refuse (400) un ttl="5m" (le defaut si omis) place apres dans l'ordre de
traitement (tools, system, messages) -- mesure reelle, pas une supposition.

Sortie. Avec --output-format json (sans image) : un objet unique ``{"type":
"result", "subtype": "success", "is_error": bool, "api_error_status":
int|null, "result": "<texte de la reponse>", "structured_output":
<objet>|absent, "num_turns", "session_id", "total_cost_usd", ...}``. Avec
--output-format stream-json (images) : le meme objet arrive en NDJSON, un
evenement par ligne, celui a retenir etant le dernier ``type: result``
(``_result_object`` gere les deux formes). Avec --json-schema, la reponse
deja decodee est dans ``structured_output`` et fait foi ; ``result`` (texte)
ne sert que si elle est absente. Dans les deux cas clipper.llm la valide
contre le schema. Une erreur API (quota, surcharge) arrive avec ``is_error:
true``, le message dans ``result`` et le code HTTP dans
``api_error_status``, et un code de sortie non nul.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from clipper.llm.backend import LLMRequest, Usage, image_b64, image_media_type
from clipper.llm.errors import LLMError, TransientLLMError

SYSTEM_PROMPT = (
    "Tu es un composant d'un pipeline automatique. Reponds uniquement avec "
    "le JSON demande, sans texte autour. Utilise l'outil Read seulement pour "
    "regarder les images dont le chemin est donne."
)

# CreateProcess refuse une ligne de commande de plus de 32 767 caracteres.
MAX_COMMAND_LINE = 32_000

_TRANSIENT_STATUS = {408, 429}
_TRANSIENT_TEXT = re.compile(
    r"usage limit|rate.?limit|overloaded|quota|timed? ?out|timeout|network|"
    r"connection|ECONNRESET|ECONNREFUSED|ENOTFOUND|ETIMEDOUT|503|529",
    re.IGNORECASE,
)


def _is_transient(status: Any, text: str) -> bool:
    if isinstance(status, int) and (status in _TRANSIENT_STATUS or status >= 500):
        return True
    if isinstance(status, int):
        return False
    return bool(_TRANSIENT_TEXT.search(text))


def _npm_shim_exe(shim: Path) -> Path | None:
    """``shim`` est un lanceur npm ``.cmd``/``.bat`` (Windows) : l'executable
    qu'il lance (``node_modules/@anthropic-ai/claude-code/bin/claude.exe`` a
    cote de lui), ou ``None`` si ``shim`` n'en est pas un ou que l'executable
    n'existe pas a cote."""
    if shim.suffix.lower() not in (".cmd", ".bat"):
        return None
    exe = shim.parent / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"
    return exe if exe.is_file() else None


def resolve_command(command: str) -> str:
    """Argv[0] a utiliser pour ``subprocess.run``. Sous Windows, Claude Code
    s'installe via npm comme un raccourci ``.cmd`` : ``subprocess.run`` sur un
    nom sans extension ne le trouve pas (FileNotFoundError, seule ``.exe`` est
    cherchee), et meme trouve, un ``.cmd``/``.bat`` passe par cmd.exe, qui
    reinterprete l'argv (``%VAR%`` developpe, ``^`` avale). On resout via
    ``shutil.which`` et, si le resultat est un tel raccourci, on appelle
    directement l'executable qu'il lance. Rien trouve : ``command`` est
    renvoye tel quel (l'erreur 'introuvable' actuelle est conservee)."""
    found = shutil.which(command)
    if not found:
        return command
    exe = _npm_shim_exe(Path(found))
    return str(exe) if exe else found


def stdin_input(request: LLMRequest) -> str:
    """Contenu envoye sur stdin. Sans image ni cache_prefix : le prompt tel
    quel (texte brut, ``--output-format json``). Avec l'un des deux : un
    unique message ``--input-format stream-json`` dont le contenu liste les
    blocs image (base64, comme clipper.llm.claude_api), puis le texte du
    prompt soit en un bloc, soit coupe en 2 blocs (cache_prefix marque
    ``cache_control``, le reste n'en porte pas) si ``cache_prefix`` est
    donne -- necessaire pour que le fournisseur puisse relire son cache sur
    ce prefixe (voir la docstring du module)."""
    if not request.images and not request.cache_prefix:
        return request.prompt
    content: list[dict[str, Any]] = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": image_media_type(p),
                "data": image_b64(p),
            },
        }
        for p in request.images
    ]
    if request.cache_prefix:
        # ttl explicite : Claude Code pose deja un cache_control ttl=1h sur le
        # systeme (interne, hors de notre controle) ; sans le meme ttl ici,
        # l'API refuse (400 : "a ttl='1h' cache_control block must not come
        # after a ttl='5m' cache_control block") puisque le defaut serait 5m,
        # place apres dans l'ordre de traitement (tools, system, messages).
        content.append(
            {
                "type": "text",
                "text": request.cache_prefix,
                "cache_control": {"type": "ephemeral", "ttl": "1h"},
            }
        )
        remainder = request.prompt[len(request.cache_prefix):]
        if remainder:
            content.append({"type": "text", "text": remainder})
    else:
        content.append({"type": "text", "text": request.prompt})
    message = {"type": "user", "message": {"role": "user", "content": content}}
    return json.dumps(message, ensure_ascii=False) + "\n"


class ClaudeCLIBackend:
    def __init__(self, settings: dict[str, Any]):
        self.command = str(settings.get("command", "claude"))
        self.timeout = settings.get("timeout", 900)
        self.last_usage: Usage | None = None

    def build_command(self, request: LLMRequest) -> list[str]:
        cmd = [resolve_command(self.command), "-p", "--model", request.model]
        if request.images or request.cache_prefix:
            # --verbose : requis par le CLI avec --print + --output-format
            # stream-json (verifie en reel, Claude Code 2.1.281 : "Error:
            # When using --print, --output-format=stream-json requires
            # --verbose"), sans effet observe sur la forme du flux NDJSON.
            cmd += ["--input-format", "stream-json", "--output-format", "stream-json", "--verbose"]
        else:
            cmd += ["--output-format", "json"]
        cmd += ["--tools", ""]
        if request.schema:
            cmd += ["--json-schema", json.dumps(request.schema, ensure_ascii=False, separators=(",", ":"))]
        cmd += [
            "--system-prompt", SYSTEM_PROMPT,
            "--setting-sources", "",
            "--no-session-persistence",
        ]
        return cmd

    def complete(self, request: LLMRequest) -> str:
        cmd = self.build_command(request)
        length = len(subprocess.list2cmdline(cmd))
        if length > MAX_COMMAND_LINE:
            raise LLMError(
                f"claude -p : ligne de commande de {length} caracteres (limite {MAX_COMMAND_LINE}), "
                "schema --json-schema trop long pour argv"
            )
        try:
            proc = subprocess.run(
                cmd,
                input=stdin_input(request),
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=self.timeout,
            )
        except FileNotFoundError as exc:
            raise LLMError(f"commande {self.command!r} introuvable (Claude Code installe ?)") from exc
        except subprocess.TimeoutExpired as exc:
            raise TransientLLMError(f"claude -p : pas de reponse en {self.timeout} s") from exc
        text, usage = parse_output(proc.stdout, proc.returncode, proc.stderr)
        self.last_usage = usage
        return text


def _usage_from(data: dict[str, Any]) -> Usage:
    """Telemetry from a successful ``claude -p --output-format json`` object.
    A missing field stays None (ADR-ad2e : aucune valeur inventee)."""
    raw = data.get("usage")
    raw = raw if isinstance(raw, dict) else {}
    return Usage(
        input_tokens=raw.get("input_tokens"),
        output_tokens=raw.get("output_tokens"),
        cache_read_tokens=raw.get("cache_read_input_tokens"),
        cost_usd=data.get("total_cost_usd"),
    )


def _result_object(stdout: str) -> dict[str, Any] | None:
    """The final ``{"type": "result", ...}`` object of the response. With
    ``--output-format json`` (no image), ``stdout`` is that object whole.
    With ``--output-format stream-json`` (images), ``stdout`` is NDJSON (one
    event per line) : the last ``type: result`` line is the one that carries
    the answer and its telemetry, same shape either way."""
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        data = None
    if isinstance(data, dict):
        return data
    result = None
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and obj.get("type") == "result":
            result = obj
    return result


def parse_output(stdout: str, returncode: int = 0, stderr: str = "") -> tuple[str, Usage]:
    """Extract the answer from ``claude -p`` output (``--output-format json``
    or ``stream-json``, see ``_result_object``) : the structured output
    (re-encoded as JSON text) when present, else the ``result`` text ;
    alongside the call's telemetry (Usage)."""
    data = _result_object(stdout)
    if not isinstance(data, dict):
        text = (stderr or stdout or "").strip()[:500]
        message = f"claude -p (code {returncode}) : sortie illisible : {text!r}"
        if _is_transient(None, text):
            raise TransientLLMError(message)
        raise LLMError(message)

    result = data.get("result")
    if data.get("is_error") or returncode != 0 or data.get("subtype") != "success":
        status = data.get("api_error_status")
        message = f"claude -p (code {returncode}, statut {status}) : {result or data.get('subtype')}"
        if _is_transient(status, str(result or "")):
            raise TransientLLMError(message)
        raise LLMError(message)
    usage = _usage_from(data)
    structured = data.get("structured_output")
    if structured is not None:
        return json.dumps(structured, ensure_ascii=False), usage
    if not isinstance(result, str):
        raise LLMError(f"claude -p : pas de champ 'result' texte dans {sorted(data)}")
    return result, usage
