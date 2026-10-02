/* Ecran « Statistiques » (SPEC-47e2) : un tableau de bord TikTok par compte, alimente UNIQUEMENT par le releve de
   TikTok Studio, releve seulement quand on s'en sert. Lit GET /api/stats/tiktok (comptes, avec `refreshing`),
   /api/stats/tiktok/<compte>?period= (vue d'ensemble), /api/stats/tiktok/<compte>/videos (liste triable) et
   /api/stats/tiktok/<compte>/videos/<id> (fiche). A l'ouverture, POST /api/stats/tiktok/open lance un releve en tache
   de fond si le dernier est perime (le dernier releve connu reste affiche, « Relevé en cours » jusqu'a la fin) ; le
   bouton « Relever maintenant » fait POST /api/stats/tiktok/refresh. Un seul releve a la fois par compte (serveur). Adresses : #/stats[/<compte>[/videos[/<id>]]].
   Graphiques en SVG calcule ici, sans bibliotheque (ADR-09ad). Une valeur que TikTok n'affiche pas (null) est un
   tiret, jamais un 0. Les mesures internes (couts LLM, durees d'etapes, videos par statut) sont dans le Tableau
   de bord. Charge apres screens.js dont il remplace l'entree Screens.stats. */
"use strict";

const STATS_STALE_MS = 4000;
const STATS_POLL_MS = 3000; // pendant un releve en tache de fond : relecture de l'etat des comptes
const STATS_VISIT_GAP_MS = 30000; // ecran quitte plus longtemps que ca : nouvelle ouverture, donc nouvelle demande
const STATS_PERIODS = [7, 28, 60];
const STATS_METRICS = [
  { id: "views", label: "Vues de vidéo", icon: "eye" },
  { id: "profile_views", label: "Vues du profil", icon: "user" },
  { id: "likes", label: "J'aime", icon: "heart" },
  { id: "comments", label: "Commentaires", icon: "message-square" },
  { id: "shares", label: "Partages", icon: "share-2" },
];
// Colonnes de la liste des videos : cle -> [libelle, numerique]. La cle est celle de ?sort= (clipper.tiktok.VIDEO_SORTS).
const STATS_COLUMNS = [
  ["caption", "Légende", false], ["posted_at", "Date", false], ["views", "Vues", true], ["likes", "J'aime", true],
  ["comments", "Commentaires", true], ["shares", "Partages", true], ["avg_watch_s", "Temps moyen", true],
  ["watched_full", "% vu en entier", true],
];
const STATS_VISIBILITY = { public: "Public", friends: "Amis", private: "Privé" };
const STATS_VIDEO_TABS = [["overview", "Vue d'ensemble"], ["viewers", "Spectateurs"], ["engagement", "Engagement"]];
const STATS_VIEWER_SECTIONS = [["types", "Types de spectateurs"], ["age", "Âge"], ["gender", "Sexe"], ["locations", "Lieux"]];

const statsUi = {
  accounts: null, overview: null, videos: null, videosAccount: "", video: null, videoAccount: "", error: null, loading: null, dirty: false, at: 0, key: "",
  period: 28, metric: "views", sort: { key: "posted_at", dir: "desc" }, q: "", vtab: "overview", refreshing: false,
  opened: {}, lastRender: 0, poll: null, wasRefreshing: {},
};

/* ---------- formats ---------- */

const statsNum = (n) => (n === null || n === undefined ? "—" : fr(n));
const statsPctValue = (fraction, digits) => (fraction === null || fraction === undefined ? "—" : `${fr(fraction * 100, digits || 0)} %`);

/* « 12 s », « 1:05 » : secondes -> mm:ss ; null -> tiret. */
function statsDuration(seconds) {
  if (seconds === null || seconds === undefined) return "—";
  const total = Math.round(seconds);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

/* Evolution : « ▲ +12,5 % » (vert), « ▼ -3 % » (rouge), « ■ 0 % » ; null -> tiret. */
function statsDelta(change) {
  if (change === null || change === undefined) return { cls: "flat", text: "—" };
  const sign = change > 0.05 ? "▲" : change < -0.05 ? "▼" : "■";
  const cls = change > 0.05 ? "up" : change < -0.05 ? "down" : "flat";
  return { cls, text: `${sign} ${change > 0 ? "+" : ""}${fr(change, 1)} %` };
}

/* Date relevee sur la page (« 2026-09-30T14:05:00 », sans fuseau) -> « 30/09 · 14:05 » ; absente -> tiret.
   Jamais de conversion de fuseau : c'est l'heure que TikTok Studio affiche. */
function statsPostedAt(iso, text) {
  const m = /^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2}))?/.exec(iso || "");
  if (!m) return text || "—";
  return m[4] ? `${m[3]}/${m[2]} · ${m[4]}:${m[5]}` : `${m[3]}/${m[2]}/${m[1]}`;
}

/* Date d'un releve (ISO avec fuseau) en heure de Paris, comme tout le reste de la console. */
const statsWhen = (iso) => fmtParis(iso, { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }).replace(",", " ·");

