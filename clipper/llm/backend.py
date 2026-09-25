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


class Backend(Protocol):
    def complete(self, request: LLMRequest) -> str:
        """Return the model's raw text answer, or raise LLMError /
        TransientLLMError."""


def image_b64(path: Path) -> str:
    return base64.b64encode(Path(path).read_bytes()).decode("ascii")


def image_media_type(path: Path) -> str:
    media_type, _ = mimetypes.guess_type(str(path))
    return media_type or "image/jpeg"
