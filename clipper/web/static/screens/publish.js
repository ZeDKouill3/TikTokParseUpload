/* Ecran « Publication » (SPEC-c100 E6, SPEC-fc0c §4). Lit GET /api/publish?channel=&week= :
   les creneaux de la semaine (avec le clip planifie ou libres), la file des clips
   approuves sans creneau et les publies / en echec de la semaine. Un clip se glisse
   (souris ou appui long au toucher) vers un creneau libre : POST .../move. En attendant
   l'API TikTok, publier = telecharger + copier + « Marquer publie » a la main ; la
   colonne statut et le compte cible gardent la place de l'autopost. Aucune logique
   serveur ici : tout passe par l'API. Charge apres screens.js dont il remplace
   l'entree Screens.publish. */
"use strict";

const PUB_STATUS = {
  approved: { label: "Approuvé", cls: "ok" }, scheduled: { label: "Planifié", cls: "info" },
  published: { label: "Publié", cls: "ok" }, failed: { label: "Échec", cls: "bad" },
};
const PUB_STALE_MS = 4000;
const PUB_HOLD_MS = 250;      // appui long avant de saisir un clip au toucher
const PUB_SLOP_PX = 8;        // mouvement tolere pendant l'appui long (sinon : defilement)
const pubEnc = encodeURIComponent;

const pubUi = { channel: "", week: "", key: "", data: null, error: null, loading: null, dirty: false, at: 0, html: "", dragKey: null, touching: false, landed: null };

const pubKey = (c) => `${c.video_id}/${c.clip_id}`;
const pubStatus = (c) => PUB_STATUS[c.publish_status] || { label: c.publish_status, cls: "pending" };
const pubTitle = (c) => c.screen_title || c.title || c.clip_id;
const pubChip = (c) => { const s = pubStatus(c); return `<span class="chip ${s.cls}">${esc(s.label)}</span>`; };
const pubCaptionText = (c) => [c.description || "", (c.hashtags || []).join(" ")].filter(Boolean).join("\n\n");
// Les dates de l'API sont deja dans le fuseau de la chaine : on les lit telles quelles.
const pubDate = (iso) => iso.slice(0, 10);
const pubTime = (iso) => iso.slice(11, 16);
const pubUtc = (ymd) => { const [y, m, d] = ymd.split("-").map(Number); return new Date(Date.UTC(y, m - 1, d)); };
const pubFmt = (ymd, opts) => pubUtc(ymd).toLocaleDateString("fr-FR", Object.assign({ timeZone: "UTC" }, opts));
const pubShift = (ymd, days) => { const d = pubUtc(ymd); d.setUTCDate(d.getUTCDate() + days); return d.toISOString().slice(0, 10); };
const pubDayIndex = (ymd, start) => Math.round((pubUtc(ymd) - pubUtc(start)) / 86400000);
const pubSlotLabel = (iso) => `${pubFmt(pubDate(iso), { weekday: "long", day: "numeric", month: "long" })} à ${pubTime(iso)}`;

function pubClips() {
  const d = pubUi.data;
  if (!d) return [];
  return [...d.unscheduled, ...d.slots.map((s) => s.clip).filter(Boolean), ...d.done];
}
const pubFind = (key) => pubClips().find((c) => pubKey(c) === key) || null;

/* ---------- Chargement ---------- */

function pubWantedKey() { return `${pubUi.channel}|${pubUi.week}`; }

function pubLoad() {
  if (pubUi.loading) { pubUi.dirty = true; return pubUi.loading; }
  const key = pubWantedKey();
  pubUi.loading = (async () => {
    try {
      const data = await api(`/api/publish?channel=${pubEnc(pubUi.channel)}&week=${pubEnc(pubUi.week)}`);
      if (key === pubWantedKey()) {
        pubUi.data = data; pubUi.error = null;
        if (!pubUi.week) pubUi.week = data.week_start; // « cette semaine » : on retient le lundi renvoye
        pubUi.key = pubWantedKey();
      }
    } catch (err) {
      if (key === pubWantedKey()) { pubUi.data = null; pubUi.error = err; pubUi.key = key; }
    } finally {
      pubUi.loading = null;
      pubUi.at = Date.now();
    }
    if (currentScreen === "publish") renderCurrent();
    if (pubUi.dirty) { pubUi.dirty = false; pubLoad(); }
  })();
  return pubUi.loading;
}

