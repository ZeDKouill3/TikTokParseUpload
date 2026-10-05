/* Ecran « Clips » (SPEC-c100 E4, SPEC-74e9 §4.5). Lit GET /api/clips ; la galerie
   9:16 ouvre une fiche (lecteur, sidecar, QA, edition en place). Aucune logique
   video ici : le texte passe par PATCH /api/clips/.../ (publish.edit_caption), le
   titre d'ecran et « Re-rendre » par la file de traitement. Charge apres
   screens.js dont il remplace l'entree Screens.clips. */
"use strict";

const CLIP_FILTERS = [
  ["à valider", "À valider"], ["approved", "Approuvés"], ["scheduled", "Planifiés"],
  ["published", "Publiés"], ["failed", "Échecs"], ["rejected", "Refusés"], ["refused_by_platform", "Refusés par TikTok"], ["all", "Tous"],
];
const CLIP_STATUS = {
  "à valider": { label: "À valider", cls: "info" }, approved: { label: "Approuvé", cls: "ok" },
  scheduled: { label: "Planifié", cls: "info" }, published: { label: "Publié", cls: "ok" },
  failed: { label: "Échec", cls: "bad" }, rejected: { label: "Refusé", cls: "bad" },
  refused_by_platform: { label: "Refusé par TikTok", cls: "bad" },
  not_ready: { label: "Pas prêt", cls: "pending" }, // rendu ou contrôle qualité pas terminé : ni à valider ni refusé
};
// SPEC-74e9 §4.5 : une entree scheduled/published n'est pas editable sans repasser approved.
const CLIP_LOCKED = ["scheduled", "published"];
const CLIPS_STALE_MS = 4000;
const CLIPS_PAGE_SIZE = 24; // la galerie n'affiche que 24 clips a la fois (« Afficher plus »)

const clipsUi = { data: null, error: null, loading: null, dirty: false, at: 0, filter: "à valider", channel: "", video: "", hashVideo: null, html: "", shown: CLIPS_PAGE_SIZE, selecting: false, selected: new Set() };

