/* Ecran « Revue des moments » (SPEC-c100 E3, T4). Charge apres screens.js dont
   il remplace l'entree Screens.review. Lit GET /api/videos/{id}/moments, envoie
   chaque decision a POST /api/videos/{id}/moments/{mid}/decide et lance le rendu
   par POST /api/videos/{id}/render (file du worker, jamais dans le processus HTTP).
   Les donnees introuvables arrivent du serveur en null avec <champ>_error :
   affichees telles quelles, jamais remplacees par une valeur de secours. */
"use strict";

const RV_MIN_GAP = 1;      // secondes minimum entre le debut et la fin d'un moment
const RV_CONTEXT = 30;     // secondes de contexte de chaque cote dans la timeline zoomee
const RV_DECISION_LABELS = { accepted: "accepté", rejected: "refusé", adjusted: "ajusté" };
const RV_DECISION_CHIP = { accepted: "done", rejected: "failed", adjusted: "review" };

const rv = {
  videoId: null, moments: null, error: null, loading: false,
  cur: 0, draft: null, window: null, body: null, busy: false,
};

const rvRound = (t) => Math.round(t * 10) / 10;
const rvClock = (t) => {
  const s = Math.max(0, t), m = Math.floor(s / 60);
  return `${m}:${fr(s - m * 60, 1).padStart(4, "0")}`;
};
const rvHashVideo = () => decodeURIComponent((location.hash.split("/")[2] || "").split("?")[0]);
const rvApi = (suffix) => `/api/videos/${encodeURIComponent(rv.videoId)}${suffix}`;
const rvMoment = () => (rv.moments || [])[rv.cur] || null;

/* Bornes en vigueur d'un moment : celles de la decision « ajustée » si elle existe. */
function rvBounds(m) {
  const d = m.decision;
  return d && d.decision === "adjusted" ? { start: d.start, end: d.end } : { start: m.start, end: m.end };
}
const rvDecisionName = (m) => (m.decision ? m.decision.decision : null);
const rvDuration = () => { const m = rvMoment(); return m ? m.source_duration : null; };
const rvDirty = () => {
  const m = rvMoment(), b = m && rvBounds(m);
  return Boolean(m && rv.draft && (rv.draft.start !== b.start || rv.draft.end !== b.end));
};

/* ---------- Donnees ---------- */
async function rvLoad(keepCur) {
  const id = rv.videoId;
  rv.loading = true;
  try {
    const moments = await api(`/api/videos/${encodeURIComponent(id)}/moments`);
    if (id !== rv.videoId) return;
    rv.moments = moments;
    rv.error = null;
    rv.cur = keepCur ? Math.min(rv.cur, moments.length - 1) : Math.max(0, moments.findIndex((m) => !m.decision));
    rvResetDraft();
  } catch (err) {
    if (id === rv.videoId) { rv.moments = null; rv.error = err; }
  } finally {
    rv.loading = false;
  }
  if (currentScreen === "review") renderCurrent();
}

function rvResetDraft() {
  const m = rvMoment();
  const b = m ? rvBounds(m) : null;
  rv.draft = b ? { start: b.start, end: b.end } : null;
  const dur = m ? m.source_duration : null;
  rv.window = b && dur ? { a: Math.max(0, b.start - RV_CONTEXT), b: Math.min(dur, b.end + RV_CONTEXT) } : null;
}

/* ---------- Decisions (toast « Annuler » : renvoie la decision precedente) ---------- */
async function rvSend(moment, payload) {
  return api(`/api/videos/${encodeURIComponent(rv.videoId)}/moments/${moment.id}/decide`, jsonBody("POST", payload));
}

function rvPayloadOf(decision) {
  if (!decision) return null;
  return decision.decision === "adjusted"
    ? { decision: "adjusted", start: decision.start, end: decision.end, comment: decision.comment || null }
    : { decision: decision.decision, comment: decision.comment || null };
}

