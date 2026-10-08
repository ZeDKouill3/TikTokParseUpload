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
  return Number.isNaN(d.getTime()) ? String(iso) : fmtParis(iso, { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
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
    ${videoThumb(video.video_id, video.platform_thumbnail)}
    <div class="job-main" style="min-width:0">
      <div class="job-title">${esc(video.title || video.video_id)}</div>
      <div class="job-meta"><span class="mono">${esc(video.source_url || "")}</span>${video.channel ? `<span class="tag">${esc(video.channel)}</span>` : ""}</div>
      <div class="job-prog"><div class="job-step"><b>${esc(STEP_LABELS[video.step] || video.step || "—")}</b>${pct != null ? `<span>${pct} %${eta}</span>` : ""}${progress && progress.message ? `<span class="muted">${esc(progress.message)}</span>` : ""}</div>
        ${progressBar(pct)}</div>
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
    ${videoThumb(video.video_id, video.platform_thumbnail)}
    <div class="li-main"><a class="li-title" href="#/videos/${encodeURIComponent(video.video_id)}" style="display:block">${esc(video.title || video.video_id)}</a>
      <div class="li-sub">${video.title && video.title !== video.video_id ? `<span class="mono">${id}</span> · ` : ""}${video.channel ? `${esc(video.channel)} · ` : ""}étape ${esc((STEP_LABELS[video.step] || video.step || "—").toLowerCase())}</div>
      <p class="reason ${kind === "failed" ? "bad" : ""}">${esc(video.reason || "Aucune raison journalisée.")}</p>${retry}</div>
    <div class="row wrap dash-problem-actions">
      <button type="button" class="btn btn-xs" data-retry-video="${id}" data-from-step="${esc(video.step || "")}">Relancer</button>
      <button type="button" class="btn btn-xs btn-ghost" data-dismiss-video="${id}">Retirer</button></div>
  </div>`;
}

/* Posts sans vue depuis zero_view_alert_hours (TASK-974e) : compte en alerte d'un bloc, pas de relevé à part. */
function dashZeroViewRow(account, post) {
  const clip = post.video_id ? `${esc(post.video_id)} · clip ${esc(post.clip_id)}` : "post non relié à un clip";
  return `<div class="list-item dash-problem" data-post="${esc(post.post_id)}">
    <span class="chip failed">0 vue</span>
    <div class="li-main"><div class="li-title mono">${esc(post.post_id)}</div>
      <div class="li-sub">${esc(account)} · ${clip} · publié le ${esc(dashDate(post.posted_at))}</div>
      <div class="li-sub">${esc(post.views)} vue(s) au relevé du ${esc(dashDate(post.read_at))}</div></div></div>`;
}

function dashZeroViewsContent(data) {
  if (data.zero_views === null || data.zero_views === undefined) {
    return dashError(data.zero_views_error || "alertes 0 vue : donnée absente de la réponse.");
  }
  const { hours, accounts, no_reading: missing } = data.zero_views;
  const rows = accounts.map((group) => {
    const head = group.level === "account"
      ? `<div class="list-item"><p class="reason bad">Le compte ${esc(group.account)} ne diffuse peut-être plus : ${group.posts.length} posts à 0 vue depuis ${esc(hours)} h.</p></div>`
      : "";
    return head + group.posts.map((post) => dashZeroViewRow(group.account, post)).join("");
  }).join("");
  const silent = missing.map((item) => `<div class="list-item muted"><div class="li-main">
    <div class="li-sub">Pas de relevé : ${esc(item.account)} · ${esc(item.post_id)} · clip ${esc(item.clip_id)}</div></div></div>`).join("");
  return rows + silent || dashEmpty(`Aucun post sans vue depuis ${esc(hours)} h.`);
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
    ["", "#/dashboard", "coins", "LLM aujourd'hui", dashKpi(data.llm_cost ? data.llm_cost.today : null, dashMoney), ""],
  ];
  return `<div class="kpis">${cards.map(([cls, href, ic, label, value]) => `<a class="kpi ${cls}" href="${href}">
    <div class="kpi-label">${icon(ic)}${esc(label)}</div><div class="kpi-value">${esc(value)}</div></a>`).join("")}</div>`;
}

/* ---------- Mesures internes (ex-ecran Statistiques, SPEC-86fe R1) : couts du modele de langage, duree par etape,
   videos par statut. Lit GET /api/measures?since=&until=&channel= ; rien de TikTok ici. ---------- */

const DASH_PRESETS = [["7", "7 jours"], ["30", "30 jours"], ["90", "90 jours"], ["all", "Tout"]];
const DASH_STATUS_LABELS = {
  pending: "En attente", running: "En cours", awaiting_review: "À valider",
  queued: "En file", done: "Terminées", failed: "En échec",
};
const DASH_NO_CHANNEL = "__none__"; // valeur de ?channel= pour « Sans chaine » (voir clipper/web/app.py)
const dashMeasures = { data: null, error: null, loading: null, dirty: false, at: 0, preset: "30", since: "", until: "", channel: "" };
const dashSeconds = (s) => (s >= 90 ? `${fr(s / 60, 1)} min` : `${fr(s, 1)} s`);

function dashIso(date) {
  const p = (n) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${p(date.getMonth() + 1)}-${p(date.getDate())}`;
}

/* Preset -> bornes (« Tout » = aucune borne, la periode reste ouverte). */
function dashApplyPreset(preset) {
  dashMeasures.preset = preset;
  if (preset === "all") { dashMeasures.since = ""; dashMeasures.until = ""; return; }
  const now = new Date();
  dashMeasures.since = dashIso(new Date(now.getFullYear(), now.getMonth(), now.getDate() - (Number(preset) - 1)));
  dashMeasures.until = dashIso(now);
}
dashApplyPreset(dashMeasures.preset);

function loadMeasures() {
  if (dashMeasures.loading) { dashMeasures.dirty = true; return dashMeasures.loading; }
  const params = new URLSearchParams();
  if (dashMeasures.since) params.set("since", dashMeasures.since);
  if (dashMeasures.until) params.set("until", dashMeasures.until);
  if (dashMeasures.channel) params.set("channel", dashMeasures.channel);
  dashMeasures.loading = (async () => {
    try {
      dashMeasures.data = await api("/api/measures?" + params.toString());
      dashMeasures.error = null;
    } catch (err) {
      dashMeasures.error = err;
    } finally {
      dashMeasures.loading = null;
      dashMeasures.at = Date.now();
    }
    if (currentScreen === "dashboard") renderCurrent();
    if (dashMeasures.dirty) { dashMeasures.dirty = false; loadMeasures(); }
  })();
  return dashMeasures.loading;
}

function dashKpiBlock(label, value, foot) {
  return `<div class="kpi"><div class="kpi-label">${esc(label)}</div><div class="kpi-value">${value}</div><div class="kpi-foot">${esc(foot)}</div></div>`;
}

/* Barres horizontales : [libelle, valeur, texte de valeur]. */
function dashBars(rows, emptyText) {
  if (!rows.length) return `<p class="muted stats-empty">${esc(emptyText)}</p>`;
  const max = Math.max(...rows.map((r) => r[1])) || 1;
  return `<div class="stats-bars">${rows.map(([label, value, text]) => `
    <div class="stats-bar"><span class="stats-bar-label">${esc(label)}</span>
      <span class="stats-bar-track"><i style="width:${Math.max(2, Math.round((value / max) * 100))}%"></i></span>
      <b class="num">${esc(text)}</b></div>`).join("")}</div>`;
}

/* Colonnes verticales par jour : [jour, valeur]. */
function dashColumns(rows, emptyText) {
  if (!rows.length) return `<p class="muted stats-empty">${esc(emptyText)}</p>`;
  const max = Math.max(...rows.map((r) => r[1])) || 1;
  return `<div class="stats-cols" role="img" aria-label="Coût par jour">${rows.map(([day, value]) => `
    <div class="stats-col" title="${esc(day)} : ${esc(dashMoney(value))}"><i style="height:${Math.max(3, Math.round((value / max) * 100))}%"></i><span>${esc(day.slice(5))}</span></div>`).join("")}</div>`;
}

function dashMeasuresCost(data) {
  const cost = data.llm_cost;
  const unreported = cost.unreported_calls
    ? `${cost.unreported_calls} appel${cost.unreported_calls > 1 ? "s" : ""} sans coût rapporté, non compté${cost.unreported_calls > 1 ? "s" : ""}`
    : "tous les appels ont un coût rapporté";
  const usages = Object.entries(cost.by_usage).sort((a, b) => b[1] - a[1]);
  const videos = Object.entries(cost.by_video).sort((a, b) => b[1].cost - a[1].cost);
  return `<section class="panel" data-block="llm"><div class="panel-head"><h2>Coûts du modèle de langage</h2><div class="right muted" style="font-size:12px">équivalent API</div></div>
    <div class="panel-pad stats-cost">
      ${dashKpiBlock("Total sur la période", `<span>${esc(fr(cost.total, 2))}</span><small>$</small>`, unreported)}
      <div><div class="field-label">Par usage</div>${dashBars(usages.map(([u, v]) => [u, v, dashMoney(v)]), "Aucun appel sur cette période.")}</div>
      <div><div class="field-label">Par jour</div>${dashColumns(Object.entries(cost.by_day), "Aucun appel sur cette période.")}</div>
      <div><div class="field-label">Par vidéo</div>${videos.length
        ? `<div class="table-scroll"><table class="table"><thead><tr><th>Vidéo</th><th class="r">Appels</th><th class="r">Coût</th></tr></thead><tbody>${videos.map(([id, v]) =>
          `<tr><td class="mono">${esc(id)}</td><td class="r num">${esc(fr(v.calls))}${v.unreported_calls ? ` <span class="muted">(${esc(v.unreported_calls)} sans coût)</span>` : ""}</td><td class="r num">${esc(dashMoney(v.cost))}</td></tr>`).join("")}</tbody></table></div>`
        : `<p class="muted stats-empty">Aucun appel sur cette période.</p>`}</div>
    </div></section>`;
}

function dashMeasuresSteps(data) {
  const rows = Object.entries(data.steps);
  const bars = dashBars(rows.map(([name, s]) => [STEP_LABELS[name] || name, s.mean_s, `${dashSeconds(s.mean_s)} · dernière ${dashSeconds(s.last_s)}`]),
    "Aucune vidéo terminée sur cette période : pas de durée à montrer.");
  const total = rows.reduce((t, [, s]) => t + s.mean_s, 0);
  const count = rows.length ? Math.max(...rows.map(([, s]) => s.count)) : 0;
  return `<section class="panel" data-block="steps"><div class="panel-head"><h2>Durée par étape</h2><div class="right muted" style="font-size:12px">moyenne · dernière, vidéos terminées</div></div>
    <div class="panel-pad">${bars}${rows.length ? `<p class="muted stats-note" style="padding:12px 0 0">Total moyen d'une vidéo : ${esc(dashSeconds(total))} (sur ${esc(count)} vidéo${count > 1 ? "s" : ""}).</p>` : ""}</div></section>`;
}

function dashMeasuresCounts(data) {
  const chip = { pending: "pending", running: "running", awaiting_review: "review", queued: "queued", done: "done", failed: "failed" };
  const total = Object.values(data.counts).reduce((t, n) => t + n, 0);
  return `<section class="panel" data-block="counts"><div class="panel-head"><h2>Vidéos par statut</h2><div class="right muted" style="font-size:12px">${total} vidéo${total > 1 ? "s" : ""}</div></div>
    <div class="panel-pad stats-counts">${Object.entries(data.counts).map(([status, n]) =>
      `<div class="stats-count"><b class="num">${esc(fr(n))}</b><span class="chip ${chip[status] || "pending"}">${esc(DASH_STATUS_LABELS[status] || status)}</span></div>`).join("")}</div></section>`;
}

function dashMeasuresToolbar() {
  const names = (store.channels || []).slice();
  if (dashMeasures.channel && dashMeasures.channel !== DASH_NO_CHANNEL && !names.includes(dashMeasures.channel)) names.push(dashMeasures.channel);
  const opt = (value, label) => `<option value="${esc(value)}"${dashMeasures.channel === value ? " selected" : ""}>${esc(label)}</option>`;
  return `<div class="stats-toolbar">
    <select class="input" data-measures-channel aria-label="Filtrer par style">${opt("", "Tous les styles")}${opt(DASH_NO_CHANNEL, "Sans style")}${names.map((n) => opt(n, n)).join("")}</select>
    <div class="seg stats-seg" role="group" aria-label="Période">${DASH_PRESETS.map(([id, label]) =>
      `<button type="button" data-measures-preset="${id}" class="${dashMeasures.preset === id ? "on" : ""}">${label}</button>`).join("")}</div>
    <div class="stats-range"><label>Du <input class="input" type="date" data-measures-since value="${esc(dashMeasures.since)}"></label>
      <label>au <input class="input" type="date" data-measures-until value="${esc(dashMeasures.until)}"></label></div></div>`;
}

function dashMeasuresSection() {
  const data = dashMeasures.data;
  let content;
  if (!data) {
    content = dashMeasures.error
      ? `<p class="reason bad">Mesures indisponibles : ${esc(dashMeasures.error.message || dashMeasures.error)}</p>`
      : `<div class="skeleton skeleton-card"></div>`;
  } else {
    content = `<div class="stats-grid">${dashMeasuresCost(data)}${dashMeasuresSteps(data)}${dashMeasuresCounts(data)}</div>`;
  }
  return `<section data-section="measures" style="margin-top:32px">
    <div class="section-title">${icon("chart-column")}Mesures internes</div>${dashMeasuresToolbar()}${content}</section>`;
}

function wireMeasures(body) {
  const channel = $("[data-measures-channel]", body);
  if (!channel) return;
  channel.onchange = (e) => { dashMeasures.channel = e.target.value; loadMeasures(); };
  $$("[data-measures-preset]", body).forEach((b) => (b.onclick = () => {
    dashApplyPreset(b.dataset.measuresPreset);
    renderCurrent();
    loadMeasures();
  }));
  const onDates = () => {
    dashMeasures.preset = "";
    dashMeasures.since = $("[data-measures-since]", body).value;
    dashMeasures.until = $("[data-measures-until]", body).value;
    loadMeasures();
  };
  $("[data-measures-since]", body).onchange = onDates;
  $("[data-measures-until]", body).onchange = onDates;
}

Screens.dashboard = {
  render(body, store) {
    const data = store.dashboard;
    if (Date.now() - dash.at > DASH_STALE_MS) loadDashboard();
    if (Date.now() - dashMeasures.at > DASH_STALE_MS) loadMeasures();
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
          ${dashSection("zero_views", "triangle-alert", "Posts à 0 vue", dashZeroViewsContent(data))}
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
      </div>
      ${dashMeasuresSection()}`;
    wireWatch(body);
    wireMeasures(body);
  },
};
