/* Ecran « Statistiques » (SPEC-c100 E7, TASK-7d86). Lit GET /api/stats?since=&until= :
   resultats par clip (outcomes + sidecar + decision humaine), couts du modele de
   langage, duree par etape, videos par statut ; l'import CSV des stats de plateforme
   passe par POST /api/stats/import. Graphiques en CSS, sans bibliotheque (ADR-09ad).
   Charge apres screens.js dont il remplace l'entree Screens.stats. */
"use strict";

const STATS_PRESETS = [["7", "7 jours"], ["30", "30 jours"], ["90", "90 jours"], ["all", "Tout"]];
const STATS_STALE_MS = 4000;
const STATS_STATUS_LABELS = {
  pending: "En attente", running: "En cours", awaiting_review: "À valider",
  queued: "En file", done: "Terminées", failed: "En échec",
};
const STATS_DECISIONS = { approved: "Approuvé", accepted: "Accepté", adjusted: "Ajusté", rejected: "Refusé" };
const STATS_CLIPS_PAGE_SIZE = 50; // « Résultats par clip » : 50 lignes à la fois, puis « Afficher plus »
const STATS_QA = { passed: { label: "QA réussie", cls: "ok" }, rejected: { label: "QA refusée", cls: "bad" } };

const STATS_NO_CHANNEL = "__none__"; // valeur de ?channel= pour « Sans chaîne » (voir clipper/web/app.py)
// Colonnes triables du tableau « Résultats par clip » : clé -> valeur comparée (null = « pas de donnée », toujours en bas).
const STATS_SORTS = {
  clip: (c) => (c.screen_title || c.clip_id || "").toLowerCase(),
  channel: (c) => (c.channel || "").toLowerCase() || null,
  qa: (c) => c.qa_status || null,
  decision: (c) => c.human_decision || null,
  views: (c) => (c.stats ? c.stats.views : null),
  retention: (c) => (c.stats ? c.stats.retention_3s : null),
  full: (c) => (c.stats ? c.stats.watched_full : null),
  shares: (c) => (c.stats ? c.stats.shares : null),
};

const statsUi = { data: null, error: null, loading: null, dirty: false, at: 0, preset: "30", since: "", until: "", shown: STATS_CLIPS_PAGE_SIZE, channel: "", sort: { key: null, dir: "asc" } };

const statsMoney = (usd) => `${fr(usd, 2)} $`;
const statsPct = (fraction) => `${fr(fraction * 100, 0)} %`;
const statsSeconds = (s) => (s >= 90 ? `${fr(s / 60, 1)} min` : `${fr(s, 1)} s`);