// Un evenement publish / video / queue rend la semaine obsolete (le serveur reste la source).
document.addEventListener("clipper:event", () => {
  pubUi.at = 0;
  if (currentScreen === "publish" && pubUi.channel && !pubUi.dragKey) pubLoad();
});

/* ---------- Rendu ---------- */

function pubPost(c, extra) {
  const draggable = (c.publish_status === "approved" || c.publish_status === "scheduled" || c.publish_status === "failed") && !c.missing;
  const icoName = c.publish_status === "published" ? "circle-check" : c.publish_status === "failed" ? "circle-alert" : "";
  return `<div class="post ${esc(c.publish_status)}${c.missing ? " missing" : ""}" data-post="${esc(pubKey(c))}" draggable="${draggable}" tabindex="0" role="button" aria-label="Ouvrir le clip ${esc(pubTitle(c))}" title="${esc(pubTitle(c))}">
    <div class="mini-clip">${c.video_url ? `<img loading="lazy" decoding="async" src="${esc(c.thumbnail_url)}" alt="" tabindex="-1">` : ""}</div>
    <span class="pt">${esc(c.missing ? `Clip introuvable (${c.clip_id})` : pubTitle(c))}</span>
    ${extra || ""}${icoName ? icon(icoName, "i-xs") : ""}</div>`;
}

function pubCalendar(d) {
  const times = Array.from(new Set(d.slots.map((s) => pubTime(s.slot_at)))).sort();
  const bySlot = {};
  d.slots.forEach((s) => { bySlot[`${pubDayIndex(pubDate(s.slot_at), d.week_start)}|${pubTime(s.slot_at)}`] = s; });
  const today = new Date().toLocaleDateString("sv-SE", { timeZone: d.timezone });
  const days = Array.from({ length: 7 }, (_, i) => pubShift(d.week_start, i));
  let h = `<div class="cal-h"></div>${days.map((ymd) => `<div class="cal-h${ymd === today ? " today" : ""}"><div class="d">${esc(pubFmt(ymd, { weekday: "short" }))}</div><div class="n">${esc(pubFmt(ymd, { day: "numeric" }))}</div></div>`).join("")}`;
  times.forEach((time) => {
    h += `<div class="cal-t">${esc(time)}</div>`;
    days.forEach((ymd, i) => {
      const s = bySlot[`${i}|${time}`];
      if (!s) { h += `<div class="cal-c off"></div>`; return; }
      const past = Date.parse(s.slot_at) < Date.now();
      h += `<div class="cal-c slot${past ? " past" : ""}${s.free ? " free" : ""}" data-slot-at="${esc(s.slot_at)}" data-slot="${esc(time)}" aria-label="Créneau ${esc(pubSlotLabel(s.slot_at))}${s.free ? ", libre" : ""}">${s.clip ? pubPost(s.clip) : ""}</div>`;
    });
  });
  return `<div class="cal-wrap"><div class="cal" id="pub-cal">${h}</div></div>`;
}

function pubQueue(d) {
  const items = d.unscheduled;
  return `<section>
    <div class="section-title">${icon("inbox")}À publier <span class="more">${items.length ? `${items.length} clip${items.length > 1 ? "s" : ""}` : ""}</span></div>
    <div class="queue" id="pub-queue">${items.length ? items.map((c) => pubPost(c, `<span class="grow"></span><span class="muted">${icon("grip-vertical", "i-xs")}</span>`)).join("")
      : `<div class="panel empty" style="padding:24px"><div class="empty-art">${icon("circle-check")}</div><p>Tout est planifié.</p></div>`}</div>
    ${items.length && d.slots.length ? `<p class="hint muted" style="font-size:12px;margin-top:8px">Glisse un clip sur un créneau libre du calendrier (appui long sur mobile).</p>` : ""}
    ${items.length && !d.slots.length ? `<p class="hint muted" style="font-size:12px;margin-top:8px">${esc(d.reason || "Aucun créneau cette semaine.")}</p>` : ""}
  </section>`;
}

