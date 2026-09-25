from __future__ import annotations

import argparse
import sys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="clipper",
        description="Pipeline de clips verticaux sous-titres a partir de videos YouTube longues",
    )
    parser.add_argument("video_id", nargs="?", help="Identifiant de la video a traiter")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Relance les etapes deja faites pour cette video",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    build_parser().parse_args(argv)
    return 0


if __name__ == "__main__":
    sys.exit(main())