async function rvDecide(kind) {
  const m = rvMoment();
  if (!m || rv.busy) return;
  const payload = kind === "adjusted"
    ? { decision: "adjusted", start: rv.draft.start, end: rv.draft.end }
    : { decision: kind };
  const previous = m.decision;   // decision a renvoyer si l'utilisateur annule
  const index = rv.cur;
  rv.busy = true;
  try {
    await rvSend(m, payload);
    await Promise.all([rvLoad(true), reloadVideo(rv.videoId)]);
  } catch (err) {
    toastError("Décision non enregistrée", err);
    return;
  } finally {
    rv.busy = false;
  }
  const label = { accepted: "Moment accepté", rejected: "Moment refusé", adjusted: "Bornes ajustées" }[kind];
  toast({
    kind: kind === "rejected" ? "warn" : "ok", title: label, body: m.hook_text || `Moment ${m.id}`,
    undo: () => rvUndo(m, index, previous),
  });
  const next = rv.moments.findIndex((x, i) => i > index && !x.decision);
  rvGo(next >= 0 ? next : rv.moments.findIndex((x) => !x.decision) >= 0 ? rv.moments.findIndex((x) => !x.decision) : index);
  renderCurrent();
}

/* Annuler : renvoie la decision precedente du moment. Sans decision anterieure,
   l'API ne sait pas en effacer une : on revient sur le moment pour en prendre une autre. */
async function rvUndo(moment, index, previous) {
  const payload = rvPayloadOf(previous);
  if (!payload) {
    rvGo(index);
    renderCurrent();
    toast({ kind: "info", title: "Aucune décision antérieure", body: "La décision reste enregistrée : choisis-en une autre pour la remplacer.", ms: 5200 });
    return;
  }
  try {
    await rvSend(moment, payload);
    await Promise.all([rvLoad(true), reloadVideo(rv.videoId)]);
    rvGo(index);
    renderCurrent();
    toast({ kind: "ok", title: "Décision restaurée", body: RV_DECISION_LABELS[previous.decision], ms: 2600 });
  } catch (err) { toastError("Annulation impossible", err); }
}

/* ---------- Rendu : conditionne par state.awaiting ---------- */
function rvVideoState() {
  return (store.videos || []).find((v) => v.video_id === rv.videoId) || null;
}

/* Raison affichee tant que des moments attendent une decision ; null si le rendu est possible. */
function rvBlockedReason() {
  const v = rvVideoState();
  if (!v) return "État de la vidéo introuvable : le rendu ne peut pas être lancé.";
  const awaiting = v.awaiting || [];
  if (!awaiting.length) return null;
  return `${awaiting.length} moment${awaiting.length > 1 ? "s" : ""} sans décision (${awaiting.map((i) => `#${i}`).join(", ")}) : décide chacun avant de lancer le rendu.`;
}

async function rvRender() {
  const reason = rvBlockedReason();
  if (reason) { toast({ kind: "warn", title: "Rendu impossible", body: reason }); return; }
  const kept = rv.moments.filter((m) => rvDecisionName(m) !== "rejected").length;
  if (!(await confirmDialog({ title: "Lancer le rendu ?", body: `${kept} moment${kept > 1 ? "s retenus seront rendus" : " retenu sera rendu"} pour ${rv.videoId}.`, confirmLabel: "Lancer le rendu", danger: false }))) return;
  try {
    await api(rvApi("/render"), { method: "POST" });
    toast({ kind: "ok", title: "Rendu mis en file", body: rv.videoId });
    await reloadVideo(rv.videoId);
    renderCurrent();
  } catch (err) { toastError("Rendu impossible", err); }
}

/* ---------- Construction de l'ecran ---------- */
function rvHeader(candidates) {
  const options = candidates.map((v) => `<option value="${esc(v.video_id)}"${v.video_id === rv.videoId ? " selected" : ""}>${esc(v.video_id)}</option>`).join("");
  return `<div class="rv-bar">
    <label class="rv-pick"><span class="muted">Vidéo</span><select class="input" id="rv-video" aria-label="Vidéo à relire">${options}</select></label>
    <span class="grow"></span>
    <div class="rv-gate"><button type="button" class="btn btn-primary" id="rv-render">${icon("film")}Lancer le rendu</button>
      <p class="reason" id="rv-reason" hidden></p></div>
  </div>`;
}