function pubDone(d) {
  if (!d.done.length) return "";
  return `<section>
    <div class="section-title">${icon("circle-check")}Publiés et échecs de la semaine <span class="more">${d.done.length}</span></div>
    <div class="panel">${d.done.map((c) => `<div class="list-item pub-done" data-post="${esc(pubKey(c))}" tabindex="0" role="button">
      <div class="mini-clip">${c.video_url ? `<img loading="lazy" decoding="async" src="${esc(c.thumbnail_url)}" alt="" tabindex="-1">` : ""}</div>
      <div class="li-main grow"><div class="li-title">${esc(pubTitle(c))}</div>
        <div class="li-sub muted">${c.publish_status === "published" ? "publié" : "échec"}${c.slot_at ? ` · ${esc(pubSlotLabel(c.slot_at))}` : ""}${c.publish_error ? ` · ${esc(c.publish_error)}` : ""}</div></div>
      ${pubChip(c)}</div>`).join("")}</div>
  </section>`;
}

function pubToolbar(channels, d) {
  const weekLabel = d ? `${pubFmt(d.week_start, { day: "numeric", month: "short" })} au ${pubFmt(d.week_end, { day: "numeric", month: "short", year: "numeric" })}` : "";
  const account = d ? (d.tiktok_account ? `Compte cible : <b>${esc(d.tiktok_account)}</b>` : `<span class="muted">Aucun compte TikTok renseigné (<span class="mono">tiktok_account</span>)</span>`) : "";
  return `<div class="toolbar pub-toolbar">
    <select class="input" id="pub-channel" aria-label="Chaîne">${channels.map((n) => `<option value="${esc(n)}"${n === pubUi.channel ? " selected" : ""}>${esc(n)}</option>`).join("")}</select>
    <div class="row" style="gap:4px"><button type="button" class="icon-btn" data-week="-1" aria-label="Semaine précédente"${d ? "" : " disabled"}>${icon("chevron-left")}</button>
      <h2 style="font-size:16px;min-width:11ch;text-align:center">${esc(weekLabel)}</h2>
      <button type="button" class="icon-btn" data-week="1" aria-label="Semaine suivante"${d ? "" : " disabled"}>${icon("chevron-right")}</button>
      <button type="button" class="btn btn-xs btn-ghost" data-week="0">Cette semaine</button></div>
    <span class="grow"></span>
    <span class="pub-account">${account}</span>
    <div class="legend"><span><i style="background:var(--info)"></i>planifié</span><span><i style="background:var(--ok)"></i>publié</span><span><i style="background:var(--bad)"></i>échec</span></div>
  </div>`;
}

function pubView(body, channels) {
  const d = pubUi.data;
  let content;
  if (pubUi.error) content = `<p class="reason bad">Chargement impossible : ${esc(pubUi.error.message || pubUi.error)}</p>`;
  else if (!d) content = `<div class="skeleton skeleton-line"></div><div class="skeleton skeleton-card"></div>`;
  else if (!d.slots.length && !d.unscheduled.length && !d.done.length) {
    content = emptyState("send", "Rien à publier", "Approuve des clips : ils apparaîtront ici avec leurs créneaux." + (d.reason ? ` Cette chaîne n'a pas de créneau : ${d.reason}.` : ""));
  } else {
    content = `<div class="banner">${icon("info", "i-lg")}<p><b>Autopost TikTok pas encore branché.</b> Au créneau : télécharge le clip, copie la description, publie depuis l'appli, puis « Marquer publié ».</p></div>
      <div class="grid g-side pub-grid" style="align-items:start"><div class="stack">${pubQueue(d)}</div>
      <div class="stack"><section>${d.slots.length ? pubCalendar(d) : `<p class="reason">${esc(d.reason || "Aucun créneau cette semaine.")}</p>`}</section>${pubDone(d)}</div></div>`;
  }
  const html = `<div class="pub-pad">${pubToolbar(channels, d)}${content}</div>`;
  if (pubUi.html === html && body.childElementCount) return false; // rien de change : on garde les vignettes et le survol
  pubUi.html = html;
  body.innerHTML = html;
  return true;
}