/* Vignette verticale : degrade stable tire de l'identifiant du post (TikTok ne donne pas d'image hors ligne). */
function statsPoster(postId) {
  let h = 0;
  for (const ch of String(postId)) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return `background:linear-gradient(160deg,hsl(${h % 360} 45% 32%),hsl(${(h >> 8) % 360} 50% 22%))`;
}

/* ---------- adresse : #/stats[/<compte>[/videos[/<id>]]] ---------- */

function statsRoute() {
  const parts = location.hash.replace(/^#\/?/, "").split("?")[0].split("/").slice(1).map((p) => decodeURIComponent(p));
  return { account: parts[0] || "", tab: parts[1] === "videos" ? "videos" : "overview", post: parts[1] === "videos" ? parts[2] || "" : "" };
}

function statsHref(account, tab, post) {
  const base = `#/stats/${encodeURIComponent(account)}`;
  if (tab === "videos") return post ? `${base}/videos/${encodeURIComponent(post)}` : `${base}/videos`;
  return base;
}

/* Compte affiche : celui de l'adresse s'il existe, sinon le premier. */
function statsAccount() {
  const accounts = statsUi.accounts || [];
  const wanted = statsRoute().account;
  return accounts.find((a) => a.account === wanted) || accounts[0] || null;
}

/* ---------- chargement ---------- */

function statsKey() {
  const account = statsAccount();
  if (!account) return "";
  const r = statsRoute();
  return [account.account, r.tab, r.post, statsUi.period, statsUi.sort.key, statsUi.sort.dir, statsUi.q].join("|");
}

function statsLoad() {
  if (statsUi.loading) { statsUi.dirty = true; return statsUi.loading; }
  statsUi.loading = (async () => {
    try {
      statsUi.accounts = (await api("/api/stats/tiktok")).accounts;
      const account = statsAccount();
      if (account) {
        const r = statsRoute();
        const base = `/api/stats/tiktok/${encodeURIComponent(account.account)}`;
        if (r.tab === "overview") {
          statsUi.overview = await api(`${base}?period=${statsUi.period}`);
        } else if (r.post) {
          statsUi.video = (await api(`${base}/videos/${encodeURIComponent(r.post)}`)).video;
          statsUi.videoAccount = account.account;
        } else {
          const params = new URLSearchParams({ sort: statsUi.sort.key, dir: statsUi.sort.dir, q: statsUi.q });
          statsUi.videos = (await api(`${base}/videos?${params}`)).videos;
          statsUi.videosAccount = account.account;
        }
      }
      statsUi.error = null;
      statsUi.key = statsKey();
    } catch (err) {
      statsUi.error = err;
      statsUi.key = statsKey();
    } finally {
      statsUi.loading = null;
      statsUi.at = Date.now();
    }
    if (currentScreen === "stats") {
      statsNotifyDone();
      renderCurrent();
      const account = statsAccount();
      if (account) statsOpen(account);
      statsSchedulePoll();
    }
    if (statsUi.dirty) { statsUi.dirty = false; statsLoad(); }
  })();
  return statsUi.loading;
}

/* Releve en cours pour ce compte : lance depuis l'ecran (bouton) ou en tache de fond sur le serveur. */
const statsRefreshing = (account) => statsUi.refreshing || Boolean(account && account.refreshing);

/* A l'ouverture de l'ecran (une fois par compte et par visite) : le serveur lance un releve en tache de fond si le
   dernier est perime ou absent (R4a) ; on affiche tout de suite le dernier releve connu, « Relevé en cours » jusqu'a la fin. */
async function statsOpen(account) {
  if (statsUi.opened[account.account] || !account.ready) return;
  statsUi.opened[account.account] = Date.now();
  try {
    const sent = await api("/api/stats/tiktok/open", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ account: account.account }) });
    if (!sent.started) return;
  } catch (err) {
    toastError("Relevé TikTok impossible", err);
    return;
  }
  statsUi.at = 0;
  statsLoad();
}

/* Tant qu'un releve tourne sur le serveur : on relit les comptes ; a la fin le dernier releve est recharge. */
function statsSchedulePoll() {
  clearTimeout(statsUi.poll);
  statsUi.poll = null;
  const account = statsAccount();
  if (currentScreen !== "stats" || !account || !account.refreshing) return;
  statsUi.poll = setTimeout(() => { statsUi.poll = null; statsUi.at = 0; statsLoad(); }, STATS_POLL_MS);
}

/* Un releve en tache de fond qui vient de finir : dit s'il a reussi ou pourquoi il a echoue (jamais silencieux). */
function statsNotifyDone() {
  for (const a of statsUi.accounts || []) {
    const was = statsUi.wasRefreshing[a.account];
    statsUi.wasRefreshing[a.account] = Boolean(a.refreshing);
    if (!was || a.refreshing) continue;
    if (a.refresh_error) toast({ kind: "bad", title: "Relevé TikTok impossible", body: `${a.label} : ${a.refresh_error}`, ms: 7000 });
    else toast({ kind: "ok", title: "Relevé terminé", body: `${a.label} : statistiques à jour.` });
  }
}