function statsIso(date) {
  const p = (n) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${p(date.getMonth() + 1)}-${p(date.getDate())}`;
}

/* Preset -> bornes (« Tout » = aucune borne, la periode reste ouverte). */
function statsApplyPreset(preset) {
  statsUi.preset = preset;
  if (preset === "all") { statsUi.since = ""; statsUi.until = ""; return; }
  const now = new Date();
  const from = new Date(now.getFullYear(), now.getMonth(), now.getDate() - (Number(preset) - 1));
  statsUi.since = statsIso(from);
  statsUi.until = statsIso(now);
}
statsApplyPreset(statsUi.preset);

function loadStats() {
  if (statsUi.loading) { statsUi.dirty = true; return statsUi.loading; }
  const params = new URLSearchParams();
  if (statsUi.since) params.set("since", statsUi.since);
  if (statsUi.until) params.set("until", statsUi.until);
  if (statsUi.channel) params.set("channel", statsUi.channel);
  statsUi.loading = (async () => {
    try {
      statsUi.data = await api("/api/stats?" + params.toString());
      statsUi.error = null;
    } catch (err) {
      statsUi.error = err;
      toastError("Statistiques indisponibles", err);
    } finally {
      statsUi.loading = null;
      statsUi.at = Date.now();
    }
    if (currentScreen === "stats") renderCurrent();
    if (statsUi.dirty) { statsUi.dirty = false; loadStats(); }
  })();
  return statsUi.loading;
}

// Un evenement serveur (video, file, publication) rend les chiffres obsoletes.
document.addEventListener("clipper:event", () => {
  statsUi.at = 0;
  if (currentScreen === "stats") loadStats();
});

function statsKpi(label, value, foot, cls) {
  return `<div class="kpi ${cls || ""}"><div class="kpi-label">${esc(label)}</div><div class="kpi-value">${value}</div><div class="kpi-foot">${esc(foot)}</div></div>`;
}

/* Barres horizontales : [libelle, valeur, texte de valeur]. */
function statsBars(rows, emptyText) {
  if (!rows.length) return `<p class="muted stats-empty">${esc(emptyText)}</p>`;
  const max = Math.max(...rows.map((r) => r[1])) || 1;
  return `<div class="stats-bars">${rows.map(([label, value, text]) => `
    <div class="stats-bar"><span class="stats-bar-label">${esc(label)}</span>
      <span class="stats-bar-track"><i style="width:${Math.max(2, Math.round((value / max) * 100))}%"></i></span>
      <b class="num">${esc(text)}</b></div>`).join("")}</div>`;
}

/* Colonnes verticales par jour : [jour, valeur]. */
function statsColumns(rows, emptyText) {
  if (!rows.length) return `<p class="muted stats-empty">${esc(emptyText)}</p>`;
  const max = Math.max(...rows.map((r) => r[1])) || 1;
  return `<div class="stats-cols" role="img" aria-label="Coût par jour">${rows.map(([day, value]) => `
    <div class="stats-col" title="${esc(day)} : ${esc(statsMoney(value))}"><i style="height:${Math.max(3, Math.round((value / max) * 100))}%"></i><span>${esc(day.slice(5))}</span></div>`).join("")}</div>`;
}

/* Texte lisible d'un avertissement QA : le serveur renvoie des objets {type, detail, source, severity}
   (clipper.qa), parfois des chaînes ; jamais « [object Object] ». */
function statsIssueText(issue) {
  if (typeof issue === "string") return issue;
  if (issue && typeof issue === "object" && (issue.detail || issue.type)) return String(issue.detail || issue.type);
  return JSON.stringify(issue);
}

/* Nombre de lignes que « Afficher plus » ajoute : une page, ou ce qui reste. */
function statsMoreCount(total, shown) {
  return Math.max(0, Math.min(STATS_CLIPS_PAGE_SIZE, total - shown));
}

/* Trie les clips en place par la colonne choisie (clic sur l'en-tête) ; sans tri, l'ordre du serveur. */
function statsSortInPlace(clips) {
  const { key, dir } = statsUi.sort;
  if (!key) return;
  const value = STATS_SORTS[key];
  const sign = dir === "desc" ? -1 : 1;
  clips.sort((a, b) => {
    const x = value(a), y = value(b);
    if (x === null && y === null) return 0;
    if (x === null) return 1;
    if (y === null) return -1;
    return (typeof x === "string" ? x.localeCompare(y, "fr") : x - y) * sign;
  });
}

function statsHead(key, label, right) {
  const on = statsUi.sort.key === key;
  const ariaSort = on ? (statsUi.sort.dir === "desc" ? "descending" : "ascending") : "none";
  return `<th class="${right ? "r " : ""}" aria-sort="${ariaSort}"><button type="button" class="th-sort" data-stats-sort="${key}">${label}${on ? (statsUi.sort.dir === "desc" ? " ▼" : " ▲") : ""}</button></th>`;
}

function statsClipRow(c) {
  const qa = STATS_QA[c.qa_status] || { label: c.qa_status || "QA inconnue", cls: "pending" };
  const issues = c.issues && c.issues.length ? `<div class="li-sub muted">${esc(c.issues.map(statsIssueText).join(" · "))}</div>` : "";
  const decision = c.human_decision
    ? `${esc(STATS_DECISIONS[c.human_decision] || c.human_decision)}<div class="li-sub muted">${c.decision_source === "feedback" ? "revue des moments" : "journal des résultats"}</div>`
    : `<span class="muted">pas de décision</span>`;
  const s = c.stats;
  const cells = s
    ? `<td class="r num">${esc(fr(s.views))}</td><td class="r num">${esc(statsPct(s.retention_3s))}</td><td class="r num">${esc(statsPct(s.watched_full))}</td><td class="r num">${esc(fr(s.shares))}</td>`
    : `<td class="r muted" colspan="4">aucune mesure importée</td>`;
  return `<tr><td><div class="stats-clip-title">${esc(c.screen_title || c.clip_id)}</div><div class="li-sub muted mono">${esc(c.video_id)}/${esc(c.clip_id)}</div></td>
    <td>${c.channel ? esc(c.channel) : `<span class="muted">sans chaîne</span>`}</td>
    <td><span class="chip ${qa.cls}">${esc(qa.label)}</span>${issues}</td><td>${decision}</td>${cells}</tr>`;
}

function statsClipsBlock(data) {
  const unmatched = data.stats_unmatched || [];
  const next = statsMoreCount(data.clips.length, statsUi.shown);
  const more = next
    ? `<div class="panel-pad"><button type="button" class="btn btn-ghost" data-stats-more>Afficher plus (${next} sur ${data.clips.length - statsUi.shown} restants)</button></div>` : "";
  const table = data.clips.length
    ? `<div class="table-scroll"><table class="table"><thead><tr>${statsHead("clip", "Clip")}${statsHead("channel", "Chaîne")}${statsHead("qa", "Contrôle qualité")}${statsHead("decision", "Décision")}${statsHead("views", "Vues", true)}${statsHead("retention", "Rétention 3 s", true)}${statsHead("full", "Vu en entier", true)}${statsHead("shares", "Partages", true)}</tr></thead>
        <tbody>${data.clips.slice(0, statsUi.shown).map(statsClipRow).join("")}</tbody></table></div>${more}`
    : `<p class="muted stats-empty">Aucun clip rendu sur cette période.</p>`;
  const orphans = unmatched.length
    ? `<div class="stats-unmatched"><b>Mesures non rattachées</b>${unmatched.map((u) => `<div class="li-sub">Clip ${esc(u.clip_id)} : ${esc(fr(u.stats.views))} vues le ${esc(u.stats.date)} — ${esc(u.reason)}</div>`).join("")}</div>`
    : "";
  return `<section class="panel" data-block="clips"><div class="panel-head"><h2>Résultats par clip</h2><div class="right muted" style="font-size:12px">${Math.min(statsUi.shown, data.clips.length)} sur ${data.clips.length} clip${data.clips.length > 1 ? "s" : ""}</div></div>
    ${table}${orphans}
    <p class="muted stats-note">Les vues et la rétention n'existent que par le CSV importé tant que l'autopost n'est pas en place.</p></section>`;
}

