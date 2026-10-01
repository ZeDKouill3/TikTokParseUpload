/* Ecrans : chaque vue renvoie { crumbs, html, mount(root) }. */
"use strict";

const Views = {};

function head(eyebrow, title, sub, actions) {
  return `<div class="page-head reveal" style="--i:0">
    <div class="titles">
      ${eyebrow ? `<div class="eyebrow">${eyebrow}</div>` : ""}
      <h1>${title}</h1>
      ${sub ? `<p class="sub">${sub}</p>` : ""}
    </div>
    ${actions ? `<div class="actions">${actions}</div>` : ""}
  </div>`;
}

function segsHTML(v) {
  return `<div class="segs" data-segs="${v.id}">${v.steps.map((s, i) =>
    `<i class="${s.status}" title="${esc(STEPS[i].label)}" ${s.status === "running" ? `style="--p:${v.progress}%"` : ""}></i>`).join("")}</div>`;
}

function jobRow(v, opts) {
  const c = chan(v.channel);
  const st = STATUS[v.status];
  const cur = v.step >= 0 ? STEPS[v.step] : null;
  let prog = "";
  if (v.status === "running") {
    prog = `<div class="job-prog">
      <div>
        <div class="job-step"><b>${cur.label}</b><span data-live-pct="${v.id}">${v.progress} %</span><span class="faint">·</span><span class="muted" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(v.detail)}</span></div>
        <div style="margin-top:8px">${segsHTML(v)}</div>
      </div>
    </div>`;
  } else {
    prog = `<div style="margin-top:12px">${segsHTML(v)}</div>`;
  }
  const reason = v.reason && opts && opts.reason ? `<p class="reason ${v.status === "failed" ? "bad" : ""}">${esc(v.reason)}</p>` : "";
  let side = `<span class="chip ${st.cls}">${st.label}</span>`;
  if (v.status === "running") side += `<div class="eta" data-eta="${v.id}">${v.eta}<small> min restantes</small></div>`;
  if (v.status === "awaiting_review") side += `<a class="btn btn-sm btn-primary" href="#/revue/${v.id}">Revoir ${v.moments} moments</a>`;
  if (v.status === "pending") side += `<span class="muted" style="font-size:13px">position ${v.position}</span>`;
  if (v.status === "done") side += `<span class="muted" style="font-size:13px">${v.clips} clips</span>`;
  return `<div class="job" data-href="#/videos/${v.id}" data-job="${v.id}" role="link" tabindex="0">
    <div class="job-thumb">${videoThumb(v)}<span class="dur">${v.duration}</span></div>
    <div style="min-width:0">
      <div class="job-title">${esc(v.title)}</div>
      <div class="job-meta">${srcIcon(c.platform)}<span>${esc(c.name)}</span><span class="dot"></span><span>${esc(c.preset)}</span><span class="dot"></span><span>ajoutée ${v.added}</span></div>
      ${prog}${reason}
    </div>
    <div class="job-side">${side}</div>
  </div>`;
}

/* ================= Tableau de bord ================= */
Views.dashboard = () => {
  const running = VIDEOS.filter((v) => v.status === "running");
  const attention = VIDEOS.filter((v) => v.status === "queued" || v.status === "failed");
  const pending = VIDEOS.filter((v) => v.status === "pending");
  const toValidate = CLIPS.filter((c) => c.status === "review");
  const toReview = VIDEOS.filter((v) => v.status === "awaiting_review").reduce((n, v) => n + v.moments, 0);
  const upcoming = POSTS.filter((p) => p.status === "scheduled");
  const weekCost = [1.21, 2.03, 0.64, 1.9, 2.4, 1.18, 1.84];

  const html = `
  ${head("Mercredi 30 septembre · 21:34", `${running.length} vidéos en cours, ${toReview} moments à revoir`,
    "La file tourne. Deux vidéos demandent une décision de ta part.",
    `<a class="btn" href="#/videos">${icon("film")}Toutes les vidéos</a><a class="btn btn-primary" href="#/revue/mdj-0928">${icon("sparkles")}Revoir les moments</a>`)}

  <div class="kpis reveal" style="--i:1">
    <a class="kpi accent" href="#/videos?f=running"><div class="kpi-label">${icon("loader")}En cours</div><div class="kpi-value"><span data-count="${running.length}">0</span></div><div class="kpi-foot">fin estimée 21:45</div></a>
    <a class="kpi" href="#/videos?f=pending"><div class="kpi-label">${icon("list-filter")}En file</div><div class="kpi-value"><span data-count="${pending.length}">0</span></div><div class="kpi-foot">3 h 06 de vidéo</div></a>
    <a class="kpi warn" href="#/videos?f=attention"><div class="kpi-label">${icon("circle-pause")}À débloquer</div><div class="kpi-value"><span data-count="${attention.length}">0</span></div><div class="kpi-foot">1 en attente, 1 échec</div></a>
    <a class="kpi" href="#/clips?f=review"><div class="kpi-label">${icon("clapperboard")}Clips à valider</div><div class="kpi-value"><span data-count="${toValidate.length}">0</span></div><div class="kpi-foot">dont 1 avertissement QA</div></a>
    <a class="kpi" href="#/stats"><div class="kpi-label">${icon("coins")}LLM aujourd'hui</div><div class="kpi-value"><span data-count="1.84" data-dec="2">0</span><small>€</small></div><div class="kpi-foot">11,20 € sur 7 jours · équiv. API</div></a>
  </div>

  <div class="grid cols-dash" style="margin-top:32px">
    <div class="stack">
      <section class="reveal" style="--i:2">
        <div class="section-title">${icon("activity")}En cours <a class="more" href="#/videos?f=running">Tout voir ${icon("chevron-right", "i-xs")}</a></div>
        <div class="panel jobs">${running.map((v) => jobRow(v)).join("")}</div>
      </section>
      <section class="reveal" style="--i:3">
        <div class="section-title">${icon("triangle-alert")}À débloquer</div>
        <div class="panel">
          ${attention.map((v) => {
            const c = chan(v.channel);
            const isQ = v.status === "queued";
            return `<div class="list-item" style="align-items:flex-start;padding-top:16px;padding-bottom:16px" data-att="${v.id}">
              <span class="chip ${isQ ? "queued" : "failed"}" style="margin-top:2px">${isQ ? "En attente" : "Échec"}</span>
              <div class="li-main">
                <a class="li-title" href="#/videos/${v.id}" style="display:block">${esc(v.title)}</a>
                <div class="li-sub">${esc(c.name)} · étape ${stepLabel(v.steps[v.step].id).toLowerCase()}</div>
                <p class="reason ${isQ ? "" : "bad"}">${esc(v.reason)}</p>
                <div class="row wrap" style="margin-top:12px;gap:8px">
                  ${isQ ? `<button class="btn btn-sm btn-primary" data-fix="letterbox">${icon("check")}Clip 3 en letterbox</button><button class="btn btn-sm" data-fix="skip">Ignorer le clip 3</button>`
                        : `<button class="btn btn-sm" data-fix="retry">${icon("refresh-cw")}Réessayer</button><button class="btn btn-sm btn-ghost" data-fix="remove">${icon("trash-2")}Retirer</button>`}
                  <a class="btn btn-sm btn-ghost" href="#/videos/${v.id}">Ouvrir le journal</a>
                </div>
              </div>
            </div>`;
          }).join("")}
        </div>
      </section>
      <section class="reveal" style="--i:4">
        <div class="section-title">${icon("list-filter")}File d'attente <span class="more">glisser pour réordonner</span></div>
        <div class="panel" id="queue-list">
          ${pending.map((v) => {
            const c = chan(v.channel);
            return `<div class="list-item" draggable="true" data-q="${v.id}">
              <span class="muted" style="cursor:grab">${icon("grip-vertical", "i-sm")}</span>
              ${srcIcon(c.platform)}
              <div class="li-main"><div class="li-title">${esc(v.title)}</div><div class="li-sub">${esc(c.name)} · ${v.duration} · ${esc(c.preset)}</div></div>
              <span class="mono muted">#${v.position}</span>
            </div>`;
          }).join("")}
        </div>
      </section>
    </div>

    <div class="stack">
      <section class="reveal" style="--i:3">
        <div class="section-title">${icon("clapperboard")}Clips à valider <a class="more" href="#/clips?f=review">${toValidate.length} au total ${icon("chevron-right", "i-xs")}</a></div>
        <div class="clips" style="grid-template-columns:repeat(4,minmax(0,1fr));gap:12px">
          ${toValidate.slice(0, 4).map((c) => `<a class="clip" href="#/clips?open=${c.id}">
            <div class="clip-poster" style="border-radius:10px">${clipPoster(c)}<div class="shade"></div>
              <div class="bottom"><span class="num">${c.duration.toFixed(0)} s</span></div>
              ${c.qa.length ? `<div class="top"><span></span><span class="pill-dark warn">${icon("triangle-alert", "i-xs")}QA</span></div>` : ""}
            </div></a>`).join("")}
        </div>
      </section>
      <section class="reveal" style="--i:4">
        <div class="section-title">${icon("send")}Prochaines publications <a class="more" href="#/publication">Calendrier ${icon("chevron-right", "i-xs")}</a></div>
        <div class="panel">
          ${upcoming.map((p) => {
            const c = clip(p.clip), ch = chan(c.channel), d = WEEK[p.day];
            return `<a class="list-item" href="#/publication">
              <div class="when">${p.slot}<small>${d.d} ${d.n}</small></div>
              <div class="mini-clip">${c.img ? `<img src="${c.img}" alt="">` : `<div style="width:100%;height:100%;background:${ch.color}44"></div>`}</div>
              <div class="li-main"><div class="li-title">${esc(c.screen_title)}</div><div class="li-sub">${esc(ch.tiktok || "compte TikTok à lier")}</div></div>
              <span class="chip info">Planifié</span>
            </a>`;
          }).join("")}
          <div class="list-item"><span class="muted">${icon("info", "i-sm")}</span><div class="li-main li-sub" style="margin:0">Autopost pas encore branché : ces créneaux servent de rappel, publication manuelle.</div></div>
        </div>
      </section>
      <section class="reveal" style="--i:5">
        <div class="section-title">${icon("coins")}Coût LLM, 7 jours <a class="more" href="#/stats">Détail ${icon("chevron-right", "i-xs")}</a></div>
        <div class="panel panel-pad">
          <div class="row" style="align-items:flex-end;gap:24px">
            <div><div class="big-num" style="font-size:44px">11,20<small> €</small></div><div class="muted" style="font-size:12px;margin-top:4px">équivalent API · backend claude-cli</div></div>
            <div class="chart grow" id="dash-cost"></div>
          </div>
        </div>
      </section>
    </div>
  </div>`;

  return {
    crumbs: [["Tableau de bord"]],
    html,
    mount(root) {
      const days = ["jeu", "ven", "sam", "dim", "lun", "mar", "mer"];
      const data = weekCost.map((v, i) => [days[i], v]);
      const box = $("#dash-cost", root);
      box.innerHTML = barChart({ data, label: "Coût LLM par jour" }).replace('viewBox="0 0 640 220"', 'viewBox="0 0 640 220" style="max-height:120px"');
      wireChart(box, data, (d) => `<span class="muted">${d[0]}</span><b>${fr(d[1], 2)} €</b>`);
      $$("[data-fix]", root).forEach((b) => b.addEventListener("click", (e) => {
        e.preventDefault();
        const item = b.closest("[data-att]");
        const v = video(item.dataset.att);
        const kind = b.dataset.fix;
        item.style.transition = "opacity 200ms ease, transform 260ms var(--ease-out)";
        item.style.opacity = "0"; item.style.transform = "translateX(12px)";
        setTimeout(() => { item.style.display = "none"; }, 260);
        const msg = { letterbox: ["Clip 3 passe en letterbox", "La vidéo reprend à l'étape recadrage."], skip: ["Clip 3 ignoré", "Les 7 autres clips continuent."],
          retry: ["Nouvel essai lancé", "download relancé avec --force."], remove: ["Vidéo retirée", "workspace/ conservé 7 jours."] }[kind];
        toast({ kind: kind === "remove" ? "warn" : "ok", title: msg[0], body: `${esc(v.title)} · ${msg[1]}`, undo: () => { item.style.display = ""; requestAnimationFrame(() => { item.style.opacity = "1"; item.style.transform = "none"; }); } });
      }));
      makeSortable($("#queue-list", root), "[data-q]");
    },
  };
};

