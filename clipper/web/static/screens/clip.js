/* Ecran « Fiche clip » (TASK-fa7619ccf83a) : #/clip/<video_id>/<clip_id>. Lit GET /api/clips/.../sheet, lecture seule :
   rien n'est recalcule ici. Une donnee absente s'affiche « inconnu », jamais 0 (ADR-ad2e). Une video supprimee
   (.mp4 absent) garde la fiche avec la mention « vidéo supprimée, fiche conservée ». */
"use strict";

const clipSheetUi = { key: null, data: null, error: null, loading: null, at: 0 };
const CLIP_SHEET_STALE_MS = 4000;

/* Cle (video/clip) lue dans l'adresse #/clip/<video_id>/<clip_id>. */
function clipSheetHashKey() {
  const parts = location.hash.replace(/^#\/?/, "").split("?")[0].split("/");
  if (parts[0] !== "clip" || !parts[1] || !parts[2]) return null;
  return { video: decodeURIComponent(parts[1]), clip: decodeURIComponent(parts[2]) };
}

function loadClipSheet(target) {
  const key = `${target.video}/${target.clip}`;
  if (clipSheetUi.loading && clipSheetUi.key === key) return clipSheetUi.loading;
  clipSheetUi.key = key;
  clipSheetUi.data = null;
  clipSheetUi.error = null;
  clipSheetUi.loading = (async () => {
    try {
      const url = `/api/clips/${encodeURIComponent(target.video)}/${encodeURIComponent(target.clip)}/sheet`;
      const data = await api(url);
      if (clipSheetUi.key === key) clipSheetUi.data = data;
    } catch (err) {
      if (clipSheetUi.key === key) clipSheetUi.error = err;
    } finally {
      if (clipSheetUi.key === key) clipSheetUi.loading = null;
      clipSheetUi.at = Date.now();
    }
    if (currentScreen === "clip") renderCurrent();
  })();
  return clipSheetUi.loading;
}

/* Valeur affichee : « inconnu » quand la donnee manque (null / undefined / vide). */
const sheetVal = (v, suffix) => (v == null || v === "" ? "inconnu" : esc(`${v}${suffix || ""}`));
const sheetRow = (label, value) => `<div class="sheet-row"><span class="muted">${esc(label)}</span><span>${value}</span></div>`;
const sheetLink = (url, text) => (url ? `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(text || url)}</a>` : "inconnu");

function clipSheetVideoHtml(video) {
  if (video.deleted || !video.video_url) {
    return `<div class="empty"><p>${esc(video.note || "vidéo supprimée, fiche conservée")}</p></div>`;
  }
  return `<video controls preload="metadata" playsinline src="${esc(video.video_url)}" style="width:100%;max-height:70vh;border-radius:12px;background:#000"></video>`;
}

function clipSheetJuryHtml(jury) {
  const judges = jury.judges && typeof jury.judges === "object"
    ? Object.entries(jury.judges).map(([name, value]) => sheetRow(`Juge ${name}`, sheetVal(value))).join("")
    : "";
  const rounds = (jury.rounds || []).map((r) => sheetRow(`Tour ${r.round}`, Object.entries(r.judges || {}).map(([name, j]) =>
    `${esc(name)} : note ${sheetVal(j.score)}, confiance ${sheetVal(j.confidence)}${j.argument ? ` — ${esc(j.argument)}` : ""}`,
  ).join("<br>") || "inconnu")).join("");
  return `${sheetRow("Confiance du jury", sheetVal(jury.confidence))}${judges}${rounds || sheetRow("Tours du jury", "inconnu")}`;
}

function clipSheetScoresHtml(scores) {
  if (!scores || typeof scores !== "object" || !Object.keys(scores).length) return sheetRow("Critères", "inconnu");
  return Object.entries(scores).map(([name, value]) => sheetRow(name, sheetVal(value))).join("");
}

function clipSheetStatsHtml(stats, clip) {
  if (!stats) {
    const reason = clip.post_url || clip.post_id ? "pas de relevé pour ce post" : "aucun post lié à ce clip";
    return `<p class="muted">Statistiques : inconnu (${esc(reason)}).</p>`;
  }
  if (stats.error) return `<p class="muted">Statistiques indisponibles : ${esc(stats.error)}</p>`;
  const history = (stats.history || []).map((h) => sheetRow(
    h.fetched_at ? h.fetched_at.replace("T", " ").slice(0, 16) : "relevé",
    `vues ${sheetVal(h.views)} · likes ${sheetVal(h.likes)} · commentaires ${sheetVal(h.comments)}`,
  )).join("");
  return `${sheetRow("Vues", sheetVal(stats.views))}${sheetRow("Likes", sheetVal(stats.likes))}${history}`;
}

function clipSheetHtml(sheet) {
  const { clip, video, jury, stats } = sheet;
  const s = clipStatus(clip);
  const qa = clip.qa_status ? `${clip.qa_status}${clip.issues && clip.issues.length ? ` (${clip.issues.join(", ")})` : ""}` : "inconnu";
  return `
    <div class="sheet-head">
      <span class="chip ${s.cls}">${esc(s.label)}</span>
      <h2>${esc(clip.screen_title || clip.title || clip.clip_id)}</h2>
      <p class="muted">${esc(video.title || clip.video_id)} · ${esc(clip.video_id)} / ${esc(clip.clip_id)}</p>
    </div>
    <div class="sheet-grid">
      <section class="panel"><h3>Vidéo</h3>${clipSheetVideoHtml(video)}
        ${sheetRow("Passage source", sheetLink(video.passage_url, "Voir le passage"))}
        ${sheetRow("Source", sheetLink(video.source_url, "Vidéo source"))}
      </section>
      <section class="panel"><h3>Clip</h3>
        ${sheetRow("Titre d'écran", sheetVal(clip.screen_title))}
        ${sheetRow("Légende", sheetVal(clip.caption))}
        ${sheetRow("Score", sheetVal(clip.score))}
        ${clipSheetScoresHtml(clip.scores)}
        ${sheetRow("Raison", sheetVal(clip.reason))}
        ${sheetRow("Accroche", sheetVal(clip.hook_text))}
        ${sheetRow("Début / fin dans la VOD", clip.start == null ? "inconnu" : `${fr(clip.start, 1)} s → ${fr(clip.end, 1)} s`)}
        ${sheetRow("Durée", clip.duration == null ? "inconnu" : clipSeconds(clip.duration))}
        ${sheetRow("Format", sheetVal(clip.layout))}
        ${sheetRow("Contrôle qualité", esc(qa))}
      </section>
      <section class="panel"><h3>Jury</h3>${clipSheetJuryHtml(jury)}</section>
      <section class="panel"><h3>Publication</h3>
        ${sheetRow("Compte", sheetVal(clip.account))}
        ${sheetRow("Statut", esc(s.label))}
        ${sheetRow("Créneau", sheetVal(clip.slot_at_paris))}
        ${sheetRow("Publié le", sheetVal(clip.published_at_paris))}
        ${sheetRow("Lien du post", sheetLink(clip.post_url))}
        ${clip.publish_error ? sheetRow("Erreur", esc(clip.publish_error)) : ""}
      </section>
      <section class="panel"><h3>Statistiques</h3>${clipSheetStatsHtml(stats, clip)}</section>
    </div>`;
}

Screens.clip = {
  render(body) {
    const target = clipSheetHashKey();
    if (!target) {
      body.innerHTML = emptyState("circle-alert", "Clip introuvable", "Adresse de fiche incomplète : ouvre un clip depuis l'écran Clips.");
      return;
    }
    const key = `${target.video}/${target.clip}`;
    if (clipSheetUi.key !== key || (Date.now() - clipSheetUi.at > CLIP_SHEET_STALE_MS && !clipSheetUi.loading)) loadClipSheet(target);
    if (clipSheetUi.error) {
      body.innerHTML = emptyState("circle-alert", "Chargement impossible", String(clipSheetUi.error.message || clipSheetUi.error));
      return;
    }
    if (!clipSheetUi.data) {
      body.innerHTML = `<div class="skeleton skeleton-line"></div><div class="skeleton skeleton-card"></div>`;
      return;
    }
    body.innerHTML = clipSheetHtml(clipSheetUi.data);
  },
};
