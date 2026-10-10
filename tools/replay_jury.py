"""Rejeu hors ligne du jury sur des posts dont la part vue est connue.

    python tools/replay_jury.py <posts.csv> [--rubric builtin:gaming-v2]
        [--perspective prompts/jury/retention/v1.md] [--root .] [--out replay.json]

``posts.csv`` (par exemple research/perf-0910/posts.csv) : une ligne par post,
colonnes ``video_id``, ``clip_id`` et ``pct_watched``. Le texte de chaque clip
est lu dans son sidecar ``<root>/output/<video_id>/<clip_id>.json`` (champ
``transcript``) ; le jury (clipper.jury, vrais appels LLM hors des tests)
note tous les clips ensemble, puis l'outil ecrit le Spearman entre la note et
``pct_watched`` pour chaque juge (note a son dernier tour) et pour la note
finale du jury. Rien n'est active ni ecrit hors du fichier ``--out``.

``--perspective`` remplace la perspective du juge ``retention`` pour ce rejeu
seulement (config.toml ne change pas). Un clip sans ``pct_watched`` est
ecarte et liste dans ``skipped`` ; un sidecar absent ou sans texte est une
erreur (ADR-ad2e). Avec moins de 3 clips notes, le rho n'a pas de sens : erreur.
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from clipper import jury, moments  # noqa: E402
from clipper.config import Config, load_config  # noqa: E402
from clipper.jury_calibration import _spearman  # noqa: E402

MIN_CLIPS = 3


class ReplayError(Exception):
    """Entree du rejeu manquante ou inutilisable."""


def _read_posts(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise ReplayError(f"fichier de posts introuvable : {path}")
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        missing = {"video_id", "clip_id", "pct_watched"} - set(reader.fieldnames or [])
        if missing:
            raise ReplayError(f"{path} : colonne(s) manquante(s) : {', '.join(sorted(missing))}")
        return list(reader)


def _candidate(root: Path, row: dict[str, str]) -> dict[str, Any]:
    sidecar = root / "output" / row["video_id"] / f"{row['clip_id']}.json"
    if not sidecar.exists():
        raise ReplayError(f"sidecar introuvable : {sidecar}")
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    text = data.get("transcript")
    if not isinstance(text, str) or not text.strip():
        raise ReplayError(f"{sidecar} : champ transcript absent ou vide")
    return {
        "id": f"{row['video_id']}/{row['clip_id']}",
        "text": text,
        "context": f"[{data['start']:.0f}-{data['end']:.0f}] s",
    }


def _with_perspective(config: Config, perspective: Path) -> Config:
    if not perspective.exists():
        raise ReplayError(f"perspective introuvable : {perspective}")
    text = perspective.read_text(encoding="utf-8").strip()
    table = dict(config.section("jury"))
    judges = dict(table.get("judges") or {})
    judges["retention"] = {**judges.get("retention", {}), "perspective": text}
    sections = {**config._sections, "jury": {**table, "judges": judges}}
    return dataclasses.replace(config, _sections=sections)


def replay(
    posts_csv: str | Path,
    *,
    rubric: str = "builtin:gaming",
    perspective: str | Path | None = None,
    config: Config | None = None,
    root: str | Path = ".",
) -> dict[str, Any]:
    root = Path(root)
    config = config if config is not None else load_config()
    if perspective is not None:
        config = _with_perspective(config, Path(perspective))
    grid = moments.load_rubric(moments.resolve_rubric_path(rubric))

    rows, skipped = [], []
    for row in _read_posts(Path(posts_csv)):
        if not (row["pct_watched"] or "").strip():
            skipped.append({"video_id": row["video_id"], "clip_id": row["clip_id"], "reason": "pct_watched absent"})
            continue
        rows.append((row, float(row["pct_watched"])))
    if len(rows) < MIN_CLIPS:
        raise ReplayError(f"{len(rows)} clip(s) avec pct_watched : au moins {MIN_CLIPS} requis pour un Spearman")
    candidates = [_candidate(root, row) for row, _ in rows]
    pct = {c["id"]: p for c, (_, p) in zip(candidates, rows)}

    outcome = jury.deliberate(candidates, grid, context="", config=config)

    by_judge: dict[str, dict[str, float]] = {}
    final: dict[str, float] = {}
    for cand in outcome["candidates"]:
        final[cand["id"]] = cand["score"]
        for rnd in sorted(cand["trace"]["rounds"], key=lambda r: r["round"]):
            for name, entry in rnd["judges"].items():
                by_judge.setdefault(name, {})[cand["id"]] = float(entry["score"])

    def rho(scores: dict[str, float]) -> float | None:
        ids = [i for i in pct if i in scores]
        if len(ids) < MIN_CLIPS:
            return None
        return _spearman([scores[i] for i in ids], [pct[i] for i in ids])

    return {
        "rubric": rubric,
        "perspective": str(perspective) if perspective is not None else None,
        "n": len(rows),
        "skipped": skipped,
        "failed_judges": outcome["failed"],
        "spearman": {"judges": {name: rho(s) for name, s in by_judge.items()}, "final": rho(final)},
    }


def main(argv: Sequence[str] | None = None, *, config: Config | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rejoue le jury sur des posts dont la part vue est connue.")
    parser.add_argument("posts_csv")
    parser.add_argument("--rubric", default="builtin:gaming")
    parser.add_argument("--perspective", default=None)
    parser.add_argument("--root", default=".")
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    result = replay(
        args.posts_csv, rubric=args.rubric, perspective=args.perspective, config=config, root=args.root,
    )
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