function rvLayout(candidates) {
  const m = rvMoment();
  return `${rvHeader(candidates)}
  <div class="review-layout" data-rv-video="${esc(rv.videoId)}">
    <aside><div class="section-title">${icon("sparkles")}Proposés par le jury<span class="more">${rv.moments.length}</span></div>
      <div class="m-list" id="rv-list"></div></aside>
    <section class="stack" style="gap:16px">
      <div class="player" id="rv-player">
        <video id="rv-media" src="${esc(m.preview_url)}" preload="metadata" playsinline></video>
        <div class="p-badge"><span class="pill-dark" id="rv-score"></span></div>
        <div class="p-ctrl"><button type="button" class="icon-btn" id="rv-play" aria-label="Lecture">${icon("play")}</button>
          <span class="p-time" id="rv-time"></span></div>
      </div>
      <div class="panel panel-pad">
        <div class="tl" id="rv-tl"></div>
        <div class="bounds" id="rv-bounds">
          <label class="b">Début (s) <input class="input rv-num" type="number" data-field="start" step="0.1" min="0" inputmode="decimal"></label>
          <label class="b">Fin (s) <input class="input rv-num" type="number" data-field="end" step="0.1" min="0" inputmode="decimal"></label>
          <span class="b">Durée <b id="rv-dur"></b></span>
          <span class="grow"></span>
          <button type="button" class="btn btn-xs btn-ghost" id="rv-reset">${icon("rotate-ccw", "i-xs")}Bornes d'origine</button>
        </div>
      </div>
      <div class="decide">
        <button type="button" class="btn btn-ok" id="rv-accept">${icon("check")}Accepter<kbd>A</kbd></button>
        <button type="button" class="btn btn-bad" id="rv-reject">${icon("x")}Refuser<kbd>R</kbd></button>
        <button type="button" class="btn" id="rv-adjust">${icon("sliders-horizontal")}Ajuster</button>
      </div>
      <div class="shortcuts" id="rv-shortcuts">
        <span><kbd>A</kbd> accepter</span><span><kbd>R</kbd> refuser</span>
        <span><kbd>J</kbd> suivant</span><span><kbd>K</kbd> précédent</span>
        <span><kbd>Espace</kbd> lecture / pause</span>
      </div>
      <div class="panel panel-pad"><div class="section-title">${icon("captions")}Transcription</div><div class="transcript" id="rv-transcript"></div></div>
    </section>
    <aside class="jury-col"><div class="panel panel-pad" id="rv-jury"></div></aside>
  </div>`;
}

function rvPaintList(body) {
  $("#rv-list", body).innerHTML = rv.moments.map((x, i) => {
    const name = rvDecisionName(x), b = rvBounds(x);
    const chip = name ? `<span class="chip ${RV_DECISION_CHIP[name]}">${esc(RV_DECISION_LABELS[name])}</span>` : "";
    return `<button type="button" class="m-item ${i === rv.cur ? "on" : ""} ${esc(name || "")}" data-moment="${i}">
      <span class="score ${x.score >= 80 ? "hi" : x.score >= 70 ? "mid" : ""}">${x.score == null ? "–" : fr(x.score)}</span>
      <span style="min-width:0"><span class="m-hook" style="display:block">${esc(x.hook_text || `Moment ${x.id}`)}</span>
        <span class="m-meta"><span class="mono">${esc(rvClock(b.start))}</span><span>${fr(b.end - b.start)} s</span>${x.parts_total > 1 ? `<span>${x.parts_total} parties</span>` : ""}${chip}</span></span>
    </button>`;
  }).join("");
  $$("[data-moment]", body).forEach((b) => (b.onclick = () => { rvGo(+b.dataset.moment); rvPaintMoment(body); }));
}