// Un evenement serveur (publication, releve) rend les chiffres obsoletes.
document.addEventListener("clipper:event", () => {
  statsUi.at = 0;
  if (currentScreen === "stats") statsLoad();
});
window.addEventListener("resize", () => { if (currentScreen === "stats") renderCurrent(); });

/* ---------- graphique SVG ---------- */

/* Trace d'une serie : un segment par suite de valeurs presentes, une valeur absente (jour sans releve) coupe la ligne. */
function statsLinePaths(values, x, y) {
  const paths = [];
  let run = [];
  values.forEach((v, i) => {
    if (v === null || v === undefined) { if (run.length) paths.push(run); run = []; } else run.push(`${x(i).toFixed(1)} ${y(v).toFixed(1)}`);
  });
  if (run.length) paths.push(run);
  return paths.map((r) => `M${r.join("L")}`).join("");
}

/* Plus haute graduation « ronde » au-dessus de la valeur max (4 graduations). */
function statsNiceMax(raw) {
  const max = Math.max(1, raw);
  const step = Math.pow(10, Math.floor(Math.log10(max / 4)));
  const nice = [1, 2, 2.5, 5, 10].map((k) => k * step).find((k) => max / k <= 4) || step * 10;
  return Math.ceil(max / nice) * nice;
}

const statsAxis = (v) => (v >= 1000 ? `${fr(Math.round(v / 100) / 10, 1)} k` : fr(Math.round(v * 10) / 10, v < 10 && v % 1 ? 1 : 0));

/* cfg : {labels, series: [{values, cls}], width, height, max, fy, tip(i), aria}. Les jours sans valeur sont des bandes grises. */
function statsChart(cfg) {
  const W = cfg.width, H = cfg.height || 240, L = 44, R = 12, T = 12, B = 26;
  const n = cfg.labels.length;
  const all = cfg.series.flatMap((s) => s.values).filter((v) => v !== null && v !== undefined);
  const top = cfg.max !== undefined ? cfg.max : statsNiceMax(Math.max(1, ...all));
  const x = (i) => L + (n === 1 ? 0 : (i / (n - 1)) * (W - L - R));
  const y = (v) => T + (1 - v / top) * (H - T - B);
  const band = n > 1 ? (W - L - R) / (n - 1) : 0;
  let g = "";
  for (let k = 0; k <= 4; k++) {
    const v = (top / 4) * k;
    g += `<line class="grid-l" x1="${L}" x2="${W - R}" y1="${y(v).toFixed(1)}" y2="${y(v).toFixed(1)}"/><text x="${L - 8}" y="${(y(v) + 4).toFixed(1)}" text-anchor="end">${esc(cfg.fy ? cfg.fy(v) : statsAxis(v))}</text>`;
  }
  const first = cfg.series[0].values;
  first.forEach((v, i) => { if ((v === null || v === undefined) && band) g += `<rect class="gapband" x="${(x(i) - band / 2).toFixed(1)}" y="${T}" width="${band.toFixed(1)}" height="${H - T - B}"/>`; });
  const every = Math.max(1, Math.ceil(n / (W < 500 ? 5 : 8)));
  cfg.labels.forEach((label, i) => {
    if ((i % every === 0 && (n - 1 - i >= every * 0.7 || i === 0)) || i === n - 1) {
      g += `<text x="${x(i).toFixed(1)}" y="${H - 6}" text-anchor="${i === 0 ? "start" : i === n - 1 ? "end" : "middle"}">${esc(label)}</text>`;
    }
  });
  cfg.series.slice().reverse().forEach((s) => {
    const d = statsLinePaths(s.values, x, y);
    if (d) g += `<path class="ln ${s.cls || ""}" d="${d}"/>`;
  });
  first.forEach((v, i) => {
    g += `<circle class="hit" cx="${x(i).toFixed(1)}" cy="${(v === null || v === undefined ? T + (H - T - B) / 2 : y(v)).toFixed(1)}" r="${v === null || v === undefined ? 4 : 6}"><title>${esc(cfg.tip(i))}</title></circle>`;
  });
  return `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="${esc(cfg.aria)}">${g}</svg>`;
}

/* Largeur du graphique : celle de l'ecran, bornee (rendu repris au redimensionnement). */
function statsChartWidth() {
  const body = $("#screen-stats [data-body]");
  return Math.max(280, Math.min(1100, ((body && body.clientWidth) || 800) - 48));
}

/* ---------- blocs ---------- */

function statsEmpty(iconName, title, text, action) { return `<div class="panel">${emptyState(iconName, title, text, action)}</div>`; }

const statsScanButton = (account) => `<button class="btn btn-primary" type="button" data-stats-scan${statsRefreshing(account) || !account.ready ? " disabled" : ""}>${icon("refresh-cw", statsRefreshing(account) ? "spin" : "")}${statsRefreshing(account) ? "Relevé en cours" : "Relever maintenant"}</button>`;