/* Vidéo visée par l'adresse : #/clips/<video_id> (lien « Voir les N clips » de la fiche vidéo), sinon "". */
const clipsHashVideo = () => decodeURIComponent((location.hash.replace(/^#\/?/, "").split("?")[0].split("/")[1] || ""));

/* Clips affichés : statut, style et vidéo choisis (chaque filtre vide = pas de filtre). L'ordre reçu (plus récents en haut) est gardé. */
function clipsFiltered(all, ui) {
  return all.filter((c) => (ui.filter === "all" || c.publish_status === ui.filter) && (!ui.channel || c.channel === ui.channel) && (!ui.video || c.video_id === ui.video));
}

const clipKey = (c) => `${c.video_id}/${c.clip_id}`;
/* Libelle d'un compte avec son service (« ClipManiaq3 (YouTube) ») : un meme nom peut exister sur TikTok et YouTube. */
const clipsAccountText = (a) => {
  const service = a.service_label || (a.service === "youtube" ? "YouTube" : a.service === "tiktok" ? "TikTok" : "");
  return `${a.label || a.id}${service ? ` (${service})` : ""}`;
};
const clipUrl = (c, tail) => `/api/clips/${encodeURIComponent(c.video_id)}/${encodeURIComponent(c.clip_id)}${tail || ""}`;
const clipStatus = (c) => CLIP_STATUS[c.publish_status] || { label: c.publish_status, cls: "pending" };
const clipSeconds = (s) => `${fr(s, 1)} s`;

function loadClips() {
  if (clipsUi.loading) { clipsUi.dirty = true; return clipsUi.loading; }
  clipsUi.loading = (async () => {
    try {
      clipsUi.data = await api("/api/clips");
      clipsUi.error = null;
    } catch (err) {
      clipsUi.error = err;
    } finally {
      clipsUi.loading = null;
      clipsUi.at = Date.now();
    }
    if (currentScreen === "clips") renderCurrent();
    if (clipsUi.dirty) { clipsUi.dirty = false; loadClips(); }
  })();
  return clipsUi.loading;
}

// Un evenement publish/video/queue rend la liste obsolete (le serveur reste la source).
document.addEventListener("clipper:event", () => {
  clipsUi.at = 0;
  if (currentScreen === "clips") loadClips();
});

function clipCaptionText(c) {
  return [c.description || "", (c.hashtags || []).join(" ")].filter(Boolean).join("\n\n");
}

function clipCard(c) {
  const s = clipStatus(c);
  const warn = c.qa_status === "rejected" ? "bad" : (c.issues && c.issues.length ? "warn" : "");
  const sel = clipsUi.selecting;
  const checked = sel && clipsUi.selected.has(clipKey(c));
  const label = sel
    ? `${checked ? "Désélectionner" : "Sélectionner"} ${esc(c.screen_title || c.clip_id)}`
    : `Ouvrir le clip ${esc(c.screen_title || c.clip_id)}`;
  return `<div class="clip${sel ? " selecting" : ""}${checked ? " checked" : ""}" data-clip="${esc(clipKey(c))}" tabindex="0" role="${sel ? "checkbox" : "button"}"${sel ? ` aria-checked="${checked}"` : ""} aria-label="${label}">
    <div class="clip-poster"><img loading="lazy" decoding="async" width="270" height="480" src="${esc(c.thumbnail_url)}" alt="" tabindex="-1"><div class="shade"></div>
      <div class="top">${sel ? `<span class="clip-check${checked ? " on" : ""}">${checked ? icon("check", "i-xs") : ""}</span>` : `<span class="pill-dark ${s.cls}">${esc(s.label)}</span>`}${c.parts_total > 1 ? `<span class="pill-dark">${esc(c.part)}/${esc(c.parts_total)}</span>` : ""}</div>
      <span class="play">${icon("play")}</span>
      <div class="bottom"><span class="num">${c.duration != null ? esc(clipSeconds(c.duration)) : ""}</span><span class="grow"></span>
        ${warn ? `<span class="pill-dark ${warn}">${icon("triangle-alert", "i-xs")}QA</span>` : ""}${c.score != null ? `<span class="pill-dark">${esc(fr(c.score))}</span>` : ""}</div>
    </div>
    <div class="clip-title">${esc(c.screen_title || c.title || c.clip_id)}</div>
    <div class="clip-sub"><span class="mono">${esc(c.video_id)}</span>${c.channel ? `<span class="tag">${esc(c.channel)}</span>` : ""}</div>
  </div>`;
}

/* Barre de selection groupee (TASK-e99b) : nombre selectionne, compte (prets seulement), approuver / annuler. */
function clipsSelectionBarHtml() {
  const n = clipsUi.selected.size;
  return `<div class="sel-bar" id="clips-selbar">
    <span>${n} clip${n === 1 ? "" : "s"} sélectionné${n === 1 ? "" : "s"}</span>
    <select class="input" id="clips-sel-account" aria-label="Compte de publication"><option value="">Chargement…</option></select>
    <span class="grow"></span>
    <button type="button" class="btn btn-ghost" data-clips-sel-cancel>Annuler</button>
    <button type="button" class="btn btn-ok" data-clips-sel-approve${n ? "" : " disabled"}>${icon("check", "i-xs")}Approuver la sélection</button>
  </div>`;
}

function clipsEmpty(all) {
  if (!all.length) return emptyState("clapperboard", "Aucun clip", "Ajoute une vidéo : les clips rendus apparaîtront ici.", addVideoButton);
  return emptyState("party-popper", "Aucun clip dans cette catégorie", "Change de filtre pour voir les autres clips.");
}

function clipsView(body) {
  const all = clipsUi.data;
  const filtered = clipsFiltered(all, clipsUi);
  const channels = Array.from(new Set(all.map((c) => c.channel).filter(Boolean))).sort();
  const videos = Array.from(new Set([...all.map((c) => c.video_id), clipsUi.video].filter(Boolean))).sort();
  const rest = filtered.length - clipsUi.shown;
  const more = rest > 0
    ? `<div class="row" style="justify-content:center;margin-top:24px"><button type="button" class="btn" data-clips-more>Afficher plus<span class="n">${esc(Math.min(rest, CLIPS_PAGE_SIZE))}</span></button></div>` : "";
  const scoped = clipsFiltered(all, { filter: "all", channel: clipsUi.channel, video: clipsUi.video }); // les compteurs suivent les filtres vidéo et style
  const count = (k) => (k === "all" ? scoped.length : scoped.filter((c) => c.publish_status === k).length);
  const html = `
    ${clipsUi.error ? `<p class="reason bad">Actualisation impossible : ${esc(clipsUi.error.message || clipsUi.error)}</p>` : ""}
    <div class="toolbar">
      <div class="seg" id="clips-filter">${CLIP_FILTERS.map(([k, l]) => `<button type="button" data-filter="${esc(k)}" class="${k === clipsUi.filter ? "on" : ""}">${esc(l)}<span class="n">${count(k)}</span></button>`).join("")}</div>
      <span class="grow"></span>
      <select class="input" id="clips-video" aria-label="Vidéo"><option value="">Toutes les vidéos</option>${videos.map((v) => `<option value="${esc(v)}"${v === clipsUi.video ? " selected" : ""}>${esc(v)}</option>`).join("")}</select>
      ${clipsUi.video ? `<button type="button" class="btn btn-xs" data-clear-video aria-label="Retirer le filtre vidéo">${icon("x", "i-xs")}Vidéo : ${esc(clipsUi.video)}</button>` : ""}
      <select class="input" id="clips-channel" aria-label="Style"><option value="">Tous les styles</option>${channels.map((n) => `<option value="${esc(n)}"${n === clipsUi.channel ? " selected" : ""}>${esc(n)}</option>`).join("")}</select>
      ${!clipsUi.selecting ? `<button type="button" class="btn btn-xs" data-clips-select>${icon("list-checks", "i-xs")}Sélectionner</button>` : ""}
    </div>
    ${filtered.length ? `<div class="clips">${filtered.slice(0, clipsUi.shown).map(clipCard).join("")}</div>${more}` : clipsEmpty(all)}
    ${clipsUi.selecting ? clipsSelectionBarHtml() : ""}`;
  if (clipsUi.html === html && body.childElementCount) return; // rien de change : on garde les vignettes en place
  clipsUi.html = html;
  body.innerHTML = html;
}

/* Le filtre vidéo vit dans l'adresse (#/clips/<video_id>) : lien partageable, bouton Retour qui marche. */
function clipsSetVideo(video) {
  location.hash = video ? `#/clips/${encodeURIComponent(video)}` : "#/clips";
}

function clipsWire(body) {
  const video = $("#clips-video", body);
  if (video) video.onchange = () => clipsSetVideo(video.value);
  const clear = $("[data-clear-video]", body);
  if (clear) clear.onclick = () => clipsSetVideo("");
  $$("[data-filter]", body).forEach((b) => (b.onclick = () => { clipsUi.filter = b.dataset.filter; clipsUi.shown = CLIPS_PAGE_SIZE; renderCurrent(); }));
  const sel = $("#clips-channel", body);
  if (sel) sel.onchange = () => { clipsUi.channel = sel.value; clipsUi.shown = CLIPS_PAGE_SIZE; renderCurrent(); };
  const more = $("[data-clips-more]", body);
  if (more) more.onclick = () => { clipsUi.shown += CLIPS_PAGE_SIZE; renderCurrent(); };
  $$("[data-clip]", body).forEach((el) => {
    const act = () => (clipsUi.selecting ? clipsToggleSelect(el.dataset.clip) : openClipDrawer(el.dataset.clip));
    el.onclick = act;
    el.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); act(); } };
  });
  const selectBtn = $("[data-clips-select]", body);
  if (selectBtn) selectBtn.onclick = () => { clipsUi.selecting = true; clipsUi.selected = new Set(); renderCurrent(); };
  const selBar = $("#clips-selbar", body);
  if (selBar) {
    clipsFillSelAccounts($("#clips-sel-account", selBar));
    $("[data-clips-sel-cancel]", selBar).onclick = () => { clipsUi.selecting = false; clipsUi.selected = new Set(); renderCurrent(); };
    const approveBtn = $("[data-clips-sel-approve]", selBar);
    if (approveBtn) approveBtn.onclick = () => clipsApproveSelection($("#clips-sel-account", selBar).value);
  }
}