/* ---------- Actions ---------- */

async function pubMove(c, slotAt) {
  const before = c.slot_at;
  try {
    await api(`/api/publish/${pubEnc(c.video_id)}/${pubEnc(c.clip_id)}/move`, jsonBody("POST", { slot_at: slotAt }));
    pubUi.landed = pubKey(c);
    await pubLoad();
    toast({
      kind: "ok", title: `Planifié ${pubSlotLabel(slotAt)}`, body: pubTitle(c),
      undo: () => pubRestore(c, before),
    });
  } catch (err) {
    toastError("Impossible de déplacer le clip", err);
    pubUi.at = 0;
    pubLoad();
  }
}

/* Annule une action : remet le clip sur `slotAt`, ou en attente sans creneau si `slotAt` est vide.
   Un clip publie ne se deplace pas : il repasse d'abord en attente (`viaUnschedule`). */
async function pubRestore(c, slotAt, viaUnschedule) {
  try {
    if (!slotAt || viaUnschedule) await api(`/api/publish/${pubEnc(c.video_id)}/${pubEnc(c.clip_id)}/unschedule`, { method: "POST" });
    if (slotAt) await api(`/api/publish/${pubEnc(c.video_id)}/${pubEnc(c.clip_id)}/move`, jsonBody("POST", { slot_at: slotAt }));
    toast({ kind: "info", title: "Annulé", body: pubTitle(c), ms: 2600 });
  } catch (err) {
    toastError("Impossible d'annuler", err);
  }
  pubUi.at = 0;
  pubLoad();
}

async function pubMarkPublished(c) {
  const account = pubUi.data && pubUi.data.tiktok_account;
  const ok = await confirmDialog({
    title: "Marquer comme publié ?",
    body: `Confirme que « ${pubTitle(c)} » est bien en ligne${account ? ` sur ${account}` : ""}. L'autopost n'est pas branché : ce statut se pose à la main.`,
    confirmLabel: "Marquer publié", danger: false,
  });
  if (!ok) return false;
  const slotAt = c.slot_at;
  try {
    await api(`/api/publish/${pubEnc(c.video_id)}/${pubEnc(c.clip_id)}/published`, { method: "POST" });
    await pubLoad();
    toast({
      kind: "ok", title: "Clip marqué publié", body: pubTitle(c),
      undo: () => pubRestore(c, slotAt, true),
    });
    return true;
  } catch (err) {
    toastError("Impossible de marquer le clip publié", err);
    return false;
  }
}

async function pubUnschedule(c) {
  const slotAt = c.slot_at;
  try {
    await api(`/api/publish/${pubEnc(c.video_id)}/${pubEnc(c.clip_id)}/unschedule`, { method: "POST" });
    await pubLoad();
    toast({
      kind: "warn", title: "Repassé en attente", body: pubTitle(c),
      undo: () => (slotAt ? pubRestore(c, slotAt) : pubLoad()),
    });
    return true;
  } catch (err) {
    toastError("Impossible de repasser le clip en attente", err);
    return false;
  }
}

/* ---------- Fiche d'un clip ---------- */

