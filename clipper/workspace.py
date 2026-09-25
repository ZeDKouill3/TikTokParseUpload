from __future__ import annotations

import json
from pathlib import Path


class Workspace:
    """Per-video working directory: workspace/<video_id>/<step>/result.json.

    Presence of a step's result is what "done" means: crash recovery and
    anti-duplicate work come from checking the filesystem, not from a
    separate ledger (see ADR-b16b).
    """

    def __init__(self, video_id: str, root: str | Path = "workspace"):
        self.video_id = video_id
        self.root = Path(root)
        self.dir = self.root / video_id

    def step_output(self, step: str) -> Path:
        return self.dir / step / "result.json"

    def is_done(self, step: str) -> bool:
        return self.step_output(step).exists()

    def mark_done(self, step: str, data: dict | None = None) -> Path:
        path = self.step_output(step)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data if data is not None else {}))
        return path

    def should_run(self, step: str, force: bool = False) -> bool:
        return force or not self.is_done(step)
