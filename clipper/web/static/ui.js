/* Briques d'interface partagees : format, icones, toasts avec « Annuler », modale de confirmation. */
"use strict";

const $ = (sel, root) => (root || document).querySelector(sel);
const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fr = (n, d) => Number(n).toLocaleString("fr-FR", { minimumFractionDigits: d || 0, maximumFractionDigits: d || 0 });

// Delai pendant lequel « Annuler » reste proposé dans un toast (SPEC-c100 T4).
const UNDO_MS = 5000;

/* Remplace chaque <span data-icon="nom"> par l'icone inline correspondante. */
function hydrateIcons(root) {
  $$("[data-icon]", root).forEach((el) => {
    el.outerHTML = icon(el.dataset.icon);
  });
}

/* ---------- Toasts ---------- */
function toast(opts) {
  const o = Object.assign({ kind: "info", title: "", body: "", undo: null, action: null, ms: 5200 }, opts);
  if (o.undo) o.ms = UNDO_MS;
  const ico = { ok: "circle-check", bad: "circle-x", warn: "triangle-alert", info: "info" }[o.kind] || "info";
  const el = document.createElement("div");
  el.className = `toast ${o.kind}`;
  el.setAttribute("role", o.kind === "bad" ? "alert" : "status");
  el.innerHTML = `<span class="t-ico">${icon(ico)}</span>
    <div><div class="t-title">${esc(o.title)}</div>${o.body ? `<div class="t-body">${esc(o.body)}</div>` : ""}</div>
    <div class="t-act">
      ${o.undo ? `<button type="button" class="btn btn-xs btn-ghost" data-undo>${icon("undo-2", "i-xs")}Annuler</button>` : ""}
      ${o.action ? `<button type="button" class="btn btn-xs btn-ghost" data-act>${esc(o.action.label)}</button>` : ""}
      <button type="button" class="icon-btn" style="width:26px;height:26px" data-close aria-label="Fermer">${icon("x", "i-xs")}</button>
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

/* Erreur d'API : toast rouge portant le detail en francais envoyé par le serveur (T2). */
function toastError(title, err) {
  toast({ kind: "bad", title, body: err && err.message ? err.message : String(err), ms: 7000 });
}

/* ---------- Overlay et modale ---------- */
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
  setTimeout(() => { if (!closeCurrent) ov.hidden = true; }, 220);
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
  $$("[data-dismiss]", el).forEach((b) => (b.onclick = closeLayer));
  if (onOpen) onOpen(el);
  return el;
}
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && closeCurrent) closeLayer(); });

/* Confirmation modale d'une action destructive ou coûteuse sans inverse (T4).
   Retourne une promesse : true si l'utilisateur confirme, false sinon. */
function confirmDialog(opts) {
  const o = Object.assign({ title: "Confirmer ?", body: "", confirmLabel: "Confirmer", danger: true }, opts);
  return new Promise((resolve) => {
    let answered = false;
    const answer = (v) => { if (!answered) { answered = true; resolve(v); } };
    const el = openPanel("modal modal-confirm", `
      <div class="modal-head"><h2>${esc(o.title)}</h2></div>
      <div class="modal-body"><p class="muted">${esc(o.body)}</p></div>
      <div class="modal-foot">
        <button type="button" class="btn btn-ghost" data-dismiss>Annuler</button>
        <button type="button" class="btn ${o.danger ? "btn-bad" : "btn-primary"}" data-confirm>${esc(o.confirmLabel)}</button>
      </div>`);
    // Toute fermeture (Échap, clic sur le fond, Annuler) vaut refus.
    const prev = closeCurrent;
    closeCurrent = () => { prev(); answer(false); };
    $("[data-confirm]", el).onclick = () => { answer(true); closeLayer(); };
    setTimeout(() => $("[data-confirm]", el).focus(), 60);
  });
}

/* ---------- Presse-papiers ---------- */
function copyText(text, what) {
  const done = () => toast({ kind: "ok", title: `${what} copiée`, ms: 2600 });
  if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(text).then(done, (e) => toastError("Copie impossible", e));
  else {
    const ta = document.createElement("textarea");
    ta.value = text; document.body.appendChild(ta); ta.select();
    try { document.execCommand("copy"); done(); } catch (e) { toastError("Copie impossible", e); }
    ta.remove();
  }
}
