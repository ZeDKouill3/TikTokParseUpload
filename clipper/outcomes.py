"""Journal des resultats par clip : verite terrain du jury (ADR-1cf0 point 1).

Bibliotheque, pas une etape : n'importe aucune etape (ADR-b16b). Chaque
resultat journalise est relie a la trace du jury par ``video_id``,
``clip_id`` et ``moment_id`` (voir clipper.jury et SPEC-350f) :

    from clipper import outcomes
    outcomes.record(
        video_id="abc123", clip_id="03", moment_id=3,
        qa={"status": "passed", "issues": []},
        human_decision="approved",  # facultatif
    )

Journal append-only en JSON Lines sous state/ (defaut state/outcomes.jsonl,
reglage ``journal_path``) : une ligne par resultat connu, jamais reecrite.

Les statistiques de plateforme (rejouees le clip une fois publie) arrivent
plus tard, importees d'un fichier CSV en attendant l'upload direct :

    outcomes.import_stats("stats.csv")

Colonnes documentees du CSV : ``clip_id``, ``views`` (vues), ``retention_3s``
(retention a 3 s, fraction 0-1), ``watched_full`` (part ayant regarde en
entier, fraction 0-1), ``shares`` (partages), ``date`` (date de la mesure).
Le CSV ne porte pas ``video_id``/``moment_id`` : ces champs valent None sur
les entrees de statistiques.

``read()`` relit le journal, filtre par periode sur ``recorded_at`` si
``since``/``until`` sont fournis (date "AAAA-MM-JJ" ou horodatage ISO 8601).

Aucun appel reseau ici : l'upload vers la plateforme est fait ailleurs, ce
module ne fait qu'importer un CSV deja telecharge.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CONFIG_DEFAULTS: dict[str, object] = {
    "journal_path": "state/outcomes.jsonl",
}

STATS_COLUMNS = ("clip_id", "views", "retention_3s", "watched_full", "shares", "date")


class OutcomesError(Exception):
    """CSV de statistiques malforme (colonne documentee manquante)."""


def _journal_path(path: str | Path | None) -> Path:
    if path is None:
        return Path(CONFIG_DEFAULTS["journal_path"])
    return Path(path)


def _append(entry: dict[str, Any], path: str | Path | None) -> dict[str, Any]:
    journal = _journal_path(path)
    journal.parent.mkdir(parents=True, exist_ok=True)
    with journal.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def record(
    video_id: str,
    clip_id: str,
    moment_id: Any,
    *,
    qa: dict[str, Any] | None = None,
    human_decision: Any = None,
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Journalise un resultat connu pour un clip : verdict et defauts qa
    (voir clipper.qa), decision humaine facultative. Relie a la trace du
    jury par video_id/clip_id/moment_id (voir clipper.jury)."""
    entry = {
        "kind": "result",
        "video_id": video_id,
        "clip_id": clip_id,
        "moment_id": moment_id,
        "qa": qa,
        "human_decision": human_decision,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    return _append(entry, path)


def import_stats(csv_path: str | Path, *, path: str | Path | None = None) -> list[dict[str, Any]]:
    """Importe des statistiques de plateforme depuis un CSV (colonnes
    STATS_COLUMNS), en attendant l'upload direct ; une entree par ligne,
    journalisee au meme titre que ``record``."""
    csv_path = Path(csv_path)
    entries: list[dict[str, Any]] = []
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        missing = set(STATS_COLUMNS) - set(reader.fieldnames or [])
        if missing:
            raise OutcomesError(
                f"colonne(s) manquante(s) dans {csv_path} : {', '.join(sorted(missing))}"
            )
        for row in reader:
            entry = {
                "kind": "stats",
                "video_id": None,
                "clip_id": row["clip_id"],
                "moment_id": None,
                "stats": {
                    "views": int(row["views"]),
                    "retention_3s": float(row["retention_3s"]),
                    "watched_full": float(row["watched_full"]),
                    "shares": int(row["shares"]),
                    "date": row["date"],
                },
                "recorded_at": datetime.now(timezone.utc).isoformat(),
            }
            entries.append(_append(entry, path))
    return entries


def _read_all(path: str | Path | None) -> list[dict[str, Any]]:
    journal = _journal_path(path)
    if not journal.exists():
        return []
    with journal.open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _bound(value: str | datetime, *, end_of_day: bool) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(value)
        if end_of_day and len(value) == 10:  # date seule "AAAA-MM-JJ"
            dt = dt.replace(hour=23, minute=59, second=59, microsecond=999999)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def read(
    path: str | Path | None = None,
    *,
    since: str | datetime | None = None,
    until: str | datetime | None = None,
) -> list[dict[str, Any]]:
    """Lit le journal des resultats, filtre par periode sur ``recorded_at``
    quand ``since``/``until`` sont fournis."""
    entries = _read_all(path)
    if since is not None:
        lower = _bound(since, end_of_day=False)
        entries = [e for e in entries if _bound(e["recorded_at"], end_of_day=False) >= lower]
    if until is not None:
        upper = _bound(until, end_of_day=True)
        entries = [e for e in entries if _bound(e["recorded_at"], end_of_day=False) <= upper]
    return entries