/* Cocher une partie coche toute sa serie (TASK-e99b) : meme decision groupee que l'approbation groupee cote serveur. */
function clipsToggleSelect(key) {
  const c = clipsUi.data.find((o) => clipKey(o) === key);
  if (!c) return;
  const series = clipSeries(c);
  const group = series.length ? series.map(clipKey) : [key];
  const adding = !clipsUi.selected.has(key);
  group.forEach((k) => (adding ? clipsUi.selected.add(k) : clipsUi.selected.delete(k)));
  if (adding && group.length > 1) {
    toast({ kind: "info", title: "Série ajoutée", body: `${group.length} parties sélectionnées ensemble : cocher une partie coche toute sa série.`, ms: 3200 });
  }
  renderCurrent();
}

/* Compte de publication de la barre de selection : comptes prets seulement (SPEC-00d1 R4). */
async function clipsFillSelAccounts(select) {
  try {
    const out = await api("/api/publish/accounts");
    const ready = out.accounts.filter((a) => a.ready_to_publish);
    const options = ready.map((a) => `<option value="${esc(a.id)}">${esc(clipsAccountText(a))}</option>`);
    options.unshift(`<option value="">${ready.length ? "Choisis un compte" : "Aucun compte prêt à publier"}</option>`);
    select.innerHTML = options.join("");
  } catch (err) {
    select.innerHTML = `<option value="">Comptes indisponibles</option>`;
  }
}

