/* Ecran « Tableau de bord » (SPEC-c100 E1). Lit GET /api/dashboard et se
   remet a jour sur chaque evenement SSE (clipper:event, emis par app.js) ;
   charge apres screens.js dont il remplace l'entree Screens.dashboard.
   Une donnee introuvable arrive du serveur en null avec une cle <champ>_error :
   elle est affichee telle quelle, jamais remplacee par un 0 muet. */
"use strict";

const DASH_STALE_MS = 4000; // repli polling : app.js re-rend toutes les 5 s sans evenement SSE
const dash = { loading: null, dirty: false, at: 0, error: null };

function loadDashboard() {
  if (dash.loading) { dash.dirty = true; return dash.loading; }
  dash.loading = (async () => {
    try {
      store.dashboard = await api("/api/dashboard");
      dash.error = null;
    } catch (err) {
      dash.error = err;
    } finally {
      dash.loading = null;
      dash.at = Date.now();
    }
    if (currentScreen === "dashboard") renderCurrent();
    if (dash.dirty) { dash.dirty = false; loadDashboard(); }
  })();
  return dash.loading;
}

// Un evenement (video, queue, publish, watch, worker) rend les donnees obsoletes.
document.addEventListener("clipper:event", () => {
  dash.at = 0;
  if (currentScreen === "dashboard") loadDashboard();
});

/* Battement du worker : seul le voyant est relu et remplace, le reste de l'ecran n'est pas touche. */
document.addEventListener("clipper:worker", async () => {
  if (currentScreen !== "dashboard" || !store.dashboard) return;
  try {
    const part = await api("/api/dashboard/worker");
    Object.assign(store.dashboard, part);
    const panel = $('[data-section="worker"] .panel', $("#screen-dashboard"));
    if (panel) panel.innerHTML = dashWorkerContent(store.dashboard);
  } catch (err) {
    // voyant inchange : la prochaine mise a jour complete (ou le prochain battement) le corrigera.
  }
});

const dashDate = (iso) => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? String(iso) : d.toLocaleString("fr-FR", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
};

const dashMoney = (usd) => `${fr(usd, 2)} $`;

/* Message d'erreur d'un champ (<champ>_error) ; chaine vide si la donnee est la. */
function dashError(error) {
  return error ? `<div class="list-item"><p class="reason bad">${esc(error)}</p></div>` : "";
}

function dashEmpty(text) {
  return `<div class="list-item muted">${esc(text)}</div>`;
}

function dashSection(key, iconName, title, content, more) {
  return `<section data-section="${key}">
    <div class="section-title">${icon(iconName)}${esc(title)}${more || ""}</div>
    <div class="panel">${content}</div></section>`;
}

/* Contenu d'une liste : erreur serveur, sinon etat vide, sinon les lignes. */
function dashList(data, field, emptyText, rowFn) {
  if (data[field] === null || data[field] === undefined) return dashError(data[`${field}_error`] || `${field} : donnée absente de la réponse.`);
  return data[field].length ? data[field].map(rowFn).join("") : dashEmpty(emptyText);
}

function dashRunningRow(video) {
  const progress = video.progress;
  const pct = progress ? Math.round(progress.fraction * 100) : null;
  const eta = progress && progress.eta_s != null ? ` · reste ${fr(Math.ceil(progress.eta_s / 60))} min` : "";
  return `<div class="job" data-video="${esc(video.video_id)}">
    ${videoThumb(video.video_id)}
    <div class="job-main" style="min-width:0">
      <div class="job-title">${esc(video.video_id)}</div>
      <div class="job-meta"><span class="mono">${esc(video.source_url || "")}</span>${video.channel ? `<span class="tag">${esc(video.channel)}</span>` : ""}</div>
      <div class="job-prog"><div class="job-step"><b>${esc(STEP_LABELS[video.step] || video.step || "—")}</b>${pct != null ? `<span>${pct} %${eta}</span>` : ""}${progress && progress.message ? `<span class="muted">${esc(progress.message)}</span>` : ""}</div>
        <div class="bar" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${pct == null ? 0 : pct}"><i style="width:${pct == null ? 8 : pct}%"></i></div></div>
    </div>
    <div class="job-side"><span class="chip running">en cours</span>
      <button type="button" class="btn btn-xs btn-ghost" data-cancel="${esc(video.video_id)}">Annuler le traitement</button></div>
  </div>`;
}