function makeSortable(list, sel) {
  if (!list) return;
  let dragEl = null;
  list.addEventListener("dragstart", (e) => { dragEl = e.target.closest(sel); if (dragEl) { dragEl.style.opacity = "0.4"; e.dataTransfer.effectAllowed = "move"; } });
  list.addEventListener("dragend", () => {
    if (!dragEl) return;
    dragEl.style.opacity = "";
    $$(sel, list).forEach((el, i) => { const n = el.querySelector(".mono"); if (n) n.textContent = "#" + (i + 1); });
    toast({ kind: "ok", title: "File réordonnée", body: "Nouvel ordre pris en compte au prochain démarrage.", ms: 2600 });
    dragEl = null;
  });
  list.addEventListener("dragover", (e) => {
    e.preventDefault();
    const over = e.target.closest(sel);
    if (!over || over === dragEl || !dragEl) return;
    const r = over.getBoundingClientRect();
    list.insertBefore(dragEl, e.clientY < r.top + r.height / 2 ? over : over.nextSibling);
  });
}

/* ================= Videos ================= */
Views.videos = (params) => {
  const filters = [
    ["all", "Toutes", () => true],
    ["running", "En cours", (v) => v.status === "running"],
    ["pending", "En file", (v) => v.status === "pending"],
    ["review", "À revoir", (v) => v.status === "awaiting_review"],
    ["attention", "À débloquer", (v) => v.status === "queued" || v.status === "failed"],
    ["done", "Terminées", (v) => v.status === "done"],
  ];
  let f = params.f || "all", q = "", ch = "";
  const html = `
    ${head("", "Vidéos", "Chaque vidéo passe par 12 étapes. Une étape déjà faite ne se relance pas, sauf si tu le demandes.",
      `<button class="btn btn-primary" data-add>${icon("plus")}Ajouter une vidéo</button>`)}
    <div class="toolbar reveal" style="--i:1">
      <div class="seg" id="vf">${filters.map(([k, l, fn]) => `<button data-v="${k}" class="${k === f ? "on" : ""}">${l}<span class="n">${VIDEOS.filter(fn).length}</span></button>`).join("")}</div>
      <span class="grow"></span>
      <label class="input-ico">${icon("search")}<input class="input" id="vq" placeholder="Filtrer par titre" style="width:220px"></label>
      <select class="input" id="vc"><option value="">Toutes les chaînes</option>${CHANNELS.map((c) => `<option value="${c.id}">${esc(c.name)}</option>`).join("")}</select>
    </div>
    <div class="panel jobs reveal" style="--i:2" id="vlist"></div>`;
  return {
    crumbs: [["Vidéos"]],
    html,
    mount(root) {
      const list = $("#vlist", root);
      const render = (animate) => {
        const fn = filters.find((x) => x[0] === f)[2];
        const items = VIDEOS.filter(fn).filter((v) => (!ch || v.channel === ch) && (!q || v.title.toLowerCase().includes(q)));
        list.innerHTML = items.length ? items.map((v, i) => jobRow(v, { reason: true }).replace('class="job" data-href', `class="job${animate ? " reveal" : ""}" style="--i:${i}" data-href`)).join("")
          : `<div class="empty"><div class="empty-art">${icon("inbox")}</div><h3>Aucune vidéo ici</h3><p>Rien ne correspond à ce filtre. Change de filtre, ou ajoute une vidéo par son URL.</p><button class="btn btn-sm" data-add>${icon("plus")}Ajouter une vidéo</button></div>`;
        $$("[data-add]", list).forEach((b) => (b.onclick = () => openAddVideo()));
      };
      // squelettes au premier affichage (chargement de /api/videos)
      list.innerHTML = Array.from({ length: 4 }, () => `<div class="job"><div class="skel" style="width:96px;aspect-ratio:16/9"></div><div><div class="skel" style="height:14px;width:60%"></div><div class="skel" style="height:10px;width:40%;margin-top:10px"></div><div class="skel" style="height:6px;margin-top:16px"></div></div><div class="skel" style="width:72px;height:22px;border-radius:11px"></div></div>`).join("");
      setTimeout(() => render(true), 380);
      initSeg($("#vf", root), (v) => { f = v; render(true); });
      $("#vq", root).addEventListener("input", (e) => { q = e.target.value.toLowerCase(); render(false); });
      $("#vc", root).addEventListener("change", (e) => { ch = e.target.value; render(true); });
      $$("[data-add]", root).forEach((b) => (b.onclick = () => openAddVideo()));
    },
  };
};

