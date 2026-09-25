"""Backend ``claude-cli`` : Claude Code en mode non interactif.

Commande construite :

    claude -p --output-format json --model <modele> --tools <Read|"">
           [--allowedTools Read --add-dir <dossier image>...]
           --system-prompt <court> --setting-sources "" --no-session-persistence

Le prompt passe par stdin, pas par argv : une transcription de 2-3 h depasse
la limite de ligne de commande de Windows (32 767 caracteres).

Images. ``claude -p`` n'a aucune option pour joindre une image (verifie sur
Claude Code 2.1.282 : ni --image ni equivalent dans ``claude --help``). Deux
voies existent :
- ``--input-format stream-json`` avec un bloc image base64 sur stdin, mais
  cela impose ``--output-format stream-json`` ;
- donner a Claude le chemin du fichier et l'outil Read, qui lit les images
  (PNG, JPEG, GIF, WebP) et les lui presente visuellement.
On prend la seconde, compatible avec ``--output-format json`` : les chemins
absolus sont listes dans le prompt, ``--tools Read`` ne rend disponible que
cet outil, ``--allowedTools Read`` evite toute demande de permission (le mode
-p n'a personne pour y repondre) et ``--add-dir`` ouvre l'acces au dossier de
chaque image. Verifie en reel une fois : image rouge 32x32 -> reponse
{"couleur": "rouge"} en 2 tours (lecture puis reponse). Sans image, ``--tools
""`` retire tous les outils.

``--system-prompt`` remplace le prompt systeme de Claude Code (~170k tokens
de contexte mis en cache par appel sinon) et ``--setting-sources ""`` ignore
CLAUDE.md, hooks et reglages de l'utilisateur : le quota est partage avec ses
sessions Claude Code (ADR-b1c1).

Sortie (--output-format json) : un objet unique ``{"type": "result",
"subtype": "success", "is_error": bool, "api_error_status": int|null,
"result": "<texte de la reponse>", "num_turns", "session_id",
"total_cost_usd", ...}``. Une erreur API (quota, surcharge) arrive avec
``is_error: true``, le message dans ``result`` et le code HTTP dans
``api_error_status``, et un code de sortie non nul.
"""

from __future__ import annotations

import json
import re
import subprocess
from typing import Any

from clipper.llm.backend import LLMRequest
from clipper.llm.errors import LLMError, TransientLLMError

SYSTEM_PROMPT = (
    "Tu es un composant d'un pipeline automatique. Reponds uniquement avec "
    "le JSON demande, sans texte autour. Utilise l'outil Read seulement pour "
    "regarder les images dont le chemin est donne."
)

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


def image_prompt(request: LLMRequest) -> str:
    if not request.images:
        return request.prompt
    paths = "\n".join(f"- {p.resolve()}" for p in request.images)
    return (
        f"Images a regarder avec l'outil Read (dans cet ordre) :\n{paths}\n\n{request.prompt}"
    )


class ClaudeCLIBackend:
    def __init__(self, settings: dict[str, Any]):
        self.command = str(settings.get("command", "claude"))
        self.timeout = settings.get("timeout", 900)

    def build_command(self, request: LLMRequest) -> list[str]:
        cmd = [self.command, "-p", "--output-format", "json", "--model", request.model]
        if request.images:
            cmd += ["--tools", "Read", "--allowedTools", "Read"]
            dirs = dict.fromkeys(str(p.resolve().parent) for p in request.images)
            for d in dirs:
                cmd += ["--add-dir", d]
        else:
            cmd += ["--tools", ""]
        cmd += [
            "--system-prompt", SYSTEM_PROMPT,
            "--setting-sources", "",
            "--no-session-persistence",
        ]
        return cmd

    def complete(self, request: LLMRequest) -> str:
        cmd = self.build_command(request)
        try:
            proc = subprocess.run(
                cmd,
                input=image_prompt(request),
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=self.timeout,
            )
        except FileNotFoundError as exc:
            raise LLMError(f"commande {self.command!r} introuvable (Claude Code installe ?)") from exc
        except subprocess.TimeoutExpired as exc:
            raise TransientLLMError(f"claude -p : pas de reponse en {self.timeout} s") from exc
        return parse_output(proc.stdout, proc.returncode, proc.stderr)


def parse_output(stdout: str, returncode: int = 0, stderr: str = "") -> str:
    """Extract the answer text from ``claude -p --output-format json``."""
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        data = None
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
    if not isinstance(result, str):
        raise LLMError(f"claude -p : pas de champ 'result' texte dans {sorted(data)}")
    return result
