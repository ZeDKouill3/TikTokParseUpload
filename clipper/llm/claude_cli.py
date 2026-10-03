"""Backend ``claude-cli`` : Claude Code en mode non interactif.

Commande construite :

    claude -p --model <modele> --output-format <json|stream-json>
           [--input-format stream-json --verbose]  # avec images
           --tools ""
           [--json-schema <schema JSON compact>]
           --system-prompt <court> --setting-sources "" --no-session-persistence
           --strict-mcp-config

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

Cache de prompt : abandonne (TASK-b384). TASK-2cbb avait pose un bloc
``cache_control`` explicite sur ``LLMRequest.cache_prefix`` (le cache de
contexte d'Anthropic marque des BLOCS de contenu, jamais un prefixe de
caracteres a l'interieur d'un bloc unique -- mesure reelle de l'epoque,
cache_read quasi nul sans frontiere de bloc). ``LLMRequest.cache_prefix`` est
maintenant ignore par ce backend : ``stdin_input`` ne le lit plus, aucun bloc
n'est jamais marque ``cache_control`` de notre part. Cause (TASK-b384,
mesuree via ``claude -p --debug api --debug-file``, script jetable rejouant
2 juges opus paralleles avec le meme prefixe) : ``--json-schema`` force un
echange interne a 2 tours (``num_turns: 2`` dans la sortie, ``stop:
tool_use`` dans le log debug, meme sans image ni cache_prefix -- observe
aussi en texte brut) ; sur le 2e tour, deja "stateless" (voir plus bas), le
nombre total de blocs ``cache_control`` que
Claude Code s'attribue LUI-MEME pour ce tour varie de facon non deterministe
entre appels par ailleurs identiques : 4 (accepte) ou 5 (400 permanent,
"A maximum of 4 blocks with cache_control may be provided. Found 5.", jamais
recupere). Mesure comparative (4 appels reels avec notre bloc : 2 echecs
definitifs sur 2 paires ; 10 appels reels sans notre bloc : 0 echec) : notre
propre bloc etait le +1 qui faisait parfois deborder ce budget prive
(mecanisme interne au CLI, non documente, hors de notre controle -- pas une
regression de notre cote, TASK-321b avait deja verifie qu'on ne posait
jamais plus d'un bloc). Cout : mesure avant/apres sur le smoke test reel
(``ank log`` TASK-b384, 5 passages consecutifs apres le fix) -- sans notre
marqueur, ``cache_read_tokens`` reste proche des valeurs d'avant (opus
~4000-8000, sonnet ~4300-4700, jamais 0 passe le premier appel "a froid" de
la session) : ``--system-prompt`` et le schema (``--json-schema``) sont deja
identiques d'un juge a l'autre d'un meme modele, et Claude Code les met en
cache pour son propre compte (bloc systeme, "hors controle" comme documente
plus haut) independamment de notre marqueur. Cout par appel jury pratiquement
inchange, pour zero 400 sur l'essai reel (25 appels/passage x 5 passages).

Effet de bord observe (sans lien avec notre marqueur, jamais corrige ici) :
que ``cache_prefix`` soit donne ou non, le tout premier essai HTTP de
*chaque* appel `claude -p --json-schema` echoue systematiquement avec un
400 "thread: a maximum of 3 blocks with cache_control may be provided when
`thread` is set" (un bloc reserve par le serveur pour un mecanisme de
"thread" interne au CLI, jamais expose par aucun flag documente) ; le CLI le
capte lui-meme (log ``[WARN] [tether] unsupported_request: resending this
turn stateless``) et renvoie seul, en stateless, sans que notre code le
voie -- ni un `--debug`, ni une erreur remontee a ``clipper.llm``. Rien a
corriger de notre cote : ce comportement est deja invisible pour l'appelant
quand il reussit, ce qui est le cas la quasi-totalite du temps.

Limite de blocs cache_control (TASK-746c, reclasse par TASK-f89f, MCP
supprime par TASK-321b, cause residuelle supprimee par TASK-b384, voir
ci-dessus). Historique MCP (TASK-321b) : sans ``--strict-mcp-config``,
``claude -p`` chargeait par defaut les serveurs MCP *globaux* de
l'utilisateur (``~/.claude.json``), connectes de facon asynchrone et dont
les blocs ``tools`` etaient mis en cache independamment par groupe de
serveur -- source d'un 400 par le passe, supprimee par ``--strict-mcp-config``
(0 serveur charge, verifie). Un 400 cache_control residuel reste un echec
explicite (LLMError), jamais transitoire (ADR-ad2e) : ``_is_transient`` ne
le reconnait pas au texte.

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
import logging
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from clipper.llm.backend import LLMRequest, Usage, image_b64, image_media_type
from clipper.llm.errors import LLMError, TransientLLMError

log = logging.getLogger(__name__)

# Taille (caracteres) de la fin de stdout/stderr gardee dans le diagnostic
# d'un blocage (TASK-db6f) : assez pour voir le dernier evenement, jamais le
# prompt entier (qui n'est de toute facon jamais dans cmd, lui passe par
# stdin).
_DIAGNOSTIC_TAIL_CHARS = 2000

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
    """Un statut connu (408/429/5xx) est toujours transitoire ; les autres
    statuts (ex. 400, y compris la limite de blocs cache_control -- voir la
    docstring du module, TASK-f89f) sont permanents sauf un texte reconnu
    comme transitoire malgre eux (quota, reseau, surcharge)."""
    if isinstance(status, int) and (status in _TRANSIENT_STATUS or status >= 500):
        return True
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


def _tail(text: str | None) -> str:
    """Fin de ``text`` (~2 Ko, _DIAGNOSTIC_TAIL_CHARS) : l'evenement le plus
    recent, pas le debut deja vu dans les logs precedents."""
    if not text:
        return ""
    return text[-_DIAGNOSTIC_TAIL_CHARS:]


def stdin_input(request: LLMRequest) -> str:
    """Contenu envoye sur stdin. Sans image : le prompt tel quel (texte brut,
    ``--output-format json``). Avec une ou des images : un unique message
    ``--input-format stream-json`` dont le contenu liste les blocs image
    (base64, comme clipper.llm.claude_api) puis le texte du prompt en un
    seul bloc. ``request.cache_prefix`` n'est jamais marque ici (voir la
    docstring du module, TASK-b384) : ce backend l'ignore."""
    if not request.images:
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
        if request.images:
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
            "--strict-mcp-config",
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
        stdin_text = stdin_input(request)
        timeout = request.timeout if request.timeout is not None else self.timeout
        start = time.monotonic()
        try:
            proc = subprocess.run(
                cmd,
                input=stdin_text,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=timeout,
            )
        except FileNotFoundError as exc:
            raise LLMError(f"commande {self.command!r} introuvable (Claude Code installe ?)") from exc
        except subprocess.TimeoutExpired as exc:
            self._log_timeout(request, cmd, stdin_text, timeout, time.monotonic() - start, exc)
            raise TransientLLMError(f"claude -p : pas de reponse en {timeout} s") from exc
        text, usage = parse_output(proc.stdout, proc.returncode, proc.stderr)
        self.last_usage = usage
        return text

    @staticmethod
    def _log_timeout(
        request: LLMRequest, cmd: list[str], stdin_text: str, timeout: float, duration: float,
        exc: subprocess.TimeoutExpired,
    ) -> None:
        """Diagnostic journalise (worker.log via le logger du module) quand
        ``claude -p`` ne repond pas dans le delai : la commande (jamais le
        prompt, qui part par stdin, pas par argv), la taille du prompt, la
        duree reelle, et la fin de ce que le sous-processus a deja ecrit sur
        stdout/stderr avant d'etre tue -- subprocess.run() les capture lui
        meme sur TimeoutExpired (communicate() apres kill) quand il les a
        captures via capture_output ; absents si rien n'a ete recu (lecture
        non bloquante, ADR-ad2e : aucune valeur inventee). Releve reel
        TASK-db6f : un 2e blocage sans cause connue (claude -p transcript_fix
        muet alors qu'un appel sonnet "ok" repond en 9 s)."""
        log.warning(
            "claude -p : pas de reponse en %.1f s (usage %s, commande %s, prompt %d caracteres) ; "
            "sortie recue avant arret -- stdout: %r, stderr: %r",
            duration, request.usage, cmd, len(stdin_text),
            _tail(exc.stdout), _tail(exc.stderr),
        )


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
