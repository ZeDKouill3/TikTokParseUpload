/* Briques d'interface partagees : format, toasts, tiroir, modale, onglets, graphiques. */
"use strict";

const $ = (sel, root) => (root || document).querySelector(sel);
const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const chan = (id) => CHANNELS.find((c) => c.id === id);
const video = (id) => VIDEOS.find((v) => v.id === id);
const clip = (id) => CLIPS.find((c) => c.id === id);
const stepLabel = (id) => (STEPS.find((s) => s.id === id) || {}).label || id;

function fmtDur(sec) {
  if (sec == null) return "…";
  if (sec < 60) return `${Math.round(sec)} s`;
  const m = Math.floor(sec / 60), s = Math.round(sec % 60);
  return m >= 60 ? `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, "0")}` : `${m} min ${String(s).padStart(2, "0")}`;
}
function fmtTC(sec) {
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  const ss = s.toFixed(1).padStart(4, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${m}:${ss}`;
}
const fr = (n, d) => Number(n).toLocaleString("fr-FR", { minimumFractionDigits: d || 0, maximumFractionDigits: d || 0 });

function srcIcon(platform) {
  return `<span class="src-ico src-${platform}" title="${platform === "twitch" ? "Twitch" : "YouTube"}">${icon(platform === "twitch" ? "twitch" : "youtube")}</span>`;
}

/* Vignette 16:9 d'une video : image reelle ou affiche generee. */
function videoThumb(v) {
  if (v.thumb) return `<img src="${v.thumb}" alt="" loading="lazy">`;
  const c = chan(v.channel);
  const n = v.poster === "cast" ? 2 : 4;
  return `<div class="plateau" style="--pc:${c.color}55">${"<i></i>".repeat(n)}<b></b></div>`;
}

/* Affiche 9:16 d'un clip */
function clipPoster(c) {
  if (c.img) return `<img src="${c.img}" alt="" loading="lazy">`;
  const cls = c.poster === "cast" ? "poster-debat poster-cast" : "poster-debat";
  return `<div class="${cls}">
    <div class="pd-title">${esc(c.screen_title)}</div>
    <div>
      <div class="pd-faces"><div class="pd-face"></div><div class="pd-face"></div></div>
    </div>
    <div class="pd-sub">${c.sub || ""}</div>
    <div class="pd-tag">aperçu généré</div>
  </div>`;
}

/* ---------- Toasts ---------- */
function toast(opts) {
  const o = Object.assign({ kind: "info", title: "", body: "", undo: null, action: null, ms: 5200 }, opts);
  const ico = { ok: "circle-check", bad: "circle-x", warn: "triangle-alert", info: "info" }[o.kind] || "info";
  const el = document.createElement("div");
  el.className = `toast ${o.kind}`;
  if (o.undo) el.dataset.seq = typeof App !== "undefined" ? App._seq || 0 : 0;
  el.setAttribute("role", "status");
  el.innerHTML = `<span class="t-ico">${icon(ico)}</span>
    <div><div class="t-title">${esc(o.title)}</div>${o.body ? `<div class="t-body">${o.body}</div>` : ""}</div>
    <div class="t-act">
      ${o.undo ? `<button class="btn btn-xs btn-ghost" data-undo>${icon("undo-2", "i-xs")}Annuler</button>` : ""}
      ${o.action ? `<button class="btn btn-xs btn-ghost" data-act>${esc(o.action.label)}</button>` : ""}
      <button class="icon-btn" style="width:26px;height:26px" data-close aria-label="Fermer">${icon("x", "i-xs")}</button>
    </div>
    <span class="t-timer" style="animation-duration:${o.ms}ms"></span>`;
  $("#toasts").appendChild(el);
  let timer = setTimeout(close, o.ms);
  function close() {
    clearTimeout(timer);
    el.classList.add("out");
    setTimeout(() => el.remove(), 220);
  }
  el.addEventListener("mouseenter", () => { clearTimeout(timer); el.querySelector(".t-timer").style.animationPlayState = "paused"; });
  el.addEventListener("mouseleave", () => { timer = setTimeout(close, 2000); });
  el.querySelector("[data-close]").onclick = close;
  if (o.undo) el.querySelector("[data-undo]").onclick = () => { o.undo(); close(); };
  if (o.action) el.querySelector("[data-act]").onclick = () => { o.action.run(); close(); };
  const all = $$("#toasts .toast");
  if (all.length > 4) all[0].remove();
  return close;
}

/* ---------- Overlay, tiroir, modale ---------- */
let closeCurrent = null;
function showOverlay(onClose) {
  const ov = $("#overlay");
  ov.hidden = false;
  requestAnimationFrame(() => ov.classList.add("show"));
  ov.onclick = () => closeLayer();
  closeCurrent = onClose;
}
function closeLayer() {
  const ov = $("#overlay");
  ov.classList.remove("show");
  setTimeout(() => { ov.hidden = true; }, 220);
  if (closeCurrent) { const f = closeCurrent; closeCurrent = null; f(); }
}
function openPanel(cls, html, onOpen) {
  if (closeCurrent) closeLayer();
  const el = document.createElement("div");
  el.className = cls;
  el.setAttribute("role", "dialog");
  el.setAttribute("aria-modal", "true");
  el.innerHTML = html;
  document.body.appendChild(el);
  showOverlay(() => { el.classList.remove("show"); setTimeout(() => el.remove(), 320); });
  requestAnimationFrame(() => requestAnimationFrame(() => el.classList.add("show")));
  el.querySelectorAll("[data-dismiss]").forEach((b) => (b.onclick = closeLayer));
  if (onOpen) onOpen(el);
  return el;
}
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && closeCurrent) closeLayer(); });

/* ---------- Segmented + tabs avec indicateur glissant ---------- */
function initSeg(root, onChange) {
  const thumb = document.createElement("span");
  thumb.className = "thumb";
  root.prepend(thumb);
  const place = () => {
    const on = root.querySelector("button.on");
    if (!on) return;
    thumb.style.left = on.offsetLeft + "px";
    thumb.style.width = on.offsetWidth + "px";
  };
  root.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
    root.querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === b));
    place();
    if (onChange) onChange(b.dataset.v);
  }));
  requestAnimationFrame(place);
  document.fonts && document.fonts.ready.then(place);
}
function initTabs(root, onChange) {
  const ink = document.createElement("span");
  ink.className = "ink";
  root.appendChild(ink);
  const place = () => {
    const on = root.querySelector("button.on");
    if (!on) return;
    ink.style.left = on.offsetLeft + "px";
    ink.style.width = on.offsetWidth + "px";
  };
  root.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
    root.querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === b));
    place();
    if (onChange) onChange(b.dataset.v);
  }));
  requestAnimationFrame(place);
  document.fonts && document.fonts.ready.then(place);
}

/* ---------- Compteurs qui montent (une fois par entree de page) ---------- */
function countUp(root) {
  $$("[data-count]", root).forEach((el) => {
    const target = parseFloat(el.dataset.count);
    const dec = parseInt(el.dataset.dec || "0", 10);
    if (document.documentElement.classList.contains("shot")) { el.textContent = fr(target, dec); return; }
    const t0 = performance.now(), dur = 700;
    const step = (t) => {
      const k = Math.min(1, (t - t0) / dur);
      const e = 1 - Math.pow(1 - k, 3);
      el.textContent = fr(target * e, dec);
      if (k < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  });
}

/* ---------- Graphiques en barres (une serie, accent unique) ---------- */
function barChart(opts) {
  // opts: data [[label, value]], w, h, unit, fmt, horizontal
  const { data, unit = "", fmtV = (v) => fr(v), horizontal = false } = opts;
  const max = Math.max(...data.map((d) => d[1])) || 1;
  if (horizontal) {
    const rowH = 26, gap = 8, lw = 124, w = 440, h = data.length * (rowH + gap);
    let s = `<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="${esc(opts.label || "")}">`;
    data.forEach((d, i) => {
      const y = i * (rowH + gap), bw = Math.max(4, ((w - lw - 64) * d[1]) / max);
      s += `<text class="lbl-t" x="0" y="${y + rowH / 2 + 4}">${esc(d[0])}</text>`;
      s += `<path class="bar-m" data-i="${i}" d="M${lw} ${y + 4} h${bw - 4} a4 4 0 0 1 4 4 v${rowH - 16} a4 4 0 0 1 -4 4 h-${bw - 4} z"><animate attributeName="opacity" from="0" to="1" dur="0.5s" begin="${i * 0.04}s" fill="freeze"/></path>`;
      s += `<text class="val-t" x="${lw + bw + 8}" y="${y + rowH / 2 + 4}">${fmtV(d[1])}${unit}</text>`;
      s += `<rect class="hit" data-i="${i}" x="0" y="${y}" width="${w}" height="${rowH}"/>`;
    });
    return s + "</svg>";
  }
  const w = 640, h = 220, pb = 24, pt = 16, pl = 28;
  const n = data.length, slot = (w - pl) / n, bw = Math.min(28, slot - 8);
  const niceMax = Math.ceil(max / 4) * 4 || 4;
  let s = `<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="${esc(opts.label || "")}">`;
  for (let k = 0; k <= 4; k++) {
    const y = pt + ((h - pb - pt) * k) / 4;
    s += `<line class="grid-l" x1="${pl}" x2="${w}" y1="${y}" y2="${y}"/>`;
    s += `<text class="axis-t" x="0" y="${y + 4}">${fr(niceMax - (niceMax * k) / 4)}</text>`;
  }
  data.forEach((d, i) => {
    const x = pl + i * slot + (slot - bw) / 2;
    const bh = ((h - pb - pt) * d[1]) / niceMax;
    const y = h - pb - bh;
    if (d[1] > 0) {
      s += `<path class="bar-m" data-i="${i}" d="M${x} ${h - pb} v-${Math.max(0, bh - 4)} a4 4 0 0 1 4 -4 h${bw - 8} a4 4 0 0 1 4 4 v${Math.max(0, bh - 4)} z" style="transform-origin:${x}px ${h - pb}px;animation:grow-bar 600ms var(--ease-out) ${i * 30}ms both"/>`;
    }
    if (i % 2 === 1 || n <= 8) s += `<text class="axis-t" x="${x + bw / 2}" y="${h - 6}" text-anchor="middle">${esc(d[0])}</text>`;
    s += `<rect class="hit" data-i="${i}" x="${pl + i * slot}" y="${pt}" width="${slot}" height="${h - pt}"/>`;
  });
  return s + "</svg>";
}
function wireChart(root, data, fmtTip) {
  const tip = document.createElement("div");
  tip.className = "tip";
  root.appendChild(tip);
  const svg = root.querySelector("svg");
  root.addEventListener("pointermove", (e) => {
    const t = e.target.closest("[data-i]");
    const bars = $$(".bar-m", root);
    if (!t) { tip.classList.remove("show"); bars.forEach((b) => b.classList.remove("dim")); return; }
    const i = +t.dataset.i;
    bars.forEach((b) => b.classList.toggle("dim", +b.dataset.i !== i));
    tip.innerHTML = fmtTip(data[i]);
    const r = root.getBoundingClientRect();
    tip.style.left = e.clientX - r.left + "px";
    tip.style.top = e.clientY - r.top + "px";
    tip.classList.add("show");
  });
  root.addEventListener("pointerleave", () => { tip.classList.remove("show"); $$(".bar-m", root).forEach((b) => b.classList.remove("dim")); });
  return svg;
}
const barStyle = document.createElement("style");
barStyle.textContent = "@keyframes grow-bar{from{transform:scaleY(0)}}";
document.head.appendChild(barStyle);

/* ---------- Presse-papiers ---------- */
function copyText(text, what) {
  const done = () => toast({ kind: "ok", title: `${what} copiée`, body: "Prête à coller dans TikTok.", ms: 2600 });
  if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(text).then(done, done);
  else {
    const ta = document.createElement("textarea");
    ta.value = text; document.body.appendChild(ta); ta.select();
    try { document.execCommand("copy"); } catch (e) { /* maquette : on confirme quand meme */ }
    ta.remove(); done();
  }
}