function statsCostBlock(data) {
  const cost = data.llm_cost;
  const unreported = cost.unreported_calls
    ? `${cost.unreported_calls} appel${cost.unreported_calls > 1 ? "s" : ""} sans coût rapporté, non compté${cost.unreported_calls > 1 ? "s" : ""}`
    : "tous les appels ont un coût rapporté";
  const usages = Object.entries(cost.by_usage).sort((a, b) => b[1] - a[1]);
  const days = Object.entries(cost.by_day);
  const videos = Object.entries(cost.by_video).sort((a, b) => b[1].cost - a[1].cost);
  return `<section class="panel" data-block="llm"><div class="panel-head"><h2>Coûts du modèle de langage</h2><div class="right muted" style="font-size:12px">équivalent API</div></div>
    <div class="panel-pad stats-cost">
      ${statsKpi("Total sur la période", `<span>${esc(fr(cost.total, 2))}</span><small>$</small>`, unreported)}
      <div><div class="field-label">Par usage</div>${statsBars(usages.map(([u, v]) => [u, v, statsMoney(v)]), "Aucun appel sur cette période.")}</div>
      <div><div class="field-label">Par jour</div>${statsColumns(days, "Aucun appel sur cette période.")}</div>
      <div><div class="field-label">Par vidéo</div>${videos.length
        ? `<div class="table-scroll"><table class="table"><thead><tr><th>Vidéo</th><th class="r">Appels</th><th class="r">Coût</th></tr></thead><tbody>${videos.map(([id, v]) =>
          `<tr><td class="mono">${esc(id)}</td><td class="r num">${esc(fr(v.calls))}${v.unreported_calls ? ` <span class="muted">(${esc(v.unreported_calls)} sans coût)</span>` : ""}</td><td class="r num">${esc(statsMoney(v.cost))}</td></tr>`).join("")}</tbody></table></div>`
        : `<p class="muted stats-empty">Aucun appel sur cette période.</p>`}</div>
    </div></section>`;
}

function statsStepsBlock(data) {
  const rows = Object.entries(data.steps);
  const bars = statsBars(rows.map(([name, s]) => [STEP_LABELS[name] || name, s.mean_s, `${statsSeconds(s.mean_s)} · dernière ${statsSeconds(s.last_s)}`]),
    "Aucune vidéo terminée sur cette période : pas de durée à montrer.");
  const total = rows.reduce((t, [, s]) => t + s.mean_s, 0);
  return `<section class="panel" data-block="steps"><div class="panel-head"><h2>Durée par étape</h2><div class="right muted" style="font-size:12px">moyenne · dernière, vidéos terminées</div></div>
    <div class="panel-pad">${bars}${rows.length ? `<p class="muted stats-note" style="padding:12px 0 0">Total moyen d'une vidéo : ${esc(statsSeconds(total))} (sur ${esc(Math.max(...rows.map(([, s]) => s.count)))} vidéo${Math.max(...rows.map(([, s]) => s.count)) > 1 ? "s" : ""}).</p>` : ""}</div></section>`;
}

function statsCountsBlock(data) {
  const chip = { pending: "pending", running: "running", awaiting_review: "review", queued: "queued", done: "done", failed: "failed" };
  const total = Object.values(data.counts).reduce((t, n) => t + n, 0);
  return `<section class="panel" data-block="counts"><div class="panel-head"><h2>Vidéos par statut</h2><div class="right muted" style="font-size:12px">${total} vidéo${total > 1 ? "s" : ""}</div></div>
    <div class="panel-pad stats-counts">${Object.entries(data.counts).map(([status, n]) =>
      `<div class="stats-count"><b class="num">${esc(fr(n))}</b><span class="chip ${chip[status] || "pending"}">${esc(STATS_STATUS_LABELS[status] || status)}</span></div>`).join("")}</div></section>`;
}