function dashProblemRow(video, kind) {
  const retry = video.retry_at ? `<div class="li-sub">Reprise prévue le ${esc(dashDate(video.retry_at))}</div>` : "";
  const id = esc(video.video_id);
  return `<div class="list-item dash-problem" data-video="${id}">
    <span class="chip ${kind === "failed" ? "failed" : "queued"}">${kind === "failed" ? "Échec" : "En attente"}</span>
    ${videoThumb(video.video_id)}
    <div class="li-main"><a class="li-title" href="#/videos/${encodeURIComponent(video.video_id)}" style="display:block">${esc(video.title || video.video_id)}</a>
      <div class="li-sub">${video.title && video.title !== video.video_id ? `<span class="mono">${id}</span> · ` : ""}${video.channel ? `${esc(video.channel)} · ` : ""}étape ${esc((STEP_LABELS[video.step] || video.step || "—").toLowerCase())}</div>
      <p class="reason ${kind === "failed" ? "bad" : ""}">${esc(video.reason || "Aucune raison journalisée.")}</p>${retry}</div>
    <div class="row wrap dash-problem-actions">
      <button type="button" class="btn btn-xs" data-retry-video="${id}" data-from-step="${esc(video.step || "")}">Relancer</button>
      <button type="button" class="btn btn-xs btn-ghost" data-dismiss-video="${id}">Retirer</button></div>
  </div>`;
}

function dashPublicationRow(entry) {
  return `<a class="list-item" href="#/publish" data-clip="${esc(entry.clip_id)}">
    <div class="when num">${esc(dashDate(entry.slot_at))}</div>
    <div class="li-main"><div class="li-title">${esc(entry.screen_title || entry.clip_id)}</div>
      <div class="li-sub">${esc(entry.channel)} · ${esc(entry.video_id)} · clip ${esc(entry.clip_id)}</div></div>
  </a>`;
}

function dashCostContent(data) {
  const cost = data.llm_cost;
  if (cost === null || cost === undefined) return dashError(data.llm_cost_error || "llm_cost : donnée absente de la réponse.");
  const usages = Object.entries(cost.by_usage || {});
  const unreported = cost.unreported_calls
    ? `<div class="list-item"><p class="reason">${esc(fr(cost.unreported_calls))} appel(s) sans coût rapporté par le modèle, non comptés ci-dessus.</p></div>` : "";
  if (!usages.length && !cost.unreported_calls) return dashEmpty("Aucun appel au modèle de langage sur les 7 derniers jours.");
  return `<div class="list-item"><div class="li-main"><div class="li-sub">Aujourd'hui</div><div class="kpi-value">${esc(dashMoney(cost.today))}</div></div>
      <div class="li-main"><div class="li-sub">7 derniers jours</div><div class="kpi-value">${esc(dashMoney(cost.week))}</div></div></div>
    ${usages.map(([name, usd]) => `<div class="list-item"><span class="li-main li-title">${esc(name)}</span><span class="num">${esc(dashMoney(usd))}</span></div>`).join("")}${unreported}`;
}

function dashHardwareContent(data) {
  const hw = data.hardware;
  if (hw === null || hw === undefined) return dashError(data.hardware_error || "hardware : donnée absente de la réponse.");
  const device = hw.device === "cpu" ? "CPU" : String(hw.device).toUpperCase();
  let vram = "";
  if (hw.vram_used_mb != null) vram = `<span class="num">${esc(fr(hw.vram_used_mb))} Mo de VRAM utilisés</span>`;
  else if (hw.vram_used_mb_error) vram = `<p class="reason bad">${esc(hw.vram_used_mb_error)}</p>`;
  return `<div class="list-item">${icon("cpu")}<div class="li-main"><div class="li-title">${esc(device)}</div></div>${vram}</div>`;
}

/* Valeur d'un KPI : « — » (et non 0) quand la donnee est introuvable. */
const dashKpi = (value, format) => (value === null || value === undefined ? "—" : format ? format(value) : fr(value));

/* Voyant du worker : « worker actif » quand le battement est récent ; sinon « worker arrêté »
   avec la raison et la commande pour le lancer (une vidéo mise en file attend sans lui). */