function pubDetailHtml(c) {
  const account = pubUi.data && pubUi.data.tiktok_account;
  const status = c.publish_status;
  const hint = status === "approved" ? "Glisse ce clip sur un créneau libre du calendrier pour le planifier."
    : status === "failed" ? "La publication a échoué : repasse le clip en attente pour le replanifier." : "";
  return `
    <div class="modal-head"><div class="row wrap" style="gap:8px">${pubChip(c)}<h2>${esc(pubTitle(c))}</h2></div>
      <p class="muted" style="margin-top:4px">${c.slot_at ? esc(pubSlotLabel(c.slot_at)) : "Sans créneau"}${account ? ` · ${esc(account)}` : ""}</p></div>
    <div class="modal-body stack" style="gap:16px">
      ${c.publish_error ? `<p class="reason bad">Publication en échec : ${esc(c.publish_error)}</p>` : ""}
      ${hint ? `<p class="muted">${esc(hint)}</p>` : ""}
      <div class="field"><span class="field-label">Description</span><div class="pub-caption">${esc(c.description || "")}</div></div>
      <div class="hashtags">${(c.hashtags || []).map((t) => `<span class="tag">${esc(t)}</span>`).join("")}</div>
    </div>
    <div class="modal-foot">
      <a class="btn btn-ghost" href="${esc(c.video_url)}" download="${esc(c.clip_id)}.mp4">${icon("download")}Télécharger</a>
      <button type="button" class="btn btn-ghost" data-copy>${icon("copy")}Copier la description</button>
      <span class="grow"></span>
      ${status === "scheduled" || status === "failed" ? `<button type="button" class="btn" data-unschedule>${icon("undo-2")}Repasser en attente</button>` : ""}
      ${status === "scheduled" ? `<button type="button" class="btn btn-primary" data-published>${icon("check")}Marquer publié</button>` : ""}
    </div>`;
}

function pubOpenDetail(key) {
  const c = pubFind(key);
  if (!c) return;
  if (c.missing) { toastError("Clip introuvable", new Error(`Le sidecar de ${c.video_id}/${c.clip_id} n'existe plus dans output/.`)); return; }
  openPanel("modal pub-modal", pubDetailHtml(c), (d) => {
    $("[data-copy]", d).onclick = () => copyText(pubCaptionText(c), "Description et hashtags");
    const un = $("[data-unschedule]", d);
    if (un) un.onclick = async () => { closeLayer(); await pubUnschedule(c); };
    const pub = $("[data-published]", d);
    if (pub) pub.onclick = async () => { closeLayer(); await pubMarkPublished(c); };
  });
}

/* ---------- Glisser-deposer (souris : HTML5 drag ; toucher : appui long + deplacement) ---------- */

function pubDropOn(cell, key) {
  const c = pubFind(key);
  if (!c || !cell || !cell.dataset.slotAt) return;
  if (cell.classList.contains("past")) { toast({ kind: "warn", title: "Créneau passé", body: "Choisis un créneau à venir." }); return; }
  if (cell.querySelector("[data-post]") && cell.querySelector("[data-post]").dataset.post !== key) {
    toast({ kind: "warn", title: "Créneau déjà pris", body: "Choisis un créneau libre ou repasse l'autre clip en attente." });
    return;
  }
  if (c.slot_at === cell.dataset.slotAt) return;
  pubMove(c, cell.dataset.slotAt);
}

const pubCells = (root) => $$(".cal-c[data-slot-at]", root);
const pubClearDrop = (root) => $$(".cal-c.drop", root).forEach((x) => x.classList.remove("drop"));
const pubDroppable = (cell) => cell && !cell.classList.contains("past");

function pubWireMouse(body) {
  $$(".post[draggable='true']", body).forEach((el) => {
    el.addEventListener("dragstart", (e) => {
      if (pubUi.touching) { e.preventDefault(); return; }
      pubUi.dragKey = el.dataset.post;
      el.classList.add("dragging");
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", el.dataset.post);
    });
    el.addEventListener("dragend", () => { el.classList.remove("dragging"); pubUi.dragKey = null; pubClearDrop(body); });
  });
  pubCells(body).forEach((cell) => {
    cell.addEventListener("dragover", (e) => {
      if (!pubUi.dragKey || !pubDroppable(cell)) return;
      e.preventDefault();
      pubClearDrop(body);
      cell.classList.add("drop");
    });
    cell.addEventListener("dragleave", (e) => { if (!cell.contains(e.relatedTarget)) cell.classList.remove("drop"); });
    cell.addEventListener("drop", (e) => {
      e.preventDefault();
      const key = pubUi.dragKey || e.dataTransfer.getData("text/plain");
      pubUi.dragKey = null;
      pubClearDrop(body);
      pubDropOn(cell, key);
    });
  });
}

