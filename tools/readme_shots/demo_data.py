"""Espace de démonstration pour les captures du README (TASK-dbb2).

``build_demo(root)`` écrit sous ``root`` (un dossier temporaire, jamais le vrai
``workspace/`` ni ``state/``) : ``config.toml``, ``presets/``, ``workspace/``,
``output/`` et ``state/`` factices, 100 % inventés : une chaîne « ma_chaine »,
un compte « mon_compte », des titres neutres. Les vignettes sont des images de
synthèse (Pillow) encodées en courtes vidéos par ffmpeg : aucune vraie vidéo.

Seul ``build_demo`` écrit ; chaque chemin d'écriture passe par ``_inside`` qui
refuse tout ce qui sort de ``root``.
"""

from __future__ import annotations

import contextlib
import json
import os
import random
import shutil
import sqlite3
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

CONFIG_DEFAULTS: dict[str, object] = {
    "channel": "ma_chaine",
    "account": "mon_compte",
    "account_label": "Compte de démonstration",
    "source_seconds": 2700,        # durée de la vidéo source de synthèse (la vignette est prise à 1/3)
    "clip_seconds": 6,             # durée des clips de synthèse
    "source_size": (640, 360),
    "clip_size": (360, 640),
    "stats_days": 62,              # profondeur de l'historique de statistiques factice
}

PASSWORD_PLACEHOLDER = "demo-factice-pas-un-secret"  # injecté dans le coffre mémoire du lanceur seulement

STEPS = ("download", "transcribe", "scenes", "audio", "moments", "vision", "parts", "captions",
         "reframe", "subtitles", "render", "qa")

CRITERIA = {"hook": 3, "standalone": 3, "payoff": 2, "emotion": 2, "value": 2, "trend": 0}
JUDGES = ("retention", "monteur", "avocat", "spectateur", "conformite")

# Titres de vidéos et de clips : inventés, neutres.
VIDEOS = (
    ("demo0001", "Soirée jeu coopératif : manche finale", "done"),
    ("demo0002", "Atelier cuisine : trois recettes en direct", "awaiting_review"),
    ("demo0003", "Partie classée : la remontée", "running"),
)
CLIPS = (  # (clip_id, titre d'écran, légende, hashtags)
    ("01", "Le retournement final", "Personne ne l'avait vu venir.", ["#jeu", "#coop"]),
    ("02-p1", "Le piège (partie 1)", "Tout se joue en dix secondes.", ["#jeu", "#astuce"]),
    ("02-p2", "Le piège (partie 2)", "La suite est encore meilleure.", ["#jeu", "#astuce"]),
    ("03", "Un fou rire inattendu", "Impossible de rester sérieux.", ["#fourire", "#live"]),
    ("04", "L'astuce qui change tout", "Teste-la à ta prochaine partie.", ["#astuce", "#jeu"]),
    ("05", "Le dernier round", "Jusqu'au bout du suspense.", ["#suspense", "#jeu"]),
    ("06", "Le duel des deux équipes", "Deux styles, un seul gagnant.", ["#coop", "#jeu"]),
)


class DemoError(Exception):
    """Dossier de démonstration refusé, ffmpeg absent ou en échec."""


def _inside(root: Path, path: Path) -> Path:
    """``path`` si elle est sous ``root`` ; sinon une erreur explicite (le script ne touche qu'au dossier temporaire)."""
    resolved = path.resolve()
    if resolved != root.resolve() and root.resolve() not in resolved.parents:
        raise DemoError(f"écriture refusée hors du dossier de démonstration : {path}")
    return path


def _write_json(root: Path, path: Path, data: Any) -> None:
    _inside(root, path).parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------- images et vidéos de synthèse

_PALETTES = (
    ((31, 64, 104), (232, 106, 51)), ((44, 82, 70), (245, 197, 66)), ((82, 45, 104), (96, 190, 214)),
    ((104, 45, 60), (238, 150, 120)), ((30, 70, 110), (140, 210, 150)), ((60, 60, 90), (220, 120, 180)),
)


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1 : police bitmap fixe, taille ignorée
        return ImageFont.load_default()