function dashWorkerContent(data) {
  const worker = data.worker;
  if (worker === null || worker === undefined) return dashError(data.worker_error || "worker : donnée absente de la réponse.");
  if (worker.state === "active") {
    return `<div class="list-item"><span class="chip done">worker actif</span><div class="li-main"><div class="li-sub">pid ${esc(worker.pid)} · dernier battement il y a ${esc(fr(Math.round(worker.age_s)))} s</div></div></div>`;
  }
  return `<div class="list-item"><span class="chip failed">worker arrêté</span><div class="li-main"><p class="reason bad">${esc(worker.reason)}</p>
      <div class="li-sub">Aucune vidéo mise en file ne démarre tant qu'il est arrêté. Lance-le :</div>
      <code class="set-cmd mono">${esc(worker.command)}</code></div></div>`;
}

function dashKpis(data) {
  const waiting = data.queue === null ? null : data.queue.filter((e) => e.status === "waiting").length;
  const blocked = data.failed === null || data.queued === null ? null : data.failed.length + data.queued.length;
  const cards = [
    ["accent", "#/videos", "loader", "En cours", dashKpi(data.running === null ? null : data.running.length), ""],
    ["", "#/videos", "list-filter", "En file", dashKpi(waiting), ""],
    ["warn", "#/videos", "circle-pause", "À débloquer", dashKpi(blocked), ""],
    ["", "#/clips", "clapperboard", "Clips à valider", dashKpi(data.clips_to_review), ""],
    ["", "#/stats", "coins", "LLM aujourd'hui", dashKpi(data.llm_cost ? data.llm_cost.today : null, dashMoney), ""],
  ];
  return `<div class="kpis">${cards.map(([cls, href, ic, label, value]) => `<a class="kpi ${cls}" href="${href}">
    <div class="kpi-label">${icon(ic)}${esc(label)}</div><div class="kpi-value">${esc(value)}</div></a>`).join("")}</div>`;
}

Screens.dashboard = {
  render(body, store) {
    const data = store.dashboard;
    if (Date.now() - dash.at > DASH_STALE_MS) loadDashboard();
    if (!data) {
      body.innerHTML = dash.error
        ? emptyState("circle-alert", "Chargement impossible", String(dash.error.message || dash.error))
        : `<div class="skeleton skeleton-line"></div><div class="skeleton skeleton-card"></div><div class="skeleton skeleton-card"></div>`;
      return;
    }
    const waiting = data.queue === null ? null : data.queue.filter((e) => e.status === "waiting");
    const queueContent = waiting === null
      ? dashError(data.queue_error)
      : waiting.length ? waiting.map(queueRow).join("") : dashEmpty("La file est vide.")
        + `<div class="list-item">${addVideoButton}</div>`;
    const clips = data.clips_to_review === null ? dashError(data.clips_to_review_error)
      : data.clips_to_review ? `<a class="list-item" href="#/clips"><span class="when num">${esc(fr(data.clips_to_review))}</span><div class="li-main"><div class="li-title">clip(s) rendu(s), prêt(s) à valider</div></div>${icon("chevron-right")}</a>`
        : dashEmpty("Aucun clip à valider.");
    body.innerHTML = `
      ${dash.error ? `<p class="reason bad">Actualisation impossible : ${esc(dash.error.message || dash.error)}</p>` : ""}
      ${dashKpis(data)}
      <div class="grid cols-dash dash-grid">
        <div class="stack">
          ${dashSection("running", "activity", "En cours", `<div class="jobs">${dashList(data, "running", "Aucune vidéo en cours de traitement.", dashRunningRow)}</div>`)}
          ${dashSection("failed", "triangle-alert", "Échecs", dashList(data, "failed", "Aucun échec : rien à relancer.", (v) => dashProblemRow(v, "failed")))}
          ${dashSection("queued", "hourglass", "En attente de reprise", dashList(data, "queued", "Aucune vidéo en attente de reprise.", (v) => dashProblemRow(v, "queued")))}
          ${dashSection("queue", "list-filter", "File d'attente", queueContent)}
          ${dashSection("watch_pending", "eye", "VOD à confirmer", dashList(data, "watch_pending", "Aucune VOD à confirmer.", watchVodRow))}
        </div>
        <div class="stack">
          ${dashSection("worker", "activity", "Worker", dashWorkerContent(data))}
          ${dashSection("clips_to_review", "clapperboard", "Clips à valider", clips)}
          ${dashSection("next_publications", "send", "Prochaines publications", dashList(data, "next_publications", "Aucune publication programmée.", dashPublicationRow))}
          ${dashSection("llm_cost", "coins", "Coût du modèle de langage", dashCostContent(data))}
          ${dashSection("hardware", "cpu", "Matériel", dashHardwareContent(data))}
        </div>
      </div>`;
    wireWatch(body);
  },
};
