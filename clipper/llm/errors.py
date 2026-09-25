from __future__ import annotations


class LLMError(Exception):
    """An LLM call failed for good: bad config, bad request, missing binary.
    Retrying the same call will not help."""


class TransientLLMError(LLMError):
    """Quota, rate limit, overload, network or timeout: the same call may
    succeed later. Callers wait and retry (ADR-ad2e: in auto mode the video
    goes back to the queue, never a silent fallback)."""


class SchemaError(LLMError):
    """The model answered, but not with JSON matching the requested schema
    (ADR-b1c1: an invalid response is a failure, not data)."""
