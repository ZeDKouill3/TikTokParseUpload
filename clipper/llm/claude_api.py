"""Backend ``claude-api`` : API Messages via le SDK ``anthropic``.

Cle lue par le SDK (ANTHROPIC_API_KEY). Les images partent en blocs base64
avant le texte. Les alias opus/sonnet/haiku acceptes par ``claude -p`` sont
traduits en identifiants complets, un nom complet passe tel quel.
"""

from __future__ import annotations

from typing import Any

from clipper.llm.backend import LLMRequest, image_b64, image_media_type
from clipper.llm.errors import LLMError, TransientLLMError

MODEL_ALIASES = {
    "fable": "claude-fable-5-1",
    "opus": "claude-opus-5-5",
    "sonnet": "claude-sonnet-5",
    "haiku": "claude-haiku-4-5-20251001",
}

_TRANSIENT_STATUS = {408, 409, 429}


def make_client(settings: dict[str, Any]) -> Any:
    import anthropic

    # Pas de re-essai dans le SDK : l'attente sur quota est decidee plus haut
    # (ADR-ad2e), une erreur transitoire remonte telle quelle.
    return anthropic.Anthropic(max_retries=0, timeout=settings.get("timeout", 900))


class ClaudeAPIBackend:
    def __init__(self, settings: dict[str, Any]):
        self.settings = settings
        self.max_tokens = int(settings.get("max_tokens", 8192))

    def complete(self, request: LLMRequest) -> str:
        import anthropic

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
        client = make_client(self.settings)
        try:
            message = client.messages.create(
                model=MODEL_ALIASES.get(request.model, request.model),
                max_tokens=self.max_tokens,
                messages=[{"role": "user", "content": content}],
            )
        except anthropic.APIConnectionError as exc:  # includes timeouts
            raise TransientLLMError(f"claude-api : reseau : {exc}") from exc
        except anthropic.APIStatusError as exc:
            message_text = f"claude-api {exc.status_code} : {exc}"
            if exc.status_code in _TRANSIENT_STATUS or exc.status_code >= 500:
                raise TransientLLMError(message_text) from exc
            raise LLMError(message_text) from exc
        except anthropic.AnthropicError as exc:
            raise LLMError(f"claude-api : {exc}") from exc

        text = "".join(b.text for b in message.content if getattr(b, "type", None) == "text")
        if getattr(message, "stop_reason", None) == "max_tokens":
            raise LLMError(f"claude-api : reponse tronquee a max_tokens={self.max_tokens}")
        return text
