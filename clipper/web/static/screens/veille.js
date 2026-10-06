/* Écran « Veille » (SPEC-bdd9 R10, ADR-ca9a), d'après research/maquettes/veille.html. Lit GET /api/veille (état du
   jour ou du dernier relevé, sélection, clés présentes en booléens) et GET /api/clips?archived=1 (titres et scores
   des clips de la sélection). Aucune logique réseau ni LLM ici : « Rafraîchir » dépose une demande
   (POST /api/veille/refresh), « Clipper » / « Ignorer » / « Restaurer » appellent les routes de la veille ; le
   worker fait le reste. Une donnée absente (null) s'affiche avec sa raison, jamais un 0. Charge après screens.js
   dont il remplace l'entrée Screens.veille. */
"use strict";

const VEILLE_STALE_MS = 4000;
const SOURCE_LABELS = { twitch: "Twitch", youtube: "YouTube", steam: "Steam", steam_fr: "Ventes Steam FR" };
const COUNT_LABELS = { games: "jeux", vods: "VOD", videos: "vidéos" };

const veilleUi = { data: null, clips: [], error: null, loading: null, dirty: false, at: 0, style: {}, busy: false, html: "" };

function loadVeille() {
  if (veilleUi.loading) { veilleUi.dirty = true; return veilleUi.loading; }
  veilleUi.loading = (async () => {
    try {
      veilleUi.data = await api("/api/veille");
      veilleUi.clips = await api("/api/clips?archived=1");
      veilleUi.error = null;
      store.veille = veilleUi.data;
    } catch (err) {
      veilleUi.error = err;
    } finally {
      veilleUi.loading = null;
      veilleUi.at = Date.now();
    }
    if (currentScreen === "veille") renderCurrent();
    updateCounts();
    if (veilleUi.dirty) { veilleUi.dirty = false; loadVeille(); }
  })();
  return veilleUi.loading;
}

// Un changement sous state/veille/ (relevé, Clipper, sélection) ou un clip qui bouge rend l'écran obsolète.
document.addEventListener("clipper:event", (e) => {
  const kind = e.detail && e.detail.kind;
  if (kind === "veille" || kind === "publish" || kind === "video") {
    veilleUi.at = 0;
    if (currentScreen === "veille" || kind === "veille") loadVeille();
  }
});

/* ---------- formats ---------- */

const veilleWhen = (iso, withDay) => {
  if (!iso) return "";
  const opts = { hour: "2-digit", minute: "2-digit" };
  if (withDay) Object.assign(opts, { weekday: "short", day: "numeric", month: "short" });
  return new Date(iso).toLocaleString("fr-FR", Object.assign({ timeZone: CLIPPER_TZ }, opts));
};
const veilleDay = (iso) => new Date(iso).toLocaleDateString("fr-FR", { timeZone: CLIPPER_TZ, day: "numeric", month: "short" });
const veilleDuration = (s) => {
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  const p = (n) => String(n).padStart(2, "0");
  return h ? `${h}:${p(m)}:${p(sec)}` : `${m}:${p(sec)}`;
};
const veilleSrcIcon = (source) => `<span class="src-ico src-${esc(source)}" title="${esc(SOURCE_LABELS[source] || source)}">${icon(source === "twitch" ? "tv" : source === "youtube" ? "play" : "users")}</span>`;

/* Δ 7 j d'un jeu : « +80 % », ou la raison de l'absence (jamais un chiffre inventé). */
function veilleDelta(game, kind) {
  if (!game) return `<span class="muted">jeu non relevé</span>`;
  if (kind === "steam" && !game.steam_match) return `<span class="muted">hors Steam</span>`;
  if (kind === "twitch" && game.twitch_match === false) return `<span class="muted">hors Twitch FR</span>`;
  const value = game[`${kind}_delta_pct`];
  if (value == null && kind === "steam" && game.steam_new_in_top) return `<b class="ok">Nouveau dans le top Steam</b>`;
  if (value == null && kind === "steam" && game.steam_rank_gain != null) return `<b class="${game.steam_rank_gain >= 0 ? "ok" : "bad"}">${game.steam_rank_gain > 0 ? "+" : ""}${esc(fr(game.steam_rank_gain))} places</b>`;
  if (value == null) return `<span class="muted">pas assez d'historique (${esc(game.baseline_days_available)} j)</span>`;
  return `<b class="${value >= 0 ? "ok" : "bad"}">${value > 0 ? "+" : ""}${esc(fr(value))} %</b>`;
}