function statsChannelFilter() {
  const names = (store.channels || []).slice();
  if (statsUi.channel && statsUi.channel !== STATS_NO_CHANNEL && !names.includes(statsUi.channel)) names.push(statsUi.channel);
  const opt = (value, label) => `<option value="${esc(value)}"${statsUi.channel === value ? " selected" : ""}>${esc(label)}</option>`;
  return `<select class="input" data-stats-channel aria-label="Filtrer par chaîne">${opt("", "Toutes les chaînes")}${opt(STATS_NO_CHANNEL, "Sans chaîne")}${names.map((n) => opt(n, n)).join("")}</select>`;
}

function statsToolbar() {
  return `<div class="stats-toolbar">
    ${statsChannelFilter()}
    <div class="seg" role="group" aria-label="Période">${STATS_PRESETS.map(([id, label]) =>
      `<button type="button" data-stats-preset="${id}" class="${statsUi.preset === id ? "on" : ""}">${label}</button>`).join("")}</div>
    <div class="stats-range"><label>Du <input class="input" type="date" data-stats-since value="${esc(statsUi.since)}"></label>
      <label>au <input class="input" type="date" data-stats-until value="${esc(statsUi.until)}"></label></div>
    <div class="stats-import"><input type="file" accept=".csv,text/csv" data-stats-file hidden aria-label="Fichier CSV des statistiques de plateforme">
      <button type="button" class="btn btn-primary" data-stats-import>${icon("upload")}Importer un CSV</button></div>
  </div>`;
}

async function statsImport(file) {
  const form = new FormData();
  form.append("file", file);
  try {
    const sent = await api("/api/stats/import", { method: "POST", body: form });
    toast({ kind: "ok", title: "Statistiques importées", body: `${sent.imported} ligne${sent.imported > 1 ? "s" : ""} ajoutée${sent.imported > 1 ? "s" : ""} au journal.` });
    statsUi.at = 0;
    await loadStats();
  } catch (err) {
    toastError("Import du CSV impossible", err);
  }
}

function statsWire(body) {
  $("[data-stats-channel]", body).onchange = (e) => {
    statsUi.channel = e.target.value;
    statsUi.shown = STATS_CLIPS_PAGE_SIZE;
    loadStats();
  };
  $$("[data-stats-sort]", body).forEach((b) => (b.onclick = () => {
    const key = b.dataset.statsSort;
    statsUi.sort = statsUi.sort.key === key ? { key, dir: statsUi.sort.dir === "asc" ? "desc" : "asc" } : { key, dir: "asc" };
    statsUi.shown = STATS_CLIPS_PAGE_SIZE;
    renderCurrent();
  }));
  const moreButton = $("[data-stats-more]", body);
  if (moreButton) moreButton.onclick = () => { statsUi.shown += STATS_CLIPS_PAGE_SIZE; renderCurrent(); };
  $$("[data-stats-preset]", body).forEach((b) => (b.onclick = () => {
    statsUi.shown = STATS_CLIPS_PAGE_SIZE;
    statsApplyPreset(b.dataset.statsPreset);
    renderCurrent();
    loadStats();
  }));
  const onDates = () => {
    statsUi.preset = "";
    statsUi.shown = STATS_CLIPS_PAGE_SIZE;
    statsUi.since = $("[data-stats-since]", body).value;
    statsUi.until = $("[data-stats-until]", body).value;
    loadStats();
  };
  $("[data-stats-since]", body).onchange = onDates;
  $("[data-stats-until]", body).onchange = onDates;
  const fileInput = $("[data-stats-file]", body);
  $("[data-stats-import]", body).onclick = () => fileInput.click();
  fileInput.onchange = async () => {
    const file = fileInput.files[0];
    fileInput.value = "";
    if (file) await statsImport(file);
  };
}

Screens.stats = {
  render(body) {
    if (Date.now() - statsUi.at > STATS_STALE_MS) loadStats();
    const data = statsUi.data;
    let content;
    if (!data) {
      content = statsUi.error
        ? emptyState("circle-alert", "Chargement impossible", String(statsUi.error.message || statsUi.error))
        : `<div class="skeleton skeleton-line"></div><div class="skeleton skeleton-card"></div><div class="skeleton skeleton-card"></div>`;
    } else {
      statsSortInPlace(data.clips);
      content = `<div class="stats-grid">${statsClipsBlock(data)}${statsCostBlock(data)}${statsStepsBlock(data)}${statsCountsBlock(data)}</div>`;
    }
    body.innerHTML = statsToolbar() + content;
    statsWire(body);
  },
};
