"""Interface web locale de clipper (TASK-634e, ADR-09ad ; v2, ADR-4f6e).

Page HTML/CSS/JS statique (clipper/web/static/), servie par un serveur
FastAPI local (voir ``python -m clipper serve``, clipper/__main__.py).
clipper.web n'appelle que clipper.pipeline, clipper.config, clipper.channel,
clipper.worker, clipper.publish et clipper.watch, et lit workspace/, output/
et state/ ; aucune logique de traitement video, audio ou LLM ici (ADR-09ad),
et le traitement lui-meme tourne toujours dans le worker separe, jamais dans
ce processus (ADR-4f6e §1).

Routes (voir clipper/web/app.py pour le detail) :
- GET    /                                    page statique
- POST   /api/queue                           met en file (worker.enqueue)
- GET    /api/queue                           liste la file de traitement
- POST   /api/queue/{video_id}/front          passe l'entree en tete
- DELETE /api/queue/{video_id}                retire l'entree en attente
- POST   /api/videos                          alias de POST /api/queue sans chaine
- GET    /api/videos                          liste les videos (workspace/*/pipeline.json)
- GET    /api/videos/{video_id}               etat detaille (pipeline.load_state)
- GET    /api/videos/{video_id}/moments       moments a valider (score, justification)
- POST   /api/videos/{video_id}/moments/{id}/decide   decision humaine (pipeline.decide)
- POST   /api/videos/{video_id}/render        reprend jusqu'au bout (file, action render)
- POST   /api/videos/{video_id}/cancel        annule la video en cours (worker.cancel)
- POST   /api/videos/{video_id}/retry         relance depuis une etape (file, force_steps)
- GET    /api/videos/{video_id}/events        journal events.jsonl (parametre since)
- GET    /api/videos/{video_id}/clips         clips produits (output/<video_id>/*.json)
- GET    /api/channels                        liste les chaines (channel.list_channels)
- GET    /api/events                          flux SSE, un evenement par fichier change
- GET    /media/source/{video_id}             video source (apercu des moments)
- GET    /media/clip/{video_id}/{clip_id}     clip rendu
"""

from __future__ import annotations

from clipper.web.app import create_app

CONFIG_DEFAULTS: dict[str, object] = {
    # Hôte et port d'écoute de 'python -m clipper serve' (ADR-4f6e §5).
    "host": "127.0.0.1",
    "port": 8000,
    # Jeton exige sur /api/* et /media/* des que l'hôte n'est pas le bouclage ;
    # vide et bouclage = pas d'authentification.
    "token": "",
    # Intervalle (s) de scrutation des mtimes par /api/events (ADR-4f6e §4).
    "sse_poll_interval_s": 1.0,
}

__all__ = ["create_app", "CONFIG_DEFAULTS"]