/* Approbation groupee (TASK-e99b) : meme decision que /approve pour chaque clip, tout ou rien cote serveur. */
async function clipsApproveSelection(account) {
  if (!account) { toast({ kind: "warn", title: "Compte manquant", body: "Choisis le compte qui publiera la sélection." }); return; }
  const clips = Array.from(clipsUi.selected).map((key) => {
    const [video_id, clip_id] = key.split("/");
    return { video_id, clip_id };
  });
  if (!clips.length) return;
  if (!(await netGuard())) return;
  try {
    const approved = await api("/api/clips/approve", jsonBody("POST", { clips, account }));
    clipsUi.selecting = false;
    clipsUi.selected = new Set();
    renderCurrent();
    toast({ kind: "ok", title: "Clips approuvés", body: `${approved.length} clip${approved.length === 1 ? "" : "s"} approuvé${approved.length === 1 ? "" : "s"}.` });
    loadClips();
  } catch (err) {
    const refused = err.body && Array.isArray(err.body.refused) ? err.body.refused : null;
    toastError("Approbation impossible", refused ? Object.assign(new Error(`${err.message} : ${refused.join(" ; ")}`), { body: err.body }) : err);
  }
}

/* ---------- Fiche d'un clip ---------- */

const clipSeries = (c) => (c.parts_total > 1
  ? clipsUi.data.filter((o) => o.video_id === c.video_id && o.parts_total === c.parts_total && o.clip_id.split("-p")[0] === c.clip_id.split("-p")[0])
    .sort((a, b) => a.part - b.part)
  : []);

function clipQaBlock(c) {
  if (c.qa_status == null) return `<div class="qa-item">${icon("triangle-alert", "i-sm")}<span>Contrôle qualité absent du sidecar de ce clip.</span></div>`;
  const issues = c.issues || [];
  if (!issues.length && c.qa_status !== "rejected") {
    return `<div class="qa-item ok">${icon("circle-check", "i-sm")}<span>Contrôle qualité : ${esc(c.qa_status === "skipped" ? "non exécuté" : "aucun problème")}.</span></div>`;
  }
  const head = c.qa_status === "rejected" ? `<div class="qa-item">${icon("circle-x", "i-sm")}<span><b>Refusé par le contrôle qualité</b></span></div>` : "";
  return head + issues.map((q) => `<div class="qa-item">${icon("triangle-alert", "i-sm")}<span>${esc(typeof q === "string" ? q : JSON.stringify(q))}</span></div>`).join("");
}

