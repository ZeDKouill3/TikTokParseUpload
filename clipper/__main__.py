from __future__ import annotations

import argparse
import json
import logging
import sys
import threading
from datetime import datetime

from clipper.config import ConfigError, load_config

_PROGRESS_POLL_SECONDS = 0.1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="clipper",
        description="Pipeline de clips verticaux sous-titres a partir de videos YouTube longues",
    )
    parser.add_argument("--config", default="config.toml", help="Fichier de configuration (defaut : config.toml)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Journal detaille des etapes")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("run", help="Traite une video : jusqu'a la revue (review) ou jusqu'au bout (auto)")
    p.add_argument("url", help="URL YouTube de la video")
    p.add_argument("--force", action="store_true", help="Relance les etapes deja faites")

    p = sub.add_parser("render", help="Reprend une video apres la revue (ou apres un echec) jusqu'au bout")
    p.add_argument("video_id")
    p.add_argument("--force", action="store_true", help="Relance les etapes deja faites")

    p = sub.add_parser("decide", help="Enregistre la decision humaine sur un moment (mode review)")
    p.add_argument("video_id")
    p.add_argument("moment_id", type=int)
    p.add_argument("decision", choices=("accepted", "rejected", "adjusted"))
    p.add_argument("--start", type=float, help="Nouveau debut (s), decision adjusted")
    p.add_argument("--end", type=float, help="Nouvelle fin (s), decision adjusted")
    p.add_argument("--comment", help="Commentaire libre, journalise avec la decision")

    p = sub.add_parser("status", help="Affiche l'etat d'une video (JSON)")
    p.add_argument("video_id")

    p = sub.add_parser("queue", help="Reprend les videos en file d'attente dont l'heure est venue")
    p.add_argument("--watch", action="store_true", help="Tourne en boucle")
    p.add_argument("--interval", type=float, default=60.0, help="Secondes entre deux passages (--watch)")

    p = sub.add_parser("serve", help="Lance l'interface web locale (FastAPI sur 127.0.0.1)")
    p.add_argument("--port", type=int, default=None, help="Port d'ecoute (defaut : [web] port de config.toml)")
    return parser


def _exit_code(state: dict) -> int:
    from clipper import pipeline

    if state["status"] in ("done", "awaiting_review"):
        return 0
    if state["status"] == "queued":
        return pipeline.EXIT_QUEUED
    return 1


def _report(state: dict) -> None:
    line = f"{state.get('video_id', '?')} : {state['status']}"
    if state.get("reason"):
        line += f" ({state['reason']})"
    if state["status"] == "awaiting_review":
        line += f" ; moments a decider : {state.get('awaiting')}"
    if state["status"] == "queued":
        line += f" ; re-essai a {state.get('retry_at')}"
    for clip in state.get("clips") or []:
        line += f"\n  {clip['clip_id']} : {'pret' if clip['ready'] else 'non pret'} (qa {clip['qa_status']})"
    print(line)


def _step_elapsed(step: dict) -> float:
    started, finished = step.get("started_at"), step.get("finished_at")
    if not started or not finished:
        return 0.0
    return (datetime.fromisoformat(finished) - datetime.fromisoformat(started)).total_seconds()


def _announce_step(name: str, step: dict, seen_running: set, reported_done: set,
                   stale_snapshot: dict) -> None:
    baseline_step = stale_snapshot.get(name)
    if baseline_step is not None:
        if step == baseline_step:
            return  # etat identique a celui d'avant l'appel : pas encore reparti
        del stale_snapshot[name]  # a bouge depuis l'appel : traite normalement desormais

    status = step["status"]
    if status == "running":
        if name not in seen_running:
            seen_running.add(name)
            print(f"[{name}] démarrée")
    elif status in ("done", "failed") and name not in reported_done:
        if name not in seen_running:
            seen_running.add(name)
            print(f"[{name}] démarrée")
        reported_done.add(name)
        if status == "done":
            print(f"[{name}] terminée en {_step_elapsed(step):.1f} s")
        else:
            print(f"[{name}] échec : {step.get('reason')}")


