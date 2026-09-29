from __future__ import annotations

import base64
import mimetypes
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class LLMRequest:
    """One call, as a backend sees it. ``prompt`` already carries the
    instruction to answer with JSON matching ``schema``."""

    usage: str
    model: str
    prompt: str
    images: list[Path] = field(default_factory=list)
    schema: dict[str, Any] = field(default_factory=dict)


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
