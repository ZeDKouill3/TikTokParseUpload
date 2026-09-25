from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

CONFIG_DEFAULTS: dict[str, object] = {
    "journal_path": "state/feedback.jsonl",
}

VALID_DECISIONS = ("accepted", "rejected", "adjusted")
POSITIVE_DECISIONS = ("accepted", "adjusted")
NEGATIVE_DECISIONS = ("rejected",)


class FeedbackError(Exception):
    """Invalid decision passed to record()."""


def _journal_path(path: str | Path | None) -> Path:
    if path is None:
        return Path(CONFIG_DEFAULTS["journal_path"])
    return Path(path)


def record(
    video_id: str,
    moment: dict,
    decision: str,
    texte_moment: str,
    commentaire: str | None = None,
    path: str | Path | None = None,
) -> dict:
    """Journalise une decision humaine sur un moment (voir ADR-ad2e)."""
    if decision not in VALID_DECISIONS:
        raise FeedbackError(
            f"decision invalide: {decision!r} (attendu: {' | '.join(VALID_DECISIONS)})"
        )

    entry = {
        "video_id": video_id,
        "moment": moment,
        "texte_moment": texte_moment,
        "decision": decision,
        "commentaire": commentaire,
        "horodatage": datetime.now(timezone.utc).isoformat(),
    }

    journal = _journal_path(path)
    journal.parent.mkdir(parents=True, exist_ok=True)
    with journal.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return entry


def _read_all(path: str | Path | None) -> list[dict]:
    journal = _journal_path(path)
    if not journal.exists():
        return []
    with journal.open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def examples(k: int, path: str | Path | None = None) -> list[dict]:
    """Les k decisions les plus recentes, equilibrees positif/negatif,
    pretes a injecter dans un prompt (voir SPEC-53f3 regle 6)."""
    entries = _read_all(path)
    indexed = list(enumerate(entries))

    positives = [pair for pair in indexed if pair[1]["decision"] in POSITIVE_DECISIONS]
    negatives = [pair for pair in indexed if pair[1]["decision"] in NEGATIVE_DECISIONS]
    positives.reverse()
    negatives.reverse()

    half = k // 2
    n_pos = min(half, len(positives))
    n_neg = min(k - half, len(negatives))

    remaining = k - n_pos - n_neg
    if remaining > 0 and len(positives) > n_pos:
        extra = min(remaining, len(positives) - n_pos)
        n_pos += extra
        remaining -= extra
    if remaining > 0 and len(negatives) > n_neg:
        extra = min(remaining, len(negatives) - n_neg)
        n_neg += extra

    selected = positives[:n_pos] + negatives[:n_neg]
    selected.sort(key=lambda pair: pair[0], reverse=True)
    return [entry for _, entry in selected]
