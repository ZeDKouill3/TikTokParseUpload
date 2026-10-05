/* Briques d'interface partagees : format, icones, toasts avec « Annuler », modale de confirmation. */
"use strict";

const $ = (sel, root) => (root || document).querySelector(sel);
const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
// Toutes les heures affichees par la console sont celles de Paris (Europe/Paris : +02:00 l'ete, +01:00 l'hiver),
// jamais le fuseau du navigateur ni un decalage fixe.
const CLIPPER_TZ = "Europe/Paris";
const fmtParis = (iso, opts) => new Date(iso).toLocaleString("fr-FR", Object.assign({ timeZone: CLIPPER_TZ }, opts));
const fr = (n, d) => Number(n).toLocaleString("fr-FR", { minimumFractionDigits: d || 0, maximumFractionDigits: d || 0 });

/* Confiance du jury (SPEC-73d0 R4) : agregat (mediane des confiances finales) puis
   confiance finale de chaque juge. Sans jury : le dit, sans valeur inventee. */
function juryConfidenceHtml(confidence, judges) {
  if (confidence == null) return `<span class="muted">non évaluée (pas de jury pour ce moment)</span>`;
  const per = Object.entries(judges || {}).map(([name, c]) => `<span class="tag">${esc(name)} ${fr(c)} %</span>`).join("");
  return `<b class="num">${fr(confidence)} %</b>${per ? `<span class="row wrap" style="gap:6px;margin-top:6px">${per}</span>` : ""}`;
}

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
  // 409 « la vidéo n'a pas de style » (approbation, publication) : le choix du style se fait depuis l'erreur.
  const needs = err && err.body && err.body.needs_channel;
  toast({
    kind: "bad", title, body: err && err.message ? err.message : String(err), ms: 7000,
    action: needs ? { label: "Attribuer un style", run: () => openAssignChannel(err.body.video_id, err.body.channels) } : null,
  });
}

/* ---------- Overlay et modale ---------- */
let closeCurrent = null;
function showOverlay(onClose) {
  const ov = $("#overlay");
  ov.hidden = false;
  const reveal = () => ov.classList.add("show");
  requestAnimationFrame(reveal);
  setTimeout(reveal, 60); // requestAnimationFrame est suspendu dans un onglet masque : le fond ne doit pas rester invisible
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
  const reveal = () => el.classList.add("show");
  requestAnimationFrame(() => requestAnimationFrame(reveal));
  setTimeout(reveal, 80); // meme garde-fou : le panneau (opacity 0 tant que .show manque) s'affiche toujours
  $$("[data-dismiss]", el).forEach((b) => (b.onclick = closeLayer));
  if (onOpen) {
    try { onOpen(el); } catch (err) { toastError("Fenêtre incomplète", err); }
  }
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

/* ---------- Garde réseau au clic (TASK-120a) ----------
   Une seule source : la dernière valeur de /api/network relevée par app.js (paintNetwork -> setNetLast).
   Toute action qui publie ou programme passe par netGuard() : ok=false ouvre une fenêtre d'alerte (rien
   n'est lancé sans « Continuer quand même », absent si le serveur bloque le navigateur) ; ok=true ou ok=null
   (inconnu) : aucune fenêtre. Aucune alerte quand le réseau change, seulement au clic. Le refus serveur
   (clipper.browser) reste la vraie barrière. */
let netLast = null;
function setNetLast(net) { netLast = net || null; }

// null : pas de fenêtre ; "block" : le serveur refusera, on ne propose que Fermer ; "ask" : Continuer possible.
function netAlertMode(net) {
  if (!net || net.ok !== false) return null;
  return net.block_browser ? "block" : "ask";
}

function netAlertDialog(net, mode) {
  return new Promise((resolve) => {
    const detected = net.country_name ? `${net.country_name} (${net.country})` : (net.country || "inconnu");
    const expected = net.expected_country_name || net.expected_country || "inconnu";
    const root = document.createElement("div");
    root.className = "net-alert";
    root.innerHTML = `<div class="net-alert-back"></div>
      <div class="modal modal-confirm net-alert-box show" role="alertdialog" aria-modal="true">
        <div class="modal-head"><h2>IP hors du pays attendu</h2></div>
        <div class="modal-body">
          <p>Pays détecté : <b>${esc(detected)}</b><br>Pays attendu : <b>${esc(expected)}</b></p>
          <p class="muted">${mode === "block"
    ? "La publication sera refusée : Clipper ne pilote pas le navigateur depuis cette IP. Change de réseau (VPN) puis recommence."
    : "La publication est risquée : le compte peut être signalé ou bloqué depuis cette IP."}</p>
        </div>
        <div class="modal-foot">
          ${mode === "block"
    ? `<button type="button" class="btn btn-primary" data-net-close>Fermer</button>`
    : `<button type="button" class="btn btn-ghost" data-net-cancel>Annuler</button>
          <button type="button" class="btn btn-bad" data-net-go>Continuer quand même</button>`}
        </div>
      </div>`;
    let done = false;
    const finish = (v) => {
      if (done) return;
      done = true;
      document.removeEventListener("keydown", onKey);
      root.remove();
      resolve(v);
    };
    const onKey = (e) => { if (e.key === "Escape") finish(false); };
    document.addEventListener("keydown", onKey);
    document.body.appendChild(root);
    const bind = (sel, v) => { const b = root.querySelector(sel); if (b) b.onclick = () => finish(v); };
    bind("[data-net-close]", false);
    bind("[data-net-cancel]", false);
    bind("[data-net-go]", true);
    root.querySelector(".net-alert-back").onclick = () => finish(false);
    const first = root.querySelector("[data-net-close], [data-net-cancel]");
    if (first) setTimeout(() => first.focus(), 30);
  });
}

/* true : l'action peut partir. */
async function netGuard() {
  if (netLast === null) {
    try { netLast = await api("/api/network"); } catch (err) { netLast = null; }
  }
  const mode = netAlertMode(netLast);
  if (!mode) return true;
  return netAlertDialog(netLast, mode);
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
