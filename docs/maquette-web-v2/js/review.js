/* Revue des moments (mode review) : lecteur, timeline globale + zoom avec
   bornes ajustables, raisons du jury, raccourcis A/R/J/K, annuler. */
"use strict";

Views.reviewIndex = () => {
  const items = VIDEOS.filter((v) => v.status === "awaiting_review");
  const html = `
    ${head("", "Revue des moments", "Les vidéos en mode review s'arrêtent après l'étape moments et attendent ta décision.")}
    <div class="panel jobs reveal" style="--i:1">${items.map((v) => jobRow(v)).join("")}</div>`;
  return { crumbs: [["Revue"]], html, mount() {} };
};

Views.review = (params) => {
  const v = video(params.id) || video("mdj-0928");
  const c = chan(v.channel);
  const ms = MOMENTS;
  let cur = Math.max(0, ms.findIndex((m) => !m.decision));
  let playing = false, playT = 0;
  const history = [];
  const WIN = 30; // secondes de contexte de chaque cote dans la vue zoom

  const html = `
    <div class="page-head reveal" style="--i:0;align-items:center">
      <div class="titles">
        <div class="eyebrow" style="color:var(--muted)">${srcIcon(c.platform)}<a href="#/videos/${v.id}" style="color:var(--text-2)">${esc(v.title)}</a></div>
        <h1>Revue des moments</h1>
      </div>
      <div class="actions" style="align-items:center">
        <div class="review-progress"><span class="muted" style="font-size:13px" id="rv-count"></span><div class="bar done"><i id="rv-bar" style="width:0"></i></div></div>
        <button class="btn btn-primary" id="rv-render">${icon("film")}Lancer le rendu</button>
      </div>
    </div>
    <div class="review-layout">
      <aside class="reveal" style="--i:1">
        <div class="section-title">Proposés par le jury <span class="more">${ms.length}</span></div>
        <div class="m-list" id="mlist"></div>
      </aside>
      <section class="stack reveal" style="--i:2;gap:16px">
        <div class="player" id="player">
          <img id="p-img" src="" alt="">
          <div class="p-badge"><span class="pill-dark" id="p-score"></span></div>
          <div class="p-sub" id="p-sub"></div>
          <div class="p-ctrl"><button class="icon-btn" id="p-play" aria-label="Lecture">${icon("play")}</button><span class="p-time" id="p-time"></span><span class="grow"></span><span class="pill-dark">source 16:9</span></div>
        </div>
        <div class="panel panel-pad">
          <div class="tl">
            <div class="row" style="margin-bottom:8px;font-size:12px"><span class="muted">VOD entière · ${v.duration}</span><span class="grow"></span><span class="muted">intensité audio + chat</span></div>
            <div class="tl-overview" id="tl-ov"></div>
            <div class="tl-zoom" id="tl-z"><div class="wave" id="wave"></div><div class="sel-range" id="sel"><span class="grip l" data-g="l"></span><span class="grip r" data-g="r"></span></div><div class="playhead" id="ph"></div><div class="tl-ticks" id="ticks"></div></div>
            <div class="bounds">
              <span class="b">Début <b id="b-s"></b><span class="nudge"><button data-n="s-">−</button><button data-n="s+">+</button></span></span>
              <span class="b">Fin <b id="b-e"></b><span class="nudge"><button data-n="e-">−</button><button data-n="e+">+</button></span></span>
              <span class="b">Durée <b id="b-d"></b></span>
              <span class="grow"></span>
              <button class="btn btn-xs btn-ghost" id="b-reset">${icon("rotate-ccw", "i-xs")}Bornes du jury</button>
            </div>
          </div>
        </div>
        <div class="decide">
          <button class="btn btn-ok" id="d-acc">${icon("check")}Accepter<kbd>A</kbd></button>
          <button class="btn btn-bad" id="d-rej">${icon("x")}Refuser<kbd>R</kbd></button>
          <button class="btn" id="d-next">Suivant<kbd>J</kbd></button>
        </div>
        <div class="shortcuts"><span><kbd>J</kbd><kbd>K</kbd> naviguer</span><span><kbd>[</kbd><kbd>]</kbd> début / fin −0,5 s, <kbd>Maj</kbd> +0,5 s</span><span><kbd>Espace</kbd> lecture</span><span><kbd>Ctrl</kbd><kbd>Z</kbd> annuler</span></div>
        <div class="panel panel-pad"><div class="section-title">Transcription</div><div class="transcript" id="tr"></div></div>
      </section>
      <aside class="jury-col reveal" style="--i:3">
        <div class="panel panel-pad" id="jury"></div>
        <div class="panel panel-pad" id="crit"></div>
      </aside>
    </div>`;

  let root;
  const m = () => ms[cur];

  function renderList() {
    $("#mlist", root).innerHTML = ms.map((x, i) => {
      const sc = x.score >= 80 ? "hi" : x.score >= 70 ? "mid" : "";
      const dec = x.decision ? `<span class="chip ${x.decision === "accepted" ? "ok" : x.decision === "rejected" ? "bad" : "info"}">${{ accepted: "accepté", rejected: "refusé", adjusted: "ajusté" }[x.decision]}</span>` : "";
      return `<button class="m-item ${i === cur ? "on" : ""} ${x.decision || ""}" data-i="${i}">
        <span class="score ${sc}">${x.score}</span>
        <span style="min-width:0"><span class="m-hook" style="display:block">${esc(x.hook)}</span>
        <span class="m-meta"><span class="mono">${fmtTC(x.start).replace(/\.\d$/, "")}</span><span>${Math.round(x.end - x.start)} s</span>${x.parts > 1 ? `<span>${x.parts} parties</span>` : ""}${dec}</span></span>
      </button>`;
    }).join("");
    $$("#mlist .m-item", root).forEach((b) => (b.onclick = () => go(+b.dataset.i)));
    const done = ms.filter((x) => x.decision).length, acc = ms.filter((x) => x.decision === "accepted" || x.decision === "adjusted").length;
    $("#rv-count", root).textContent = `${done}/${ms.length} traités · ${acc} retenus`;
    $("#rv-bar", root).style.width = (done / ms.length) * 100 + "%";
    $("#rv-render", root).disabled = acc === 0;
    $("#rv-render", root).innerHTML = `${icon("film")}Lancer le rendu${acc ? ` (${acc})` : ""}`;
    const onEl = $("#mlist .m-item.on", root);
    if (onEl && onEl.scrollIntoView && window.innerWidth < 900) onEl.scrollIntoView({ block: "nearest", inline: "center", behavior: "smooth" });
  }

  function renderOverview() {
    const total = REVIEW_VIDEO.total;
    let heat = "";
    for (let i = 0; i < 120; i++) {
      const t = (i / 120) * total;
      let h = 18 + 22 * Math.abs(Math.sin(i * 0.37)) + 14 * Math.abs(Math.sin(i * 1.7));
      ms.forEach((x) => { if (Math.abs(t - x.start) < total / 80) h = Math.min(100, h + x.score * 0.6); });
      heat += `<i style="height:${h}%"></i>`;
    }
    $("#tl-ov", root).innerHTML = `<div class="heat">${heat}</div>` + ms.map((x, i) =>
      `<span class="mk ${i === cur ? "on" : ""} ${x.decision || ""}" data-i="${i}" title="${esc(x.hook)}" style="left:${(x.start / total) * 100}%;width:${((x.end - x.start) / total) * 100}%"></span>`).join("");
    $$("#tl-ov .mk", root).forEach((k) => (k.onclick = () => go(+k.dataset.i)));
  }

  function zoomRange() { const x = m(); return [x.start - WIN, x.end + WIN]; }
  function renderZoom(first) {
    const x = m(), [a, b] = zoomRange(), span = b - a;
    if (first) {
      let w = "";
      for (let i = 0; i < 90; i++) {
        const seed = Math.sin((x.start + i) * 12.9898) * 43758.5453;
        const r = seed - Math.floor(seed);
        w += `<i style="height:${12 + r * 70 + (i > 25 && i < 65 ? 18 : 0)}%"></i>`;
      }
      $("#wave", root).innerHTML = w;
      const ticks = [];
      for (let k = 0; k <= 4; k++) ticks.push(`<span>${fmtTC(Math.round(a + (span * k) / 4)).replace(/\.\d$/, "")}</span>`);
      $("#ticks", root).innerHTML = ticks.join("");
    }
    const sel = $("#sel", root);
    sel.style.left = ((x.start - a) / span) * 100 + "%";
    sel.style.width = ((x.end - x.start) / span) * 100 + "%";
    $$("#wave i", root).forEach((el, i) => { const t = a + ((i + 0.5) / 90) * span; el.classList.toggle("in", t >= x.start && t <= x.end); });
    $("#b-s", root).textContent = fmtTC(x.start);
    $("#b-e", root).textContent = fmtTC(x.end);
    $("#b-d", root).textContent = (x.end - x.start).toFixed(1).replace(".", ",") + " s";
    placePlayhead();
  }
  function placePlayhead() {
    const x = m(), [a, b] = zoomRange();
    $("#ph", root).style.left = ((x.start + playT - a) / (b - a)) * 100 + "%";
    $("#p-time", root).textContent = `${fmtTC(x.start + playT).replace(/\.\d$/, "")} · ${playT.toFixed(0)} / ${Math.round(x.end - x.start)} s`;
    const lines = x.transcript;
    const k = Math.min(lines.length - 1, Math.floor((playT / (x.end - x.start)) * lines.length));
    $("#p-sub", root).innerHTML = `<span>${lines[k][1].replace(/<\/?mark>/g, "")}</span>`;
  }

  function renderJury() {
    const x = m();
    $("#jury", root).innerHTML = `<div class="row" style="margin-bottom:16px;align-items:flex-end"><div><div class="section-title" style="margin:0">Jury</div><div class="muted" style="font-size:12px">5 juges · écart ${Math.max(...x.judges.map((j) => j[1])) - Math.min(...x.judges.map((j) => j[1]))} pts</div></div><span class="grow"></span><div class="big-num" style="font-size:44px">${x.score}<small>/100</small></div></div>` +
      x.judges.map(([k, s, why]) => {
        const j = JUDGES[k];
        return `<div class="judge"><div class="judge-name">${j.label}${j.veto ? `<span class="chip warn plain" style="height:18px;font-size:11px">veto</span>` : ""}<span class="faint mono" style="font-size:11px;font-weight:400">${j.model}</span></div><div class="judge-score">${s}</div><div class="bar ${s >= 80 ? "done" : ""}"><i style="width:${s}%"></i></div><div class="judge-why">${esc(why)}</div></div>`;
      }).join("");
    $("#crit", root).innerHTML = `<div class="section-title">Grille <span class="more mono">rubric.toml</span></div>` +
      Object.entries(x.crit).map(([k, n]) => `<div class="crit"><span>${CRITERIA[k][0]} <span class="w">×${CRITERIA[k][1]}</span></span><span class="dots">${[1, 2, 3, 4, 5].map((d) => `<i class="${d <= n ? "on" : ""}"></i>`).join("")}</span><b>${n}/5</b></div>`).join("") +
      `<div style="margin-top:16px;padding-top:16px;border-top:1px solid var(--line)"><div class="field-label" style="margin-bottom:8px">Titre d'écran proposé</div><input class="input" style="width:100%" value="${esc(x.title)}" id="m-title"><p class="muted" style="font-size:12px;margin-top:8px">${x.parts > 1 ? `Découpé en ${x.parts} parties (reprise 3 s avant la coupe).` : "Une seule partie."}</p></div>`;
    $("#m-title", root).addEventListener("change", () => { x.title = $("#m-title", root).value; toast({ kind: "ok", title: "Titre modifié", ms: 1800 }); });
  }

  function renderPlayer() {
    const x = m(), img = $("#p-img", root);
    img.style.opacity = "0.2";
    setTimeout(() => { img.src = x.frame; img.style.opacity = "1"; }, 120);
    $("#p-score", root).textContent = `score ${x.score}`;
    $("#tr", root).innerHTML = x.transcript.map(([s, t]) => `<p style="margin-bottom:8px"><span class="spk">${esc(s)}</span> ${t}</p>`).join("");
  }

  function go(i) {
    cur = (i + ms.length) % ms.length;
    playT = 0;
    renderList(); renderOverview(); renderZoom(true); renderJury(); renderPlayer();
  }

  function decide(kind) {
    const x = m();
    const prev = { i: cur, d: x.decision };
    x.decision = kind;
    history.push(prev);
    const next = ms.findIndex((y, k) => k > cur && !y.decision);
    const label = kind === "accepted" ? "Moment accepté" : kind === "rejected" ? "Moment refusé" : "Bornes ajustées";
    toast({ kind: kind === "rejected" ? "warn" : "ok", title: label, body: esc(x.hook), undo: undo, ms: 4000 });
    if (ms.every((y) => y.decision)) {
      renderList(); renderOverview();
      const acc = ms.filter((y) => y.decision !== "rejected").length;
      setTimeout(() => toast({ kind: "ok", title: "Revue terminée", body: `${acc} moments retenus. Tu peux lancer le rendu.`, action: { label: "Lancer", run: startRender } }), 500);
      $("#rv-render", root).animate([{ boxShadow: "0 0 0 0 var(--accent-soft)" }, { boxShadow: "0 0 0 10px transparent" }], { duration: 900, iterations: 3 });
    } else go(next >= 0 ? next : ms.findIndex((y) => !y.decision));
  }
  function undo() {
    const h = history.pop();
    if (!h) return;
    ms[h.i].decision = h.d;
    go(h.i);
  }
  function nudge(which, d) {
    const x = m();
    if (which === "s") x.start = Math.max(0, Math.min(x.end - 5, +(x.start + d).toFixed(1)));
    else x.end = Math.max(x.start + 5, +(x.end + d).toFixed(1));
    if (!x.decision || x.decision === "accepted") x.decision = "adjusted";
    renderZoom(false); renderList(); renderOverview();
  }
  function startRender() {
    const acc = ms.filter((y) => y.decision === "accepted" || y.decision === "adjusted").length;
    openPanel("modal", `<div class="modal-head"><h2>Lancer le rendu de ${acc} moments ?</h2></div>
      <div class="modal-body"><p class="muted">Enchaîne vision, découpage, légendes, recadrage, sous-titres, rendu et contrôle qualité avec le preset <b style="color:var(--text)">${esc(c.preset)}</b>.</p>
      <div class="row wrap" style="gap:6px">${STEPS.slice(5).map((s) => `<span class="tag">${icon(s.icon, "i-xs")}${s.label}</span>`).join("")}</div>
      <p class="reason" style="border-color:var(--info)">Estimation : 24 min sur cette machine. Tu seras notifié à la fin.</p></div>
      <div class="modal-foot"><button class="btn btn-ghost" data-dismiss>Pas maintenant</button><button class="btn btn-primary" id="go-render">${icon("film")}Lancer</button></div>`,
      (el) => { $("#go-render", el).onclick = () => { closeLayer(); toast({ kind: "ok", title: "Rendu lancé", body: `${acc} moments · ${esc(v.title)}`, action: { label: "Suivre", run: () => (location.hash = "#/videos/" + v.id) } }); }; });
  }

  function wireDrag() {
    const z = $("#tl-z", root), sel = $("#sel", root);
    z.addEventListener("pointerdown", (e) => {
      const g = e.target.dataset.g;
      const r = z.getBoundingClientRect();
      const [a, b] = zoomRange();
      const toT = (cx) => a + ((cx - r.left) / r.width) * (b - a);
      if (!g) { // clic dans la zone : deplacer la tete de lecture
        const t = toT(e.clientX) - m().start;
        playT = Math.max(0, Math.min(m().end - m().start, t));
        placePlayhead();
        return;
      }
      e.preventDefault();
      sel.classList.add("dragging");
      e.target.setPointerCapture(e.pointerId);
      const x = m();
      const mv = (ev) => {
        const t = +toT(ev.clientX).toFixed(1);
        if (g === "l") x.start = Math.max(a, Math.min(x.end - 5, t)); else x.end = Math.min(b, Math.max(x.start + 5, t));
        renderZoom(false);
      };
      const up = () => {
        e.target.removeEventListener("pointermove", mv); e.target.removeEventListener("pointerup", up);
        sel.classList.remove("dragging");
        if (!x.decision || x.decision === "accepted") x.decision = "adjusted";
        renderList(); renderOverview();
        toast({ kind: "info", title: "Bornes ajustées", body: `${fmtTC(x.start)} → ${fmtTC(x.end)}`, ms: 2400 });
      };
      e.target.addEventListener("pointermove", mv); e.target.addEventListener("pointerup", up);
    });
  }

  return {
    crumbs: [["Revue", "#/revue"], [v.title]],
    html,
    mount(r) {
      root = r;
      ms.forEach((x) => { x._s = x._s || x.start; x._e = x._e || x.end; });
      go(cur);
      wireDrag();
      $("#d-acc", root).onclick = () => decide(m().decision === "adjusted" ? "adjusted" : "accepted");
      $("#d-rej", root).onclick = () => decide("rejected");
      $("#d-next", root).onclick = () => go(cur + 1);
      $("#rv-render", root).onclick = startRender;
      $("#b-reset", root).onclick = () => { const x = m(); x.start = x._s; x.end = x._e; if (x.decision === "adjusted") x.decision = null; renderZoom(false); renderList(); renderOverview(); };
      $$("[data-n]", root).forEach((b) => (b.onclick = () => nudge(b.dataset.n[0], b.dataset.n[1] === "+" ? 0.5 : -0.5)));
      const togglePlay = () => {
        playing = !playing;
        $("#p-play", root).innerHTML = icon(playing ? "pause" : "play");
      };
      $("#p-play", root).onclick = togglePlay;
      $("#player", root).addEventListener("click", (e) => { if (!e.target.closest(".p-ctrl")) togglePlay(); });
      App.onTick(root, () => {
        if (!playing) return;
        playT += 1;
        if (playT > m().end - m().start) playT = 0;
        placePlayhead();
      });
      App.onKey(root, (e) => {
        if (/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) return false;
        const k = e.key.toLowerCase();
        if ((e.ctrlKey || e.metaKey) && k === "z") { undo(); return true; }
        if (e.ctrlKey || e.metaKey || e.altKey) return false;
        if (k === "a") { $("#d-acc", root).click(); flash("#d-acc"); return true; }
        if (k === "r") { decide("rejected"); flash("#d-rej"); return true; }
        if (k === "j") { go(cur + 1); return true; }
        if (k === "k") { go(cur - 1); return true; }
        if (e.key === "[") { nudge("s", e.shiftKey ? 0.5 : -0.5); return true; }
        if (e.key === "]") { nudge("e", e.shiftKey ? 0.5 : -0.5); return true; }
        if (e.key === "{") { nudge("s", 0.5); return true; }
        if (e.key === "}") { nudge("e", 0.5); return true; }
        if (e.key === " ") { togglePlay(); return true; }
        return false;
      });
      function flash(sel) { $(sel, root).animate([{ transform: "scale(0.96)" }, { transform: "none" }], { duration: 160, easing: "ease-out" }); }
    },
  };
};
