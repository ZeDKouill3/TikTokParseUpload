/* Ecran de chaine = preset. Onglet Agencement : editeur 1080x1920 repris de
   research/ma_chaine/editeur/editeur.html (glisser, redimensionner, zone sure,
   magnetisme axe central), integre a la console. */
"use strict";

const CANVAS_W = 1080, CANVAS_H = 1920, SRC_W = 1920, SRC_H = 1080;
const SAFE = { x0: 150, y0: 160, x1: 930, y1: 1520 };

const LAYOUTS = {
  split: () => ({
    webcam:    { label: "Webcam", icon: "scan-face", x: 20, y: 0, w: 1040, h: 640, src: [0, 346, 354, 252], on: true },
    gameplay:  { label: "Jeu", icon: "monitor", x: 0, y: 640, w: 1080, h: 1280, src: [504, 0, 912, 1080], on: true },
    badge:     { label: "Badge chaîne", icon: "twitch", x: 330, y: 590, w: 420, h: 100, on: true },
    subtitles: { label: "Sous-titres", icon: "captions", x: 150, y: 710, w: 780, h: 150, fs: 80, on: true },
    title:     { label: "Titre d'écran", icon: "type", x: 190, y: 170, w: 700, h: 80, on: false },
    endcard:   { label: "Carte de fin", icon: "heart", x: 190, y: 1380, w: 700, h: 110, on: false },
  }),
  top: () => ({
    webcam:    { label: "Webcam", icon: "scan-face", x: 330, y: 250, w: 420, h: 300, src: [0, 346, 354, 252], on: true },
    gameplay:  { label: "Jeu", icon: "monitor", x: 0, y: 580, w: 1080, h: 608, src: [0, 0, 1920, 1080], on: true },
    badge:     { label: "Badge chaîne", icon: "twitch", x: 330, y: 1210, w: 420, h: 100, on: false },
    subtitles: { label: "Sous-titres", icon: "captions", x: 150, y: 1360, w: 780, h: 110, fs: 64, on: true },
    title:     { label: "Titre d'écran", icon: "type", x: 190, y: 160, w: 700, h: 72, on: true },
    endcard:   { label: "Carte de fin", icon: "heart", x: 190, y: 1380, w: 700, h: 110, on: false },
  }),
  letterbox: () => ({
    gameplay:  { label: "Vidéo", icon: "monitor", x: 0, y: 656, w: 1080, h: 608, src: [0, 0, 1920, 1080], on: true },
    webcam:    { label: "Webcam", icon: "scan-face", x: 330, y: 250, w: 420, h: 300, src: [0, 346, 354, 252], on: false },
    badge:     { label: "Pseudo de chaîne", icon: "at-sign", x: 330, y: 560, w: 420, h: 60, on: true, pseudo: true },
    subtitles: { label: "Sous-titres", icon: "captions", x: 150, y: 1330, w: 780, h: 120, fs: 64, on: true },
    title:     { label: "Titre d'écran", icon: "type", x: 150, y: 420, w: 780, h: 110, on: true },
    endcard:   { label: "Carte de fin", icon: "heart", x: 190, y: 1380, w: 700, h: 110, on: false },
  }),
};