function statsControls(account) {
  const accounts = statsUi.accounts;
  const options = accounts.map((a) => `<option value="${esc(a.account)}"${a.account === account.account ? " selected" : ""}>${esc(a.label)} · ${esc(a.account)}</option>`).join("");
  const linked = account.channel
    ? `<div class="linked">${icon("link", "i-sm")}<span>Style Clipper lié : <b>${esc(account.channel)}</b></span></div>`
    : `<div class="linked none">${icon("link", "i-sm")}<span>Aucun style Clipper lié</span></div>`;
  const periods = `${STATS_PERIODS.map((n) => `<button type="button" data-stats-period="${n}" class="${n === statsUi.period ? "on" : ""}" aria-pressed="${n === statsUi.period}">${n} jours</button>`).join("")}`;
  const when = account.fetched_at
    ? `Dernier relevé : <b>${esc(statsWhen(account.fetched_at))}</b><br><span class="faint">${esc(fr(account.snapshots))} relevé${account.snapshots > 1 ? "s" : ""} enregistré${account.snapshots > 1 ? "s" : ""}</span>`
    : "Dernier relevé : <b>jamais</b>";
  const notReady = account.ready ? "" : `<div class="banner warn" role="status" data-stats-notready>${icon("lock", "i-sm")}<div><b>Compte non prêt à publier : aucun relevé n'est lancé.</b><br><span class="muted">${esc(account.not_ready_reason)}</span></div></div>`;
  const running = statsRefreshing(account) ? `<div class="banner" role="status" data-stats-running>${icon("refresh-cw", "i-sm spin")}<div><b>Relevé en cours.</b><br><span class="muted">${account.fetched_at ? "Les chiffres affichés sont ceux du dernier relevé ; ils se mettent à jour à la fin." : "Aucun relevé enregistré pour l'instant ; les chiffres apparaissent à la fin."}</span></div></div>` : "";
  const failed = account.error ? `<div class="banner bad" role="alert" data-stats-error>${icon("circle-alert", "i-sm")}<div><b>Dernier relevé arrêté (${esc(account.error.code)}).</b><br><span class="muted">${esc(account.error.reason)}</span></div></div>` : "";
  return `<section class="ctl" aria-label="Compte et période">
      <div class="acct field"><label for="stats-account">Compte TikTok</label><select class="input" id="stats-account" data-stats-account>${options}</select></div>
      ${linked}
      <div class="field"><span class="field-label" id="stats-lbl-period">Période</span><div class="seg stats-seg" data-stats-periods role="group" aria-labelledby="stats-lbl-period">${periods}</div></div>
      <div class="scan"><div class="scan-when">${when}</div>${statsScanButton(account)}</div>
    </section>${notReady}${running}${failed}`;
}

function statsTabs(account, tab, count) {
  const tabs = [["overview", "Vue d'ensemble", null], ["videos", "Vidéos", count]];
  return `<div class="tabs" role="tablist" aria-label="Sections">${tabs.map(([id, label, n]) =>
    `<a role="tab" class="${tab === id ? "on" : ""}" aria-selected="${tab === id}" href="${statsHref(account.account, id)}" data-stats-tab="${id}">${esc(label)}${n === null ? "" : ` <span class="n">${esc(fr(n))}</span>`}</a>`).join("")}</div>`;
}