/* Un jeu monte : hausse vs 7 jours (Twitch, Steam) ≥ min %, OU nouveau dans un top Steam (mondial ou ventes FR),
   OU gain de places ≥ gainMin dans l'un de ces tops. */
const veilleRises = (game, min, gainMin = 5) => [game.twitch_delta_pct, game.steam_delta_pct].some((v) => v != null && v >= min)
  || game.steam_new_in_top === true || game.steam_sellers_new === true
  || [game.steam_rank_gain, game.steam_sellers_gain].some((v) => v != null && v >= gainMin);

/* Top des ventes Steam du pays : « #5 (+107 places) », « #3 (nouveau dans le top ventes FR) », ou la raison de l'absence. */
function veilleSellers(game) {
  if (game.steam_sellers_rank == null) return `<span class="muted">hors top ventes FR</span>`;
  const gain = game.steam_sellers_new ? `<b class="ok">Nouveau dans le top ventes FR</b>`
    : game.steam_sellers_gain != null ? `<b class="${game.steam_sellers_gain >= 0 ? "ok" : "bad"}">${game.steam_sellers_gain > 0 ? "+" : ""}${esc(fr(game.steam_sellers_gain))} places</b>` : "";
  return `<span class="mono">#${esc(game.steam_sellers_rank)}</span> ${gain}`;
}

/* ---------- sections ---------- */

function veilleSources(data) {
  const day = data.day;
  const pills = Object.keys(SOURCE_LABELS).map((name) => {
    const s = (day.sources || {})[name];
    if (!s) return `<span class="src-pill">${veilleSrcIcon(name)}${esc(SOURCE_LABELS[name])} : pas relevée</span>`;
    const bad = s.status === "error";
    const counts = Object.entries(s.counts || {}).map(([k, v]) => `${v} ${COUNT_LABELS[k] || k}`).join(", ");
    return `<span class="src-pill${bad ? " bad" : ""}">${veilleSrcIcon(name)}${esc(SOURCE_LABELS[name])}${bad ? " : erreur" : counts ? ` : ${esc(counts)}` : ""}</span>`;
  }).join("");
  const errors = Object.keys(SOURCE_LABELS).filter((n) => (day.sources || {})[n] && day.sources[n].status === "error")
    .map((n) => `<p class="reason bad" role="alert"><b>${esc(SOURCE_LABELS[n])} :</b> ${esc(day.sources[n].error)}</p>`).join("");
  const llm = day.llm || {};
  const llmChip = llm.status === "ok" ? `<span class="chip accent plain">Claude : ${esc(day.proposals.length)} proposition${day.proposals.length > 1 ? "s" : ""}</span>`
    : llm.status === "error" ? `<span class="chip bad plain">Claude : erreur</span>` : `<span class="chip plain">Claude : pas appelé</span>`;
  const llmError = llm.status === "error" ? `<p class="reason bad" role="alert"><b>Choix de Claude :</b> ${esc(llm.error)}</p>` : "";
  const when = data.running ? `<span class="chip running plain">Relevé en cours…</span>`
    : `<span>Relevé du <b class="mono">${esc(veilleWhen(day.finished_at || day.started_at, true))}</b></span>`;
  return `<div data-veille-sources><div class="sources">${when}${pills}${llmChip}</div>${errors}${llmError}</div>`;
}

