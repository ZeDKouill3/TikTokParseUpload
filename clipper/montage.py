"""Bibliotheque : planche d'images legendee (SPEC-b0f3 R8).

Pas une etape du pipeline : elle n'importe aucune etape et n'ecrit que la
planche demandee, dans le dossier que l'appelant lui donne. Utilisee par
``clipper.vision`` et ``clipper.action`` (ADR-b16b : une etape n'importe
jamais une autre etape).

Une planche assemble plusieurs images fixes en une seule : grille
horizontale, chaque image reduite a ``max_width`` (jamais agrandie) et
legendee « Image <index> : <timecode> s ». Les images d'origine ne sont
jamais modifiees.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2
import numpy as np


class MontageError(RuntimeError):
    """Image illisible ou planche impossible a ecrire ; le message nomme le fichier."""


# Hauteur de la bande de legende (index, timecode) au-dessus de chaque image
# de la planche ; fait partie du format de sortie, pas un detail interne.
LABEL_HEIGHT = 28
_LABEL_FONT = cv2.FONT_HERSHEY_SIMPLEX
_LABEL_SCALE = 0.6
_LABEL_COLOR = (255, 255, 255)


def _labeled_cell(image: np.ndarray, index: int, timecode: float, target_h: int) -> np.ndarray:
    h, w = image.shape[:2]
    if h < target_h:
        image = np.vstack([image, np.zeros((target_h - h, w, 3), dtype=image.dtype)])
    label = np.zeros((LABEL_HEIGHT, w, 3), dtype=np.uint8)
    cv2.putText(
        label, f"Image {index} : {timecode:.1f} s", (4, LABEL_HEIGHT - 8),
        _LABEL_FONT, _LABEL_SCALE, _LABEL_COLOR, 1, cv2.LINE_AA,
    )
    return np.vstack([label, image])


def montage(batch: list[dict[str, Any]], video_dir: Path, dest_dir: Path, max_width: int, index: int) -> Path:
    """Assemble ``batch`` (deja trie par timecode ; chaque element porte
    ``path`` relatif a ``video_dir`` et ``timecode``) en une planche unique
    ``dest_dir/<index:05d>_montage.jpg`` et renvoie son chemin."""
    images = []
    for f in batch:
        path = video_dir / f["path"]
        image = cv2.imread(str(path))
        if image is None:
            raise MontageError(f"image illisible : {path}")
        h, w = image.shape[:2]
        if w > max_width:
            image = cv2.resize(image, (max_width, max(1, round(h * max_width / w))))
        images.append(image)
    target_h = max(image.shape[0] for image in images)
    cells = [
        _labeled_cell(image, n, f["timecode"], target_h)
        for n, (image, f) in enumerate(zip(images, batch))
    ]
    board = np.hstack(cells)
    dest = dest_dir / f"{index:05d}_montage.jpg"
    if not cv2.imwrite(str(dest), board):
        raise MontageError(f"ecriture impossible : {dest}")
    return dest