function statsOverview(account) {
  const data = statsUi.overview;
  if (!data || data.account !== account.account) return `<div class="skeleton skeleton-card"></div>`;
  if (!data.tiles) return statsEmpty("inbox", `Aucun relevé pour ${account.label}`, "Clipper n'a encore rien relevé sur TikTok Studio pour ce compte. Le premier relevé remplit les tuiles et démarre les courbes par jour.");
  const period = data.period;
  const metric = STATS_METRICS.find((m) => m.id === statsUi.metric) || STATS_METRICS[0];
  const tiles = STATS_METRICS.map((m) => {
    const tile = data.tiles[m.id];
    const given = statsDelta(tile.change_pct);
    const hist = tile.history_change_pct === null || tile.history_change_pct === undefined ? "" : `<small title="Calculée sur nos relevés : valeur il y a ${period} jours">relevés : ${esc(statsDelta(tile.history_change_pct).text)}</small>`;
    return `<button class="kpi kpi-btn" type="button" data-stats-metric="${m.id}" aria-pressed="${m.id === metric.id}">
      <div class="kpi-label">${icon(m.icon)}${esc(m.label)}</div><div class="kpi-value">${esc(statsNum(tile.value))}</div>
      <span class="delta ${given.cls}">${esc(given.text)} <small>vs ${period} j précédents (TikTok)</small></span>${hist}</button>`;
  }).join("");
  const s = data.series[metric.id];
  const chart = statsChart({
    labels: s.labels.map((d) => `${d.slice(8, 10)}/${d.slice(5, 7)}`), width: statsChartWidth(),
    series: [{ values: s.values }, { values: s.previous, cls: "prev" }], aria: `${metric.label} par jour sur ${period} jours`,
    tip: (i) => `${s.labels[i].slice(8, 10)}/${s.labels[i].slice(5, 7)} : ${s.values[i] === null ? "pas de relevé" : fr(s.values[i])}${s.previous[i] === null ? "" : ` · période précédente : ${fr(s.previous[i])}`}`,
  });
  const noPoint = s.values.every((v) => v === null);
  return `<div class="kpis" data-stats-tiles>${tiles}</div>
    <div class="panel" style="margin-top:24px" data-stats-curve>
      <div class="panel-head"><h2>${esc(metric.label)} par jour</h2><div class="right"><span class="muted" style="font-size:13px">${period} derniers jours · ${esc(statsNum(data.tiles[metric.id].value))} sur la période</span></div></div>
      <div class="toolbar" style="margin:16px 24px 0"><div class="seg stats-seg" role="group" aria-label="Métrique de la courbe">${STATS_METRICS.map((m) => `<button type="button" data-stats-metric="${m.id}" class="${m.id === metric.id ? "on" : ""}" aria-pressed="${m.id === metric.id}">${esc(m.label)}</button>`).join("")}</div></div>
      <div class="chart-wrap"><div class="chart">${noPoint ? `<p class="muted stats-empty">TikTok n'affichait aucune valeur pour « ${esc(metric.label)} » sur les relevés.</p>` : chart}</div></div>
      <div class="legend"><span><i></i>${period} derniers jours</span><span><i class="prev"></i>${period} jours précédents</span><span><i class="gap"></i>Jour sans relevé</span></div>
      <div class="pager-note"><span class="note">${icon("info", "i-xs")}<span>Les tuiles viennent du dernier relevé de la page Données analytiques. Un point de la courbe est la valeur de la tuile ${period} jours au dernier relevé du jour : un jour sans relevé reste vide au lieu d'être inventé.</span></span></div>
    </div>`;
}

function statsVideoRow(v) {
  const vis = STATS_VISIBILITY[v.visibility] || (v.visibility ? esc(v.visibility) : "—");
  const proc = v.processing;
  const nums = [statsNum(v.views), statsNum(v.likes), statsNum(v.comments), statsNum(v.shares), statsDuration(v.avg_watch_s), statsPctValue(v.watched_full, 0)];
  const labels = ["Vues", "J'aime", "Commentaires", "Partages", "Temps moyen", "% vu en entier"];
  const origin = v.outside_clipper ? `<span class="chip plain">publié hors Clipper</span>` : `<span class="chip plain ok">clip Clipper</span>`;
  return `<tr class="clickable" tabindex="0" role="link" data-stats-open="${esc(v.post_id)}" aria-label="Fiche : ${esc(v.caption || v.post_id)}">
    <td class="c-thumb"><div class="thumb-p ${proc ? "proc" : ""}" ${proc ? "" : `style="${statsPoster(v.post_id)}"`}><i></i></div></td>
    <td class="c-cap"><div class="cap">${esc(v.caption || "(sans légende)")}</div><div class="vis">${proc ? `<span class="chip warn">En cours de traitement</span>` : `<span class="chip plain ${v.visibility === "public" ? "ok" : ""}">${vis}</span>`}${origin}</div></td>
    <td class="c-date">${esc(statsPostedAt(v.posted_at, v.posted_at_text))}</td>
    ${nums.map((n, i) => `<td class="r ${proc || n === "—" ? "dim" : ""}" data-l="${labels[i]}">${esc(n)}</td>`).join("")}</tr>`;
}

function statsVideosList(account) {
  const videos = statsUi.videos;
  if (!videos || statsUi.videosAccount !== account.account) return `<div class="skeleton skeleton-card"></div>`;
  if (!account.fetched_at) return statsEmpty("inbox", `Aucune publication relevée pour ${account.label}`, "Les publications apparaissent après le premier relevé de la page Contenu de TikTok Studio.");
  if (!videos.length && !statsUi.q) return statsEmpty("film", "Aucune publication sur ce compte", "Le relevé est à jour, mais TikTok Studio ne liste aucune vidéo pour ce compte. Publie un clip depuis Clipper : il apparaîtra ici au relevé suivant.", `<a class="btn" href="#/publish">${icon("send")}Aller à Publication</a>`);
  const sort = statsUi.sort;
  const head = `<th aria-label="Vignette" style="width:56px"></th>` + STATS_COLUMNS.map(([key, label, right]) =>
    `<th class="${right ? "r" : ""}" ${sort.key === key ? `aria-sort="${sort.dir === "asc" ? "ascending" : "descending"}"` : ""}><button type="button" data-stats-sort="${key}">${esc(label)}<span class="arr" aria-hidden="true">${sort.key === key ? (sort.dir === "asc" ? "▲" : "▼") : ""}</span></button></th>`).join("");
  const body = videos.length ? videos.map(statsVideoRow).join("")
    : `<tr><td colspan="9" class="muted" style="text-align:center;padding:32px">Aucune légende ne contient « ${esc(statsUi.q)} ».</td></tr>`;
  return `<div class="panel" data-stats-videos>
    <div class="panel-head"><h2>Vidéos de ${esc(account.label)}</h2><div class="right"><span class="input-ico">${icon("search")}<input class="input" id="stats-q" data-stats-q type="search" placeholder="Filtrer par légende" value="${esc(statsUi.q)}" aria-label="Filtrer par légende" style="width:220px"></span></div></div>
    <div class="sort-m"><select class="input" data-stats-sort-select aria-label="Trier par">${STATS_COLUMNS.map(([key, label]) => `<option value="${key}"${sort.key === key ? " selected" : ""}>Trier : ${esc(label)}</option>`).join("")}</select><button class="btn" type="button" data-stats-sort-dir aria-label="Inverser le tri">${sort.dir === "asc" ? "▲" : "▼"}</button></div>
    <div style="overflow-x:auto"><table class="table ptable"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>
    <div class="pager-note">${icon("info", "i-xs")}<span>${esc(fr(videos.length))} vidéo${videos.length > 1 ? "s" : ""} · cliquer une ligne ouvre sa fiche. Les vidéos en cours de traitement sont relevées à nouveau au prochain passage.</span></div></div>`;
}

/* Barres « libelle · part » d'un onglet Spectateurs / Engagement ; une part est une fraction ou un nombre. */
function statsEntryBars(entries, asPercent) {
  if (!entries || !entries.length) return `<p class="muted stats-empty">TikTok n'affiche rien ici pour l'instant.</p>`;
  const max = Math.max(...entries.map((e) => e.value || 0)) || 1;
  return entries.map((e) => `<div class="src-row"><span>${esc(e.label)}</span><div class="bar"><i style="width:${Math.max(2, Math.round(((e.value || 0) / (asPercent ? 1 : max)) * 100))}%"></i></div><b>${esc(e.value === null ? "—" : asPercent ? statsPctValue(e.value, 0) : fr(e.value))}</b></div>`).join("");
}

const statsFig = (label, value) => `<div class="fig"><div class="l">${esc(label)}</div><div class="v">${esc(value)}</div></div>`;

function statsVideoOverviewTab(v) {
  const hours = v.watch_total_s === null || v.watch_total_s === undefined ? null : v.watch_total_s / 3600;
  const figs = [["Vues de vidéo", statsNum(v.views)], ["Temps de lecture total", hours === null ? "—" : hours >= 1 ? `${fr(hours, 1)} h` : statsDuration(v.watch_total_s)],
    ["Temps de visionnage moyen", statsDuration(v.avg_watch_s)], ["A regardé toute la vidéo", statsPctValue(v.watched_full, 1)],
    ["Nouveaux followers", statsNum(v.new_followers)], ["J'aime", statsNum(v.likes)], ["Commentaires", statsNum(v.comments)], ["Partages", statsNum(v.shares)]];
  const curve = v.retention_curve;
  const retention = curve && curve.length
    ? `<div class="chart">${statsChart({ labels: curve.map((p) => statsDuration(p.t_s)), width: statsChartWidth() > 640 ? 640 : statsChartWidth(), height: 200, max: 100,
      series: [{ values: curve.map((p) => (p.share === null ? null : p.share * 100)) }], fy: (n) => `${fr(Math.round(n))} %`, aria: "Taux de rétention",
      tip: (i) => `à ${statsDuration(curve[i].t_s)} : ${statsPctValue(curve[i].share, 0)} des spectateurs` })}</div>`
    : `<p class="muted stats-empty">${v.retention === null || v.retention === undefined ? "Courbe de rétention non relevée (TikTok ne l'affiche pas encore)." : `Taux de rétention : ${esc(statsPctValue(v.retention, 1))} (courbe non relevée).`}</p>`;
  const sources = v.traffic_sources
    ? `<p>${esc(v.traffic_sources)}</p>`
    : `<div class="reason">${icon("lock", "i-sm")}<span>Sources de trafic <b>disponibles dès 100 vues</b> : TikTok n'affiche pas encore la répartition.</span></div>`;
  const track = (v.history || []).map((h) => ({ label: statsWhen(h.fetched_at), views: h.views }));
  const history = track.length > 1 ? `<div class="panel panel-pad"><div class="section-title">${icon("trending-up")}Vues à chaque relevé</div><div class="chart">${statsChart({
    labels: track.map((t) => t.label.slice(0, 5)), width: statsChartWidth() > 640 ? 640 : statsChartWidth(), height: 180, series: [{ values: track.map((t) => t.views) }],
    aria: "Vues à chaque relevé", tip: (i) => `${track[i].label} : ${track[i].views === null ? "—" : fr(track[i].views)} vues` })}</div></div>` : "";
  return `<div class="stack"><div class="figs">${figs.map(([l, val]) => statsFig(l, val)).join("")}</div>
    <div class="panel"><div class="panel-head"><h2>Taux de rétention</h2><div class="right muted" style="font-size:13px">Part des spectateurs encore présents</div></div><div class="chart-wrap">${retention}</div></div>
    ${history}<div class="panel panel-pad"><div class="section-title">${icon("trending-up")}Sources de trafic</div>${sources}</div></div>`;
}

