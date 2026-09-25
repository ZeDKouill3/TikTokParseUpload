"""Interface web locale de clipper (TASK-634e, ADR-09ad).

Page HTML/CSS/JS statique (clipper/web/static/), servie par un serveur
FastAPI local (voir ``python -m clipper serve``, clipper/__main__.py).
clipper.web n'appelle que clipper.pipeline (et clipper.feedback via
pipeline.decide) et lit workspace/ et output/ pour lister l'etat des videos,
les moments a valider et les clips produits ; aucune logique de traitement
video, audio ou LLM ici (ADR-09ad).

Routes (voir clipper/web/app.py pour le detail) :
- GET  /                                    page statique
- POST /api/videos                          soumet une URL, lance pipeline.run
- GET  /api/videos                          liste les videos (workspace/*/pipeline.json)
- GET  /api/videos/{video_id}               etat detaille (pipeline.load_state)
- GET  /api/videos/{video_id}/moments       moments a valider (score, justification)
- POST /api/videos/{video_id}/moments/{id}/decide   decision humaine (pipeline.decide)
- POST /api/videos/{video_id}/render        reprend jusqu'au bout (pipeline.render)
- GET  /api/videos/{video_id}/clips         clips produits (output/<video_id>/*.json)
- GET  /media/source/{video_id}             video source (apercu des moments)
- GET  /media/clip/{video_id}/{clip_id}     clip rendu
"""

from __future__ import annotations

from clipper.web.app import create_app

CONFIG_DEFAULTS: dict[str, object] = {
    # Port d'ecoute de 'python -m clipper serve' ; l'hote est toujours
    # 127.0.0.1, jamais configurable (interface locale, ADR-09ad).
    "port": 8000,
}

__all__ = ["create_app", "CONFIG_DEFAULTS"]