function veilleKpis(data) {
  const day = data.day, cfg = data.settings || {};
  const rising = (day.games || []).filter((g) => veilleRises(g, cfg.rise_min_pct ?? 50, cfg.steam_rank_gain_min ?? 5)).length;
  const proposed = day.proposals.filter((p) => p.status !== "ignored").length;
  const sel = data.selection || { kept: [], archived: [] };
  const clipKeys = (rows) => new Set(rows.map((r) => `${r.video_id}/${r.clip_id}`)).size;
  const kept = clipKeys(sel.kept), rendered = kept + clipKeys(sel.archived);
  const kpi = (label, value, foot, cls) => `<div class="kpi${cls ? ` ${cls}` : ""}"><div class="kpi-label">${esc(label)}</div><div class="kpi-value">${value}</div><div class="kpi-foot">${esc(foot)}</div></div>`;
  return `<div class="kpis kpis-4" data-veille-kpi>
    ${kpi("Jeux qui montent", esc(rising), `sur ${(day.games || []).length} relevés (≥ ${cfg.rise_min_pct ?? 50} % ou ≥ ${cfg.steam_rank_gain_min ?? 5} places Steam)`, "accent")}
    ${kpi("VOD proposées", `${esc(proposed)}<small>/ ${esc(cfg.max_vods_per_day ?? "?")}</small>`, day.excluded ? `${day.excluded.already_known || 0} déjà connues, ${day.excluded.too_short || 0} trop courtes` : "")}
    ${kpi("Clips gardés", `${esc(kept)}<small>/ ${esc(rendered)} rendus</small>`, `${cfg.best_clips_per_day ?? "?"} meilleurs par jour`)}
    ${kpi("Prochain relevé", data.next_run_at ? esc(veilleWhen(data.next_run_at, true)) : "—", data.enabled ? `à ${cfg.run_at || "?"} (${cfg.timezone || "Europe/Paris"})` : "veille désactivée")}
  </div>`;
}

function veilleProposal(p, game, channels) {
  const c = p.candidate;
  const queued = p.status === "queued";
  const sig = (source, label, html) => `<span class="sig">${veilleSrcIcon(source)}${esc(label)} ${html}</span>`;
  const signals = [
    sig("twitch", "Twitch FR", veilleDelta(game, "twitch")),
    sig("steam", "Steam", veilleDelta(game, "steam")),
    game && game.steam_sellers_rank != null ? sig("steam", "Ventes FR", veilleSellers(game)) : "",
    c.source === "youtube" && c.views_per_hour != null ? sig("youtube", "YouTube", `<b>${esc(fr(Math.round(c.views_per_hour)))} vues/h</b>`) : "",
  ].join("");
  const chosen = veilleUi.style[p.candidate_id] || "";
  const styleSelect = `<select class="input" data-veille-style aria-label="Style"><option value="">Sans style (config.toml)</option>${channels.map((n) => `<option value="${esc(n)}"${n === chosen ? " selected" : ""}>Style : ${esc(n)}</option>`).join("")}</select>`;
  const actions = queued
    ? `<span class="chip queued">en file</span><span class="note">Mise en file à ${esc(veilleWhen(p.decided_at))}${p.channel ? ` avec le style <b class="mono">${esc(p.channel)}</b>` : ""} · ne sera plus proposée.</span><span class="spacer"></span><a class="btn btn-sm btn-ghost" href="#/videos">Voir dans Vidéos</a>`
    : `<a class="btn btn-sm btn-ghost" href="${esc(c.url)}" target="_blank" rel="noopener">Voir la VOD</a><span class="spacer"></span>${styleSelect}<button class="btn btn-sm btn-primary" type="button" data-veille-clip>Clipper</button><button class="btn btn-sm btn-ghost" type="button" data-veille-ignore>Ignorer</button>`;
  const meta = [c.channel_name, c.game_name, c.published_at ? `publié le ${veilleDay(c.published_at)}` : "", c.view_count != null ? `${fr(c.view_count)} vues` : ""].filter(Boolean).map(esc).join(" · ");
  return `<article class="prop${queued ? " queued" : ""}" data-veille-prop="${esc(p.candidate_id)}">
    <div class="prop-thumb"><span class="rank">${esc(p.rank)}</span><div class="art"></div><span class="dur">${esc(veilleDuration(c.duration_s))}</span></div>
    <div class="prop-main">
      <div class="prop-title">${esc(c.title)}</div>
      <div class="prop-meta">${veilleSrcIcon(c.source)}<span>${meta}</span></div>
      <div class="signals">${signals}</div>
      <p class="reason"><b>Pourquoi :</b> ${esc(p.reason)}</p>
      <div class="prop-actions">${actions}</div>
    </div>
  </article>`;
}