function clipDrawerHtml(c) {
  const s = clipStatus(c);
  const locked = CLIP_LOCKED.includes(c.publish_status);
  const series = clipSeries(c);
  const lockHint = locked ? `<span class="hint">Statut « ${esc(s.label.toLowerCase())} » : l'édition demande de repasser le clip en « approuvé ».</span>` : "";
  const sidecar = JSON.stringify(c, null, 2);
  return `
    <div class="drawer-head">
      <span class="chip ${s.cls}">${esc(s.label)}</span>
      <h2>${esc(c.screen_title || c.clip_id)}</h2>
      <button type="button" class="icon-btn" data-dismiss aria-label="Fermer">${icon("x")}</button>
    </div>
    <div class="drawer-body">
      <div>
        <div class="phone"><video src="${esc(c.video_url)}" controls playsinline preload="metadata"></video></div>
        ${series.length ? `<div class="parts-label muted">Parties</div><div class="parts">${series.map((p) => `<button type="button" class="part ${p.clip_id === c.clip_id ? "on" : ""}" data-part="${esc(clipKey(p))}" title="Partie ${esc(p.part)}" aria-label="Partie ${esc(p.part)}">${esc(p.part)}</button>`).join("")}</div>` : ""}
        <div class="row" style="justify-content:center;margin-top:16px;gap:16px;font-size:13px">
          ${c.duration != null ? `<span class="mono">${esc(clipSeconds(c.duration))}</span><span class="muted">·</span>` : ""}<span class="mono">1080×1920</span>${c.score != null ? `<span class="muted">·</span><span>score <b class="num" style="font-size:16px">${esc(fr(c.score))}</b></span>` : ""}
        </div>
      </div>
      <div class="stack" style="gap:24px">
        <div class="row wrap muted" style="font-size:13px;gap:8px"><span class="mono">${esc(c.video_id)}</span>${c.channel ? `<span class="tag">${esc(c.channel)}</span>` : ""}${c.parts_total > 1 ? `<span>·</span><span>partie ${esc(c.part)}/${esc(c.parts_total)}</span>` : ""}${c.slot_at ? `<span>·</span><span>créneau ${esc(fmtParis(c.slot_at, { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }))}</span>` : ""}</div>
        ${c.publish_error ? `<p class="reason bad">Publication en échec : ${esc(c.publish_error)}</p>` : ""}
        <div class="field"><label for="clip-title">Titre d'écran</label><input class="input" id="clip-title" value="${esc(c.screen_title)}"${locked ? " disabled" : ""}>
          <span class="hint">Affiché en haut du clip. Le modifier relance le rendu puis le contrôle qualité de ce clip.</span>
          <div><button type="button" class="btn btn-xs" data-save-title${locked ? " disabled" : ""}>${icon("refresh-cw", "i-xs")}Enregistrer et re-rendre</button></div></div>
        <div class="field"><label for="clip-desc">Description</label><textarea class="input" id="clip-desc" rows="4"${locked ? " disabled" : ""}>${esc(c.description)}</textarea></div>
        <div class="field"><label for="clip-tags">Hashtags</label><input class="input" id="clip-tags" value="${esc((c.hashtags || []).join(" "))}"${locked ? " disabled" : ""}>
          <span class="hint">Séparés par des espaces.</span></div>
        ${lockHint}
        <div class="field" data-clip-account-field><label for="clip-account">Compte de publication</label>
          <select class="input" id="clip-account" data-clip-account><option value="">Chargement…</option></select>
          <span class="hint" data-clip-account-hint>Choisis le compte qui publiera ce clip ; seuls les comptes « prêts à publier » (écran Comptes) sont proposés, avec les créneaux du compte.</span></div>
        <div><button type="button" class="btn btn-xs" data-save-caption${locked ? " disabled" : ""}>${icon("check", "i-xs")}Enregistrer la description et les hashtags</button></div>
        <div class="field"><span class="field-label">Contrôle qualité</span>${clipQaBlock(c)}</div>
        <div class="field"><span class="field-label">Confiance du jury</span><div data-jury-confidence>${juryConfidenceHtml(c.jury_confidence, c.jury_judge_confidences)}</div></div>
        <details><summary class="muted" style="cursor:pointer;font-size:13px">Sidecar JSON (SPEC-6a47)</summary><div class="code" style="margin-top:8px">${esc(sidecar)}</div></details>
      </div>
    </div>
    <div class="drawer-foot">
      ${c.publish_status === "à valider" || c.publish_status === "approved" ? `<button type="button" class="btn btn-primary" data-publish-now>${icon("send")}Publier maintenant</button>` : ""}
      ${c.publish_status === "à valider" || c.publish_status === "approved" ? `<button type="button" class="btn btn-ok" data-approve>${icon("check")}Approuver</button>` : ""}
      <button type="button" class="btn btn-bad" data-reject>${icon("x")}Refuser</button>
      <button type="button" class="btn" data-rerender>${icon("refresh-cw")}Re-rendre</button>
      <span class="grow"></span>
      <button type="button" class="btn btn-ghost" data-copy>${icon("copy")}Copier la description</button>
      <a class="btn btn-ghost" href="${esc(c.video_url)}" download="${esc(c.clip_id)}.mp4">${icon("download")}Télécharger</a>
    </div>`;
}