function pubWireTouch(body) {
  $$(".post[draggable='true']", body).forEach((el) => {
    let timer = null, ghost = null, origin = null, over = null;
    const stop = () => {
      clearTimeout(timer); timer = null;
      if (ghost) ghost.remove();
      ghost = null; over = null;
      el.classList.remove("dragging");
      pubClearDrop(body);
      pubUi.dragKey = null;
      setTimeout(() => { pubUi.touching = false; }, 400);
    };
    const place = (t) => { ghost.style.left = `${t.clientX}px`; ghost.style.top = `${t.clientY}px`; };
    el.addEventListener("touchstart", (e) => {
      if (e.touches.length !== 1) return;
      const t = e.touches[0];
      origin = { x: t.clientX, y: t.clientY };
      timer = setTimeout(() => {
        timer = null;
        pubUi.touching = true;
        pubUi.dragKey = el.dataset.post;
        el.classList.add("dragging");
        ghost = el.cloneNode(true);
        ghost.classList.add("post-ghost");
        document.body.appendChild(ghost);
        place(t);
        if (navigator.vibrate) navigator.vibrate(15);
      }, PUB_HOLD_MS);
    }, { passive: true });
    el.addEventListener("touchmove", (e) => {
      const t = e.touches[0];
      if (timer) { if (Math.hypot(t.clientX - origin.x, t.clientY - origin.y) > PUB_SLOP_PX) { clearTimeout(timer); timer = null; } return; }
      if (!ghost) return;
      e.preventDefault(); // le doigt deplace le clip, la page ne defile plus
      place(t);
      const hit = document.elementFromPoint(t.clientX, t.clientY);
      const cell = hit ? hit.closest(".cal-c[data-slot-at]") : null;
      over = pubDroppable(cell) ? cell : null;
      pubClearDrop(body);
      if (over) over.classList.add("drop");
    }, { passive: false });
    el.addEventListener("touchend", (e) => {
      if (!ghost) { clearTimeout(timer); timer = null; return; }
      e.preventDefault();
      const target = over, key = pubUi.dragKey;
      stop();
      if (target) pubDropOn(target, key);
    });
    el.addEventListener("touchcancel", stop);
    el.addEventListener("contextmenu", (e) => { if (ghost || pubUi.touching) e.preventDefault(); });
  });
}

function pubWire(body) {
  const sel = $("#pub-channel", body);
  if (sel) sel.onchange = () => { pubUi.channel = sel.value; pubUi.week = ""; pubUi.data = null; pubUi.error = null; pubUi.html = ""; renderCurrent(); };
  $$("[data-week]", body).forEach((b) => (b.onclick = () => {
    const step = Number(b.dataset.week);
    pubUi.week = step === 0 ? "" : pubShift(pubUi.data.week_start, 7 * step);
    pubUi.data = null; pubUi.html = "";
    renderCurrent();
  }));
  $$("[data-post]", body).forEach((el) => {
    const open = () => pubOpenDetail(el.dataset.post);
    el.onclick = open;
    el.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } };
  });
  pubWireMouse(body);
  pubWireTouch(body);
  if (pubUi.landed) {
    const landed = $(`.cal-c [data-post="${pubUi.landed}"]`, body);
    if (landed) landed.classList.add("landed");
    pubUi.landed = null;
  }
}

Screens.publish = {
  render(body, store) {
    const channels = store.channels;
    if (channels === null) {
      body.innerHTML = `<div class="skeleton skeleton-line"></div><div class="skeleton skeleton-card"></div>`;
      return;
    }
    if (!channels.length) {
      pubUi.html = "";
      body.innerHTML = emptyState("send", "Rien à publier", "Crée une chaîne, par exemple « ma_chaine » : ses clips approuvés apparaîtront ici avec leurs créneaux.");
      return;
    }
    if (pubUi.dragKey) return; // pas de rendu pendant un glisser-deposer
    if (!channels.includes(pubUi.channel)) { pubUi.channel = channels[0]; pubUi.week = ""; pubUi.data = null; pubUi.html = ""; }
    if (pubUi.key !== pubWantedKey() || Date.now() - pubUi.at > PUB_STALE_MS) pubLoad();
    if (pubView(body, channels)) pubWire(body, channels);
  },
};
