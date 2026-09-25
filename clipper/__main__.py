from __future__ import annotations

import argparse
import json
import logging
import sys

from clipper.config import ConfigError, load_config


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


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(asctime)s %(levelname)s %(message)s")

    from clipper import pipeline

    try:
        config = load_config(args.config)
        if args.command == "run":
            state = pipeline.run(args.url, config=config, force=args.force)
        elif args.command == "render":
            state = pipeline.render(args.video_id, config=config, force=args.force)
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
    except (pipeline.PipelineError, ConfigError) as exc:
        print(f"erreur : {exc}", file=sys.stderr)
        return 1

    _report(state)
    return _exit_code(state)


if __name__ == "__main__":
    sys.exit(main())