function statsVideoViewersTab(v) {
  if (!v.viewers) return `<div class="panel panel-pad"><div class="reason">${icon("lock", "i-sm")}<span>Données <b>disponibles dès 100 vues</b> : TikTok n'affiche pas encore les spectateurs de cette vidéo.</span></div></div>`;
  return `<div class="stack"><div class="figs">${statsFig("Total des spectateurs", statsNum(v.viewers.total))}</div>${STATS_VIEWER_SECTIONS.map(([key, label]) =>
    `<div class="panel panel-pad" data-stats-section="${key}"><div class="section-title">${esc(label)}</div>${statsEntryBars(v.viewers[key], true)}</div>`).join("")}</div>`;
}

function statsVideoEngagementTab(v) {
  if (!v.engagement) return `<div class="panel panel-pad"><div class="reason">${icon("lock", "i-sm")}<span>Données <b>disponibles dès 100 vues</b> : TikTok n'affiche pas encore l'engagement de cette vidéo.</span></div></div>`;
  return `<div class="stack"><div class="figs">${statsFig("J'aime", statsNum(v.likes))}${statsFig("Commentaires", statsNum(v.comments))}${statsFig("Partages", statsNum(v.engagement.shares))}</div>
    <div class="panel panel-pad" data-stats-section="likes_over_time"><div class="section-title">J'aime dans le temps</div>${statsEntryBars(v.engagement.likes_over_time, false)}</div>
    <div class="panel panel-pad" data-stats-section="comment_words"><div class="section-title">Mots les plus utilisés dans les commentaires</div>${statsEntryBars(v.engagement.comment_words, false)}</div></div>`;
}

