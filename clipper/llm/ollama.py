"""Backend ``ollama`` : API HTTP locale (POST /api/chat, stream false).

``keep_alive: 0`` decharge le modele de la VRAM des la reponse rendue
(ADR-fb9b : un seul modele lourd en VRAM a la fois, 4 Go sur la RTX 3050).
Le schema JSON est passe dans ``format`` (sortie structuree d'ollama) et les
images en base64 dans ``messages[].images``.
"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from typing import Any

from clipper.llm.backend import LLMRequest, image_b64
from clipper.llm.errors import LLMError, TransientLLMError


class OllamaBackend:
    def __init__(self, settings: dict[str, Any]):
        self.url = str(settings.get("url", "http://127.0.0.1:11434")).rstrip("/")
        self.timeout = settings.get("timeout", 900)

    def payload(self, request: LLMRequest) -> dict[str, Any]:
        message: dict[str, Any] = {"role": "user", "content": request.prompt}
        if request.images:
            message["images"] = [image_b64(p) for p in request.images]
        return {
            "model": request.model,
            "messages": [message],
            "stream": False,
            "format": request.schema,
            "keep_alive": 0,
        }

    def complete(self, request: LLMRequest) -> str:
        body = json.dumps(self.payload(request)).encode("utf-8")
        http_request = urllib.request.Request(
            f"{self.url}/api/chat",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(http_request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:500]
            message = f"ollama {exc.code} : {detail}"
            if exc.code in (408, 429) or exc.code >= 500:
                raise TransientLLMError(message) from exc
            raise LLMError(message) from exc
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as exc:
            raise TransientLLMError(f"ollama injoignable sur {self.url} : {exc}") from exc

        content = (data.get("message") or {}).get("content")
        if not isinstance(content, str):
            raise LLMError(f"ollama : reponse sans message.content : {str(data)[:300]}")
        return content
