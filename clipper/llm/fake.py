"""Fake backend for the tests of the other pipeline steps (ADR-b1c1: no
test ever calls the real Claude).

    from clipper import llm
    from clipper.llm.fake import FakeBackend

    fake = FakeBackend([{"moments": [...]}])
    with llm.use_backend(fake):
        run_the_step()
    assert fake.calls[0].usage == "moments"

Each scripted response is consumed in order and may be:
- a dict/list: returned as JSON text, then validated like a real answer;
- a str: returned as is (the raw text a model would produce);
- an Exception instance: raised (e.g. TransientLLMError("quota"));
- a callable taking the LLMRequest: called, its result handled as above.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from clipper.llm.backend import LLMRequest


class FakeBackend:
    def __init__(self, responses: Iterable[Any] = ()):
        self.responses = list(responses)
        self.calls: list[LLMRequest] = []

    def complete(self, request: LLMRequest) -> str:
        self.calls.append(request)
        assert self.responses, f"FakeBackend : plus de reponse scriptee pour {request.usage!r}"
        response = self.responses.pop(0)
        if callable(response) and not isinstance(response, type):
            response = response(request)
        if isinstance(response, BaseException):
            raise response
        if isinstance(response, str):
            return response
        return json.dumps(response)