/* ================= Fiche video + frise ================= */
Views.video = (params) => {
  const v = video(params.id) || VIDEOS[0];
  const c = chan(v.channel);
  const st = STATUS[v.status];
  let sel = v.status === "running" || v.status === "queued" || v.status === "failed" || v.status === "awaiting_review" ? v.step : 11;

  const outputs = {
    download: ["source.mp4", "info.json"], transcribe: ["transcript.json", "words.json"], scenes: ["scenes.json", "keyframes/"],
    audio: ["audio.json (énergie, rires)"], moments: ["moments.json", "jury.json"], vision: ["vision.json"], parts: ["parts.json"],
    captions: ["captions.json"], reframe: ["reframe/<clip>.json"], subtitles: ["subtitles/<clip>.ass"], render: ["output/<id>/<clip>.mp4"], qa: ["qa.json"],
  };
  const actions = v.status === "running"
    ? `<button class="btn btn-bad" data-cancel>${icon("ban")}Annuler</button>`
    : v.status === "awaiting_review" ? `<a class="btn btn-primary" href="#/revue/${v.id}">${icon("sparkles")}Revoir les moments</a>`
    : v.status === "done" ? `<a class="btn" href="#/clips">${icon("clapperboard")}Voir les ${v.clips} clips</a>`
    : v.status === "failed" ? `<button class="btn btn-primary" data-retry>${icon("refresh-cw")}Réessayer</button>` : "";

  const html = `
    <div class="page-head reveal" style="--i:0;align-items:center">
      <div class="job-thumb" style="width:168px;border-radius:10px">${videoThumb(v)}<span class="dur">${v.duration}</span></div>
      <div class="titles">
        <div class="eyebrow" style="color:var(--muted)">${srcIcon(c.platform)}<a href="#/chaines/${c.id}" style="color:var(--text-2)">${esc(c.name)}</a><span class="faint">·</span><span class="mono" style="text-transform:none;letter-spacing:0">${v.id}</span></div>
        <h1 style="font-size:32px">${esc(v.title)}</h1>
        <div class="row wrap" style="margin-top:12px;gap:8px"><span class="chip ${st.cls}" id="v-status">${st.label}</span><span class="tag">${icon("layers")}${esc(c.preset)}</span><span class="tag">${icon(c.mode === "auto" ? "zap" : "eye")}mode ${c.mode}</span><a class="tag" href="${v.url}" target="_blank" rel="noopener">${icon("external-link")}source</a></div>
      </div>
      <div class="actions">${actions}<button class="btn btn-ghost" aria-label="Plus">${icon("ellipsis")}</button></div>
    </div>

    ${v.reason ? `<div class="banner reveal" style="--i:1;background:var(${v.status === "failed" ? "--bad-soft" : "--warn-soft"});border-color:transparent">${icon(v.status === "failed" ? "circle-x" : "circle-pause", "i-lg")}<p style="flex:1"><b>${v.status === "failed" ? "Échec" : "En attente d'une décision"}.</b> ${esc(v.reason)}</p>${v.status === "queued" ? `<button class="btn btn-sm btn-primary" data-fix>Clip 3 en letterbox</button>` : ""}</div>` : ""}

    <section class="panel panel-pad reveal" style="--i:2">
      <div class="row" style="margin-bottom:24px">
        <h2 style="font-size:15px">Progression</h2>
        <span class="muted" style="font-size:13px" id="v-summary"></span>
        <span class="grow"></span>
        ${v.status === "running" ? `<span class="eta"><span data-eta="${v.id}">${v.eta}</span><small> min restantes</small></span>` : ""}
      </div>
      <div class="frise" id="frise"><div class="frise-fill" id="frise-fill"></div></div>
    </section>

    <div class="grid step-detail" style="margin-top:24px">
      <section class="panel reveal" style="--i:3" id="step-panel"></section>
      <section class="panel reveal" style="--i:4">
        <div class="panel-head"><h2>Journal</h2><span class="muted mono" style="font-size:12px">workspace/${v.id}/pipeline.log</span><div class="right"><button class="btn btn-xs btn-ghost" id="log-copy">${icon("copy", "i-xs")}Copier</button></div></div>
        <div style="padding:16px"><div class="log" id="log"></div></div>
      </section>
    </div>`;

  function renderFrise(root) {
    const fr_ = $("#frise", root);
    const fill = $("#frise-fill", root);
    fr_.querySelectorAll(".fstep").forEach((n) => n.remove());
    v.steps.forEach((s, i) => {
      const el = document.createElement("button");
      el.className = `fstep ${s.status}${i === sel ? " sel" : ""}`;
      el.dataset.i = i;
      if (s.status === "running") el.style.setProperty("--p", v.progress);
      const ic = s.status === "done" ? "check" : s.status === "failed" ? "x" : s.status === "queued" ? "circle-pause" : STEPS[i].icon;
      const time = s.status === "running" ? `${v.progress} %` : s.status === "review" ? "à revoir" : s.status === "queued" ? "attente" : s.d != null ? fmtDur(s.d) : "·";
      el.innerHTML = `<span class="node">${icon(ic)}</span><span class="fstep-name">${STEPS[i].label}</span><span class="fstep-time">${time}</span>`;
      el.onclick = () => { sel = i; renderFrise(root); renderStep(root); };
      fr_.appendChild(el);
    });
    const doneCount = v.steps.filter((s) => s.status === "done").length;
    const lastDone = v.steps.reduce((k, s, i) => (s.status === "done" ? i : k), -1);
    const partial = v.status === "running" ? v.progress / 100 : 0;
    const frac = Math.max(0, (lastDone + partial) / 11);
    requestAnimationFrame(() => { fill.style.width = `calc((100% - 100% / 12) * ${Math.min(1, frac)})`; });
    const total = v.steps.reduce((t, s) => t + (s.d || 0), 0);
    $("#v-summary", root).textContent = `${doneCount}/12 étapes · ${fmtDur(total)} de calcul`;
  }
  function renderStep(root) {
    const s = v.steps[sel], def = STEPS[sel];
    const label = { done: "Terminée", running: "En cours", pending: "Pas commencée", failed: "Échec", queued: "En attente", review: "En attente de revue" }[s.status];
    const cls = { done: "done", running: "running", pending: "pending", failed: "failed", queued: "queued", review: "review" }[s.status];
    $("#step-panel", root).innerHTML = `
      <div class="panel-head"><span class="node" style="width:32px;height:32px;border-width:1px;color:var(--text-2)">${icon(def.icon, "i-sm")}</span><h2>${def.label}</h2><span class="chip ${cls}">${label}</span></div>
      <div style="padding:24px">
        <dl class="kv">
          <dt>Module</dt><dd class="mono">${def.mod}</dd>
          <dt>Durée</dt><dd>${s.status === "running" ? `${v.progress} %, reste ${v.eta} min` : s.d != null ? fmtDur(s.d) : "·"}</dd>
          <dt>Sorties</dt><dd class="mono">${(outputs[def.id] || []).map((o) => esc(o.startsWith("output/") ? o.replace("<id>", v.id) : `workspace/${v.id}/${o}`)).join("<br>")}</dd>
          ${s.status === "running" ? `<dt>Détail</dt><dd>${esc(v.detail)}</dd>` : ""}
          ${def.id === "moments" && (s.status === "done" || s.status === "review") ? `<dt>LLM</dt><dd>moments · strong · 41 200 jetons · 0,39 € équiv.</dd>` : ""}
        </dl>
        <div class="row wrap" style="margin-top:24px;gap:8px">
          ${s.status === "done" || s.status === "failed" ? `<button class="btn btn-sm" data-force>${icon("rotate-ccw")}Relancer cette étape</button>` : ""}
          ${s.status === "review" ? `<a class="btn btn-sm btn-primary" href="#/revue/${v.id}">${icon("sparkles")}Ouvrir la revue</a>` : ""}
          ${s.status === "pending" ? `<span class="muted" style="font-size:13px">Démarre quand l'étape précédente est terminée.</span>` : ""}
        </div>
      </div>`;
    const fb = $("[data-force]", root);
    if (fb) fb.onclick = () => confirmForce(def, sel);
  }
  function confirmForce(def, idx) {
    const after = STEPS.slice(idx + 1).map((s) => s.label.toLowerCase());
    openPanel("modal", `
      <div class="modal-head"><h2>Relancer « ${def.label} » ?</h2></div>
      <div class="modal-body">
        <p class="muted">L'étape repart de zéro (<span class="mono">--force</span>). Les étapes suivantes seront refaites aussi, car elles dépendent de ses sorties :</p>
        <div class="row wrap" style="gap:6px">${after.length ? after.map((a) => `<span class="tag">${a}</span>`).join("") : `<span class="muted">aucune</span>`}</div>
        <p class="reason">Les clips déjà rendus de cette vidéo seront remplacés. Les publications planifiées restent en place.</p>
      </div>
      <div class="modal-foot"><button class="btn btn-ghost" data-dismiss>Annuler</button><button class="btn btn-primary" id="go-force">${icon("rotate-ccw")}Relancer</button></div>`,
      (el) => { $("#go-force", el).onclick = () => { closeLayer(); toast({ kind: "info", title: `${def.label} relancée`, body: `${after.length} étapes suivantes remises en attente.`, undo: () => toast({ kind: "ok", title: "Relance annulée", ms: 2000 }) }); }; });
  }

  return {
    crumbs: [["Vidéos", "#/videos"], [v.title]],
    html,
    mount(root) {
      renderFrise(root);
      renderStep(root);
      const log = $("#log", root);
      const lines = v.status === "running" && v.id === "mdj-0929" ? LOG_LINES
        : v.status === "failed" ? [["08:02:41", "i", "download", "yt-dlp " + v.url], ["08:02:44", "e", "download", "ERROR: [youtube] Join this channel to get access to members-only content"], ["08:02:44", "e", "pipeline", "étape download en échec, vidéo arrêtée (ADR-ad2e : pas de repli)"]]
        : v.status === "queued" ? [["11:58:02", "i", "reframe", "clip 3/7 · webcam vivante 29 % des images clés (seuil 50 %)"], ["11:58:02", "w", "reframe", "format stream impossible pour le clip 3, raison journalisée"], ["11:58:02", "w", "pipeline", "EXIT_QUEUED : décision attendue (letterbox ou ignorer)"]]
        : [["—", "i", "pipeline", "reprise depuis pipeline.json"], ["", "i", v.steps[Math.max(0, v.step)].id, v.detail]];
      const add = (l, fresh) => {
        const d = document.createElement("div");
        if (fresh) d.className = "new";
        d.innerHTML = `<span class="t">${l[0]}</span><span class="lv-${l[1]}">${l[1] === "e" ? "ERREUR" : l[1] === "w" ? "ATTENTION" : "info"}</span> <span class="faint">${l[2]}</span> ${esc(l[3])}`;
        log.appendChild(d);
        log.scrollTop = log.scrollHeight;
      };
      lines.forEach((l) => add(l));
      $("#log-copy", root).onclick = () => copyText(log.innerText, "Journal");
      const cb = $("[data-cancel]", root);
      if (cb) cb.onclick = () => openPanel("modal", `<div class="modal-head"><h2>Annuler le traitement ?</h2></div><div class="modal-body"><p class="muted">L'étape en cours (${stepLabel(v.steps[v.step].id).toLowerCase()}) s'arrête. Les étapes terminées restent dans workspace/ : tu pourras reprendre plus tard sans tout refaire.</p></div><div class="modal-foot"><button class="btn btn-ghost" data-dismiss>Continuer le traitement</button><button class="btn btn-bad" id="go-cancel">${icon("ban")}Annuler</button></div>`,
        (el) => { $("#go-cancel", el).onclick = () => { closeLayer(); $("#v-status", root).className = "chip queued"; $("#v-status", root).textContent = "Annulée"; toast({ kind: "warn", title: "Traitement annulé", body: "Étapes terminées conservées.", undo: () => { $("#v-status", root).className = "chip running"; $("#v-status", root).textContent = "En cours"; } }); }; });
      const rb = $("[data-retry]", root);
      if (rb) rb.onclick = () => toast({ kind: "info", title: "Nouvel essai lancé", body: "download relancé avec --force." });
      const fx = $("[data-fix]", root);
      if (fx) fx.onclick = () => toast({ kind: "ok", title: "Clip 3 passe en letterbox", body: "Reprise à l'étape recadrage.", undo: () => {} });
      // Journal vivant pour la video en cours
      if (v.id === "mdj-0929") {
        let k = 5;
        App.onTick(root, () => {
          if (Math.random() < 0.5) add([new Date(NOW.getTime() + App.elapsed * 1000).toTimeString().slice(0, 8), "i", "reframe", `clip ${k}/8 m${k + 3} · webcam vivante ${90 + (k % 7)} % · stream split`], true), (k = Math.min(8, k + 1));
          renderFriseLive(root);
        });
      }
      function renderFriseLive(r) {
        const run = $(".fstep.running", r);
        if (run) { run.style.setProperty("--p", v.progress); run.querySelector(".fstep-time").textContent = `${v.progress} %`; }
        const lastDone = v.steps.reduce((k2, s, i) => (s.status === "done" ? i : k2), -1);
        $("#frise-fill", r).style.width = `calc((100% - 100% / 12) * ${Math.min(1, (lastDone + v.progress / 100) / 11)})`;
        if (run && +run.dataset.i !== v.step) { renderFrise(r); renderStep(r); }
      }
    },
  };
};

/* ================= Clips ================= */
Views.clips = (params) => {
  const filters = [["review", "À valider"], ["approved", "Approuvés"], ["scheduled", "Planifiés"], ["published", "Publiés"], ["rejected", "Refusés"], ["all", "Tous"]];
  let f = params.f || "review", ch = "";
  const html = `
    ${head("", "Clips", "Vérifie chaque clip avant publication : texte à l'écran, description, contrôle qualité.",
      `<button class="btn" id="dl-all">${icon("download")}Télécharger les approuvés</button>`)}
    <div class="toolbar reveal" style="--i:1">
      <div class="seg" id="cf">${filters.map(([k, l]) => `<button data-v="${k}" class="${k === f ? "on" : ""}">${l}<span class="n">${k === "all" ? CLIPS.length : CLIPS.filter((c) => c.status === k).length}</span></button>`).join("")}</div>
      <span class="grow"></span>
      <select class="input" id="cc"><option value="">Toutes les chaînes</option>${CHANNELS.map((c) => `<option value="${c.id}">${esc(c.name)}</option>`).join("")}</select>
    </div>
    <div class="clips" id="cgrid"></div>`;
  return {
    crumbs: [["Clips"]],
    html,
    mount(root) {
      const grid = $("#cgrid", root);
      const render = () => {
        const items = CLIPS.filter((c) => (f === "all" || c.status === f) && (!ch || c.channel === ch));
        if (!items.length) {
          grid.innerHTML = `<div class="empty" style="grid-column:1/-1"><div class="empty-art">${icon("party-popper")}</div><h3>Tout est traité</h3><p>Plus aucun clip dans cette catégorie. Les prochains arriveront quand la VOD du 29/09 aura fini son rendu.</p></div>`;
          return;
        }
        grid.innerHTML = items.map((c, i) => {
          const s = CLIP_STATUS[c.status], chn = chan(c.channel);
          return `<div class="clip reveal" style="--i:${i}" data-clip="${c.id}" tabindex="0">
            <div class="clip-poster">${clipPoster(c)}<div class="shade"></div>
              <div class="top"><span class="pill-dark ${s.cls}">${s.label}</span>${c.parts[1] > 1 ? `<span class="pill-dark">${c.parts[0]}/${c.parts[1]}</span>` : ""}</div>
              <span class="play">${icon("play")}</span>
              <div class="bottom"><span class="num">${c.duration.toFixed(1).replace(".", ",")} s</span><span class="grow"></span>${c.qa.length ? `<span class="pill-dark warn">${icon("triangle-alert", "i-xs")}QA</span>` : ""}<span class="pill-dark">${c.score}</span></div>
            </div>
            <div class="clip-title">${esc(c.screen_title)}</div>
            <div class="clip-sub">${srcIcon(chn.platform)}${esc(chn.name)}</div>
          </div>`;
        }).join("");
        $$("[data-clip]", grid).forEach((el) => {
          el.onclick = () => openClip(el.dataset.clip, render);
          el.onkeydown = (e) => { if (e.key === "Enter") openClip(el.dataset.clip, render); };
        });
      };
      render();
      initSeg($("#cf", root), (v) => { f = v; render(); });
      $("#cc", root).addEventListener("change", (e) => { ch = e.target.value; render(); });
      $("#dl-all", root).onclick = () => toast({ kind: "ok", title: "Archive en préparation", body: "1 clip approuvé · .mp4 + .json" });
      if (params.open) setTimeout(() => openClip(params.open, render), 250);
    },
  };
};

function openClip(id, onChange) {
  const c = clip(id), chn = chan(c.channel), v = video(c.video), s = CLIP_STATUS[c.status];
  const sidecar = {
    clip_id: c.id, video_id: c.video, file: `output/${c.video}/${c.id}.mp4`, duration: c.duration,
    screen_title: c.screen_title, description: c.description, hashtags: c.hashtags,
    part: c.parts[0], parts_total: c.parts[1], score: c.score, layout: chn.layout, qa: { issues: c.qa },
  };
  const el = openPanel("drawer", `
    <div class="drawer-head">
      <span class="chip ${s.cls}">${s.label}</span>
      <h2>${esc(c.screen_title)}</h2>
      <button class="icon-btn" data-dismiss aria-label="Fermer">${icon("x")}</button>
    </div>
    <div class="drawer-body">
      <div>
        <div class="phone" id="ph">${clipPoster(c)}<div class="pbtn"><span>${icon("play", "i-lg")}</span></div><div class="scrub"><i></i></div></div>
        ${c.parts[1] > 1 ? `<div class="parts">${Array.from({ length: c.parts[1] }, (_, k) => `<div class="part ${k + 1 === c.parts[0] ? "on" : ""}">Partie ${k + 1}</div>`).join("")}</div>` : ""}
        <div class="row" style="justify-content:center;margin-top:16px;gap:16px;font-size:13px" >
          <span class="muted">${icon("timer", "i-xs")}</span><span class="mono">${c.duration.toFixed(1)} s</span><span class="muted">·</span><span class="mono">1080×1920</span><span class="muted">·</span><span>score <b class="num" style="font-size:16px">${c.score}</b></span>
        </div>
      </div>
      <div class="stack" style="gap:24px">
        <div class="row wrap muted" style="font-size:13px;gap:8px">${srcIcon(chn.platform)}${esc(chn.name)}<span>·</span><a href="#/videos/${v ? v.id : ""}" style="text-decoration:underline;text-underline-offset:3px">${esc(v ? v.title : c.video)}</a></div>
        <div class="field"><label for="f-title">Titre d'écran</label><input class="input" id="f-title" value="${esc(c.screen_title)}"><span class="hint">Affiché en haut du clip. Sobre, sans emoji (SPEC-6a86).</span></div>
        <div class="field"><label for="f-desc">Description</label><textarea class="input" id="f-desc" rows="3">${esc(c.description)}</textarea><div class="counter"><span id="f-count">${c.description.length}</span> / 2 200</div></div>
        <div class="field"><span class="field-label">Hashtags</span><div class="hashtags">${c.hashtags.map((h) => `<span class="tag">${esc(h)}</span>`).join("")}<button class="tag" style="color:var(--muted);border-style:dashed">${icon("plus", "i-xs")}ajouter</button></div></div>
        <div class="field"><span class="field-label">Contrôle qualité</span>
          ${c.qa.length ? c.qa.map((q) => `<div class="qa-item">${icon("triangle-alert", "i-sm")}<span>${esc(q)}</span></div>`).join("") : `<div class="qa-item ok">${icon("circle-check", "i-sm")}<span>Aucun problème : 1080×1920, durée conforme, pas de silence initial, sous-titres dans la zone sûre.</span></div>`}
        </div>
        <details><summary class="muted" style="cursor:pointer;font-size:13px">Sidecar JSON (SPEC-6a47)</summary><div class="code" style="margin-top:8px">${esc(JSON.stringify(sidecar, null, 2))}</div></details>
      </div>
    </div>
    <div class="drawer-foot">
      <button class="btn btn-ok" id="d-ok">${icon("check")}Approuver</button>
      <button class="btn btn-bad" id="d-no">${icon("x")}Refuser</button>
      <button class="btn" id="d-rr">${icon("refresh-cw")}Re-rendre</button>
      <span class="grow"></span>
      <button class="btn btn-ghost" id="d-copy">${icon("copy")}Copier la description</button>
      <button class="btn btn-ghost" id="d-dl">${icon("download")}Télécharger</button>
    </div>`, (d) => {
    const ph = $("#ph", d);
    ph.onclick = () => ph.classList.toggle("playing");
    $("#f-desc", d).addEventListener("input", (e) => ($("#f-count", d).textContent = e.target.value.length));
    const decide = (st, kind, title) => {
      const prev = c.status;
      c.status = st;
      closeLayer();
      onChange && onChange();
      toast({ kind, title, body: esc(c.screen_title), undo: () => { c.status = prev; onChange && onChange(); } });
      App.refreshCounts();
    };
    $("#d-ok", d).onclick = () => decide("approved", "ok", "Clip approuvé");
    $("#d-no", d).onclick = () => decide("rejected", "warn", "Clip refusé");
    $("#d-rr", d).onclick = () => toast({ kind: "info", title: "Nouveau rendu en file", body: "render + qa relancés pour ce clip." });
    $("#d-copy", d).onclick = () => copyText(`${$("#f-desc", d).value}\n\n${c.hashtags.join(" ")}`, "Description");
    $("#d-dl", d).onclick = () => toast({ kind: "ok", title: "Téléchargement", body: `${c.id}.mp4 (${(c.duration * 0.21).toFixed(1).replace(".", ",")} Mo)`, ms: 2600 });
  });
  return el;
}

/* ================= Publication ================= */
Views.publication = () => {
  const html = `
    ${head("", "Publication", "Planifie les clips approuvés sur les créneaux de chaque chaîne.",
      `<button class="btn" id="auto-fill">${icon("wand-sparkles")}Remplir les créneaux libres</button>`)}
    <div class="banner reveal" style="--i:1">${icon("info", "i-lg")}<p><b>Autopost TikTok pas encore branché.</b> Au créneau, Clipper te notifie : télécharge le clip, copie la description, publie depuis l'appli. Le statut passe à « publié » quand tu confirmes.</p></div>
    <div class="grid g-side reveal" style="--i:2;align-items:start" id="pub-grid">
      <div class="stack">
        <section>
          <div class="section-title">${icon("inbox")}À publier <span class="more" id="q-count"></span></div>
          <div class="queue" id="queue"></div>
        </section>
        <section>
          <div class="section-title">${icon("user")}Comptes TikTok</div>
          <div class="panel">${CHANNELS.map((c) => `<div class="list-item"><span class="src-ico" style="background:${c.color};color:#111;font-weight:700;font-size:12px">${c.initial}</span><div class="li-main"><div class="li-title">${esc(c.tiktok || "Aucun compte")}</div><div class="li-sub">${esc(c.name)} · créneaux ${c.slots.join(", ")}</div></div><button class="btn btn-xs" disabled>Lier</button></div>`).join("")}</div>
        </section>
      </div>
      <section>
        <div class="row wrap" style="margin-bottom:12px">
          <div class="row" style="gap:4px"><button class="icon-btn" aria-label="Semaine précédente">${icon("chevron-left")}</button><h2 style="font-size:16px">28 sept. au 4 oct.</h2><button class="icon-btn" aria-label="Semaine suivante">${icon("chevron-right")}</button></div>
          <span class="grow"></span>
          <div class="legend">${CHANNELS.map((c) => `<span><i style="background:${c.color}"></i>${esc(c.name)}</span>`).join("")}<span><i style="background:var(--ok)"></i>publié</span><span><i style="background:var(--bad)"></i>échec</span></div>
        </div>
        <div class="cal-wrap"><div class="cal" id="cal"></div></div>
      </section>
    </div>`;
  return {
    crumbs: [["Publication"]],
    html,
    mount(root) {
      const cal = $("#cal", root), queue = $("#queue", root);
      const postHTML = (id, extra, st) => {
        const c = clip(id);
        return `<div class="post ch-${c.channel} ${st || ""}" draggable="${st === "published" ? "false" : "true"}" data-post="${id}" title="${esc(c.screen_title)}">
          <div class="mini-clip">${c.img ? `<img src="${c.img}" alt="">` : `<div style="width:100%;height:100%;background:${chan(c.channel).color}55"></div>`}</div>
          <span class="pt">${esc(c.screen_title)}</span>${extra || ""}</div>`;
      };
      const render = () => {
        let h = `<div class="cal-h"></div>` + WEEK.map((d) => `<div class="cal-h ${d.today ? "today" : ""}"><div class="d">${d.d}</div><div class="n">${d.n}</div></div>`).join("");
        CAL_SLOTS.forEach((slot) => {
          h += `<div class="cal-t">${slot}</div>`;
          WEEK.forEach((d, di) => {
            const past = di < 2 || (di === 2 && slot < "21:34");
            const posts = POSTS.filter((p) => p.day === di && p.slot === slot);
            h += `<div class="cal-c ${past ? "past" : ""}" data-day="${di}" data-slot="${slot}">${posts.map((p) => postHTML(p.clip, p.status === "published" ? icon("circle-check", "i-xs") : p.status === "failed" ? icon("circle-alert", "i-xs") : "", p.status)).join("")}</div>`;
          });
        });
        cal.innerHTML = h;
        const q = QUEUE.filter((id) => !POSTS.some((p) => p.clip === id));
        queue.innerHTML = q.length ? q.map((id) => postHTML(id, `<span class="grow"></span><span class="muted">${icon("grip-vertical", "i-xs")}</span>`)).join("")
          : `<div class="panel empty" style="padding:24px"><div class="empty-art">${icon("circle-check")}</div><p>Tout est planifié.</p></div>`;
        $("#q-count", root).textContent = q.length ? `${q.length} clips` : "";
      };
      render();
      let dragId = null;
      root.addEventListener("dragstart", (e) => { const p = e.target.closest("[data-post]"); if (!p) return; dragId = p.dataset.post; p.classList.add("dragging"); e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", dragId); });
      root.addEventListener("dragend", (e) => { const p = e.target.closest("[data-post]"); if (p) p.classList.remove("dragging"); $$(".cal-c.drop", root).forEach((c) => c.classList.remove("drop")); });
      root.addEventListener("dragover", (e) => { const c = e.target.closest(".cal-c"); if (!c || c.classList.contains("past")) return; e.preventDefault(); $$(".cal-c.drop", root).forEach((x) => x !== c && x.classList.remove("drop")); c.classList.add("drop"); });
      root.addEventListener("drop", (e) => {
        const c = e.target.closest(".cal-c"); if (!c || !dragId) return; e.preventDefault();
        schedule(dragId, +c.dataset.day, c.dataset.slot);
      });
      function schedule(id, day, slot) {
        const prev = POSTS.find((p) => p.clip === id);
        const before = prev ? { day: prev.day, slot: prev.slot } : null;
        if (prev) { prev.day = day; prev.slot = slot; prev.status = "scheduled"; } else POSTS.push({ clip: id, day, slot, status: "scheduled" });
        render();
        const landed = $(`.cal-c[data-day="${day}"][data-slot="${slot}"] [data-post="${id}"]`, root);
        if (landed) landed.classList.add("landed");
        const d = WEEK[day];
        toast({ kind: "ok", title: `Planifié ${d.d} ${d.n} à ${slot}`, body: esc(clip(id).screen_title), undo: () => {
          const p = POSTS.find((x) => x.clip === id);
          if (before) { p.day = before.day; p.slot = before.slot; } else POSTS.splice(POSTS.indexOf(p), 1);
          render();
        } });
      }
      $("#auto-fill", root).onclick = () => {
        const q = QUEUE.filter((id) => !POSTS.some((p) => p.clip === id));
        const free = [[3, "12:30"], [3, "18:00"], [4, "12:30"], [4, "08:00"]];
        q.forEach((id, k) => { if (free[k]) POSTS.push({ clip: id, day: free[k][0], slot: free[k][1], status: "scheduled" }); });
        render();
        $$(".post", cal).forEach((p) => q.includes(p.dataset.post) && p.classList.add("landed"));
        toast({ kind: "ok", title: `${q.length} clips planifiés`, body: "Sur les créneaux libres de leur chaîne.", undo: () => { q.forEach((id) => { const i = POSTS.findIndex((p) => p.clip === id); if (i >= 0) POSTS.splice(i, 1); }); render(); } });
      };
    },
  };
};

/* ================= Statistiques ================= */
Views.stats = () => {
  const totalCost = LLM_USAGE.reduce((t, u) => t + u[2], 0);
  const totalTok = LLM_USAGE.reduce((t, u) => t + u[1], 0);
  const perHour = STEP_TIME.reduce((t, s) => t + s[1], 0);
  const html = `
    ${head("", "Statistiques", "Production, coûts et temps de calcul. Les vues TikTok arriveront avec l'autopost.",
      `<div class="seg" id="range"><button data-v="7" class="on">7 jours</button><button data-v="30">30 jours</button><button data-v="all">Tout</button></div>`)}
    <div class="kpis kpis-4 reveal" style="--i:1">
      <div class="kpi"><div class="kpi-label">Clips produits</div><div class="kpi-value"><span data-count="64">0</span></div><div class="kpi-foot">sur 14 jours · 4,6 par jour</div></div>
      <div class="kpi"><div class="kpi-label">Acceptés en revue</div><div class="kpi-value"><span data-count="71">0</span><small>%</small></div><div class="kpi-foot">45 sur 63 moments proposés</div></div>
      <div class="kpi"><div class="kpi-label">Calcul par heure de vidéo</div><div class="kpi-value"><span data-count="${perHour.toFixed(1)}" data-dec="1">0</span><small>min</small></div><div class="kpi-foot">GPU RTX 3050, rendu x264</div></div>
      <div class="kpi"><div class="kpi-label">Coût LLM</div><div class="kpi-value"><span data-count="${totalCost.toFixed(2)}" data-dec="2">0</span><small>€</small></div><div class="kpi-foot">${fr(totalTok / 1e6, 2)} M jetons · équiv. API</div></div>
    </div>
    <div class="grid g-wide-l reveal" style="--i:2;margin-top:24px">
      <section class="panel"><div class="panel-head"><h2>Clips produits par jour</h2><div class="right muted" style="font-size:12px">14 derniers jours</div></div><div class="panel-pad"><div class="chart" id="ch-day"></div></div></section>
      <section class="panel"><div class="panel-head"><h2>Coût LLM par usage</h2><div class="right muted" style="font-size:12px">7 jours · €</div></div><div class="panel-pad"><div class="chart" id="ch-cost"></div></div></section>
    </div>
    <div class="grid g-wide-r reveal" style="--i:3;margin-top:24px">
      <section class="panel"><div class="panel-head"><h2>Temps par étape</h2><div class="right muted" style="font-size:12px">min de calcul par heure de vidéo</div></div><div class="panel-pad"><div class="chart" id="ch-step"></div></div></section>
      <section class="panel soon"><div class="panel-head"><h2>Résultats par clip</h2></div>
        <table class="table"><thead><tr><th>Clip</th><th>Chaîne</th><th class="r">Score</th><th class="r">Vues</th><th class="r">Rétention</th></tr></thead><tbody>
        ${CLIPS.filter((c) => c.status === "published" || c.status === "scheduled").map((c) => `<tr class="clickable"><td style="font-weight:600">${esc(c.screen_title)}</td><td class="muted">${esc(chan(c.channel).name)}</td><td class="r num" style="font-size:16px">${c.score}</td><td class="r faint">·</td><td class="r faint">·</td></tr>`).join("")}
        </tbody></table>
        <p class="muted" style="font-size:13px;padding:16px 24px">Les colonnes vues et rétention se rempliront via clipper.outcomes quand l'autopost remontera les chiffres TikTok. Elles serviront aussi à recalibrer le jury.</p>
      </section>
    </div>`;
  return {
    crumbs: [["Statistiques"]],
    html,
    mount(root) {
      const d1 = $("#ch-day", root); d1.innerHTML = barChart({ data: CLIPS_PER_DAY, label: "Clips par jour" });
      wireChart(d1, CLIPS_PER_DAY, (d) => `<span class="muted">${d[0]}</span><b>${d[1]} clips</b>`);
      const cost = LLM_USAGE.map((u) => [u[0], u[2]]);
      const d2 = $("#ch-cost", root); d2.innerHTML = barChart({ data: cost, horizontal: true, unit: " €", fmtV: (v) => fr(v, 2), label: "Coût par usage" });
      wireChart(d2, LLM_USAGE, (u) => `<span class="muted mono">${u[0]}</span><b>${fr(u[2], 2)} €</b><span class="muted">${fr(u[1])} jetons</span>`);
      const st = STEP_TIME.map((s) => [stepLabel(s[0]), s[1]]);
      const d3 = $("#ch-step", root); d3.innerHTML = barChart({ data: st, horizontal: true, unit: " min", fmtV: (v) => fr(v, 1), label: "Temps par étape" });
      wireChart(d3, st, (s) => `<span class="muted">${s[0]}</span><b>${fr(s[1], 1)} min / h</b>`);
      initSeg($("#range", root), () => toast({ kind: "info", title: "Période changée", body: "Maquette : mêmes données factices.", ms: 2000 }));
    },
  };
};

/* ================= Chaines (liste) ================= */
Views.channels = () => {
  const html = `
    ${head("", "Chaînes", "Une chaîne = une source, un preset de rendu, un mode et des créneaux de publication.",
      `<button class="btn btn-primary" id="new-ch">${icon("plus")}Nouvelle chaîne</button>`)}
    <div class="channels">
      ${CHANNELS.map((c, i) => `
      <article class="panel ch-card reveal" style="--i:${i + 1}">
        <div class="ch-cover">${c.id === "ma_chaine" ? `<img src="img/frame_180.jpg" alt="">` : c.cover ? `<img src="${c.cover}" alt="">` : `<div style="position:absolute;inset:0;background:radial-gradient(90% 140% at 15% 0%, ${c.color}66, transparent 60%), repeating-linear-gradient(135deg, transparent 0 12px, rgba(255,255,255,0.025) 12px 13px)"></div>`}</div>
        <div class="ch-avatar" style="background:${c.color};color:#111">${c.initial}</div>
        <div class="ch-body">
          <div><div class="ch-name">${esc(c.name)}</div><div class="ch-handle">${srcIcon(c.platform)}${esc(c.handle)}</div><div class="muted" style="font-size:13px;margin-top:4px">${esc(c.genre)}</div></div>
          <div class="ch-stats"><div><b>${c.stats.videos}</b><span>vidéos</span></div><div><b>${c.stats.clips}</b><span>clips</span></div><div><b style="color:${c.stats.pending ? "var(--accent)" : "inherit"}">${c.stats.pending}</b><span>à valider</span></div></div>
          <dl class="ch-props">
            <dt>Nouvelles VOD</dt><dd><label class="switch"><input type="checkbox" data-watch="${c.id}" ${c.watch ? "checked" : ""}><span></span></label><span class="muted" style="font-size:12px" data-watch-l="${c.id}">${c.watch ? `surveillée · ${c.lastCheck}` : "surveillance coupée"}</span></dd>
            <dt>Preset</dt><dd><span class="tag">${icon("layers")}${esc(c.preset)}</span></dd>
            <dt>Mode</dt><dd><span class="chip ${c.mode === "auto" ? "running" : "info"} plain">${icon(c.mode === "auto" ? "zap" : "eye", "i-xs")}${c.mode === "auto" ? "auto (jury décide)" : "review (tu valides)"}</span></dd>
            <dt>TikTok</dt><dd>${c.tiktok ? `<span>${esc(c.tiktok)}</span><span class="faint" style="font-size:12px">non lié</span>` : `<span class="faint">à définir</span>`}</dd>
            <dt>Créneaux</dt><dd>${c.slots.map((s) => `<span class="mono">${s}</span>`).join(" ")}</dd>
          </dl>
          <div class="ch-foot"><a class="btn btn-sm grow" href="#/chaines/${c.id}">${icon("sliders-horizontal")}Éditer le preset</a><a class="btn btn-sm btn-ghost" href="#/videos">${icon("film")}Vidéos</a></div>
        </div>
      </article>`).join("")}
      <button class="panel ch-card ch-new reveal" style="--i:4" id="new-ch-2"><div class="empty"><div class="empty-art">${icon("plus")}</div><h3>Ajouter une chaîne</h3><p>Colle l'URL d'une chaîne YouTube ou Twitch, on part d'un preset existant.</p></div></button>
    </div>`;
  return {
    crumbs: [["Chaînes"]],
    html,
    mount(root) {
      $$("[data-watch]", root).forEach((inp) => inp.addEventListener("change", () => {
        const c = chan(inp.dataset.watch);
        c.watch = inp.checked;
        $(`[data-watch-l="${c.id}"]`, root).textContent = c.watch ? "surveillée · vérifiée à l'instant" : "surveillance coupée";
        toast({ kind: c.watch ? "ok" : "warn", title: c.watch ? `Surveillance activée` : `Surveillance coupée`, body: `${esc(c.name)} · ${c.watch ? "nouvelle VOD = ajout automatique en file" : "les nouvelles VOD ne sont plus ajoutées"}`, undo: () => { inp.checked = !inp.checked; inp.dispatchEvent(new Event("change")); } });
      }));
      const nc = () => toast({ kind: "info", title: "Nouvelle chaîne", body: "Maquette : formulaire à venir (URL, preset de départ, mode)." });
      $("#new-ch", root).onclick = nc; $("#new-ch-2", root).onclick = nc;
    },
  };
};

/* ================= Reglages ================= */
Views.settings = () => {
  const usages = [["moments", "claude-cli", "strong"], ["vision", "claude-cli", "fast"], ["parts", "claude-cli", "fast"], ["captions", "claude-cli", "fast"], ["jury_retention", "claude-cli", "strong"], ["jury_spectateur", "claude-cli", "fast"], ["jury_monteur", "claude-cli", "strong"], ["jury_avocat", "claude-cli", "strong"], ["jury_conformite", "claude-cli", "fast"]];
  const sel = (opts, v) => `<select class="input" style="height:32px;font-size:13px">${opts.map((o) => `<option ${o === v ? "selected" : ""}>${o}</option>`).join("")}</select>`;
  const html = `
    ${head("", "Réglages", "Écrits dans config.toml. Chaque table correspond au CONFIG_DEFAULTS d'un module.")}
    <div class="settings">
      <nav class="settings-nav reveal" style="--i:1" id="snav">
        <a href="#s-general" class="on">Général</a><a href="#s-llm">LLM et modèles</a><a href="#s-jury">Jury</a><a href="#s-dirs">Dossiers</a><a href="#s-machine">Machine</a><a href="#s-notif">Notifications</a><a href="#s-remote">Accès distant</a><a href="#s-keys">Raccourcis</a>
      </nav>
      <div class="stack" id="sform">
        <section class="panel reveal" style="--i:2" id="s-general"><div class="panel-head"><h2>Général</h2><span class="muted mono" style="font-size:12px">[pipeline]</span></div><div class="panel-pad">
          <div class="toggle-row"><div class="li-main"><div class="li-title">Mode par défaut</div><div class="li-sub">Review : tu valides les moments. Auto : le jury décide, un veto conformité repasse en review. Chaque chaîne peut surcharger.</div></div><div class="seg" id="mode-seg"><button data-v="review" class="on">review</button><button data-v="auto">auto</button></div></div>
          <div class="toggle-row"><div class="li-main"><div class="li-title">Thème</div><div class="li-sub">Sombre par défaut. Suit aussi le bouton en haut.</div></div><div class="seg" id="theme-seg"><button data-v="dark" class="${document.documentElement.dataset.theme !== "light" ? "on" : ""}">${icon("moon", "i-xs")}Sombre</button><button data-v="light" class="${document.documentElement.dataset.theme === "light" ? "on" : ""}">${icon("sun", "i-xs")}Clair</button></div></div>
          <div class="toggle-row"><div class="li-main"><div class="li-title">Vidéos en parallèle</div><div class="li-sub">Un seul modèle lourd en VRAM à la fois (ADR-fb9b) : la 2ᵉ vidéo prend le CPU pour ses étapes lourdes.</div></div>${sel(["1", "2", "3"], "2")}</div>
        </div></section>

        <section class="panel reveal" style="--i:3" id="s-llm"><div class="panel-head"><h2>LLM et modèles</h2><span class="muted mono" style="font-size:12px">[llm]</span></div><div class="panel-pad">
          <div class="form-grid">
            <div class="field"><label>Backend par défaut</label>${sel(["claude-cli", "ollama"], "claude-cli")}<span class="hint">Texte et images fixes seulement (ADR-b1c1).</span></div>
            <div class="field"><label>Essais de réparation</label>${sel(["0", "1", "2"], "1")}<span class="hint">Réponse hors schéma JSON : 0 = échoue tout de suite.</span></div>
            <div class="field"><label>Niveau strong</label><input class="input" value="opus"></div>
            <div class="field"><label>Niveau fast</label><input class="input" value="sonnet"></div>
          </div>
          <table class="table" style="margin-top:24px"><thead><tr><th>Usage</th><th>Backend</th><th>Modèle</th><th class="r">7 jours</th></tr></thead><tbody>
          ${usages.map((u) => { const cost = (LLM_USAGE.find((x) => x[0] === u[0]) || [0, 0, 0])[2]; return `<tr><td class="mono">${u[0]}</td><td>${sel(["claude-cli", "ollama"], u[1])}</td><td>${sel(["strong", "fast"], u[2])}</td><td class="r num" style="font-size:15px">${fr(cost, 2)} €</td></tr>`; }).join("")}
          </tbody></table>
        </div></section>

        <section class="panel reveal" style="--i:4" id="s-jury"><div class="panel-head"><h2>Jury</h2><span class="muted mono" style="font-size:12px">[jury]</span></div><div class="panel-pad">
          ${Object.entries(JUDGES).map(([k, j]) => `<div class="toggle-row"><div class="li-main"><div class="li-title">${j.label}</div><div class="li-sub mono">jury_${k} · ${j.model}</div></div>${j.veto ? `<span class="chip warn plain">veto</span>` : ""}<label class="switch" title="Actif"><input type="checkbox" checked><span></span></label></div>`).join("")}
          <div class="field" style="margin-top:16px"><label>Écart max entre juges avant revue humaine</label><div class="row"><input type="range" min="10" max="60" value="30" id="gap-r"><b class="num" style="font-size:18px;width:48px;text-align:right" id="gap-v">30 pts</b></div></div>
        </div></section>

        <section class="panel reveal" style="--i:5" id="s-dirs"><div class="panel-head"><h2>Dossiers</h2></div><div class="panel-pad"><div class="form-grid">
          <div class="field"><label>Espace de travail</label><input class="input mono" value="workspace/"></div>
          <div class="field"><label>Sorties</label><input class="input mono" value="output/"></div>
          <div class="field"><label>Grille de notation</label><input class="input mono" value="rubric.toml"><span class="hint">Fichier absent = erreur explicite, pas de grille de secours.</span></div>
          <div class="field"><label>Garder workspace/ après publication</label>${sel(["7 jours", "30 jours", "toujours"], "7 jours")}</div>
        </div></div></section>

        <section class="panel reveal" style="--i:6" id="s-machine"><div class="panel-head"><h2>Machine</h2><span class="muted mono" style="font-size:12px">clipper.gpu</span></div><div class="panel-pad">
          <dl class="kv"><dt>Device</dt><dd>auto → <b>cuda</b> (RTX 3050 Laptop, 4 Go)</dd><dt>Transcription</dt><dd>faster-whisper large-v3 · float16</dd><dt>Encodeur</dt><dd>x264 medium, crf 20 (nvenc p5 disponible)</dd><dt>ffmpeg</dt><dd class="mono">7.1 · WinGet</dd></dl>
        </div></section>

        <section class="panel reveal" style="--i:7" id="s-notif"><div class="panel-head"><h2>Notifications</h2></div><div class="panel-pad">
          <div class="toggle-row"><div class="li-main"><div class="li-title">Notifications du navigateur</div><div class="li-sub">Même onglet fermé : vidéo terminée, en attente, en échec.</div></div><label class="switch"><input type="checkbox" id="n-browser"><span></span></label></div>
          <div class="toggle-row"><div class="li-main"><div class="li-title">Vidéo terminée</div></div><label class="switch"><input type="checkbox" checked><span></span></label></div>
          <div class="toggle-row"><div class="li-main"><div class="li-title">Vidéo en attente ou en échec</div></div><label class="switch"><input type="checkbox" checked><span></span></label></div>
          <div class="toggle-row"><div class="li-main"><div class="li-title">Rappel de créneau de publication</div><div class="li-sub">15 min avant, tant que l'autopost n'est pas branché.</div></div><label class="switch"><input type="checkbox" checked><span></span></label></div>
        </div></section>

        <section class="panel reveal" style="--i:8" id="s-remote"><div class="panel-head"><h2>Accès distant</h2><span class="chip info plain">plus tard</span></div><div class="panel-pad">
          <p class="muted" style="max-width:65ch">Aujourd'hui l'interface écoute sur 127.0.0.1 seulement. Pour valider depuis le téléphone hors du réseau local : mot de passe simple + tunnel. Rien n'est exposé tant que ce n'est pas activé.</p>
          <div class="toggle-row" style="margin-top:12px"><div class="li-main"><div class="li-title">Écouter sur le réseau local</div><div class="li-sub mono">http://192.168.1.24:8000</div></div><label class="switch"><input type="checkbox"><span></span></label></div>
        </div></section>

        <section class="panel reveal" style="--i:9" id="s-keys"><div class="panel-head"><h2>Raccourcis clavier</h2></div><div class="panel-pad">
          <dl class="kv" style="grid-template-columns:120px 1fr"><dt><kbd>Ctrl</kbd> <kbd>K</kbd></dt><dd>Rechercher, aller à</dd><dt><kbd>N</kbd></dt><dd>Ajouter une vidéo</dd><dt><kbd>G</kbd> puis <kbd>D</kbd>/<kbd>V</kbd>/<kbd>C</kbd></dt><dd>Tableau de bord, vidéos, clips</dd><dt><kbd>A</kbd> / <kbd>R</kbd></dt><dd>Revue : accepter, refuser</dd><dt><kbd>J</kbd> / <kbd>K</kbd></dt><dd>Revue : moment suivant, précédent</dd><dt><kbd>[</kbd> / <kbd>]</kbd></dt><dd>Revue : décaler le début, la fin (0,5 s ; <kbd>Maj</kbd> = 0,1 s)</dd><dt><kbd>Espace</kbd></dt><dd>Lecture, pause</dd><dt><kbd>Ctrl</kbd> <kbd>Z</kbd></dt><dd>Annuler la dernière action</dd></dl>
        </div></section>

        <div class="save-bar" id="save-bar"><span class="muted">${icon("pencil", "i-sm")}</span><p>Modifications non enregistrées dans <span class="mono">config.toml</span></p><button class="btn btn-sm btn-ghost" id="s-cancel">Annuler</button><button class="btn btn-sm btn-primary" id="s-save">Enregistrer</button></div>
      </div>
    </div>`;
  return {
    crumbs: [["Réglages"]],
    html,
    mount(root) {
      initSeg($("#mode-seg", root), () => dirty());
      initSeg($("#theme-seg", root), (v) => App.setTheme(v));
      const bar = $("#save-bar", root);
      const dirty = () => bar.classList.add("show");
      $("#sform", root).addEventListener("input", (e) => { if (!e.target.closest("#theme-seg")) dirty(); });
      $("#sform", root).addEventListener("change", (e) => {
        if (e.target.id === "n-browser" && e.target.checked) toast({ kind: "info", title: "Autorisation demandée", body: "Le navigateur va demander la permission d'afficher des notifications." });
        dirty();
      });
      $("#gap-r", root).addEventListener("input", (e) => ($("#gap-v", root).textContent = e.target.value + " pts"));
      $("#s-save", root).onclick = () => { bar.classList.remove("show"); toast({ kind: "ok", title: "config.toml enregistré", body: "Pris en compte à la prochaine étape lancée." }); };
      $("#s-cancel", root).onclick = () => { bar.classList.remove("show"); toast({ kind: "info", title: "Modifications annulées", ms: 2000 }); };
      // Suivi de la section visible
      const links = $$("#snav a", root);
      links.forEach((a) => a.addEventListener("click", (e) => { e.preventDefault(); $(a.getAttribute("href"), root).scrollIntoView({ behavior: "smooth", block: "start" }); }));
      const io = new IntersectionObserver((ents) => ents.forEach((en) => { if (en.isIntersecting) links.forEach((a) => a.classList.toggle("on", a.getAttribute("href") === "#" + en.target.id)); }), { rootMargin: "-30% 0px -60% 0px" });
      $$("#sform > section", root).forEach((s) => io.observe(s));
    },
  };
};