def _baseline_progress(video_id: str, config, force: bool) -> tuple[set, set, dict]:
    """Etapes deja terminees avant cet appel (deja faites, cache) : elles ne
    refont pas de travail visible cette fois-ci et ne doivent pas etre
    annoncees. --force les relance toutes, donc rien n'est mis de cote.

    Une etape en echec n'est PAS mise de cote : elle repart pour de vrai et
    doit etre reannoncee ('demarree' puis 'terminee'/'echec'). Mais tant que
    son etat sur disque n'a pas encore bouge depuis cet instant (une lecture
    peut survenir juste avant que la relance ne la touche), son ancien statut
    'failed' ne doit pas etre pris pour une nouvelle annonce : stale_snapshot
    retient l'etat de depart de chaque etape non 'done' pour le detecter."""
    from clipper import pipeline

    if force:
        return set(), set(), {}
    try:
        state = pipeline.load_state(video_id, config=config)
    except pipeline.PipelineError:
        return set(), set(), {}
    seen_running: set = set()
    reported_done: set = set()
    stale_snapshot: dict = {}
    for name in pipeline.STEPS:
        step = state["steps"][name]
        if step["status"] == "done":
            seen_running.add(name)
            reported_done.add(name)
        else:
            stale_snapshot[name] = dict(step)
    return seen_running, reported_done, stale_snapshot


def _watch_progress(video_id: str, config, stop_event: threading.Event,
                    seen_running: set, reported_done: set, stale_snapshot: dict) -> None:
    from clipper import pipeline

    while not stop_event.is_set():
        try:
            state = pipeline.load_state(video_id, config=config)
        except pipeline.PipelineError:
            stop_event.wait(_PROGRESS_POLL_SECONDS)
            continue
        for name in pipeline.STEPS:
            _announce_step(name, state["steps"][name], seen_running, reported_done, stale_snapshot)
        stop_event.wait(_PROGRESS_POLL_SECONDS)


def _run_with_progress(action, video_id: str, config, force: bool) -> dict:
    """Execute ``action`` (pipeline.run ou pipeline.render) en affichant la
    progression au fil de l'eau, lue depuis l'etat expose par
    clipper.pipeline (pipeline.json), sans toucher aux etapes ni a
    pipeline.py."""
    from clipper import pipeline

    seen_running, reported_done, stale_snapshot = _baseline_progress(video_id, config, force)
    stop_event = threading.Event()
    watcher = threading.Thread(
        target=_watch_progress,
        args=(video_id, config, stop_event, seen_running, reported_done, stale_snapshot),
        daemon=True,
    )
    watcher.start()
    try:
        state = action()
    finally:
        stop_event.set()
        watcher.join(timeout=2.0)
    for name in pipeline.STEPS:
        step = state.get("steps", {}).get(name)
        if step is not None:
            _announce_step(name, step, seen_running, reported_done, stale_snapshot)
    return state


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(asctime)s %(levelname)s %(message)s")

    from clipper import download, pipeline

    try:
        config = load_config(args.config)
        if args.command == "run":
            video_id = download.extract_video_id(args.url)
            state = _run_with_progress(
                lambda: pipeline.run(args.url, config=config, force=args.force),
                video_id, config, args.force,
            )
        elif args.command == "render":
            state = _run_with_progress(
                lambda: pipeline.render(args.video_id, config=config, force=args.force),
                args.video_id, config, args.force,
            )
        elif args.command == "decide":
            pipeline.decide(args.video_id, args.moment_id, args.decision, start=args.start, end=args.end,
                            comment=args.comment, config=config)
            print(f"{args.video_id} : moment {args.moment_id} {args.decision}")
            return 0
        elif args.command == "status":
            print(json.dumps(pipeline.load_state(args.video_id, config=config), ensure_ascii=False, indent=2))
            return 0
        elif args.command == "serve":
            import uvicorn

            from clipper.web import create_app

            port = args.port if args.port is not None else config.section("web")["port"]
            uvicorn.run(create_app(config=config), host="127.0.0.1", port=int(port))
            return 0
        else:
            if args.watch:
                pipeline.watch_queue(config=config, interval=args.interval)
                return 0
            states = pipeline.process_queue(config=config)
            for state in states:
                _report(state)
            return max((_exit_code(s) for s in states), default=0)
    except (pipeline.PipelineError, ConfigError, download.DownloadError) as exc:
        print(f"erreur : {exc}", file=sys.stderr)
        return 1

    _report(state)
    return _exit_code(state)


if __name__ == "__main__":
    sys.exit(main())
