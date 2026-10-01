/* Ecrans de la console. Chaque ecran est un module { render(body, store, actions) }
   branche sur sa section HTML (#screen-<id>) ; la coquille (app.js) fournit
   le magasin de donnees (store) et les actions. Seuls le tableau de bord et la
   liste des videos lisent l'API pour l'instant, les autres ecrans arrivent
   dans les taches suivantes. */
"use strict";

const STEP_LABELS = {
  download: "Téléchargement", transcribe: "Transcription", scenes: "Plans",
  audio: "Audio", moments: "Moments", vision: "Images", parts: "Découpage",
  captions: "Légendes", reframe: "Recadrage", subtitles: "Sous-titres",
  render: "Rendu", qa: "Contrôle qualité",
};
const STATUS_LABELS = {
  pending: "en attente", running: "en cours", done: "terminée",
  awaiting_review: "à valider", queued: "en file", failed: "échec",
};
const STATUS_CHIP = {
  pending: "pending", running: "running", done: "done",
  awaiting_review: "review", queued: "queued", failed: "failed",
};

const statusChip = (status) => `<span class="chip ${STATUS_CHIP[status] || "pending"}">${esc(STATUS_LABELS[status] || status)}</span>`;

function emptyState(iconName, title, text, actionHtml) {
  return `<div class="empty"><div class="empty-art">${icon(iconName)}</div><h3>${esc(title)}</h3><p>${esc(text)}</p>${actionHtml || ""}</div>`;
}

/* Etape courante d'une video : celle qui tourne, sinon la premiere non terminee. */
function currentStep(video) {
  const steps = Object.entries(video.steps || {});
  const running = steps.find(([, s]) => s.status === "running");
  const found = running || steps.find(([, s]) => s.status !== "done");
  return found ? { name: found[0], step: found[1] } : null;
}

function stepsDone(video) {
  return Object.values(video.steps || {}).filter((s) => s.status === "done").length;
}

function videoRow(video) {
  const cur = currentStep(video);
  const progress = cur && cur.step.progress ? cur.step.progress : null;
  const pct = progress ? Math.round(progress.fraction * 100) : null;
  const eta = progress && progress.eta_s != null ? ` · reste ${esc(fr(Math.ceil(progress.eta_s / 60)))} min` : "";
  const reason = video.reason ? `<div class="job-meta"><span>${esc(video.reason)}</span></div>` : "";
  const stepLine = video.status === "running" && cur
    ? `<div class="job-prog"><div class="job-step"><b>${esc(STEP_LABELS[cur.name] || cur.name)}</b>${pct != null ? `<span>${pct} %${eta}</span>` : ""}</div>
         <div class="bar" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${pct == null ? 0 : pct}"><i style="width:${pct == null ? 8 : pct}%"></i></div></div>`
    : `<div class="job-meta"><span>${stepsDone(video)} / 12 étapes</span></div>`;
  return `<div class="job" data-video="${esc(video.video_id)}">
    <div class="job-main" style="min-width:0">
      <div class="job-title">${esc(video.video_id)}</div>
      <div class="job-meta"><span class="mono">${esc(video.source_url || "")}</span>${video.channel ? `<span class="tag">${esc(video.channel)}</span>` : ""}</div>
      ${stepLine}${reason}
    </div>
    <div class="job-side">${statusChip(video.status)}
      ${video.status === "running" ? `<button type="button" class="btn btn-xs btn-ghost" data-cancel="${esc(video.video_id)}">Annuler le traitement</button>` : ""}
    </div>
  </div>`;
}

function queueRow(entry, index) {
  return `<div class="list-item" data-queue="${esc(entry.video_id)}">
    <span class="when num">${index + 1}</span>
    <div class="li-main grow"><div class="li-title">${esc(entry.video_id)}</div>
      <div class="li-sub muted">${esc(entry.action === "render" ? "rendu" : "traitement complet")}${entry.channel ? ` · ${esc(entry.channel)}` : ""}</div></div>
    ${index > 0 ? `<button type="button" class="btn btn-xs" data-front="${esc(entry.video_id)}">Passer en tête</button>` : ""}
    <button type="button" class="btn btn-xs btn-bad" data-remove="${esc(entry.video_id)}">Retirer</button>
  </div>`;
}

const addVideoButton = `<button type="button" class="btn btn-primary" data-add>${icon("plus")}Ajouter une vidéo</button>`;

const Screens = {
  dashboard: {
    render(body, store) {
      const videos = store.videos || [];
      const running = videos.filter((v) => v.status === "running");
      const attention = videos.filter((v) => v.status === "failed" || v.status === "queued" || v.status === "awaiting_review");
      const queue = (store.queue || []).filter((e) => e.status === "waiting");
      if (!videos.length && !queue.length) {
        body.innerHTML = emptyState("film", "Rien en cours", "Ajoute une vidéo pour lancer un premier traitement.", addVideoButton);
        return;
      }
      body.innerHTML = `
        <div class="panel-head"><h2>En cours</h2><div class="right"><span class="chip running plain">${running.length}</span></div></div>
        <div class="jobs">${running.length ? running.map(videoRow).join("") : `<div class="list-item muted">Aucune vidéo en cours de traitement.</div>`}</div>
        <div class="panel-head"><h2>File d'attente</h2><div class="right"><span class="chip queued plain">${queue.length}</span></div></div>
        <div>${queue.length ? queue.map(queueRow).join("") : `<div class="list-item muted">La file est vide.</div>`}</div>
        <div class="panel-head"><h2>À traiter</h2><div class="right"><span class="chip warn plain">${attention.length}</span></div></div>
        <div class="jobs">${attention.length ? attention.map(videoRow).join("") : `<div class="list-item muted">Rien ne demande ton attention.</div>`}</div>`;
    },
  },

  videos: {
    render(body, store) {
      const videos = store.videos || [];
      if (!videos.length) {
        body.innerHTML = emptyState("film", "Aucune vidéo", "Ajoute une vidéo pour commencer.", addVideoButton);
        return;
      }
      body.innerHTML = `<div class="jobs">${videos.map(videoRow).join("")}</div>`;
    },
  },

  review: soon("sparkles", "Aucun moment à valider", "Ajoute une vidéo : ses moments à valider apparaîtront ici."),
  clips: soon("clapperboard", "Aucun clip", "Ajoute une vidéo : les clips rendus apparaîtront ici."),
  publish: soon("send", "Rien à publier", "Approuve des clips : ils apparaîtront ici avec leurs créneaux."),
  channels: soon("tv", "Aucune chaîne", "Crée une chaîne, par exemple « ma_chaine », pour lui donner son agencement et ses créneaux.", (store) => {
    const names = store.channels || [];
    return names.length ? names.map((n) => `<div class="list-item"><span class="tag">${esc(n)}</span></div>`).join("") : null;
  }),
  stats: soon("chart-column", "Pas encore de statistiques", "Les résultats des clips et les coûts s'affichent ici dès qu'il y a des données."),
  settings: soon("settings", "Réglages", "L'édition de la configuration arrive dans une prochaine étape."),
};

/* Ecran d'attente : message vide utile ; peut etre surchargé par une liste
   de donnees deja disponibles (ex. noms de chaines). */
function soon(iconName, title, text, listFn) {
  return {
    render(body, store) {
      const list = listFn ? listFn(store) : null;
      body.innerHTML = list || emptyState(iconName, title, text);
    },
  };
}