function rvPaintTimeline(body) {
  const m = rvMoment(), dur = rvDuration(), tl = $("#rv-tl", body);
  if (!dur) {
    tl.innerHTML = `<p class="reason bad">${esc(m.source_duration_error || "source_duration : donnée absente de la réponse.")}</p>`;
    return;
  }
  const w = rv.window, span = w.b - w.a;
  const markers = rv.moments.map((x, i) => {
    const b = rvBounds(x);
    return `<span class="mk ${i === rv.cur ? "on" : ""} ${esc(rvDecisionName(x) || "")}" data-moment="${i}" title="${esc(x.hook_text || "")}" style="left:${(b.start / dur) * 100}%;width:${((b.end - b.start) / dur) * 100}%"></span>`;
  }).join("");
  const ticks = [0, 1, 2, 3, 4].map((k) => `<span>${esc(rvClock(w.a + (span * k) / 4))}</span>`).join("");
  tl.innerHTML = `<div class="row" style="margin-bottom:8px;font-size:12px"><span class="muted">Vidéo entière · ${esc(rvClock(dur))}</span></div>
    <div class="tl-overview" id="rv-ov">${markers}</div>
    <div class="tl-zoom" id="rv-zoom">
      <div class="sel-range" id="rv-sel"><span class="grip l" data-handle="start" role="slider" aria-label="Début du moment" tabindex="0"></span><span class="grip r" data-handle="end" role="slider" aria-label="Fin du moment" tabindex="0"></span></div>
      <div class="playhead" id="rv-ph"></div><div class="tl-ticks">${ticks}</div></div>`;
  $$("#rv-ov [data-moment]", tl).forEach((k) => (k.onclick = () => { rvGo(+k.dataset.moment); rvPaintMoment(body); }));
  $$("[data-handle]", tl).forEach((g) => g.addEventListener("pointerdown", (e) => rvDrag(e, g, body)));
}

/* Poignee glissee : met a jour le brouillon, les champs numeriques et le lecteur. */
function rvDrag(e, grip, body) {
  e.preventDefault();
  const which = grip.dataset.handle, zoom = $("#rv-zoom", body), sel = $("#rv-sel", body);
  grip.setPointerCapture(e.pointerId);
  sel.classList.add("dragging");
  const move = (ev) => {
    const r = zoom.getBoundingClientRect(), w = rv.window;
    rvSetBound(which, rvRound(w.a + ((ev.clientX - r.left) / r.width) * (w.b - w.a)));
    rvPaintBounds(body);
    rvSeek(body, rv.draft[which]);
  };
  const up = () => {
    grip.removeEventListener("pointermove", move);
    grip.removeEventListener("pointerup", up);
    grip.removeEventListener("pointercancel", up);
    sel.classList.remove("dragging");
  };
  grip.addEventListener("pointermove", move);
  grip.addEventListener("pointerup", up);
  grip.addEventListener("pointercancel", up);
}

/* Fixe une borne du brouillon dans [0, duree de la source] avec un ecart minimal. */
function rvSetBound(which, value) {
  const dur = rvDuration(), d = rv.draft;
  const max = dur || Infinity;
  if (which === "start") d.start = rvRound(Math.max(0, Math.min(value, d.end - RV_MIN_GAP)));
  else d.end = rvRound(Math.min(max, Math.max(value, d.start + RV_MIN_GAP)));
}

function rvPaintBounds(body) {
  const d = rv.draft, w = rv.window, dirty = rvDirty();
  $$("[data-field]", body).forEach((f) => {
    if (document.activeElement !== f) f.value = d[f.dataset.field];
    if (rvDuration()) f.max = rvDuration();
  });
  $("#rv-dur", body).textContent = `${fr(d.end - d.start, 1)} s`;
  $("#rv-adjust", body).disabled = !dirty;
  $("#rv-reset", body).disabled = !dirty;
  const sel = $("#rv-sel", body);
  if (sel && w) {
    const span = w.b - w.a;
    sel.style.left = `${((d.start - w.a) / span) * 100}%`;
    sel.style.width = `${((d.end - d.start) / span) * 100}%`;
  }
}

function rvSeek(body, t) {
  const media = $("#rv-media", body);
  if (media && media.readyState > 0) media.currentTime = t;
}