def synthetic_frame(size: tuple[int, int], seed: int, label: str, *, vertical_ui: bool = False) -> Image.Image:
    """Image de synthèse : dégradé, formes abstraites, étiquette neutre ; ``vertical_ui`` ajoute le bandeau de titre
    et la zone de sous-titres d'un clip (maquette, sans texte réel)."""
    rng = random.Random(seed)
    width, height = size
    top, bottom = _PALETTES[seed % len(_PALETTES)]
    image = Image.new("RGB", size)
    draw = ImageDraw.Draw(image)
    for y in range(height):
        t = y / max(height - 1, 1)
        draw.line([(0, y), (width, y)], fill=tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    for _ in range(7):
        radius = rng.randint(width // 12, width // 4)
        cx, cy = rng.randint(0, width), rng.randint(0, height)
        shade = tuple(min(255, int(c * rng.uniform(0.5, 1.3))) for c in bottom)
        draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=shade)
    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    odraw.rectangle([0, 0, width, height], fill=(0, 0, 0, 70))
    if vertical_ui:
        odraw.rounded_rectangle([width * 0.1, height * 0.1, width * 0.9, height * 0.1 + height * 0.1],
                                radius=14, fill=(255, 255, 255, 235))
        odraw.rounded_rectangle([width * 0.12, height * 0.8, width * 0.88, height * 0.86], radius=10, fill=(0, 0, 0, 150))
    image = Image.alpha_composite(image.convert("RGBA"), overlay)
    draw = ImageDraw.Draw(image)
    font = _font(max(12, width // 12))
    box = draw.textbbox((0, 0), label, font=font)
    draw.text(((width - (box[2] - box[0])) / 2, height * (0.13 if vertical_ui else 0.42)), label,
              font=font, fill=(20, 20, 20, 255) if vertical_ui else (255, 255, 255, 255))
    return image.convert("RGB")


def _ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    if path is None:
        raise DemoError("ffmpeg introuvable dans le PATH : il génère les vignettes de synthèse (installe-le puis relance)")
    return path


def encode_still(image_path: Path, target: Path, seconds: int, *, fps: int) -> None:
    """Encode une image fixe en mp4 H.264 de ``seconds`` secondes (vidéo de synthèse, quelques Ko)."""
    command = [_ffmpeg(), "-y", "-loglevel", "error", "-loop", "1", "-framerate", str(fps), "-i", str(image_path),
               "-t", str(seconds), "-c:v", "libx264", "-tune", "stillimage", "-preset", "veryfast", "-crf", "32",
               "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(target)]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise DemoError(f"ffmpeg a échoué pour {target.name} : {result.stderr.strip()[-300:]}")


# ---------------------------------------------------------------- pipeline.json, moments, jury

def _steps(now: datetime, done: int, running_progress: dict[str, Any] | None = None, *, started: datetime) -> dict[str, Any]:
    steps: dict[str, Any] = {}
    cursor = started
    for index, name in enumerate(STEPS):
        if index < done:
            length = timedelta(seconds=20 + 37 * index % 140)
            steps[name] = {"status": "done", "reason": None, "started_at": _iso(cursor),
                           "finished_at": _iso(cursor + length), "progress": None}
            cursor += length
        elif index == done and running_progress is not None:
            steps[name] = {"status": "running", "reason": None, "started_at": _iso(cursor), "finished_at": None,
                           "progress": running_progress}
        else:
            steps[name] = {"status": "pending", "reason": None, "started_at": None, "finished_at": None, "progress": None}
    return steps


# Chaque juge a sa sensibilité : les courbes du radar ne se superposent pas.
JUDGE_BIAS = {
    "retention": {"hook": 1.4, "payoff": -1.2, "value": -0.6},
    "monteur": {"standalone": 1.3, "emotion": -1.3, "trend": 0.8},
    "avocat": {"hook": -1.9, "value": 1.2, "payoff": -1.4, "standalone": -0.8},
    "spectateur": {"emotion": 1.5, "value": -1.4, "hook": 0.5},
    "conformite": {"trend": -2.2, "standalone": 0.7, "emotion": -0.6},
}


def _judge(rng: random.Random, name: str, base: dict[str, float], spread: float, bias: float = 1.0) -> dict[str, Any]:
    scores = {k: round(max(1.0, min(10.0, v + JUDGE_BIAS[name].get(k, 0.0) * bias + rng.uniform(-spread, spread))), 1)
              for k, v in base.items()}
    weighted = sum(scores[k] * w for k, w in CRITERIA.items()) / sum(CRITERIA.values()) * 10
    return {"scores": scores, "score": round(weighted, 1), "argument": "Évaluation de démonstration.",
            "confidence": rng.randint(55, 95)}


def _jury(rng: random.Random, base: dict[str, float], *, debate: bool, veto: str | None = None) -> dict[str, Any]:
    round_one = {name: _judge(rng, name, base, 0.7) for name in JUDGES}
    rounds = [{"round": 1, "judges": round_one}]
    if debate:
        rounds.append({"round": 2, "judges": {name: _judge(rng, name, base, 0.4, 0.4) for name in ("avocat", "spectateur")}})
    last = {**round_one, **(rounds[-1]["judges"] if debate else {})}
    score = round(sum(j["score"] for j in last.values()) / len(last), 1)
    return {"score": score, "confidence": round(sum(j["confidence"] for j in last.values()) / len(last)),
            "veto": veto, "debated": debate, "proposer": {"scores": base},
            "trace": {"rounds": rounds, "revisions": [], "dissent": []}}


def _moments_json(video_id: str, count: int, rejected: int, seed: int) -> dict[str, Any]:
    rng = random.Random(seed)
    kept, dropped = [], []
    for index in range(count + rejected):
        strong = index < count
        base = {k: round(rng.uniform(6.8, 9.2) if strong else rng.uniform(3.0, 5.6), 1) for k in CRITERIA}
        jury = _jury(rng, base, debate=index % 2 == 0)
        final = round(jury["score"] + rng.uniform(0, 4), 1) if strong else round(min(jury["score"], 54.0), 1)
        start = 120.0 + index * 310.0
        moment = {"id": index, "start": start, "end": start + 24 + index * 6, "duration": 24.0 + index * 6,
                  "format": "single", "parts": [], "scores": base, "bonus": {"total": 1.0}, "final_score": final,
                  "justification": "Moment de démonstration : accroche nette et fin sur une chute.",
                  "hook_text": f"Phrase d'accroche d'exemple n°{index + 1}.", "jury": jury}
        if strong:
            kept.append(moment)
        else:
            dropped.append({**moment, "reason": f"score {final} < min_score 60"})
    return {"video_id": video_id, "selection": "jury", "exploration": None,
            "rubric": {"path": "rubric.toml", "weights": CRITERIA, "min_score": 60},
            "jury": {"judges": [{"name": n, "usage": f"jury_{n}", "model": "demo", "veto": n == "conformite"} for n in JUDGES]},
            "moments": kept, "rejected": dropped}


def _parts_json(video_id: str, moments: list[dict[str, Any]]) -> dict[str, Any]:
    out = []
    for moment in moments:
        out.append({"id": moment["id"], "start": moment["start"], "end": moment["end"], "duration": moment["duration"],
                    "format": "single", "parts_total": 1, "proposed_cuts": [],
                    "parts": [{"part": 1, "start": moment["start"], "end": moment["end"], "duration": moment["duration"],
                               "hook_text": moment["hook_text"], "suspense": None}]})
    return {"video_id": video_id, "moments": out, "rejected": []}


def _events(path: Path, root: Path, now: datetime, lines: list[tuple[str, str, str]]) -> None:
    _inside(root, path).parent.mkdir(parents=True, exist_ok=True)
    start = now - timedelta(minutes=len(lines))
    rows = [{"at": _iso(start + timedelta(minutes=i)), "level": level, "step": step, "message": message}
            for i, (level, step, message) in enumerate(lines)]
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- construction

def build_demo(root: Path, *, now: datetime | None = None, settings: dict[str, object] | None = None) -> dict[str, Any]:
    """Écrit l'espace de démonstration sous ``root`` (doit exister et être vide ou neuf). Rend ``{"posts": [...]}``,
    les identifiants utiles au script de capture."""
    cfg = {**CONFIG_DEFAULTS, **(settings or {})}
    root = Path(root)
    now = now or datetime.now(timezone.utc)
    channel, account = str(cfg["channel"]), str(cfg["account"])
    work = _inside(root, root / "workspace")
    out = _inside(root, root / "output")
    state = _inside(root, root / "state")

    (root / "config.toml").write_text('mode = "review"\n', encoding="utf-8")
    _write_json(root, state / "accounts.json", {"accounts": [{
        "id": account, "label": cfg["account_label"], "platform": "TikTok", "username": account,
        "notes": "Compte fictif pour les captures.", "has_password": True,
        "created_at": _iso(now - timedelta(days=40)), "updated_at": _iso(now - timedelta(days=2)),
        "ready_to_publish": True, "ready_note": None, "r4_halt": None,
        "login": {"state": "connected", "checked_at": _iso(now - timedelta(hours=3)),
                  "expires_at": _iso(now + timedelta(days=60))}}]})
    _fake_profile(root, state / "browser" / account, now)
    presets = _inside(root, root / "presets")
    presets.mkdir()
    (presets / f"{channel}.toml").write_text(
        f'[channel]\ndisplay_name = "{channel}"\ntimezone = "Europe/Paris"\ntiktok_account = "{account}"\n'
        'slots = [{ day = "mon", time = "18:00" }, { day = "wed", time = "18:00" }, { day = "fri", time = "12:30" }, '
        '{ day = "sun", time = "10:00" }]\n', encoding="utf-8")

    scratch = _inside(root, root / "_synthese")
    scratch.mkdir()
    source_w, source_h = cfg["source_size"]
    clip_w, clip_h = cfg["clip_size"]

    # -- vidéos
    for number, (video_id, title, status) in enumerate(VIDEOS):
        folder = work / video_id
        folder.mkdir(parents=True)
        frame = scratch / f"{video_id}.png"
        synthetic_frame((source_w, source_h), number + 1, f"Démo {number + 1}").save(frame)
        encode_still(frame, folder / f"{video_id}.mp4", int(cfg["source_seconds"]), fps=1)
        _write_json(root, folder / "meta.json", {"title": title, "duration": float(cfg["source_seconds"]),
                                                  "uploader": channel, "thumbnail": f"/media/source/{video_id}/thumbnail"})
        started = now - timedelta(days=3 - number, minutes=40)
        base_state = {"video_id": video_id, "source_url": f"https://exemple.invalid/video/{video_id}", "channel": channel,
                      "mode": "review", "status": status, "reason": None, "attempts": 1, "retry_at": None, "awaiting": [],
                      "enqueued_at": _iso(started), "updated_at": _iso(now), "clips": []}
        if status == "done":
            moments = _moments_json(video_id, 6, 2, seed=11)
            _write_json(root, folder / "moments.json", moments)
            _write_json(root, folder / "parts.json", _parts_json(video_id, moments["moments"]))
            base_state["steps"] = _steps(now, 12, started=started)
            _events(folder / "events.jsonl", root, now, [
                ("info", "download", "téléchargement terminé"), ("info", "moments", "jury : 6 moments retenus, 2 écartés"),
                ("info", "render", "6 clips rendus"), ("info", "qa", "contrôle qualité : 5 acceptés, 1 refusé")])
        elif status == "awaiting_review":
            moments = _moments_json(video_id, 4, 1, seed=23)
            _write_json(root, folder / "moments.json", moments)
            _write_json(root, folder / "parts.json", _parts_json(video_id, moments["moments"]))
            base_state["steps"] = _steps(now, 7, started=started)
            base_state["awaiting"] = [m["id"] for m in moments["moments"]]
            _events(folder / "events.jsonl", root, now, [("info", "moments", "4 moments proposés : en attente de revue")])
        else:
            base_state["steps"] = _steps(now, 1, {"fraction": 0.42, "eta_s": 540.0, "message": "42 % de l'audio transcrit"},
                                         started=now - timedelta(minutes=25))
            _events(folder / "events.jsonl", root, now, [("info", "download", "téléchargement terminé"),
                                                         ("info", "transcribe", "transcription démarrée")])
        _write_json(root, folder / "pipeline.json", base_state)

    # -- clips de la première vidéo
    video_id = VIDEOS[0][0]
    clips_dir = out / video_id
    clips_dir.mkdir(parents=True)
    state_clips = []
    for index, (clip_id, screen_title, caption, hashtags) in enumerate(CLIPS):
        frame = scratch / f"clip-{clip_id}.png"
        synthetic_frame((clip_w, clip_h), index + 2, f"Clip {clip_id}", vertical_ui=True).save(frame)
        encode_still(frame, clips_dir / f"{clip_id}.mp4", int(cfg["clip_seconds"]), fps=4)
        part = int(clip_id.split("-p")[1]) if "-p" in clip_id else None
        qa_status = "rejected" if clip_id == "05" else "passed"
        sidecar = {
            "video_id": video_id, "source_url": f"https://exemple.invalid/video/{video_id}", "source_title": VIDEOS[0][1],
            "clip_id": clip_id, "moment_id": min(index, 5), "part": part, "parts_total": 2 if part else 1,
            "start": 120.0 + index * 310.0, "end": 150.0 + index * 310.0, "duration": 30.0, "language": "fr",
            "score": round(88 - index * 3.2, 1), "scores": {k: 8 for k in CRITERIA}, "reason": "Moment de démonstration.",
            "hook_text": f"Phrase d'accroche d'exemple n°{index + 1}.", "title": screen_title, "screen_title": screen_title,
            "caption": caption, "hashtags": hashtags, "transcript": "Transcription de démonstration.", "layout": "single",
            "ready": qa_status == "passed", "format": "letterbox",
            "qa": {"status": qa_status, "issues": ["sous-titres hors zone sûre (démo)"] if qa_status == "rejected" else []},
            "created_at": _iso(now - timedelta(days=2, minutes=index))}
        state_clips.append({"clip_id": clip_id, "ready": sidecar["ready"], "qa_status": qa_status})
        _write_json(root, clips_dir / f"{clip_id}.json", sidecar)
    first = json.loads((work / video_id / "pipeline.json").read_text(encoding="utf-8"))
    first["clips"] = state_clips
    _write_json(root, work / video_id / "pipeline.json", first)

    with _working_in(root):  # clipper.channel lit state/accounts.json relativement au dossier courant
        posts = _publication_state(root, state, clips_dir, video_id, channel, account, now)
    _write_stats(root, state, account, posts, now, int(cfg["stats_days"]))
    shutil.rmtree(scratch)
    return {"posts": posts, "video_id": video_id, "channel": channel, "account": account}


def _fake_profile(root: Path, profile: Path, now: datetime) -> None:
    """Profil Chrome factice : une base de cookies où seul le nom d'un cookie de session TikTok existe (aucune valeur),
    pour que l'écran Comptes lise « connecté » sans lancer de navigateur."""
    from clipper import browser

    cookies = _inside(root, profile / "Default" / "Network" / "Cookies")
    cookies.parent.mkdir(parents=True)
    expires_utc = int((now + timedelta(days=60)).timestamp() + 11_644_473_600) * 1_000_000
    db = sqlite3.connect(cookies)
    try:
        db.execute("CREATE TABLE cookies (host_key TEXT, name TEXT, expires_utc INTEGER, is_persistent INTEGER)")
        db.execute("INSERT INTO cookies VALUES (?, ?, ?, 1)", (str(browser.CONFIG_DEFAULTS["login_domains"][0]),
                                                                str(browser.CONFIG_DEFAULTS["login_cookies"][0]), expires_utc))
        db.commit()
    finally:
        db.close()


@contextlib.contextmanager
def _working_in(folder: Path):
    previous = Path.cwd()
    os.chdir(folder)
    try:
        yield
    finally:
        os.chdir(previous)


def _publication_state(root: Path, state: Path, clips_dir: Path, video_id: str, channel: str, account: str,
                       now: datetime) -> list[dict[str, Any]]:
    """Publications de démonstration : une publiée (liée aux statistiques), deux programmées sur des créneaux de la
    chaîne, une en échec (arrêt sur captcha), une approuvée sans créneau ; le dernier clip reste « à valider »."""
    from clipper import publish as publish_mod

    kwargs = {"output_dir": root / "output", "state_dir": state / "publish", "presets_dir": root / "presets",
              "base": root / "config.toml"}
    entries = []
    post_id = "7300000000000000001"
    published_at = now - timedelta(days=2)
    entries.append({"video_id": video_id, "clip_id": "01", "series_id": None, "part": None, "status": "published",
                    "slot_at": _iso(published_at), "decided_at": _iso(published_at - timedelta(hours=2)),
                    "published_at": _iso(published_at), "error": None, "account": account, "post_id": post_id,
                    "post_url": f"https://exemple.invalid/@{account}/video/{post_id}", "tiktok_state": "published",
                    "publish_mode": "immediate"})
    sidecar_path = clips_dir / "01.json"
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    sidecar["tiktok_post"] = {"account": account, "id": post_id, "url": entries[0]["post_url"]}
    _write_json(root, sidecar_path, sidecar)
    entries.append({"video_id": video_id, "clip_id": "04", "series_id": None, "part": None, "status": "failed",
                    "slot_at": _iso(now - timedelta(hours=20)), "decided_at": _iso(now - timedelta(days=1)),
                    "published_at": None, "account": account, "publish_mode": "immediate",
                    "error": "captcha détecté sur TikTok Studio : arrêt immédiat, rien n'a été publié"})
    _write_json(root, state / "publish" / f"{channel}.json", entries)
    for clip_id in ("02-p1", "02-p2", "03"):
        publish_mod.approve(video_id, clip_id, channel, now=now, account=account, **kwargs)
    return [{"post_id": post_id, "clip_id": "01"}]


def _write_stats(root: Path, state: Path, account: str, posts: list[dict[str, Any]], now: datetime, days: int) -> None:
    """Historique de relevés TikTok Studio factice : un relevé complet par jour sur ``days`` jours, croissant, et la liste
    de quatre publications (une liée au clip publié)."""
    rng = random.Random(7)
    folder = state / "stats" / "tiktok" / account
    video_rows = [
        (posts[0]["post_id"], "Le retournement final #jeu #coop", 2, 18400, 1260, 96, 214, 17.4, 0.31),
        ("7300000000000000002", "Recette d'exemple en 30 secondes #cuisine", 9, 9100, 640, 41, 88, 13.1, 0.24),
        ("7300000000000000003", "Astuce rapide pour la semaine #astuce", 16, 5200, 330, 22, 51, 9.8, 0.19),
        ("7300000000000000004", "Rendez-vous du dimanche #live", 24, 2300, 140, 9, 18, 7.2, 0.14),
    ]
    for offset in range(days, -1, -1):
        stamp = now - timedelta(days=offset)
        growth = (days - offset + 8) / (days + 8)
        overview = {}
        for period in (7, 28, 60):
            base = {"views": 21000, "profile_views": 2600, "likes": 1500, "comments": 120, "shares": 260}
            overview[str(period)] = {
                key: {"value": int(value * growth * period / 28 * rng.uniform(0.93, 1.07)), "change_pct": round(rng.uniform(-6, 24), 1)}
                for key, value in base.items()}
        posts_rows = []
        for post_id, caption, age, views, likes, comments, shares, avg_watch, full in video_rows:
            if age < offset:
                continue
            reached = ((age - offset + 1) / (age + 1)) ** 0.5
            posted = now - timedelta(days=age)
            row = {"post_id": post_id, "post_url": f"https://exemple.invalid/@{account}/video/{post_id}", "caption": caption,
                   "posted_at": posted.replace(microsecond=0, tzinfo=None).isoformat(), "posted_at_text": None,
                   "visibility": "public", "views": int(views * reached), "likes": int(likes * reached),
                   "comments": int(comments * reached), "shares": int(shares * reached),
                   "avg_watch_s": avg_watch, "watched_full": full}
            if offset == 0:
                row.update(_post_detail(rng, views, shares))
            posts_rows.append(row)
        snapshot = {"account": account, "fetched_at": _iso(stamp.replace(hour=9, minute=0, second=0)), "source": "tiktok_studio",
                    "origin": "full", "overview": overview, "posts": posts_rows}
        name = stamp.astimezone(timezone.utc).strftime("%Y%m%dT090000000000Z") + ".json"
        _write_json(root, folder / name, snapshot)


def _post_detail(rng: random.Random, views: int, shares: int) -> dict[str, Any]:
    curve = [{"t_s": float(t), "share": round(max(0.12, 1.0 - 0.09 * t - rng.uniform(0, 0.03)), 2)} for t in range(0, 31, 3)]
    pct = lambda label, value: {"label": label, "value": value}  # noqa: E731
    return {
        "retention_curve": curve, "traffic_sources": "Pour toi 78 % · Abonnés 12 % · Profil 6 % · Autres 4 %",
        "viewers": {"total": int(views * 0.62),
                    "types": [pct("Nouveaux spectateurs", 0.71), pct("Spectateurs connus", 0.29)],
                    "age": [pct("18-24", 0.34), pct("25-34", 0.41), pct("35-44", 0.17), pct("45+", 0.08)],
                    "gender": [pct("Homme", 0.58), pct("Femme", 0.39), pct("Autre", 0.03)],
                    "locations": [pct("France", 0.72), pct("Belgique", 0.09), pct("Canada", 0.06), pct("Suisse", 0.04)]},
        "engagement": {"shares": shares,
                       "likes_over_time": [pct("Jour 1", 0.46), pct("Jour 2", 0.27), pct("Jour 3", 0.15), pct("Jour 4 et après", 0.12)],
                       "comment_words": [pct("bravo", 31), pct("incroyable", 24), pct("astuce", 17), pct("suite", 12)]},
        "retention": None,
    }