function statsVideoSheet(account) {
  const v = statsUi.video;
  const back = `<a class="btn btn-ghost" href="${statsHref(account.account, "videos")}" data-stats-back>${icon("chevron-left")}Toutes les vidéos</a>`;
  if (!v || v.post_id !== statsRoute().post || statsUi.videoAccount !== account.account) return `${back}<div class="skeleton skeleton-card"></div>`;
  const links = [`<a class="btn" href="${esc(v.post_url)}" target="_blank" rel="noopener noreferrer">${icon("external-link")}<span>Ouvrir sur TikTok</span></a>`];
  if (v.clip) {
    links.push(`<a class="btn" href="#/clips/${encodeURIComponent(v.clip.video_id)}">${icon("clapperboard")}<span>Voir le clip dans Clipper</span></a>`,
      `<a class="btn" href="#/videos/${encodeURIComponent(v.clip.video_id)}">${icon("film")}<span>Vidéo source : ${esc(v.clip.video_id)}</span></a>`);
  }
  const origin = v.outside_clipper ? `<p class="muted" style="font-size:13px;margin-top:12px" data-stats-outside>${icon("info", "i-xs")} Publié hors Clipper : aucun clip ni vidéo source ne correspond à ce post.</p>` : "";
  const vis = STATS_VISIBILITY[v.visibility] || v.visibility || "—";
  const tab = STATS_VIDEO_TABS.some(([id]) => id === statsUi.vtab) ? statsUi.vtab : "overview";
  const content = { overview: statsVideoOverviewTab, viewers: statsVideoViewersTab, engagement: statsVideoEngagementTab }[tab](v);
  return `${back}<div class="video-sheet" data-stats-sheet>
    <div><div class="poster-big" style="${v.processing ? "background:var(--surface-3)" : statsPoster(v.post_id)}"><span>${esc((v.caption || "").split("#")[0].trim() || v.post_id)}</span></div>
      <h2 style="font-size:17px;margin-top:16px">${esc(v.caption || "(sans légende)")}</h2>
      <div class="muted" style="font-size:13px;margin-top:8px">Publié le ${esc(statsPostedAt(v.posted_at, v.posted_at_text))} · <span class="chip plain ${v.visibility === "public" ? "ok" : ""}">${esc(vis)}</span></div>
      <div class="dlinks">${links.join("")}</div>${origin}</div>
    <div><div class="tabs" role="tablist" aria-label="Sections de la fiche">${STATS_VIDEO_TABS.map(([id, label]) => `<button type="button" role="tab" class="${tab === id ? "on" : ""}" aria-selected="${tab === id}" data-stats-vtab="${id}">${esc(label)}</button>`).join("")}</div>
      ${v.processing ? `<div class="reason">${icon("hourglass", "i-sm")}<span><b>TikTok traite encore cette vidéo.</b> Les chiffres arrivent en général dans l'heure qui suit la publication ; Clipper la relèvera au prochain passage.</span></div>` : ""}
      ${content}</div></div>`;
}

/* ---------- relevé a la demande ---------- */

/* Ouvre le Chrome du profil sur ce PC (visible) ; un arret sur (captcha, connexion expiree, compte non pret) revient
   en 409 avec sa raison, affichee telle quelle. */
async function statsScan(account) {
  statsUi.refreshing = true;
  renderCurrent();
  try {
    const sent = await api("/api/stats/tiktok/refresh", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ account: account.account }) });
    const posts = Object.values(sent.accounts).reduce((t, a) => t + (a.posts || 0), 0);
    if (Object.values(sent.accounts).some((a) => a.running)) toast({ kind: "info", title: "Relevé déjà en cours", body: `${account.label} : un relevé tourne déjà, rien n'est relancé.` });
    else toast({ kind: "ok", title: "Relevé terminé", body: `${account.label} : ${posts} publication${posts > 1 ? "s" : ""} relevée${posts > 1 ? "s" : ""}.` });
  } catch (err) {
    toastError("Relevé TikTok impossible", err);
  } finally {
    statsUi.refreshing = false;
    statsUi.at = 0;
    await statsLoad();
  }
}