/* Compte de publication (SPEC-00d1 R4, SPEC-6076 R2) : les comptes prêts, à choisir à chaque publication (un style n'a plus de compte). */
async function clipFillAccounts(c, d) {
  const select = $("#clip-account", d), hint = $("[data-clip-account-hint]", d);
  try {
    const out = await api("/api/publish/accounts");
    const ready = out.accounts.filter((a) => a.ready_to_publish);
    const options = ready.map((a) => `<option value="${esc(a.id)}">${esc(clipsAccountText(a))}</option>`);
    options.unshift(`<option value="">Choisis un compte</option>`);
    if (!ready.length) hint.textContent = "Aucun compte prêt à publier : connecte-en un dans l'écran Comptes.";
    select.innerHTML = options.join("");
  } catch (err) {
    select.innerHTML = `<option value="">Comptes indisponibles</option>`;
    hint.textContent = String(err.message || err);
  }
}

function parseHashtags(text) {
  return text.split(/[\s,]+/).filter(Boolean).map((t) => (t.startsWith("#") ? t : `#${t}`));
}

/* Remplace le clip dans la liste locale et rafraichit la galerie sous la fiche. */
function clipsReplace(updated) {
  const i = clipsUi.data.findIndex((c) => c.video_id === updated.video_id && c.clip_id === updated.clip_id);
  if (i >= 0) clipsUi.data[i] = updated;
  renderCurrent();
}

async function clipSaveCaption(c, description, hashtags, undoable) {
  const previous = { description: c.description, hashtags: c.hashtags };
  try {
    const out = await api(clipUrl(c), jsonBody("PATCH", { description, hashtags }));
    clipsReplace(out.clip);
    toast({
      kind: "ok", title: undoable ? "Texte enregistré" : "Texte rétabli", body: c.screen_title || c.clip_id,
      undo: undoable ? () => clipSaveCaption(out.clip, previous.description, previous.hashtags, false) : null,
    });
    return out.clip;
  } catch (err) {
    toastError("Impossible d'enregistrer le texte", err);
    return null;
  }
}