function veilleProposals(data, channels) {
  const day = data.day;
  const games = Object.fromEntries((day.games || []).map((g) => [g.key, g]));
  const shown = day.proposals.filter((p) => p.status !== "ignored").sort((a, b) => a.rank - b.rank);
  const ignored = day.proposals.length - shown.length;
  const empty = day.llm && day.llm.status === "error" ? "Claude n'a rien proposé : voir l'erreur ci-dessus."
    : "Aucune VOD proposée aujourd'hui.";
  const note = day.skipped_note ? `<div class="arch-row"><span class="t muted">${esc(day.skipped_note)}</span></div>` : "";
  const excluded = ignored ? `<div class="arch-row"><span class="t muted">${esc(ignored)} proposition${ignored > 1 ? "s" : ""} ignorée${ignored > 1 ? "s" : ""} aujourd'hui : elle${ignored > 1 ? "s ne seront" : " ne sera"} plus proposée${ignored > 1 ? "s" : ""}.</span></div>` : "";
  return `<section data-veille-proposals><div class="panel">
    ${shown.length ? shown.map((p) => veilleProposal(p, games[p.candidate.game_key], channels)).join("") : `<div class="list-item muted">${esc(empty)}</div>`}
    ${note}${excluded}</div></section>`;
}

function veilleClipTitle(c) {
  return `${c.screen_title || c.title || c.clip_id}${c.parts_total > 1 ? ` (${c.part}/${c.parts_total})` : ""}`;
}