function statsWire(body, account) {
  const select = $("[data-stats-account]", body);
  if (select) select.onchange = () => { location.hash = statsHref(select.value, statsRoute().tab); };
  $$("[data-stats-period]", body).forEach((b) => (b.onclick = () => { statsUi.period = Number(b.dataset.statsPeriod); renderCurrent(); statsLoad(); }));
  $$("[data-stats-metric]", body).forEach((b) => (b.onclick = () => { statsUi.metric = b.dataset.statsMetric; renderCurrent(); }));
  const scan = $("[data-stats-scan]", body);
  if (scan) scan.onclick = () => statsScan(account);
  $$("[data-stats-sort]", body).forEach((b) => (b.onclick = () => {
    const key = b.dataset.statsSort;
    statsUi.sort = statsUi.sort.key === key ? { key, dir: statsUi.sort.dir === "asc" ? "desc" : "asc" } : { key, dir: key === "caption" ? "asc" : "desc" };
    renderCurrent();
    statsLoad();
  }));
  const sortSelect = $("[data-stats-sort-select]", body);
  if (sortSelect) sortSelect.onchange = () => { statsUi.sort = { key: sortSelect.value, dir: sortSelect.value === "caption" ? "asc" : "desc" }; renderCurrent(); statsLoad(); };
  const sortDir = $("[data-stats-sort-dir]", body);
  if (sortDir) sortDir.onclick = () => { statsUi.sort = { key: statsUi.sort.key, dir: statsUi.sort.dir === "asc" ? "desc" : "asc" }; renderCurrent(); statsLoad(); };
  const search = $("[data-stats-q]", body);
  if (search) {
    let timer = null;
    search.oninput = () => {
      statsUi.q = search.value;
      clearTimeout(timer);
      timer = setTimeout(async () => {
        await statsLoad();
        const again = $("[data-stats-q]");
        if (again) { again.focus(); again.setSelectionRange(again.value.length, again.value.length); }
      }, 250);
    };
  }
  $$("[data-stats-open]", body).forEach((tr) => {
    const open = () => { statsUi.vtab = "overview"; location.hash = statsHref(account.account, "videos", tr.dataset.statsOpen); };
    tr.onclick = open;
    tr.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } };
  });
  $$("[data-stats-vtab]", body).forEach((b) => (b.onclick = () => { statsUi.vtab = b.dataset.statsVtab; renderCurrent(); }));
}

Screens.stats = {
  render(body) {
    if (Date.now() - statsUi.lastRender > STATS_VISIT_GAP_MS) statsUi.opened = {}; // ecran rouvert : nouvelle ouverture
    statsUi.lastRender = Date.now();
    if (!statsUi.accounts || statsUi.key !== statsKey() || Date.now() - statsUi.at > STATS_STALE_MS) statsLoad();
    if (!statsUi.accounts) {
      body.innerHTML = statsUi.error
        ? emptyState("circle-alert", "Chargement impossible", String(statsUi.error.message || statsUi.error))
        : `<div class="skeleton skeleton-line"></div><div class="skeleton skeleton-card"></div><div class="skeleton skeleton-card"></div>`;
      return;
    }
    const account = statsAccount();
    if (!account) {
      body.innerHTML = emptyState("users", "Aucun compte TikTok", "Ajoute un compte dans l'écran Comptes : les statistiques sont relevées compte par compte.", `<a class="btn btn-primary" href="#/accounts">${icon("users")}Aller à Comptes</a>`);
      return;
    }
    const route = statsRoute();
    let pane;
    if (route.tab === "videos" && route.post) pane = statsVideoSheet(account);
    else {
      const count = statsUi.videos && route.tab === "videos" ? statsUi.videos.length : null;
      pane = statsTabs(account, route.tab, count) + (route.tab === "videos" ? statsVideosList(account) : statsOverview(account));
    }
    body.innerHTML = `${statsUi.error ? `<p class="reason bad">Actualisation impossible : ${esc(statsUi.error.message || statsUi.error)}</p>` : ""}${statsControls(account)}${pane}`;
    statsWire(body, account);
  },
};
