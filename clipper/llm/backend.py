from __future__ import annotations

import base64
import mimetypes
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class LLMRequest:
    """One call, as a backend sees it. ``prompt`` already carries the
    instruction to answer with JSON matching ``schema``.

    ``cache_prefix``, when given, is a prefix of ``prompt`` shared byte for
    byte with other calls (e.g. clipper.jury's same-model judges): a backend
    that supports Anthropic-style prompt caching should send it as its own
    content block carrying ``cache_control``, since the cache matches whole
    blocks, not an arbitrary prefix inside one block of text (TASK-2cbb) ; a
    backend that does not support this can ignore the field.

    ``timeout``, when given, overrides this one call's timeout (seconds) in
    place of the backend's own configured default ([llm.<backend>] timeout) :
    other calls, including other usages sharing the same backend, are
    unaffected (TASK-db6f)."""

    usage: str
    model: str
    prompt: str
    images: list[Path] = field(default_factory=list)
    schema: dict[str, Any] = field(default_factory=dict)
    cache_prefix: str | None = None
    timeout: float | None = None


@dataclass(frozen=True)
class Usage:
    """Telemetry for one backend.complete() call. A field the backend does
    not report stays None (ADR-ad2e: no invented value)."""

    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    cost_usd: float | None = None


class Backend(Protocol):
    def complete(self, request: LLMRequest) -> str:
        """Return the model's raw text answer, or raise LLMError /
        TransientLLMError. A backend that can report telemetry sets
        ``self.last_usage`` (a Usage) for the call it just completed; a
        backend without one is read as Usage() (every field None)."""


def image_b64(path: Path) -> str:
    return base64.b64encode(Path(path).read_bytes()).decode("ascii")


def image_media_type(path: Path) -> str:
    media_type, _ = mimetypes.guess_type(str(path))
    return media_type or "image/jpeg"