function rvPaintMoment(body) {
  const m = rvMoment(), d = rv.draft;
  rvPaintList(body);
  rvPaintTimeline(body);
  rvPaintBounds(body);
  $("#rv-score", body).textContent = m.score == null ? "sans score" : `score ${fr(m.score)}`;
  $("#rv-transcript", body).innerHTML = m.transcript
    ? `<p>${esc(m.transcript)}</p>`
    : `<p class="reason bad">${esc(m.transcript_error || "transcript : donnée absente de la réponse.")}</p>`;
  $("#rv-jury", body).innerHTML = `<div class="row" style="margin-bottom:16px;align-items:flex-end">
      <div><div class="section-title" style="margin:0">Justification du jury</div><div class="muted" style="font-size:12px">moment #${m.id}${m.parts_total > 1 ? ` · ${m.parts_total} parties` : ""}</div></div>
      <span class="grow"></span><div class="big-num" style="font-size:44px">${m.score == null ? "–" : fr(m.score)}<small>/100</small></div></div>
    ${m.justification ? `<p class="judge-why" style="font-size:14px;color:var(--text-2)">${esc(m.justification)}</p>` : `<p class="reason bad">justification : aucune donnée pour ce moment.</p>`}
    ${m.hook_text ? `<div class="field-label" style="margin:16px 0 4px">Accroche proposée</div><p>${esc(m.hook_text)}</p>` : ""}`;
  const media = $("#rv-media", body);
  const start = () => { media.currentTime = d.start; };
  if (media.readyState > 0) start(); else media.addEventListener("loadedmetadata", start, { once: true });
  rvPaintTime(body);
}

/* Navigation entre moments (J / K, liste, repères de la timeline). */
function rvGo(i) {
  if (!rv.moments || !rv.moments.length) return;
  rv.cur = (i + rv.moments.length) % rv.moments.length;
  rvResetDraft();
  if (rv.body) rvPaintMoment(rv.body);
}

function rvPaintTime(body) {
  const media = $("#rv-media", body), d = rv.draft;
  if (!media || !d) return;
  const t = Math.max(d.start, Math.min(d.end, media.currentTime || d.start));
  $("#rv-time", body).textContent = `${rvClock(t)} · ${fr(t - d.start)} / ${fr(d.end - d.start)} s`;
  const w = rv.window, ph = $("#rv-ph", body);
  if (ph && w) ph.style.left = `${((t - w.a) / (w.b - w.a)) * 100}%`;
}

/* Lecteur cale sur le moment : jamais hors de [debut, fin] du brouillon. */
function rvWirePlayer(body) {
  const media = $("#rv-media", body), play = $("#rv-play", body);
  media.addEventListener("timeupdate", () => {
    const d = rv.draft;
    if (!d) return;
    if (media.currentTime >= d.end) { media.pause(); media.currentTime = d.start; }
    else if (media.currentTime < d.start - 0.3) media.currentTime = d.start;
    rvPaintTime(body);
  });
  media.addEventListener("play", () => { play.innerHTML = icon("pause"); });
  media.addEventListener("pause", () => { play.innerHTML = icon("play"); });
  media.addEventListener("error", () => toast({ kind: "bad", title: "Lecture impossible", body: `La vidéo source de ${rv.videoId} n'a pas pu être chargée.`, ms: 7000 }));
  play.onclick = () => rvTogglePlay(body);
  $("#rv-player", body).addEventListener("click", (e) => { if (!e.target.closest(".p-ctrl")) rvTogglePlay(body); });
}

function rvTogglePlay(body) {
  const media = $("#rv-media", body), d = rv.draft;
  if (!media || !d) return;
  if (!media.paused) { media.pause(); return; }
  if (media.currentTime < d.start || media.currentTime >= d.end) media.currentTime = d.start;
  media.play().catch((err) => toastError("Lecture impossible", err));
}