async function openClipDrawer(key) {
  const c = clipsUi.data.find((o) => clipKey(o) === key);
  if (!c) return;
  const el = openPanel("drawer", clipDrawerHtml(c), (d) => {
    $$("[data-part]", d).forEach((b) => (b.onclick = () => { closeLayer(); setTimeout(() => openClipDrawer(b.dataset.part), 340); }));
    $("[data-save-caption]", d).onclick = () => clipSaveCaption(c, $("#clip-desc", d).value, parseHashtags($("#clip-tags", d).value), true);
    $("[data-save-title]", d).onclick = async () => {
      const title = $("#clip-title", d).value.trim();
      if (!title) { toast({ kind: "warn", title: "Titre d'écran vide", body: "Écris un titre avant de re-rendre." }); return; }
      if (!(await confirmDialog({ title: "Re-rendre ce clip ?", body: `Le titre « ${title} » relance le rendu puis le contrôle qualité de ce clip. Le fichier vidéo sera remplacé.`, confirmLabel: "Re-rendre", danger: false }))) return;
      try {
        await api(clipUrl(c), jsonBody("PATCH", { screen_title: title, confirm: true }));
        closeLayer();
        toast({ kind: "ok", title: "Re-rendu en file", body: `${c.video_id} : rendu puis contrôle qualité.` });
      } catch (err) { toastError("Impossible de relancer le rendu", err); }
    };
    clipFillAccounts(c, d);
    const now = $("[data-publish-now]", d);
    // « Publier maintenant » ouvre le formulaire de l'ecran Publication, prerempli avec ce clip (SPEC-1ed3 R5)
    if (now) now.onclick = () => { closeLayer(); setTimeout(() => pubOpenForm({ video_id: c.video_id, clip_id: c.clip_id }), 340); };
    const approve = $("[data-approve]", d);  // absent hors « à valider » / approved (revue fable-comptes 3)
    if (approve) approve.onclick = async () => {
      const chosen = $("#clip-account", d).value;
      if (!chosen) { toast({ kind: "warn", title: "Compte manquant", body: "Choisis le compte qui publiera ce clip." }); return; }
      if (!(await netGuard())) return;
      try {
        await api(clipUrl(c, "/approve"), jsonBody("POST", { account: chosen }));
        closeLayer();
        toast({ kind: "ok", title: "Clip approuvé", body: c.screen_title || c.clip_id });
        loadClips();
      } catch (err) { toastError("Impossible d'approuver le clip", err); }
    };
    $("[data-reject]", d).onclick = async () => {
      const series = c.parts_total > 1;
      const ok = await confirmDialog({
        title: series ? "Refuser toute la série ?" : "Refuser ce clip ?",
        body: series ? `Ce clip est la partie ${c.part}/${c.parts_total} : refuser une partie refuse toute la série (${c.parts_total} parties).` : "Le clip ne sera pas publié.",
        confirmLabel: series ? "Refuser toute la série" : "Refuser",
      });
      if (!ok) return;
      try {
        await api(clipUrl(c, "/reject"), { method: "POST" });
        closeLayer();
        toast({ kind: "warn", title: series ? "Série refusée" : "Clip refusé", body: c.screen_title || c.clip_id });
        loadClips();
      } catch (err) { toastError("Impossible de refuser le clip", err); }
    };
    $("[data-rerender]", d).onclick = async () => {
      if (!(await confirmDialog({ title: "Re-rendre ce clip ?", body: "Le rendu puis le contrôle qualité de ce clip sont relancés ; le fichier vidéo sera remplacé.", confirmLabel: "Re-rendre", danger: false }))) return;
      try {
        await api(clipUrl(c, "/rerender"), { method: "POST" });
        closeLayer();
        toast({ kind: "ok", title: "Re-rendu en file", body: `${c.video_id} : rendu puis contrôle qualité.` });
      } catch (err) { toastError("Impossible de relancer le rendu", err); }
    };
    $("[data-copy]", d).onclick = () => copyText(clipCaptionText(c), "Description et hashtags");
  });
  return el;
}

Screens.clips = {
  render(body) {
    const wanted = clipsHashVideo();
    if (wanted !== clipsUi.hashVideo) { // l'adresse a changé : le filtre vidéo la suit (lien depuis une fiche vidéo : tous les statuts)
      clipsUi.hashVideo = wanted;
      clipsUi.video = wanted;
      clipsUi.shown = CLIPS_PAGE_SIZE;
      if (wanted) clipsUi.filter = "all";
    }
    if (Date.now() - clipsUi.at > CLIPS_STALE_MS) loadClips();
    if (!clipsUi.data) {
      clipsUi.html = "";
      body.innerHTML = clipsUi.error
        ? emptyState("circle-alert", "Chargement impossible", String(clipsUi.error.message || clipsUi.error))
        : `<div class="skeleton skeleton-line"></div><div class="skeleton skeleton-card"></div><div class="skeleton skeleton-card"></div>`;
      return;
    }
    clipsView(body);
    clipsWire(body);
  },
};
