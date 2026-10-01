/* Ecran Videos (SPEC-c100 E2) : ajout par URL, liste filtrable cote serveur,
   fiche d'une video (frise des 12 etapes, journal en direct, relancer,
   annuler). Charge apres screens.js (qui definit Screens, STEP_LABELS,
   STATUS_LABELS, statusChip, emptyState) et avant app.js ; remplace
   l'entree Screens.videos de la coquille.

   L'ecran garde son DOM : app.js rappelle render() a chaque evenement, et
   refaire tout le HTML ferait perdre le focus des champs de filtre. */
"use strict";

(function () {
  const STEP_ORDER = Object.keys(STEP_LABELS);
  const STALE_MS = 4000; // le polling de repli (5 s) rafraichit au-dela
  const STEP_ICON = { done: "check", failed: "x", running: "loader", pending: "clock", queued: "circle-pause" };

  const state = {
    root: null,
    filters: { channel: "", status: "", q: "" },
    list: null, listAt: 0, listBusy: false, listAgain: false, listKey: null,
    detailId: null, detail: null, detailAt: 0, detailBusy: false, detailAgain: false,
    events: [], step: null,
    channelsAsked: false, formChannels: null,
  };

  const selectedId = () => {
    const hit = location.hash.match(/^#\/videos\/([^/?#]+)/);
    return hit ? decodeURIComponent(hit[1]) : null;
  };

  function fmtDur(seconds) {
    if (seconds == null) return null;
    const s = Math.round(seconds);
    if (s < 60) return `${s} s`;
    const m = Math.floor(s / 60);
    if (m < 60) return `${m} min ${String(s % 60).padStart(2, "0")} s`;
    return `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, "0")}`;
  }

  const clock = (iso) => {
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? esc(iso) : d.toLocaleTimeString("fr-FR");
  };

  /* ---------- Structure fixe de l'ecran ---------- */
  function build(body) {
    body.innerHTML = `
      <div class="vscreen">
        <div data-vlist-view>
          <form class="vadd" data-add-form autocomplete="off">
            <div class="field vadd-url"><label for="vadd-url">Adresse de la vidéo (URL)</label>
              <input class="input" id="vadd-url" name="url" type="url" required placeholder="https://…"></div>
            <div class="field"><label for="vadd-channel">Chaîne</label>
              <select class="input" id="vadd-channel" name="channel"><option value="">Sans chaîne (config.toml)</option></select></div>
            <div class="field"><label for="vadd-action">Action</label>
              <select class="input" id="vadd-action" name="action">
                <option value="run">Traitement complet</option><option value="render">Rendu seul</option></select></div>
            <button class="btn btn-primary" type="submit">${icon("plus")}Mettre en file</button>
          </form>
          <div class="toolbar vfilters">
            <label class="input-ico">${icon("search")}<input class="input" name="q" type="search" placeholder="Titre, identifiant ou adresse" aria-label="Filtrer par texte"></label>
            <select class="input" name="filter-channel" aria-label="Filtrer par chaîne"><option value="">Toutes les chaînes</option></select>
            <select class="input" name="filter-status" aria-label="Filtrer par statut"><option value="">Tous les statuts</option>
              ${Object.keys(STATUS_LABELS).map((k) => `<option value="${k}">${esc(STATUS_LABELS[k])}</option>`).join("")}</select>
            <span class="grow"></span><span class="muted" data-vcount></span>
          </div>
          <div class="jobs" data-vlist></div>
        </div>
        <div data-vdetail-view hidden></div>
      </div>`;
    state.root = body;
    $("[data-add-form]", body).onsubmit = submitAdd;
    const filterChange = () => {
      state.filters.channel = $('[name="filter-channel"]', body).value;
      state.filters.status = $('[name="filter-status"]', body).value;
      refreshList();
    };
    $('[name="filter-channel"]', body).onchange = filterChange;
    $('[name="filter-status"]', body).onchange = filterChange;
    let timer = null;
    $('[name="q"]', body).oninput = (e) => {
      clearTimeout(timer);
      timer = setTimeout(() => { state.filters.q = e.target.value.trim(); refreshList(); }, 250);
    };
    $("[data-vlist]", body).innerHTML = skeletonRows();
  }

  const skeletonRows = () => Array.from({ length: 3 }, () => `<div class="job vrow"><div><div class="skeleton skeleton-line"></div><div class="skeleton skeleton-line"></div></div></div>`).join("");

  /* ---------- Chaines : selecteurs d'ajout et de filtre ---------- */
  async function ensureChannels() {
    if (state.channelsAsked) return;
    state.channelsAsked = true;
    try {
      store.channels = await api("/api/channels");
    } catch (err) {
      state.channelsAsked = false;
      toastError("Chaînes indisponibles", err);
      return;
    }
    paintChannelSelects();
  }

  function paintChannelSelects() {
    const names = store.channels || [];
    const key = names.join("|");
    if (state.formChannels === key) return;
    state.formChannels = key;
    const options = (first) => `<option value="">${first}</option>` + names.map((n) => `<option value="${esc(n)}">${esc(n)}</option>`).join("");
    const keep = (sel, html) => { const v = sel.value; sel.innerHTML = html; sel.value = v; };
    keep($('[name="channel"]', state.root), options("Sans chaîne (config.toml)"));
    keep($('[name="filter-channel"]', state.root), options("Toutes les chaînes"));
  }

  /* ---------- Ajout par URL ---------- */
  async function submitAdd(e) {
    e.preventDefault();
    const form = e.target;
    const url = $('[name="url"]', form).value.trim();
    const channel = $('[name="channel"]', form).value || null;
    const action = $('[name="action"]', form).value;
    try {
      const entry = await api("/api/queue", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ url, channel, action }) });
      toast({ kind: "ok", title: "Vidéo mise en file", body: entry.video_id });
      form.reset();
      await Promise.all([loadVideos(), loadQueue()]);
      updateCounts();
      refreshList();
    } catch (err) { toastError("Ajout impossible", err); }
  }

  /* ---------- Liste filtree (serveur) ---------- */
  async function refreshList() {
    if (state.listBusy) { state.listAgain = true; return; }
    state.listBusy = true;
    const params = new URLSearchParams();
    for (const [k, v] of Object.entries(state.filters)) if (v) params.set(k, v);
    try {
      state.list = await api(`/api/videos?${params.toString()}`);
      state.listAt = Date.now();
      paintList();
    } catch (err) {
      $("[data-vlist]", state.root).innerHTML = emptyState("circle-alert", "Liste indisponible", String(err.message || err));
      toastError("Liste des vidéos indisponible", err);
    } finally {
      state.listBusy = false;
      if (state.listAgain) { state.listAgain = false; refreshList(); }
    }
  }

  function segs(video) {
    const steps = video.steps || {};
    return `<div class="segs" aria-hidden="true">${STEP_ORDER.map((n) => `<i class="${esc((steps[n] || {}).status || "pending")}"></i>`).join("")}</div>`;
  }

  function listRow(video) {
    const cur = video.current_step;
    const step = cur ? (video.steps || {})[cur] : null;
    const progress = step && step.progress ? step.progress : null;
    const pct = progress ? Math.round(progress.fraction * 100) : null;
    const eta = progress && progress.eta_s != null ? ` · reste ${esc(fr(Math.ceil(progress.eta_s / 60)))} min` : "";
    const where = cur ? `<span>${esc(STEP_LABELS[cur] || cur)}${pct != null ? ` · ${pct} %${eta}` : ""}</span>` : `<span>toutes les étapes terminées</span>`;
    return `<a class="job vrow" href="#/videos/${encodeURIComponent(video.video_id)}" data-video="${esc(video.video_id)}">
      <div style="min-width:0">
        <div class="job-title">${esc(video.title)}</div>
        <div class="job-meta"><span class="mono">${esc(video.video_id)}</span>${video.channel ? `<span class="tag">${esc(video.channel)}</span>` : `<span class="muted">sans chaîne</span>`}${where}</div>
        <div style="margin-top:10px">${segs(video)}</div>
        ${video.reason ? `<p class="reason ${video.status === "failed" ? "bad" : ""}">${esc(video.reason)}</p>` : ""}
      </div>
      <div class="job-side">${statusChip(video.status)}</div>
    </a>`;
  }

  function paintList() {
    const list = state.list || [];
    const filtered = Object.values(state.filters).some(Boolean);
    $("[data-vcount]", state.root).textContent = `${list.length} vidéo${list.length > 1 ? "s" : ""}`;
    $("[data-vlist]", state.root).innerHTML = list.length
      ? list.map(listRow).join("")
      : (filtered
        ? emptyState("inbox", "Aucune vidéo ne correspond", "Change les filtres, ou ajoute une vidéo par son adresse.")
        : emptyState("film", "Aucune vidéo", "Ajoute une vidéo par son adresse ci-dessus pour lancer un premier traitement."));
  }

  /* ---------- Fiche d'une video ---------- */
  async function refreshDetail() {
    const id = state.detailId;
    if (!id) return;
    if (state.detailBusy) { state.detailAgain = true; return; }
    state.detailBusy = true;
    try {
      const enc = encodeURIComponent(id);
      const query = new URLSearchParams();
      if (state.events.length) query.set("since", state.events[state.events.length - 1].at);
      const [detail, fresh] = await Promise.all([api(`/api/videos/${enc}`), api(`/api/videos/${enc}/events?${query.toString()}`)]);
      if (state.detailId !== id) return; // l'utilisateur a change de video entre-temps
      state.detail = detail;
      state.detailAt = Date.now();
      state.events = state.events.concat(fresh);
      paintDetail();
    } catch (err) {
      if (state.detailId === id) {
        $("[data-vdetail-view]", state.root).innerHTML = backLink() + emptyState("circle-alert", "Vidéo indisponible", String(err.message || err));
      }
      toastError("Fiche vidéo indisponible", err);
    } finally {
      state.detailBusy = false;
      if (state.detailAgain) { state.detailAgain = false; refreshDetail(); }
    }
  }

  const backLink = () => `<a class="btn btn-sm btn-ghost vback" href="#/videos">${icon("chevron-left")}Toutes les vidéos</a>`;

  function stepStatusOf(video, name) {
    return ((video.steps || {})[name] || {}).status || "pending";
  }

  function stepTime(video, name) {
    const step = (video.steps || {})[name] || {};
    if (step.status === "running") {
      return step.progress ? `${Math.round(step.progress.fraction * 100)} %` : "en cours";
    }
    if (step.status === "done") return fmtDur((video.durations || {})[name]) || "durée inconnue";
    if (step.status === "failed") return "échec";
    return "en attente";
  }

  function friseHtml(video) {
    const last = STEP_ORDER.reduce((k, n, i) => (stepStatusOf(video, n) === "done" ? i : k), -1);
    const cur = video.current_step ? (video.steps[video.current_step] || {}) : {};
    const partial = cur.status === "running" && cur.progress ? cur.progress.fraction : 0;
    const fill = Math.min(1, Math.max(0, (last + partial) / (STEP_ORDER.length - 1)));
    return `<div class="frise" role="list"><div class="frise-fill" style="width:calc((100% - 100% / 12) * ${fill})"></div>
      ${STEP_ORDER.map((n) => {
        const st = stepStatusOf(video, n);
        return `<button type="button" role="listitem" class="fstep ${st}${n === state.step ? " sel" : ""}" data-step="${n}">
          <span class="node">${icon(STEP_ICON[st] || "clock")}</span><span class="fstep-name">${esc(STEP_LABELS[n])}</span><span class="fstep-time">${esc(stepTime(video, n))}</span></button>`;
      }).join("")}</div>`;
  }

  function stepPanelHtml(video) {
    const name = state.step;
    const step = (video.steps || {})[name] || {};
    const st = stepStatusOf(video, name);
    const progress = step.progress;
    const dur = fmtDur((video.durations || {})[name]);
    const canRetry = (st === "done" || st === "failed") && video.status !== "running";
    return `<div class="panel-head"><h2>${esc(STEP_LABELS[name])}</h2><div class="right">${statusChip(st)}</div></div>
      <div class="vstep">
        <dl class="kv">
          <dt>Durée</dt><dd>${dur ? esc(dur) : (st === "done" ? "inconnue : horodatage absent de pipeline.json" : "pas terminée")}</dd>
          ${step.started_at ? `<dt>Début</dt><dd>${clock(step.started_at)}</dd>` : ""}
          ${step.finished_at ? `<dt>Fin</dt><dd>${clock(step.finished_at)}</dd>` : ""}
          ${progress ? `<dt>Progression</dt><dd>${Math.round(progress.fraction * 100)} %${progress.eta_s != null ? ` · reste ${esc(fmtDur(progress.eta_s))}` : ""}${progress.message ? ` · ${esc(progress.message)}` : ""}
            <div class="bar" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Math.round(progress.fraction * 100)}"><i style="width:${Math.round(progress.fraction * 100)}%"></i></div></dd>` : ""}
          ${step.reason ? `<dt>Raison</dt><dd class="vreason">${esc(step.reason)}</dd>` : ""}
        </dl>
        ${canRetry ? `<div class="row wrap" style="margin-top:20px"><button type="button" class="btn btn-sm" data-retry="${name}">${icon("rotate-ccw")}Relancer depuis cette étape</button></div>` : ""}
      </div>`;
  }

  function levelClass(level) {
    const l = String(level || "").toLowerCase();
    return l === "error" || l === "critical" ? "lv-e" : l === "warning" || l === "warn" ? "lv-w" : "lv-i";
  }

  const logLine = (ev) => `<div><span class="t">${clock(ev.at)}</span><span class="${levelClass(ev.level)}">${esc(String(ev.level || "info").toLowerCase())}</span>${ev.step ? ` <span class="faint">${esc(ev.step)}</span>` : ""} ${esc(ev.message)}</div>`;

  function paintDetail() {
    const video = state.detail;
    const view = $("[data-vdetail-view]", state.root);
    if (!video) return;
    if (!state.step || !STEP_ORDER.includes(state.step)) state.step = video.current_step || STEP_ORDER[STEP_ORDER.length - 1];
    const enc = encodeURIComponent(video.video_id);
    const review = video.status === "awaiting_review" || (video.awaiting || []).length;
    const logEl = $(".log", view);
    const stick = !logEl || logEl.scrollTop + logEl.clientHeight >= logEl.scrollHeight - 24;

    view.innerHTML = `
      ${backLink()}
      <div class="vhead">
        <div style="min-width:0">
          <h2 class="vtitle">${esc(video.title)}</h2>
          ${video.title_reason ? `<p class="muted vsub">${esc(video.title_reason)}</p>` : ""}
          <div class="job-meta"><span class="mono">${esc(video.video_id)}</span>${video.channel ? `<span class="tag">${esc(video.channel)}</span>` : `<span class="muted">sans chaîne</span>`}${video.source_url ? `<span class="mono">${esc(video.source_url)}</span>` : ""}${statusChip(video.status)}</div>
        </div>
        <div class="vactions">
          ${review ? `<a class="btn btn-primary" href="#/review/${enc}">${icon("sparkles")}Revoir les moments${(video.awaiting || []).length ? ` (${video.awaiting.length})` : ""}</a>` : ""}
          ${(video.clips || []).length ? `<a class="btn" href="#/clips/${enc}">${icon("clapperboard")}Voir les ${video.clips.length} clips</a>` : ""}
          ${video.status === "running" ? `<button type="button" class="btn btn-bad" data-cancel-video>${icon("ban")}Annuler le traitement</button>` : ""}
        </div>
      </div>
      ${video.reason ? `<div class="banner"><p><b>${video.status === "failed" ? "Échec" : "Information"} :</b> ${esc(video.reason)}${video.retry_at ? ` · nouvelle tentative prévue ${clock(video.retry_at)}` : ""}</p></div>` : ""}
      <section class="vsection"><div class="row" style="margin-bottom:16px"><h3>Progression</h3><span class="muted vsum"></span></div>${friseHtml(video)}</section>
      <div class="step-detail vgrid">
        <section class="vsection vstep-panel">${stepPanelHtml(video)}</section>
        <section class="vsection">
          <div class="panel-head"><h3>Journal</h3><span class="muted mono">workspace/${esc(video.video_id)}/events.jsonl</span><div class="right"><button type="button" class="btn btn-xs btn-ghost" data-log-copy>${icon("copy", "i-xs")}Copier</button></div></div>
          <div style="padding:16px"><div class="log" role="log" aria-live="polite">${state.events.length ? state.events.map(logLine).join("") : `<span class="faint">Aucun événement pour l'instant.</span>`}</div></div>
        </section>
      </div>`;

    const done = STEP_ORDER.filter((n) => stepStatusOf(video, n) === "done").length;
    const total = STEP_ORDER.reduce((t, n) => t + ((video.durations || {})[n] || 0), 0);
    $(".vsum", view).textContent = `${done} / ${STEP_ORDER.length} étapes · ${fmtDur(total) || "0 s"} de calcul`;
    const log = $(".log", view);
    if (stick) log.scrollTop = log.scrollHeight;
    wireDetail(view, video);
  }

  function wireDetail(view, video) {
    $$("[data-step]", view).forEach((b) => (b.onclick = () => { state.step = b.dataset.step; paintDetail(); }));
    const retry = $("[data-retry]", view);
    if (retry) retry.onclick = () => retryFrom(video, retry.dataset.retry);
    const cancel = $("[data-cancel-video]", view);
    if (cancel) cancel.onclick = () => cancelVideo(video);
    $("[data-log-copy]", view).onclick = () => copyText(state.events.map((e) => `${e.at} ${e.level} ${e.step || ""} ${e.message}`).join("\n"), "Journal");
  }

  /* Relancer : remet cette etape et les suivantes a zero (SPEC-fc0c 3.3). */
  async function retryFrom(video, step) {
    const after = STEP_ORDER.slice(STEP_ORDER.indexOf(step) + 1).map((n) => STEP_LABELS[n]);
    const ok = await confirmDialog({
      title: `Relancer depuis « ${STEP_LABELS[step]} » ?`,
      body: `Cette étape repart de zéro${after.length ? `, ainsi que : ${after.join(", ")}` : ""}. Les clips déjà rendus de cette vidéo seront remplacés.`,
      confirmLabel: "Relancer", danger: false,
    });
    if (!ok) return;
    try {
      await api(`/api/videos/${encodeURIComponent(video.video_id)}/retry`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ from_step: step }) });
      toast({ kind: "ok", title: "Relance mise en file", body: `${video.video_id} : depuis « ${STEP_LABELS[step]} »` });
      await Promise.all([loadVideos(), loadQueue()]);
      refreshDetail();
    } catch (err) { toastError("Relance impossible", err); }
  }

  async function cancelVideo(video) {
    const ok = await confirmDialog({ title: "Annuler le traitement ?", body: `Le traitement de ${video.video_id} sera arrêté.`, confirmLabel: "Annuler le traitement" });
    if (!ok) return;
    try {
      await api(`/api/videos/${encodeURIComponent(video.video_id)}/cancel`, { method: "POST" });
      toast({ kind: "ok", title: "Traitement annulé", body: video.video_id });
      await loadVideos();
      updateCounts();
      refreshDetail();
    } catch (err) { toastError("Annulation impossible", err); }
  }

  /* ---------- Branchement sur la coquille ---------- */
  function openDetail(id) {
    if (state.detailId === id) return;
    state.detailId = id;
    state.detail = null;
    state.events = [];
    state.step = null;
    $("[data-vdetail-view]", state.root).innerHTML = backLink() + `<div class="skeleton skeleton-card"></div>`;
  }

  /* Temps reel (T3) : un evenement « video » rafraichit la fiche ouverte (et
     son journal) ou la liste, jamais la page. */
  document.addEventListener("clipper:event", (e) => {
    if (currentScreen !== "videos" || !state.root || e.detail.kind !== "video") return;
    if (state.detailId) { if (e.detail.id === state.detailId) refreshDetail(); } else refreshList();
  });

  Screens.videos = {
    render(body) {
      if (!body.querySelector(".vscreen")) { state.root = null; state.list = null; state.formChannels = null; state.channelsAsked = false; state.detailId = null; build(body); }
      const id = selectedId();
      $("[data-vlist-view]", body).hidden = Boolean(id);
      $("[data-vdetail-view]", body).hidden = !id;
      ensureChannels();
      paintChannelSelects();
      if (id) {
        openDetail(id);
        if (!state.detail || Date.now() - state.detailAt > STALE_MS) refreshDetail();
      } else {
        state.detailId = null;
        if (state.list === null || Date.now() - state.listAt > STALE_MS) refreshList();
      }
    },
  };
})();