function veilleBest(data) {
  const sel = data.selection;
  if (!sel) return `<section data-veille-best><div class="panel"><div class="list-item muted">Aucun clip de veille terminé pour l'instant : la sélection des meilleurs clips du jour apparaît ici.</div></div></section>`;
  const byKey = Object.fromEntries(veilleUi.clips.map((c) => [`${c.video_id}/${c.clip_id}`, c]));
  const clipOf = (row) => byKey[`${row.video_id}/${row.clip_id}`] || { video_id: row.video_id, clip_id: row.clip_id };
  const keptCards = sel.kept.map((row) => {
    const c = clipOf(row);
    return `<div class="clip veille-clip"><div class="mini-clip"><img loading="lazy" alt="" src="/media/clip/${encodeURIComponent(row.video_id)}/${encodeURIComponent(row.clip_id)}/thumbnail"><span class="score">${esc(fr(row.score, 1))}</span></div>
      <div class="clip-title">${esc(veilleClipTitle(c))}</div>
      <div class="veille-clip-actions"><a class="btn btn-xs btn-ghost" href="#/clips/${encodeURIComponent(row.video_id)}">Voir</a><a class="btn btn-xs" href="#/clips/${encodeURIComponent(row.video_id)}">Approuver</a></div></div>`;
  }).join("");
  const archivedRows = sel.archived.map((row) => {
    const c = clipOf(row);
    return `<div class="arch-row" data-veille-archived="${esc(row.video_id)}/${esc(row.clip_id)}"><span class="score">${esc(fr(row.score, 1))}</span><span class="t">${esc(veilleClipTitle(c))}</span><span class="why">rang ${esc(row.rank)}</span><button class="btn btn-xs btn-ghost" type="button" data-veille-restore>${icon("undo-2", "i-xs")}Restaurer</button></div>`;
  }).join("");
  return `<section data-veille-best><div class="panel">
    <div class="panel-head"><h2>Sélection du ${esc(veilleDay(`${sel.date}T12:00:00Z`))}</h2><div class="right"><span class="chip ok plain">${sel.kept.length} gardé${sel.kept.length > 1 ? "s" : ""}</span><span class="chip plain">${sel.archived.length} archivé${sel.archived.length > 1 ? "s" : ""}</span></div></div>
    ${keptCards ? `<div class="clips-grid">${keptCards}</div>` : `<div class="list-item muted">Aucun clip gardé.</div>`}
    ${archivedRows ? `<details class="archived"><summary>${icon("check", "i-xs")}Archivés (${sel.archived.length}) : sous le meilleur du jour, masqués de l'écran Clips, jamais supprimés</summary>${archivedRows}</details>` : ""}
  </div></section>`;
}

function veilleRising(data) {
  const games = [...(data.day.games || [])].sort((a, b) => Math.max(b.twitch_delta_pct ?? -1e9, b.steam_delta_pct ?? -1e9) - Math.max(a.twitch_delta_pct ?? -1e9, a.steam_delta_pct ?? -1e9));
  const num = (v, reason) => (v == null ? `<span class="muted">${esc(reason)}</span>` : esc(fr(v)));
  const rows = games.map((g) => `<tr>
    <td>${esc(g.name)}</td>
    <td class="r">${g.twitch_match === false ? `<span class="muted">hors Twitch FR</span>` : num(g.twitch_fr_viewers, "pas relevé")}</td><td class="r">${veilleDelta(g, "twitch")}</td>
    <td class="r">${g.steam_match ? num(g.steam_players, "pas relevé") : `<span class="muted">hors Steam</span>`}</td><td class="r">${veilleDelta(g, "steam")}</td><td class="r">${veilleSellers(g)}</td>
    <td class="r">${num(g.youtube_views_per_hour == null ? null : Math.round(g.youtube_views_per_hour), "clé absente ou pas de vidéo")}</td>
    <td class="r">${esc(g.vod_count)}</td></tr>`).join("");
  return `<section data-veille-rising><div class="section-title">${icon("trending-up")}Ce qui monte</div><div class="panel">
    ${rows ? `<div class="table-wrap"><table class="table"><thead><tr><th>Jeu</th><th class="r">Twitch FR (viewers)</th><th class="r">Δ 7 j</th><th class="r">Steam (joueurs)</th><th class="r">Δ 7 j</th><th class="r">Ventes FR</th><th class="r">YouTube FR (vues/h)</th><th class="r">VOD FR</th></tr></thead><tbody>${rows}</tbody></table></div>`
      : `<div class="list-item muted">Aucun jeu relevé : vérifie les sources ci-dessus.</div>`}
    <div class="arch-row"><span class="t muted">Un jeu sans correspondance Steam ou hors du top ventes FR l'indique ; une donnée absente est expliquée, aucune valeur n'est inventée.</span></div>
  </div></section>`;
}

function veilleSettings(data) {
  const cfg = data.settings || {};
  const field = (label, value) => `<div class="field"><label>${esc(label)}</label><input class="input" value="${esc(value)}" readonly></div>`;
  const key = (label, set, source) => `<div class="key">${veilleSrcIcon(source)}<span>${esc(label)}</span><span class="chip ${set ? "ok" : "bad"} plain">${set ? "saisie" : "absente"}</span></div>`;
  return `<section data-veille-settings><div class="panel panel-pad stack">
    <div class="form-grid">
      <div class="field full"><label>Mes goûts (texte libre, lu par Claude)</label><textarea class="input" rows="2" readonly>${esc(cfg.taste || "")}</textarea></div>
      ${field("VOD proposées par jour (max)", cfg.max_vods_per_day)}${field("Meilleurs clips gardés par jour", cfg.best_clips_per_day)}
      ${field(`Heure du relevé (${cfg.timezone || "Europe/Paris"})`, cfg.run_at)}${field("Langue des streams / région", `${cfg.language} / ${cfg.region}`)}
    </div>
    <div class="keys">${key("Twitch (client id + secret)", data.twitch_client_id_set && data.twitch_client_secret_set, "twitch")}${key("YouTube (clé API)", data.youtube_api_key_set, "youtube")}
      <div class="key">${veilleSrcIcon("steam")}<span>Steam</span><span class="chip ok plain">sans clé</span></div></div>
    <a class="btn btn-sm" href="#set-veille">Modifier dans Réglages › Veille</a>
  </div></section>`;
}

function veilleView(body) {
  const data = veilleUi.data;
  if (!data.enabled) {
    veilleUi.html = "";
    body.innerHTML = emptyState("trending-up", "Veille désactivée", "La veille propose chaque jour des VOD à clipper d'après ce qui monte sur Twitch, YouTube et Steam. Active-la et saisis tes clés dans Réglages › Veille.", `<a class="btn btn-primary" href="#set-veille">Ouvrir Réglages › Veille</a>`);
    return;
  }
  const refresh = `<button type="button" class="btn" data-veille-refresh${data.running || veilleUi.busy ? " disabled" : ""}>${icon("rotate-ccw", "i-xs")}${data.running ? "Relevé en cours…" : "Rafraîchir"}</button>`;
  if (!data.day) {
    body.innerHTML = `<div class="toolbar"><span class="grow"></span>${refresh}</div>${emptyState("trending-up", "Aucun relevé pour l'instant", `Le premier relevé aura lieu ${data.next_run_at ? `le ${veilleWhen(data.next_run_at, true)}` : "bientôt"} ; « Rafraîchir » le lance maintenant.`)}`;
    return;
  }
  const channels = store.channels || [];
  const html = `<div class="stack">
    <div class="toolbar"><span class="muted">Relevé quotidien à ${esc((data.settings || {}).run_at || "?")} · les VOD déjà clippées ne sont plus proposées.</span><span class="grow"></span>${refresh}</div>
    ${veilleSources(data)}${veilleKpis(data)}${veilleProposals(data, channels)}${veilleBest(data)}${veilleRising(data)}${veilleSettings(data)}
  </div>`;
  if (veilleUi.html === html && body.childElementCount) return;
  veilleUi.html = html;
  body.innerHTML = html;
}

/* ---------- actions ---------- */

async function veilleCall(path, method, payload, okTitle, errTitle) {
  try {
    const result = await api(path, payload === undefined ? { method } : jsonBody(method, payload));
    if (okTitle) toast({ kind: "ok", title: okTitle });
    return result;
  } catch (err) {
    toastError(errTitle, err);
    return null;
  } finally {
    veilleUi.at = 0;
    await loadVeille();
  }
}

function veilleWire(body) {
  const dayDate = () => veilleUi.data.day.date;
  const cand = (el) => el.closest("[data-veille-prop]").dataset.veilleProp;
  $$("[data-veille-style]", body).forEach((s) => (s.onchange = () => { veilleUi.style[cand(s)] = s.value; }));
  $$("[data-veille-refresh]", body).forEach((b) => (b.onclick = async () => {
    veilleUi.busy = true;
    b.disabled = true;
    await veilleCall("/api/veille/refresh", "POST", undefined, "Relevé demandé : le worker le lance", "Impossible de rafraîchir la veille");
    veilleUi.busy = false;
    renderCurrent();
  }));
  $$("[data-veille-clip]", body).forEach((b) => (b.onclick = async () => {
    const id = cand(b);
    b.disabled = true;
    const channel = veilleUi.style[id] || null;
    const entry = await veilleCall(`/api/veille/${encodeURIComponent(dayDate())}/${encodeURIComponent(id)}/clip`, "POST", { channel, short_clips: null }, "VOD mise en file", "Impossible de clipper cette VOD");
    if (entry) { try { await loadQueue(); } catch (err) { toastError("File indisponible", err); } }
  }));
  $$("[data-veille-ignore]", body).forEach((b) => (b.onclick = async () => {
    const id = cand(b);
    if (!(await confirmDialog({ title: "Ignorer cette VOD ?", body: "Elle ne sera plus jamais proposée.", confirmLabel: "Ignorer" }))) return;
    await veilleCall(`/api/veille/${encodeURIComponent(dayDate())}/${encodeURIComponent(id)}/ignore`, "POST", undefined, null, "Impossible d'ignorer cette VOD");
  }));
  $$("[data-veille-restore]", body).forEach((b) => (b.onclick = async () => {
    const [video, clip] = b.closest("[data-veille-archived]").dataset.veilleArchived.split("/");
    b.disabled = true;
    await veilleCall(`/api/veille/clips/${encodeURIComponent(video)}/${encodeURIComponent(clip)}/restore`, "POST", undefined, "Clip restauré", "Impossible de restaurer le clip");
  }));
}

Screens.veille = {
  render(body) {
    if (Date.now() - veilleUi.at > VEILLE_STALE_MS) loadVeille();
    if (!veilleUi.data) {
      body.innerHTML = veilleUi.error
        ? emptyState("circle-alert", "Chargement impossible", String(veilleUi.error.message || veilleUi.error))
        : `<div class="skeleton skeleton-line"></div><div class="skeleton skeleton-card"></div><div class="skeleton skeleton-card"></div>`;
      return;
    }
    veilleView(body);
    veilleWire(body);
  },
};