Views.channel = (params) => {
  const c = chan(params.id) || CHANNELS[0];
  const isStream = c.platform === "twitch";
  let layout = c.layout;
  let blocks = LAYOUTS[layout]();
  let selected = isStream ? "webcam" : "title";
  let frame = isStream ? "img/frame_5400.jpg" : "img/frame_180.jpg";
  let showSafe = false, snap = true;
  const sub = { font: "Barlow", size: 80, spoken: "#ffffff", upcoming: "#ffffff", emph: isStream ? "#9146ff" : "#ff8a00", outline: 6, shadow: true, words: 3 };
  const tab = params.tab || "layout";

  const html = `
    <div class="page-head reveal" style="--i:0;align-items:center">
      <div class="ch-avatar" style="margin:0;background:${c.color};color:#111;box-shadow:none">${c.initial}</div>
      <div class="titles">
        <div class="eyebrow" style="color:var(--muted)">${srcIcon(c.platform)}${esc(c.handle)}</div>
        <h1>${esc(c.name)}</h1>
      </div>
      <div class="actions"><span class="muted" style="font-size:13px;align-self:center" id="dirty"></span><button class="btn" id="ed-test">${icon("play")}Aperçu sur un vrai moment</button><button class="btn btn-primary" id="ed-save">${icon("check")}Enregistrer le preset</button></div>
    </div>
    <div class="tabs reveal" style="--i:1" id="ch-tabs">
      <button data-v="layout" class="${tab === "layout" ? "on" : ""}">${icon("layers", "i-sm")}Agencement</button>
      <button data-v="subs" class="${tab === "subs" ? "on" : ""}">${icon("captions", "i-sm")}Sous-titres</button>
      <button data-v="title" class="${tab === "title" ? "on" : ""}">${icon("type", "i-sm")}Titre et appel</button>
      <button data-v="rubric" class="${tab === "rubric" ? "on" : ""}">${icon("scale", "i-sm")}Notation</button>
      <button data-v="source" class="${tab === "source" ? "on" : ""}">${icon("radio", "i-sm")}Source et publication</button>
    </div>
    <div id="ch-pane" class="reveal" style="--i:2"></div>`;

  let root = null;
  const markDirty = () => { $("#dirty", root).textContent = "modifié, non enregistré"; };

  /* ---------- Agencement ---------- */
  function paneLayout() {
    return `<div class="editor">
      <aside class="editor-side editor-layers stack" style="gap:24px">
        <div><div class="section-title">Format</div>
          <div class="layout-pick" id="lp">
            ${[["letterbox", "Letterbox", [[40, 60, "#"]]], ["top", "Stream", [[10, 12], [36, 34]]], ["split", "Split", [[0, 33], [33, 67]]]].map(([k, l, parts]) =>
              `<button data-l="${k}" class="${k === layout ? "on" : ""}"><span class="lp-mini">${parts.map((p) => `<i style="top:${p[0]}%;height:${p[1]}%;${k === "top" && p === parts[0] ? "left:30%;right:30%" : ""}"></i>`).join("")}</span>${l}</button>`).join("")}
          </div>
          <p class="muted" style="font-size:12px;margin-top:8px" id="lp-hint"></p>
        </div>
        <div><div class="section-title">Calques</div><div class="layer-list" id="layers"></div></div>
        <div><div class="section-title">Image d'aperçu</div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px" id="frames">
            ${["frame_180", "frame_2400", "frame_5400", "frame_8400"].map((f) => `<button data-f="img/${f}.jpg" style="border-radius:6px;overflow:hidden;aspect-ratio:16/9;outline:2px solid ${"img/" + f + ".jpg" === frame ? "var(--accent)" : "transparent"};outline-offset:1px;transition:outline-color 160ms ease"><img src="img/${f}.jpg" alt="" style="width:100%;height:100%;object-fit:cover"></button>`).join("")}
          </div>
        </div>
      </aside>
      <div class="stage-wrap">
        <div class="stage-tools">
          <label class="row" style="gap:8px;font-size:13px"><span class="switch"><input type="checkbox" id="t-safe"><span></span></span>Zone sûre TikTok</label>
          <label class="row" style="gap:8px;font-size:13px"><span class="switch"><input type="checkbox" id="t-snap" checked><span></span></span>Magnétisme</label>
          <button class="btn btn-xs btn-ghost" id="t-reset">${icon("rotate-ccw", "i-xs")}Réinitialiser</button>
        </div>
        <div class="stage-outer" id="stage-outer"><div class="stage" id="stage"><img class="stage-bg" id="stage-bg" src="${frame}" alt=""><div class="safe" id="safe" style="left:${SAFE.x0}px;top:${SAFE.y0}px;width:${SAFE.x1 - SAFE.x0}px;height:${SAFE.y1 - SAFE.y0}px"></div><div class="guide-v" id="guide"></div></div></div>
        <p class="muted" style="font-size:12px">Glisse un bloc pour le déplacer, tire un coin pour le redimensionner. Flèches : 1 px, <kbd>Maj</kbd> : 10 px.</p>
      </div>
      <aside class="editor-side panel panel-pad stack" style="gap:24px" id="props"></aside>
    </div>`;
  }

  function scaleStage() {
    const outer = $("#stage-outer", root);
    if (!outer) return;
    const wrap = outer.parentElement;
    const availW = wrap.clientWidth - 48;
    const availH = Math.max(480, Math.min(window.innerHeight - 340, 720));
    const s = Math.max(0.16, Math.min(availW / CANVAS_W, availH / CANVAS_H));
    outer.style.width = CANVAS_W * s + "px";
    outer.style.height = CANVAS_H * s + "px";
    $("#stage", root).style.transform = `scale(${s})`;
    outer.dataset.s = s;
  }

  function blockInner(id, b) {
    if (id === "webcam" || id === "gameplay") return `<div class="crop"><img src="${frame}" alt="" draggable="false"></div>`;
    if (id === "badge") return b.pseudo
      ? `<div class="b-pseudo" style="justify-content:center;font-size:34px">${esc(c.handle)}</div>`
      : `<div class="b-badge"><div class="ico"><img src="img/twitch-logo.png" alt=""></div><div class="nm">${esc(c.name)}</div></div>`;
    if (id === "subtitles") return `<div class="b-sub" style="${subStyle(b.fs)}">${subWords()}</div>`;
    if (id === "title") return `<div class="b-title">${isStream ? "La carte ne ment pas" : "Qui paie la hausse du SMIC ?"}</div>`;
    if (id === "endcard") return `<div class="b-endcard">Abonne-toi !</div>`;
    return "";
  }
  function subStyle(fs, k) {
    const o = Math.round(sub.outline * (k || 1) * 10) / 10;
    const sh = [];
    for (const [dx, dy] of [[-1, -1], [1, -1], [-1, 1], [1, 1], [0, -1], [0, 1], [-1, 0], [1, 0]]) sh.push(`${dx * o}px ${dy * o}px 0 #000`);
    if (sub.shadow) sh.push(`0 ${o + 4}px ${o * 2}px rgba(0,0,0,.7)`);
    return `font-family:'${sub.font}',sans-serif;font-size:${fs || sub.size}px;color:${sub.upcoming};text-shadow:${sh.join(",")};font-weight:800;text-transform:uppercase`;
  }
  let subTick = 0;
  function subWords(cur) {
    const words = (isStream ? "moi, j'vois le parc" : "ce n'est pas l'état qui paie").split(" ").slice(0, sub.words);
    const k = cur == null ? 1 : cur % words.length;
    return words.map((w, i) => `<span class="w ${i === k ? "cur" : ""}" style="color:${i === k ? sub.emph : i < k ? sub.spoken : sub.upcoming}">${esc(w)}</span>`).join(" ");
  }

  function renderStage() {
    const stage = $("#stage", root);
    $$(".blk", stage).forEach((n) => n.remove());
    Object.entries(blocks).forEach(([id, b]) => {
      if (!b.on) return;
      const el = document.createElement("div");
      el.className = "blk" + (id === selected ? " sel" : "");
      el.dataset.id = id;
      el.innerHTML = blockInner(id, b) + `<span class="blk-tag">${esc(b.label)}</span>` + ["nw", "ne", "sw", "se"].map((h) => `<span class="hdl ${h}" data-h="${h}"></span>`).join("");
      stage.appendChild(el);
      place(el, id, b);
    });
  }
  function place(el, id, b) {
    el.style.left = b.x + "px"; el.style.top = b.y + "px"; el.style.width = b.w + "px"; el.style.height = b.h + "px";
    if (b.src) {
      const img = el.querySelector(".crop img");
      const sx = b.w / b.src[2], sy = b.h / b.src[3];
      img.style.width = SRC_W * sx + "px"; img.style.height = SRC_H * sy + "px";
      img.style.left = -b.src[0] * sx + "px"; img.style.top = -b.src[1] * sy + "px";
    }
  }
  function renderLayers() {
    $("#layers", root).innerHTML = Object.entries(blocks).map(([id, b]) =>
      `<div class="layer ${id === selected && b.on ? "on" : ""} ${b.on ? "" : "off"}" data-id="${id}" role="button" tabindex="0">${icon(b.icon === "at-sign" ? "user" : b.icon, "i-sm")}${esc(b.label)}<button class="eye" data-eye="${id}" aria-label="${b.on ? "Masquer" : "Afficher"}">${icon(b.on ? "eye" : "eye-off", "i-sm")}</button></div>`).join("");
    const hints = { letterbox: "Zoom fixe, titre en haut, sous-titres dans la bande floue du bas (SPEC-6a47).", top: "Webcam agrandie en haut, jeu en dessous (SPEC-3a88). Choisi par clip si la webcam est vivante.", split: "Webcam en haut, jeu en bas, badge à la jonction (SPEC-76dc, stream_variant = split)." };
    $("#lp-hint", root).textContent = hints[layout];
  }
  function renderProps() {
    const b = blocks[selected];
    const box = $("#props", root);
    if (!b || !b.on) { box.innerHTML = `<div class="empty" style="padding:24px 0"><div class="empty-art">${icon("mouse-pointer-click")}</div><p>Sélectionne un bloc sur le canevas ou dans les calques.</p></div>`; return; }
    const num = (k, v) => `<label>${k}<input class="input" type="number" data-k="${k}" value="${Math.round(v)}"></label>`;
    box.innerHTML = `
      <div class="row"><span class="src-ico" style="background:var(--accent-soft);color:var(--accent)">${icon(b.icon === "at-sign" ? "user" : b.icon, "i-xs")}</span><h2 style="font-size:16px">${esc(b.label)}</h2></div>
      <div><div class="field-label" style="margin-bottom:8px">Position sur le clip <span class="faint" style="font-weight:400">(px, 1080×1920)</span></div><div class="coords" id="c-dest">${num("x", b.x)}${num("y", b.y)}${num("w", b.w)}${num("h", b.h)}</div>
        <div class="row" style="margin-top:8px;gap:8px"><button class="btn btn-xs" data-al="cx">${icon("maximize-2", "i-xs")}Centrer</button><button class="btn btn-xs" data-al="fw">Pleine largeur</button></div></div>
      ${b.src ? `<div><div class="field-label" style="margin-bottom:8px">Zone prise dans la source <span class="faint" style="font-weight:400">(px, 1920×1080)</span></div><div class="coords" id="c-src">${num("x", b.src[0])}${num("y", b.src[1])}${num("w", b.src[2])}${num("h", b.src[3])}</div>
        ${selected === "webcam" ? `<p class="muted row" style="font-size:12px;margin-top:8px;gap:8px;align-items:flex-start">${icon("scan-face", "i-xs")}<span>Détectée automatiquement une fois par vidéo (visage sur 88 % des images clés). Ici tu fixes une valeur pour la chaîne.</span></p>` : ""}</div>` : ""}
      ${b.fs ? `<div class="field"><label>Taille du texte</label><div class="row"><input type="range" min="36" max="120" value="${b.fs}" id="c-fs"><b class="num" style="width:48px;text-align:right;font-size:18px" id="c-fsv">${b.fs}</b></div></div>` : ""}
      <details><summary class="muted" style="cursor:pointer;font-size:13px">JSON du preset</summary><div class="code" style="margin-top:8px;max-height:220px" id="c-json"></div></details>`;
    const upd = () => { const el = $(`.blk[data-id="${selected}"]`, root); if (el) place(el, selected, b); $("#c-json", root).textContent = exportJSON(); markDirty(); };
    $$("#c-dest input", box).forEach((inp) => inp.addEventListener("input", () => { b[inp.dataset.k] = +inp.value || 0; upd(); }));
    $$("#c-src input", box).forEach((inp) => inp.addEventListener("input", () => { b.src[["x", "y", "w", "h"].indexOf(inp.dataset.k)] = +inp.value || 1; upd(); }));
    const fs = $("#c-fs", box);
    if (fs) fs.addEventListener("input", () => { b.fs = +fs.value; $("#c-fsv", box).textContent = fs.value; const el = $(`.blk[data-id="${selected}"] .b-sub`, root); if (el) el.style.fontSize = b.fs + "px"; markDirty(); });
    $$("[data-al]", box).forEach((bt) => bt.onclick = () => { if (bt.dataset.al === "cx") b.x = Math.round((CANVAS_W - b.w) / 2); else { b.x = 0; b.w = CANVAS_W; } renderProps(); upd(); });
    $("#c-json", root).textContent = exportJSON();
  }
  function exportJSON() {
    const o = { canvas: { w: 1080, h: 1920 }, layout };
    Object.entries(blocks).forEach(([id, b]) => {
      o[id] = b.on ? Object.assign({ dest: { x: b.x, y: b.y, w: b.w, h: b.h } }, b.src ? { source: { x: b.src[0], y: b.src[1], w: b.src[2], h: b.src[3] } } : {}, b.fs ? { font_size: b.fs } : {}) : { visible: false };
    });
    return JSON.stringify(o, null, 1).replace(/\n\s+(?=[}\]"\d-])/g, " ").replace(/\{ "/g, '{"');
  }
  function select(id) {
    selected = id;
    $$(".blk", root).forEach((el) => el.classList.toggle("sel", el.dataset.id === id));
    renderLayers(); renderProps();
  }

  function wireStage() {
    const stage = $("#stage", root);
    const guide = $("#guide", root);
    stage.addEventListener("pointerdown", (e) => {
      const el = e.target.closest(".blk");
      if (!el) return;
      e.preventDefault();
      const id = el.dataset.id, b = blocks[id];
      if (selected !== id) select(id);
      const s = +$("#stage-outer", root).dataset.s;
      const h = e.target.dataset.h;
      const st = { x: e.clientX, y: e.clientY, b: { x: b.x, y: b.y, w: b.w, h: b.h } };
      const target = $(`.blk[data-id="${id}"]`, root);
      target.setPointerCapture(e.pointerId);
      const move = (ev) => {
        const dx = (ev.clientX - st.x) / s, dy = (ev.clientY - st.y) / s;
        if (!h) {
          b.x = Math.round(st.b.x + dx); b.y = Math.round(st.b.y + dy);
          const cx = b.x + b.w / 2;
          const near = snap && Math.abs(cx - CANVAS_W / 2) < 14;
          if (near) b.x = Math.round(CANVAS_W / 2 - b.w / 2);
          guide.classList.toggle("show", near);
        } else {
          if (h.includes("e")) b.w = Math.max(40, Math.round(st.b.w + dx));
          if (h.includes("s")) b.h = Math.max(30, Math.round(st.b.h + dy));
          if (h.includes("w")) { b.w = Math.max(40, Math.round(st.b.w - dx)); b.x = st.b.x + st.b.w - b.w; }
          if (h.includes("n")) { b.h = Math.max(30, Math.round(st.b.h - dy)); b.y = st.b.y + st.b.h - b.h; }
        }
        place(target, id, b);
        const inputs = $$("#c-dest input", root);
        if (inputs.length) [b.x, b.y, b.w, b.h].forEach((v, i) => (inputs[i].value = v));
      };
      const up = () => {
        target.removeEventListener("pointermove", move); target.removeEventListener("pointerup", up);
        guide.classList.remove("show");
        $("#c-json", root) && ($("#c-json", root).textContent = exportJSON());
        if (st.b.x !== b.x || st.b.y !== b.y || st.b.w !== b.w || st.b.h !== b.h) markDirty();
      };
      target.addEventListener("pointermove", move); target.addEventListener("pointerup", up);
    });
  }

  function applyLayout(k, animate) {
    layout = k;
    blocks = LAYOUTS[k]();
    if (!blocks[selected] || !blocks[selected].on) selected = Object.keys(blocks).find((id) => blocks[id].on);
    $$("#lp button", root).forEach((b) => b.classList.toggle("on", b.dataset.l === k));
    if (animate) {
      // morph : on garde les blocs existants et on anime leur nouvelle place (changement rare, 420 ms)
      const olds = {};
      $$(".blk", root).forEach((el) => (olds[el.dataset.id] = el.getBoundingClientRect()));
      renderStage();
      $$(".blk", root).forEach((el) => {
        const o = olds[el.dataset.id]; if (!o) { el.animate([{ opacity: 0, transform: "scale(0.96)" }, { opacity: 1, transform: "none" }], { duration: 320, easing: "cubic-bezier(0.23,1,0.32,1)" }); return; }
        const n = el.getBoundingClientRect();
        el.animate([{ transform: `translate(${(o.left - n.left) / +$("#stage-outer", root).dataset.s}px, ${(o.top - n.top) / +$("#stage-outer", root).dataset.s}px) scale(${o.width / n.width}, ${o.height / n.height})`, transformOrigin: "top left" }, { transform: "none", transformOrigin: "top left" }], { duration: 420, easing: "cubic-bezier(0.77,0,0.175,1)" });
      });
    } else renderStage();
    renderLayers(); renderProps();
    markDirty();
  }

  function mountLayout() {
    scaleStage();
    renderStage(); renderLayers(); renderProps(); wireStage();
    $("#dirty", root).textContent = "";
    $$("#lp button", root).forEach((b) => (b.onclick = () => { if (b.dataset.l !== layout) { applyLayout(b.dataset.l, true); toast({ kind: "info", title: `Format ${b.textContent.trim()}`, body: "Positions par défaut de ce format appliquées.", ms: 2400 }); } }));
    $("#layers", root).addEventListener("click", (e) => {
      const eye = e.target.closest("[data-eye]");
      if (eye) { const b = blocks[eye.dataset.eye]; b.on = !b.on; if (b.on) selected = eye.dataset.eye; renderStage(); renderLayers(); renderProps(); markDirty(); return; }
      const l = e.target.closest(".layer"); if (l && blocks[l.dataset.id].on) select(l.dataset.id);
    });
    $$("#frames button", root).forEach((b) => (b.onclick = () => {
      frame = b.dataset.f;
      $$("#frames button", root).forEach((x) => (x.style.outlineColor = x === b ? "var(--accent)" : "transparent"));
      $("#stage-bg", root).src = frame;
      $$(".crop img", root).forEach((img) => (img.src = frame));
    }));
    $("#t-safe", root).onchange = (e) => $("#safe", root).classList.toggle("show", e.target.checked);
    $("#t-snap", root).onchange = (e) => (snap = e.target.checked);
    $("#t-reset", root).onclick = () => { const prev = JSON.stringify(blocks); applyLayout(layout, true); toast({ kind: "info", title: "Positions réinitialisées", undo: () => { blocks = JSON.parse(prev); renderStage(); renderLayers(); renderProps(); } }); };
    App.onKey($("#stage", root), (e) => {
      if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(e.key) || /INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) return false;
      const b = blocks[selected]; if (!b) return false;
      const d = e.shiftKey ? 10 : 1;
      if (e.key === "ArrowLeft") b.x -= d; if (e.key === "ArrowRight") b.x += d; if (e.key === "ArrowUp") b.y -= d; if (e.key === "ArrowDown") b.y += d;
      place($(`.blk[data-id="${selected}"]`, root), selected, b); renderProps();
      return true;
    });
    window.addEventListener("resize", scaleStage);
    App.onTick($("#stage", root), () => { subTick++; $$(".blk[data-id=subtitles] .b-sub", root).forEach((el) => (el.innerHTML = subWords(subTick))); });
  }

  /* ---------- Sous-titres ---------- */
  function paneSubs() {
    const color = (k, l) => `<label class="swatch"><input type="color" data-c="${k}" value="${sub[k]}">${l}</label>`;
    return `<div class="grid g-half" style="align-items:start">
      <section class="panel panel-pad stack" style="gap:24px">
        <div class="form-grid">
          <div class="field"><label>Police</label><select class="input" data-s="font"><option value="Barlow">Poppins ExtraBold (défaut)</option><option value="Barlow Condensed">Barlow Condensed</option><option value="JetBrains Mono">Monospace</option></select><span class="hint">Aperçu en Barlow : la vraie police est dans clipper/assets.</span></div>
          <div class="field"><label>Mots par groupe</label><div class="seg" id="words-seg">${[2, 3, 4].map((n) => `<button data-v="${n}" class="${n === sub.words ? "on" : ""}">${n}</button>`).join("")}</div></div>
        </div>
        <div class="field"><label>Taille</label><div class="row"><input type="range" min="48" max="120" value="${sub.size}" data-s="size"><b class="num" style="width:48px;text-align:right;font-size:18px" data-sv="size">${sub.size}</b></div></div>
        <div class="field"><label>Contour</label><div class="row"><input type="range" min="0" max="12" value="${sub.outline}" data-s="outline"><b class="num" style="width:48px;text-align:right;font-size:18px" data-sv="outline">${sub.outline}</b></div></div>
        <div class="field"><span class="field-label">Couleurs</span><div class="swatches">${color("spoken", "déjà dit")}${color("upcoming", "à venir")}${color("emph", "mot courant")}</div></div>
        <div class="toggle-row"><div class="li-main"><div class="li-title">Ombre portée</div></div><label class="switch"><input type="checkbox" data-s="shadow" checked><span></span></label></div>
        <div class="field"><label>Zone de placement (fraction de la hauteur)</label><div class="row"><span class="mono muted">0,20</span><div class="grow" style="height:6px;border-radius:3px;background:linear-gradient(90deg,var(--surface-3) 20%,var(--accent) 20% 78%,var(--surface-3) 78%)"></div><span class="mono muted">0,78</span></div><span class="hint">Le texte évite le haut (~15 %) et le bas (~20 %) masqués par l'interface TikTok, et la colonne d'icônes à droite.</span></div>
      </section>
      <section class="stack" style="gap:16px">
        <div class="sub-preview" id="sp"><div class="b-sub" id="sp-t"></div></div>
        <div class="sub-preview" id="sp2" style="background-image:url(img/frame_5400.jpg)"><div class="b-sub" id="sp-t2"></div></div>
        <p class="muted" style="font-size:12px">Aperçu vivant : le mot courant change toutes les 1,2 s, comme au rendu (karaoké mot par mot).</p>
      </section>
    </div>`;
  }
  function mountSubs() {
    const paint = () => {
      [$("#sp-t", root), $("#sp-t2", root)].forEach((el) => { el.setAttribute("style", subStyle(sub.size * 0.4, 0.4) + ";white-space:normal;padding:0 24px"); el.innerHTML = subWords(subTick); });
    };
    paint();
    $$("[data-s]", root).forEach((inp) => inp.addEventListener("input", () => {
      const k = inp.dataset.s;
      sub[k] = inp.type === "checkbox" ? inp.checked : inp.type === "range" ? +inp.value : inp.value;
      const lbl = $(`[data-sv="${k}"]`, root); if (lbl) lbl.textContent = inp.value;
      paint(); markDirty();
    }));
    $$("[data-c]", root).forEach((inp) => inp.addEventListener("input", () => { sub[inp.dataset.c] = inp.value; paint(); markDirty(); }));
    initSeg($("#words-seg", root), (v) => { sub.words = +v; paint(); markDirty(); });
    App.onTick($("#sp", root), () => { subTick++; paint(); });
  }

  /* ---------- Titre et appel ---------- */
  function paneTitle() {
    return `<div class="grid g-wide-l" style="align-items:start">
      <section class="panel panel-pad">
        <div class="toggle-row"><div class="li-main"><div class="li-title">Titre d'écran</div><div class="li-sub">Généré par l'étape captions. Sobre : ni emoji, ni superlatif (SPEC-6a86, proposée).</div></div><label class="switch"><input type="checkbox" ${isStream ? "" : "checked"}><span></span></label></div>
        <div class="toggle-row"><div class="li-main"><div class="li-title">Longueur max du titre</div></div><select class="input" style="width:120px"><option>42 car.</option><option>60 car.</option></select></div>
        <div class="toggle-row"><div class="li-main"><div class="li-title">${isStream ? "Badge de chaîne (logo + nom)" : "Pseudo de chaîne sous le titre"}</div><div class="li-sub">${isStream ? "À la jonction webcam / jeu (SPEC-76dc)." : "Discret, sous le titre d'écran (SPEC-6a47)."}</div></div><label class="switch"><input type="checkbox" checked><span></span></label></div>
        <div class="toggle-row"><div class="li-main"><div class="li-title">Carte de fin « Abonne-toi ! »</div><div class="li-sub">Désactivée par défaut. Ajoute 1,5 s à la fin du clip.</div></div><label class="switch"><input type="checkbox"><span></span></label></div>
        <div class="toggle-row"><div class="li-main"><div class="li-title">Numéro de partie</div><div class="li-sub">« Partie 1/2 » en haut à droite quand un moment est découpé.</div></div><label class="switch"><input type="checkbox" checked><span></span></label></div>
        <div class="field" style="margin-top:16px"><label>Description type</label><textarea class="input" rows="3">{accroche}\n\nExtrait de ${esc(c.name)} · ${esc(c.handle)}</textarea><span class="hint">Variables : {accroche}, {titre}, {partie}. Hashtags proposés par l'étape captions.</span></div>
      </section>
      <section class="stack" style="gap:16px;align-items:center">
        <div class="phone" style="width:240px">${isStream ? `<img src="img/rendu-2400.jpg" alt="">` : clipPoster(CLIPS[4])}</div>
        <p class="muted" style="font-size:12px;text-align:center">Rendu réel d'un clip de cette chaîne.</p>
      </section>
    </div>`;
  }

  /* ---------- Notation ---------- */
  function paneRubric() {
    return `<div class="grid g-half" style="align-items:start">
      <section class="panel panel-pad">
        <div class="section-title">Poids des critères <span class="more mono">rubric.toml</span></div>
        ${Object.entries(CRITERIA).map(([k, [l, w]]) => `<div class="rubric-row"><span>${l}<span class="faint mono" style="font-size:11px;margin-left:8px">${k}</span></span><input type="range" min="0" max="5" value="${w}" data-rw="${k}"><b data-rv="${k}">${w}</b></div>`).join("")}
        <p class="muted" style="font-size:12px;margin-top:8px">Tendance à 0 : pas de signal fiable pour l'instant.</p>
      </section>
      <section class="panel panel-pad stack" style="gap:16px">
        <div class="field"><label>Qui note</label><div class="seg" id="sel-seg"><button data-v="single">Proposeur seul</button><button data-v="jury" class="on">Jury (5 juges)</button></div><span class="hint">En mode auto, le jury note toujours.</span></div>
        <div class="form-grid">
          <div class="field"><label>Durée min (s)</label><input class="input" type="number" value="${isStream ? 20 : 25}"></div>
          <div class="field"><label>Durée max d'une partie (s)</label><input class="input" type="number" value="${isStream ? 60 : 75}"></div>
          <div class="field"><label>Score minimum</label><input class="input" type="number" value="65"></div>
          <div class="field"><label>Clips max par vidéo</label><input class="input" type="number" value="${isStream ? 8 : 5}"></div>
        </div>
        <div class="field"><label>Exclusions</label><div class="hashtags">${["pubs et sponsors", "pseudos de spectateurs lisibles", "contenu sous droits (musique)"].map((x) => `<span class="tag" style="color:var(--text-2);border-color:var(--line-2)">${x}</span>`).join("")}</div></div>
      </section>
    </div>`;
  }

  /* ---------- Source et publication ---------- */
  function paneSource() {
    return `<div class="grid g-half" style="align-items:start">
      <section class="panel panel-pad">
        <div class="section-title">Source</div>
        <div class="field"><label>Chaîne</label><div class="input-ico" style="width:100%">${icon(c.platform === "twitch" ? "twitch" : "youtube")}<input class="input" style="width:100%" value="${c.platform === "twitch" ? "https://www.twitch.tv/ma_chaine/videos" : "https://www.youtube.com/" + c.handle}"></div></div>
        <div class="toggle-row" style="margin-top:12px"><div class="li-main"><div class="li-title">Surveiller les nouvelles ${c.platform === "twitch" ? "VOD" : "vidéos"}</div><div class="li-sub">Vérifie toutes les 30 min, ajoute en file avec ce preset.</div></div><label class="switch"><input type="checkbox" ${c.watch ? "checked" : ""}><span></span></label></div>
        <div class="toggle-row"><div class="li-main"><div class="li-title">Durée minimum</div><div class="li-sub">Ignore les vidéos plus courtes.</div></div><select class="input" style="width:120px"><option>20 min</option><option>45 min</option><option>1 h</option></select></div>
        <div class="toggle-row"><div class="li-main"><div class="li-title">Mode</div><div class="li-sub">Surcharge le mode global.</div></div><div class="seg" id="m-seg"><button data-v="review" class="${c.mode === "review" ? "on" : ""}">review</button><button data-v="auto" class="${c.mode === "auto" ? "on" : ""}">auto</button></div></div>
      </section>
      <section class="panel panel-pad">
        <div class="section-title">Publication</div>
        <div class="field"><label>Compte TikTok</label><div class="row"><input class="input grow" value="${esc(c.tiktok || "")}" placeholder="@compte"><button class="btn" disabled>${icon("link", "i-sm")}Lier (bientôt)</button></div></div>
        <div class="field" style="margin-top:16px"><label>Créneaux quotidiens</label><div class="slots" id="slots">${c.slots.map((s) => `<span class="slot-chip">${s}<button aria-label="Retirer">${icon("x", "i-xs")}</button></span>`).join("")}<button class="slot-chip" id="add-slot" style="color:var(--muted);border-style:dashed;padding:0 12px">${icon("plus", "i-xs")}</button></div></div>
        <div class="toggle-row" style="margin-top:12px"><div class="li-main"><div class="li-title">Séries : parties le même jour</div><div class="li-sub">Partie 2 publiée 1 h après la partie 1.</div></div><label class="switch"><input type="checkbox" checked><span></span></label></div>
      </section>
    </div>`;
  }

  const panes = { layout: [paneLayout, mountLayout], subs: [paneSubs, mountSubs], title: [paneTitle, null], rubric: [paneRubric, () => {
    $$("[data-rw]", root).forEach((r) => r.addEventListener("input", () => { $(`[data-rv="${r.dataset.rw}"]`, root).textContent = r.value; markDirty(); }));
    initSeg($("#sel-seg", root), markDirty);
  }], source: [paneSource, () => {
    initSeg($("#m-seg", root), markDirty);
    $("#slots", root).addEventListener("click", (e) => {
      const b = e.target.closest("button"); if (!b) return;
      if (b.id === "add-slot") { const s = document.createElement("span"); s.className = "slot-chip"; s.style.animation = "pop 420ms var(--ease-spring)"; s.innerHTML = `21:00<button aria-label="Retirer">${icon("x", "i-xs")}</button>`; b.before(s); }
      else b.closest(".slot-chip").remove();
      markDirty();
    });
  }] };

  function showPane(k, first) {
    const pane = $("#ch-pane", root);
    const go = () => {
      pane.innerHTML = panes[k][0]();
      pane.style.opacity = ""; pane.style.transform = "";
      if (!first) pane.animate([{ opacity: 0, transform: "translateY(6px)" }, { opacity: 1, transform: "none" }], { duration: 260, easing: "cubic-bezier(0.23,1,0.32,1)" });
      if (panes[k][1]) panes[k][1]();
      $$("input,select,textarea", pane).forEach((i) => i.addEventListener("change", markDirty));
    };
    if (first) go(); else { pane.style.transition = "opacity 100ms ease"; pane.style.opacity = "0"; setTimeout(go, 100); }
    history.replaceState(null, "", `#/chaines/${c.id}?tab=${k}`);
  }

  return {
    crumbs: [["Chaînes", "#/chaines"], [c.name]],
    html,
    mount(r) {
      root = r;
      initTabs($("#ch-tabs", root), (k) => showPane(k));
      showPane(tab, true);
      $("#ed-save", root).onclick = () => { $("#dirty", root).textContent = ""; toast({ kind: "ok", title: "Preset enregistré", body: `${esc(c.preset)} · appliqué aux prochaines vidéos de ${esc(c.name)}.`, action: { label: "Voir le JSON", run: () => {} } }); };
      $("#ed-test", root).onclick = () => toast({ kind: "info", title: "Aperçu lancé", body: "Rendu de 5 s sur le moment « Moi, j'vois » (reframe + subtitles + render)." });
    },
  };
};