function rvWireControls(body) {
  $$("[data-field]", body).forEach((f) => (f.onchange = () => {
    const which = f.dataset.field, value = parseFloat(f.value);
    if (Number.isNaN(value) || value < 0) {
      toast({ kind: "bad", title: "Borne invalide", body: "Saisis un nombre de secondes positif.", ms: 4000 });
    } else {
      rvSetBound(which, rvRound(value));
      rvSeek(body, rv.draft[which]);
    }
    f.value = rv.draft[which];
    rvPaintBounds(body);
  }));
  $("#rv-reset", body).onclick = () => { rvResetDraft(); rvPaintMoment(body); };
  $("#rv-accept", body).onclick = () => rvAccept();
  $("#rv-reject", body).onclick = () => rvDecide("rejected");
  $("#rv-adjust", body).onclick = () => rvDecide("adjusted");
  $("#rv-render", body).onclick = rvRender;
  $("#rv-video", body).onchange = (e) => { location.hash = `#/review/${encodeURIComponent(e.target.value)}`; };
}

/* Accepter : avec des bornes modifiees, la decision est « ajustée » (bornes gardees dans review.json). */
const rvAccept = () => rvDecide(rvDirty() ? "adjusted" : "accepted");

/* Bouton « lancer le rendu » : inactif tant que des moments attendent, raison affichee. */
function rvPaintGate(body) {
  const reason = rvBlockedReason(), btn = $("#rv-render", body), box = $("#rv-reason", body);
  btn.disabled = Boolean(reason);
  box.hidden = !reason;
  box.textContent = reason || "";
}

/* ---------- Raccourcis clavier : A R J K espace ---------- */
document.addEventListener("keydown", (e) => {
  if (currentScreen !== "review" || !rv.moments || !rv.body) return;
  if (e.ctrlKey || e.metaKey || e.altKey || document.querySelector(".modal.show")) return;
  const target = e.target;
  if (target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return;
  const key = e.key.toLowerCase();
  if (key === "a") rvAccept();
  else if (key === "r") rvDecide("rejected");
  else if (key === "j") rvGo(rv.cur + 1);
  else if (key === "k") rvGo(rv.cur - 1);
  else if (key === " ") rvTogglePlay(rv.body);
  else return;
  e.preventDefault();
});

/* ---------- Ecran ---------- */
Screens.review = {
  render(body, store) {
    const candidates = (store.videos || []).filter((v) => v.status === "awaiting_review");
    const id = rvHashVideo() || (candidates.find((v) => v.video_id === rv.videoId) || candidates[0] || {}).video_id || null;
    if (!id) {
      rv.videoId = null; rv.moments = null; rv.body = null;
      body.innerHTML = emptyState("sparkles", "Aucun moment à valider", "Ajoute une vidéo : ses moments à valider apparaîtront ici.");
      return;
    }
    if (id !== rv.videoId) {
      rv.videoId = id; rv.moments = null; rv.error = null; rv.body = null; rv.loading = false;
      body.innerHTML = `<div class="skeleton skeleton-line"></div><div class="skeleton skeleton-card"></div>`;
    }
    if (rv.error) {
      rv.body = null;
      body.innerHTML = emptyState("circle-alert", "Moments indisponibles", String(rv.error.message || rv.error));
      return;
    }
    if (rv.moments === null) {
      if (!rv.loading) rvLoad(false);
      return;
    }
    if (!rv.moments.length) {
      rv.body = null;
      body.innerHTML = emptyState("sparkles", "Aucun moment proposé", `Le jury n'a retenu aucun moment pour ${id}.`);
      return;
    }
    // Les evenements SSE re-rendent l'ecran : on ne reconstruit pas le lecteur pour autant.
    if (rv.body !== body || !$(".review-layout", body) || body.dataset.rvVideo !== id) {
      body.dataset.rvVideo = id;
      rv.body = body;
      body.innerHTML = rvLayout(candidates.length ? candidates : [{ video_id: id }]);
      hydrateIcons(body);
      rvWirePlayer(body);
      rvWireControls(body);
      rvPaintMoment(body);
    } else {
      rvPaintList(body);
    }
    rvPaintGate(body);
  },
};
