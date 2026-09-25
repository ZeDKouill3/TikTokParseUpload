from __future__ import annotations

from collections.abc import Callable
from typing import Any

from clipper.workspace import Workspace

STEPS: dict[str, Callable[..., Any]] = {}


def step(name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Register a pipeline step function under ``name``.

    Steps never call clipper.web or each other directly (ADR-b16b): they are
    only ever reached through this registry.
    """

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        STEPS[name] = fn
        return fn

    return decorator


def run_step(workspace: Workspace, name: str, *args: Any, force: bool = False, **kwargs: Any) -> Any:
    """Run the step registered as ``name`` unless its result already exists
    in the workspace, in which case it is skipped (ADR-b16b), unless
    ``force`` is set."""
    if not workspace.should_run(name, force=force):
        return workspace.step_output(name)
    return STEPS[name](*args, **kwargs)
