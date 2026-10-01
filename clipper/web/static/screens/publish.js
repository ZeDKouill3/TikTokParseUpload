/* Ecran « Publication » (SPEC-c100 E6, SPEC-74e9 §4). Lit GET /api/publish?channel=&week= :
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
// Statut TikTok d'une publication (SPEC-9225 R3, R4), calcule par l'API : prime sur le statut de la file.
const PUB_TIKTOK = {
  pending: { label: "En attente", cls: "pending" }, in_progress: { label: "En cours", cls: "info" }, scheduled_on_tiktok: { label: "Programmée sur TikTok", cls: "info" },
  published: { label: "Publiée", cls: "ok" }, failed: { label: "Échec", cls: "bad" },
};
const PUB_STALE_MS = 4000;
const PUB_HOLD_MS = 250;      // appui long avant de saisir un clip au toucher
const PUB_SLOP_PX = 8;        // mouvement tolere pendant l'appui long (sinon : defilement)
const pubEnc = encodeURIComponent;

const pubUi = { channel: "", week: "", key: "", data: null, error: null, loading: null, dirty: false, at: 0, html: "", dragKey: null, touching: false, landed: null };

// Publications pilotees (SPEC-1ed3) : GET /api/publications, independantes de la chaine choisie.
const pubPosts = { data: null, error: null, loading: null, dirty: false, at: 0 };

const pubAccountLabel = (id) => {
  const accounts = [...((pubUi.data && pubUi.data.accounts) || []), ...((pubPosts.data && pubPosts.data.accounts) || [])];
  const found = accounts.find((a) => a.id === id);
  return found ? (found.label || id) : id;
};
const pubKey = (c) => `${c.video_id}/${c.clip_id}`;
const pubStatus = (c) => PUB_STATUS[c.publish_status] || { label: c.publish_status, cls: "pending" };
const pubTitle = (c) => c.screen_title || c.title || c.clip_id;
const pubChip = (c) => { const s = c.waiting_reason ? { label: "En attente du compte", cls: "warn" } : (PUB_TIKTOK[c.tiktok_status] || pubStatus(c)); return `<span class="chip ${s.cls}">${esc(s.label)}</span>`; };
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

function pubPostsLoad() {
  if (pubPosts.loading) { pubPosts.dirty = true; return pubPosts.loading; }
  pubPosts.loading = (async () => {
    try {
      pubPosts.data = await api("/api/publications");
      pubPosts.error = null;
    } catch (err) {
      pubPosts.error = err;
    } finally {
      pubPosts.loading = null;
      pubPosts.at = Date.now();
    }
    if (currentScreen === "publish") renderCurrent();
    if (pubPosts.dirty) { pubPosts.dirty = false; pubPostsLoad(); }
  })();
  return pubPosts.loading;
}

// Un evenement publish / video / queue rend la semaine et la liste obsoletes (le serveur reste la source).
document.addEventListener("clipper:event", () => {
  pubUi.at = 0;
  pubPosts.at = 0;
  if (currentScreen === "publish" && !pubUi.dragKey) {
    if (pubUi.channel) pubLoad();
    pubPostsLoad();
  }
});

/* ---------- Rendu ---------- */

function pubPost(c, extra) {
  const draggable = (c.publish_status === "approved" || c.publish_status === "scheduled" || c.publish_status === "failed") && !c.missing;
  const icoName = c.publish_status === "published" ? "circle-check" : c.publish_status === "failed" ? "circle-alert" : "";
  return `<div class="post ${esc(c.publish_status)}${c.missing ? " missing" : ""}" data-post="${esc(pubKey(c))}" draggable="${draggable}" tabindex="0" role="button" aria-label="Ouvrir le clip ${esc(pubTitle(c))}" title="${esc(pubTitle(c))}">
    <div class="mini-clip">${c.video_url ? `<img loading="lazy" decoding="async" width="36" height="64" src="${esc(c.thumbnail_url)}" alt="" tabindex="-1">` : ""}</div>
    <span class="pt">${esc(c.missing ? `Clip introuvable (${c.clip_id})` : pubTitle(c))}</span>
    ${c.account ? `<span class="pub-acct${c.waiting_reason ? " waiting" : ""}" data-post-account title="${esc(c.waiting_reason || `Compte : ${pubAccountLabel(c.account)}`)}">${esc(pubAccountLabel(c.account))}</span>` : ""}
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
      <div class="mini-clip">${c.video_url ? `<img loading="lazy" decoding="async" width="36" height="64" src="${esc(c.thumbnail_url)}" alt="" tabindex="-1">` : ""}</div>
      <div class="li-main grow"><div class="li-title">${esc(pubTitle(c))}</div>
        <div class="li-sub muted">${c.publish_status === "published" ? "publié" : "échec"}${c.slot_at ? ` · ${esc(pubSlotLabel(c.slot_at))}` : ""}${c.account ? ` · ${esc(pubAccountLabel(c.account))}` : ""}${c.publish_error ? ` · ${esc(c.publish_error)}` : ""}${c.post_url ? ` · <a href="${esc(c.post_url)}" target="_blank" rel="noopener">voir sur TikTok</a>` : ""}</div></div>
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
    <div class="legend"><span><i style="background:var(--info)"></i>planifié / programmé</span><span><i style="background:var(--ok)"></i>publié</span><span><i style="background:var(--bad)"></i>échec</span></div>
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
    content = `<div class="banner">${icon("info", "i-lg")}<p><b>Le worker publie sur TikTok au créneau</b> (compte cible ci-dessus, Chrome visible). Un arrêt (captcha, connexion expirée...) met le clip en échec avec une capture : « Réessayer » le relance. Tu peux aussi publier à la main : télécharge, copie la description, puis « Marquer publié ».</p></div>
      <div class="grid g-side pub-grid" style="align-items:start"><div class="stack">${pubQueue(d)}</div>
      <div class="stack"><section>${d.slots.length ? pubCalendar(d) : `<p class="reason">${esc(d.reason || "Aucun créneau cette semaine.")}</p>`}</section>${pubDone(d)}</div></div>`;
  }
  const html = `<div class="pub-pad">${pubPostsSection()}${pubToolbar(channels, d)}${content}</div>`;
  if (pubUi.html === html && body.childElementCount) return false; // rien de change : on garde les vignettes et le survol
  pubUi.html = html;
  body.innerHTML = html;
  return true;
}


/* ---------- Publications pilotees : liste, statuts, modifier / annuler (SPEC-1ed3 R5) ---------- */

const pubWhen = (iso) => new Date(iso).toLocaleString("fr-FR", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const pubPostChip = (p) => {
  const s = p.waiting_reason ? { label: "En attente du compte", cls: "warn" } : (PUB_TIKTOK[p.tiktok_status] || { label: p.publish_status, cls: "pending" });
  return `<span class="chip ${s.cls}">${esc(s.label)}</span>`;
};

function pubPostRow(p) {
  const mode = p.publish_mode === "scheduled" ? "programmée" : "maintenant";
  const when = p.tiktok_publish_at ? `en ligne le ${pubWhen(p.tiktok_publish_at)}` : (p.slot_at ? `${mode} · ${pubWhen(p.slot_at)}` : "");
  const detail = [when, p.account ? pubAccountLabel(p.account) : "", p.channel || "sans chaîne"].filter(Boolean).join(" · ");
  return `<div class="list-item pub-post-row" data-pub-row="${esc(pubKey(p))}">
    <div class="mini-clip">${p.thumbnail_url ? `<img loading="lazy" decoding="async" width="36" height="64" src="${esc(p.thumbnail_url)}" alt="">` : ""}</div>
    <div class="li-main grow"><div class="li-title">${esc(pubTitle(p))}</div>
      <div class="li-sub muted">${esc(detail)}</div>
      ${p.waiting_reason ? `<div class="li-sub warn" data-waiting-reason>${esc(p.waiting_reason)}</div>` : ""}
      ${p.publish_error ? `<div class="li-sub bad">Échec : ${esc(p.publish_error)}</div>` : ""}
      ${p.postponed_reason ? `<div class="li-sub muted">${esc(p.postponed_reason)}</div>` : ""}
      ${p.capture_url ? `<a href="${esc(p.capture_url)}" target="_blank" rel="noopener">voir la capture d'écran</a>` : ""}
      ${p.post_url ? `<a href="${esc(p.post_url)}" target="_blank" rel="noopener">voir sur TikTok</a>` : ""}
      ${p.tiktok_status === "scheduled_on_tiktok" && !p.post_url ? `<span class="muted">programmée sur TikTok${p.post_note ? ` : ${esc(p.post_note)}` : ""}</span>` : ""}</div>
    ${pubPostChip(p)}
    <div class="row" style="gap:6px">
      ${p.publish_status === "failed" ? `<button type="button" class="btn btn-xs btn-primary" data-pub-retry>Réessayer</button>` : ""}
      ${p.editable ? `<button type="button" class="btn btn-xs" data-pub-edit>Modifier</button><button type="button" class="btn btn-xs btn-ghost" data-pub-cancel>Annuler</button>` : ""}
    </div></div>`;
}

function pubPostsSection() {
  const head = `<div class="section-title">${icon("send")}Publications <span class="more">${pubPosts.data ? pubPosts.data.publications.length || "" : ""}</span>
    <span class="grow"></span><button type="button" class="btn btn-primary btn-xs" data-pub-new>${icon("plus", "i-xs")}Nouvelle publication</button></div>`;
  if (pubPosts.error) return `<section>${head}<p class="reason bad">Chargement impossible : ${esc(pubPosts.error.message || pubPosts.error)}</p></section>`;
  if (!pubPosts.data) return `<section>${head}<div class="skeleton skeleton-line"></div></section>`;
  const rows = pubPosts.data.publications;
  return `<section>${head}${rows.length ? `<div class="panel" id="pub-posts">${rows.map(pubPostRow).join("")}</div>`
    : `<p class="muted" style="font-size:13px">Aucune publication : « Nouvelle publication » choisit un clip, le compte, maintenant ou à une date.</p>`}</section>`;
}

async function pubPostCancel(p) {
  const ok = await confirmDialog({ title: "Annuler cette publication ?", body: `« ${pubTitle(p)} » ne sera pas publié ; le clip redevient « à valider ».`, confirmLabel: "Annuler la publication" });
  if (!ok) return;
  try {
    await api(`/api/publications/${pubEnc(p.video_id)}/${pubEnc(p.clip_id)}`, { method: "DELETE" });
    toast({ kind: "warn", title: "Publication annulée", body: pubTitle(p), ms: 2600 });
  } catch (err) { toastError("Impossible d'annuler la publication", err); }
  pubPosts.at = 0;
  pubPostsLoad();
}

/* ---------- Formulaire « Nouvelle publication » (SPEC-1ed3 R1, R2) ---------- */

const PUB_VISIBILITIES = [["public", "Tout le monde"], ["friends", "Ami(e)s"], ["private", "Toi uniquement"]];
const PUB_CHECKS = [["off", "Désactivée (rapide)"], ["wait", "Attendre le résultat (~10 min)"]];
const pubLocalInput = (iso) => { const d = new Date(iso); const p = (n) => String(n).padStart(2, "0"); return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`; };

function pubFormClips(clips) {
  return clips.filter((c) => c.ready && (c.publish_status === "à valider" || c.publish_status === "approved"))
    .sort((a, b) => String(b.created_at || "").localeCompare(String(a.created_at || "")) || pubKey(b).localeCompare(pubKey(a)));
}

function pubFormHtml(f) {
  const videos = Array.from(new Set(f.clips.map((c) => c.video_id)));
  const channels = Array.from(new Set(f.clips.map((c) => c.channel || ""))).sort();
  const ready = f.accounts.filter((a) => a.ready_to_publish);
  const o = f.options;
  const editing = Boolean(f.edit);
  return `
    <div class="modal-head"><h2>${editing ? "Modifier la publication" : "Nouvelle publication"}</h2>
      <p class="muted" style="margin-top:4px">Valider approuve le clip et le met en file : aucun créneau de chaîne n'est nécessaire.</p></div>
    <div class="modal-body stack" style="gap:16px">
      ${editing ? "" : `<div class="field"><span class="field-label">Clip</span>
        <div class="row wrap" style="gap:8px">
          <input class="input" id="pub-form-search" type="search" placeholder="Rechercher (titre, description, identifiant)" aria-label="Rechercher un clip" style="flex:1 1 220px">
          <select class="input" id="pub-form-video" aria-label="Filtrer par vidéo"><option value="">Toutes les vidéos</option>${videos.map((v) => `<option value="${esc(v)}">${esc(v)}</option>`).join("")}</select>
          <select class="input" id="pub-form-channel" aria-label="Filtrer par chaîne"><option value="">Toutes les chaînes</option>${channels.map((ch) => `<option value="${esc(ch)}">${esc(ch || "sans chaîne")}</option>`).join("")}</select></div>
        <div class="pubf-clips" id="pub-form-clips" role="listbox" aria-label="Clips à publier"></div></div>`}
      <div class="field"><label for="pub-form-account">Compte</label>
        <select class="input" id="pub-form-account">${ready.length ? ready.map((a) => `<option value="${esc(a.id)}">${esc(a.label || a.id)}</option>`).join("") : `<option value="">Aucun compte prêt à publier</option>`}</select>
        <span class="hint">Seuls les comptes « prêts à publier » (écran Comptes) sont proposés ; prérempli avec le compte de la chaîne.</span></div>
      <div class="field"><span class="field-label">Quand</span>
        <div class="row wrap" style="gap:16px">
          <label class="row" style="gap:6px"><input type="radio" name="pub-form-when" value="immediate" id="pub-form-now"${f.mode === "immediate" ? " checked" : ""}> Maintenant</label>
          <label class="row" style="gap:6px"><input type="radio" name="pub-form-when" value="scheduled" id="pub-form-later"${f.mode === "scheduled" ? " checked" : ""}> Programmer</label>
          <input class="input" id="pub-form-at" type="datetime-local" aria-label="Date et heure"${f.mode === "scheduled" ? "" : " hidden"} value="${esc(f.at || "")}"></div>
        <span class="hint">Programmer : TikTok programme la vidéo si la date est entre ${esc(f.minMinutes)} min et ${esc(f.maxDays)} jours ; au-delà, Clipper la garde et la programme le moment venu.</span></div>
      <div class="field"><label for="pub-form-caption">Légende</label><textarea class="input" id="pub-form-caption" rows="3">${esc(f.caption)}</textarea></div>
      <div class="field"><label for="pub-form-tags">Hashtags</label><input class="input" id="pub-form-tags" value="${esc(f.tags)}"><span class="hint">Séparés par des espaces.</span></div>
      <div class="field"><label for="pub-form-visibility">Visibilité</label>
        <select class="input" id="pub-form-visibility">${PUB_VISIBILITIES.map(([k, l]) => `<option value="${k}"${o.visibility === k ? " selected" : ""}>${esc(l)}</option>`).join("")}</select>
        <span class="hint">Une vidéo « Toi uniquement » ne peut pas être programmée (règle de TikTok).</span></div>
      <div class="field"><span class="field-label">Autoriser</span>
        <label class="row" style="gap:6px"><input type="checkbox" id="pub-form-comments"${o.allow_comments ? " checked" : ""}> Les commentaires</label>
        <label class="row" style="gap:6px"><input type="checkbox" id="pub-form-reuse"${o.allow_reuse ? " checked" : ""}> La réutilisation du contenu (duo, collage)</label>
        <label class="row" style="gap:6px"><input type="checkbox" id="pub-form-ai"${o.ai_generated ? " checked" : ""}> Contenu généré par IA (étiquette)</label></div>
      <div class="field"><label for="pub-form-check">Vérification de contenu</label>
        <select class="input" id="pub-form-check">${PUB_CHECKS.map(([k, l]) => `<option value="${k}"${o.content_check === k ? " selected" : ""}>${esc(l)}</option>`).join("")}</select></div>
      <p class="reason bad" id="pub-form-error" hidden role="alert"></p>
    </div>
    <div class="modal-foot"><button type="button" class="btn btn-ghost" data-dismiss>Fermer</button><span class="grow"></span>
      <button type="button" class="btn btn-primary" id="pub-form-submit">${editing ? "Enregistrer" : "Valider et publier"}</button></div>`;
}

function pubFormClipCards(f, d) {
  const q = ($("#pub-form-search", d).value || "").trim().toLowerCase();
  const video = $("#pub-form-video", d).value, channel = $("#pub-form-channel", d).value;
  const list = f.clips.filter((c) => (!video || c.video_id === video) && (channel === "" ? true : (c.channel || "") === channel)
    && (!q || [c.screen_title, c.description, c.clip_id, c.video_id].some((t) => String(t || "").toLowerCase().includes(q))));
  const box = $("#pub-form-clips", d);
  box.innerHTML = list.length ? list.map((c) => `<button type="button" class="pubf-clip${pubKey(c) === f.selected ? " on" : ""}" role="option" aria-selected="${pubKey(c) === f.selected}" data-pubf-clip="${esc(pubKey(c))}">
      <span class="mini-clip">${c.thumbnail_url ? `<img loading="lazy" decoding="async" width="36" height="64" src="${esc(c.thumbnail_url)}" alt="">` : ""}</span>
      <span class="pubf-clip-main"><b>${esc(pubTitle(c))}</b><span class="muted">${esc(c.video_id)} · ${c.channel ? esc(c.channel) : "sans chaîne"}</span></span>
      <span class="num" title="Score">${c.score != null ? esc(fr(c.score)) : ""}</span></button>`).join("")
    : `<p class="muted" style="padding:8px">Aucun clip à valider ou approuvé ne correspond.</p>`;
  $$("[data-pubf-clip]", box).forEach((b) => (b.onclick = () => pubFormSelect(f, d, b.dataset.pubfClip)));
}

async function pubFormSelect(f, d, key) {
  f.selected = key;
  const c = f.clips.find((x) => pubKey(x) === key);
  if (!c) return;
  $("#pub-form-caption", d).value = c.description || "";
  $("#pub-form-tags", d).value = (c.hashtags || []).join(" ");
  pubFormClipCards(f, d);
  try {
    const out = await api(`/api/publish/accounts?channel=${pubEnc(c.channel || "")}`);
    const pick = $("#pub-form-account", d);
    const known = f.accounts.find((a) => a.id === out.default && a.ready_to_publish);
    if (known) pick.value = known.id;
  } catch (err) { /* pas de compte par defaut : le choix reste a l'utilisateur */ }
}

function pubFormBody(f, d) {
  const now = $("#pub-form-now", d).checked;
  const body = {
    account: $("#pub-form-account", d).value, mode: now ? "immediate" : "scheduled",
    description: $("#pub-form-caption", d).value, hashtags: parseHashtags($("#pub-form-tags", d).value),
    options: {
      visibility: $("#pub-form-visibility", d).value, allow_comments: $("#pub-form-comments", d).checked,
      allow_reuse: $("#pub-form-reuse", d).checked, ai_generated: $("#pub-form-ai", d).checked,
      content_check: $("#pub-form-check", d).value,
    },
  };
  if (!now) {
    const at = $("#pub-form-at", d).value;
    body.publish_at = at ? new Date(at).toISOString() : null;
  }
  return body;
}

async function pubFormSubmit(f, d) {
  const err = $("#pub-form-error", d);
  err.hidden = true;
  const body = pubFormBody(f, d);
  if (!body.account) { err.textContent = "Choisis un compte prêt à publier (écran Comptes)."; err.hidden = false; return; }
  if (!f.edit && !f.selected) { err.textContent = "Choisis un clip."; err.hidden = false; return; }
  const [video_id, clip_id] = f.edit ? [f.edit.video_id, f.edit.clip_id] : f.selected.split("/");
  try {
    if (f.edit) await api(`/api/publications/${pubEnc(video_id)}/${pubEnc(clip_id)}`, jsonBody("PATCH", body));
    else await api("/api/publications", jsonBody("POST", Object.assign({ video_id, clip_id }, body)));
  } catch (e) {
    err.textContent = e.message || String(e);
    if (e.body && e.body.next_at) { // plafond depasse : la raison est dite, la prochaine heure possible se prend en un clic
      const next = e.body.next_at;
      err.innerHTML = `${esc(e.message)} <button type="button" class="btn btn-xs" id="pub-form-use-next">Programmer à ${esc(pubWhen(next))}</button>`;
      $("#pub-form-use-next", err).onclick = () => { $("#pub-form-later", d).checked = true; $("#pub-form-at", d).hidden = false; $("#pub-form-at", d).value = pubLocalInput(next); err.hidden = true; };
    }
    err.hidden = false;
    return;
  }
  closeLayer();
  toast({ kind: "ok", title: f.edit ? "Publication modifiée" : (body.mode === "immediate" ? "Publication en file : le worker la publie dès qu'il est libre" : "Publication programmée"), body: f.edit ? pubTitle(f.edit) : "", ms: 3200 });
  pubPosts.at = 0;
  pubPostsLoad();
  if (typeof loadClips === "function") loadClips();
}

/* ouvre le formulaire ; `preset` { video_id, clip_id } prerempli depuis l'ecran Clips ; `edit` : une publication a modifier */
async function pubOpenForm(preset, edit) {
  let clips, data;
  try {
    [clips, data] = await Promise.all([api("/api/clips"), api("/api/publications")]);
  } catch (err) { toastError("Impossible d'ouvrir le formulaire", err); return null; }
  const base = edit || (preset && clips.find((c) => c.video_id === preset.video_id && c.clip_id === preset.clip_id)) || null;
  const f = {
    clips: pubFormClips(clips), accounts: data.accounts, edit: edit || null, selected: base && !edit ? pubKey(base) : "",
    options: Object.assign({}, data.defaults.options, edit ? edit.post_options : {}),
    mode: edit && edit.publish_mode === "scheduled" ? "scheduled" : "immediate",
    at: edit && edit.publish_mode === "scheduled" && edit.slot_at ? pubLocalInput(edit.slot_at) : "",
    caption: base ? (base.description || "") : "", tags: base ? (base.hashtags || []).join(" ") : "",
    minMinutes: data.defaults.schedule_min_minutes, maxDays: data.defaults.schedule_max_days,
  };
  if (preset && !edit && base && !f.clips.some((c) => pubKey(c) === pubKey(base))) {
    toastError("Ce clip ne peut pas être publié", new Error("Il n'est ni à valider ni approuvé (refusé, déjà publié ou déjà en file)."));
    return null;
  }
  return openPanel("modal pub-modal pub-form", pubFormHtml(f), (d) => {
    if (!edit) {
      ["#pub-form-search"].forEach((s) => ($(s, d).oninput = () => pubFormClipCards(f, d)));
      ["#pub-form-video", "#pub-form-channel"].forEach((s) => ($(s, d).onchange = () => pubFormClipCards(f, d)));
      pubFormClipCards(f, d);
      if (f.selected) pubFormSelect(f, d, f.selected);
    }
    if (edit && edit.account) $("#pub-form-account", d).value = edit.account;
    $$("input[name='pub-form-when']", d).forEach((r) => (r.onchange = () => { $("#pub-form-at", d).hidden = !$("#pub-form-later", d).checked; }));
    $("#pub-form-submit", d).onclick = () => pubFormSubmit(f, d);
  });
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

async function pubRetry(c) {
  try {
    await api(`/api/publish/${pubEnc(c.video_id)}/${pubEnc(c.clip_id)}/retry`, { method: "POST" });
    if (pubUi.channel) await pubLoad();
    toast({ kind: "info", title: "Publication relancée", body: pubTitle(c), ms: 2600 });
    return true;
  } catch (err) {
    toastError("Impossible de réessayer la publication", err);
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

function pubAccountField(c) {
  const accounts = (pubUi.data && pubUi.data.accounts) || [];
  const locked = c.publish_status === "published" || c.missing;
  const options = accounts.filter((a) => a.ready_to_publish || a.id === c.account)
    .map((a) => `<option value="${esc(a.id)}"${a.id === c.account ? " selected" : ""}${a.ready_to_publish ? "" : " disabled"}>${esc(a.label || a.id)}${a.ready_to_publish ? "" : " (non prêt à publier)"}</option>`);
  if (!c.account) options.unshift(`<option value="" selected>Aucun compte</option>`);
  return `<div class="field"><label for="pub-account">Compte de publication</label>
    <select class="input" id="pub-account" data-pub-account${locked ? " disabled" : ""}>${options.join("")}</select>
    <span class="hint">Seuls les comptes « prêts à publier » (écran Comptes) peuvent être choisis.</span></div>`;
}

async function pubSetAccount(c, account) {
  try {
    await api(`/api/publish/${pubEnc(c.video_id)}/${pubEnc(c.clip_id)}/account`, jsonBody("POST", { account }));
    await pubLoad();
    toast({ kind: "ok", title: "Compte de publication changé", body: `${pubTitle(c)} : ${pubAccountLabel(account)}`, ms: 2600 });
  } catch (err) {
    toastError("Impossible de changer le compte", err);
    pubUi.at = 0;
    pubLoad();
  }
}

function pubDetailHtml(c) {
  const account = c.account || (pubUi.data && pubUi.data.tiktok_account);
  const status = c.publish_status;
  const hint = status === "approved" ? "Glisse ce clip sur un créneau libre du calendrier pour le planifier."
    : status === "failed" ? "La publication s'est arrêtée : regarde la capture, règle le problème dans le navigateur du compte, puis « Réessayer » (ou repasse le clip en attente pour le replanifier)." : "";
  return `
    <div class="modal-head"><div class="row wrap" style="gap:8px">${pubChip(c)}<h2>${esc(pubTitle(c))}</h2></div>
      <p class="muted" style="margin-top:4px">${c.slot_at ? esc(pubSlotLabel(c.slot_at)) : "Sans créneau"}${account ? ` · ${esc(pubAccountLabel(account))}` : ""}</p></div>
    <div class="modal-body stack" style="gap:16px">
      ${c.publish_error ? `<p class="reason bad">Publication en échec : ${esc(c.publish_error)}</p>` : ""}
      ${c.waiting_reason ? `<p class="reason warn" data-waiting-reason>En attente, non tentée : ${esc(c.waiting_reason)}</p>` : ""}
      ${pubAccountField(c)}
      ${c.capture_url ? `<a href="${esc(c.capture_url)}" target="_blank" rel="noopener" title="Capture d'écran de l'arrêt"><img class="pub-capture" loading="lazy" src="${esc(c.capture_url)}" alt="Capture d'écran de l'arrêt" style="max-width:100%;border-radius:8px"></a>` : ""}
      ${c.post_url ? `<p>Publiée : <a href="${esc(c.post_url)}" target="_blank" rel="noopener">${esc(c.post_url)}</a></p>` : ""}
      ${c.post_note ? `<p class="muted">${esc(c.post_note)}</p>` : ""}
      ${c.postponed_reason ? `<p class="muted">Reportée : ${esc(c.postponed_reason)}</p>` : ""}
      ${hint ? `<p class="muted">${esc(hint)}</p>` : ""}
      <div class="field"><span class="field-label">Description</span><div class="pub-caption">${esc(c.description || "")}</div></div>
      <div class="hashtags">${(c.hashtags || []).map((t) => `<span class="tag">${esc(t)}</span>`).join("")}</div>
    </div>
    <div class="modal-foot">
      <a class="btn btn-ghost" href="${esc(c.video_url)}" download="${esc(c.clip_id)}.mp4">${icon("download")}Télécharger</a>
      <button type="button" class="btn btn-ghost" data-copy>${icon("copy")}Copier la description</button>
      <span class="grow"></span>
      ${status === "failed" ? `<button type="button" class="btn btn-primary" data-retry>${icon("rotate-ccw")}Réessayer</button>` : ""}
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
    const acc = $("[data-pub-account]", d);
    if (acc) acc.onchange = async () => { if (acc.value && acc.value !== c.account) { closeLayer(); await pubSetAccount(c, acc.value); } };
    const retry = $("[data-retry]", d);
    if (retry) retry.onclick = async () => { closeLayer(); await pubRetry(c); };
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
  const fresh = $("[data-pub-new]", body);
  if (fresh) fresh.onclick = () => pubOpenForm(null);
  $$("[data-pub-row]", body).forEach((row) => {
    const p = pubPosts.data.publications.find((x) => pubKey(x) === row.dataset.pubRow);
    if (!p) return;
    const edit = $("[data-pub-edit]", row), cancel = $("[data-pub-cancel]", row), retry = $("[data-pub-retry]", row);
    if (edit) edit.onclick = () => pubOpenForm(null, p);
    if (cancel) cancel.onclick = () => pubPostCancel(p);
    if (retry) retry.onclick = async () => { await pubRetry(p); pubPosts.at = 0; pubPostsLoad(); };
  });
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
    if (!pubPosts.data && !pubPosts.loading) pubPostsLoad();
    else if (Date.now() - pubPosts.at > PUB_STALE_MS) pubPostsLoad();
    if (!channels.length) {
      const html = `<div class="pub-pad">${pubPostsSection()}${emptyState("send", "Aucun créneau de chaîne", "Les créneaux de chaîne sont facultatifs (mode auto) : « Nouvelle publication » publie sans chaîne, avec un compte.")}</div>`;
      if (pubUi.html === html && body.childElementCount) return;
      pubUi.html = html;
      body.innerHTML = html;
      pubWire(body, channels);
      return;
    }
    if (pubUi.dragKey) return; // pas de rendu pendant un glisser-deposer
    if (!channels.includes(pubUi.channel)) { pubUi.channel = channels[0]; pubUi.week = ""; pubUi.data = null; pubUi.html = ""; }
    if (pubUi.key !== pubWantedKey() || Date.now() - pubUi.at > PUB_STALE_MS) pubLoad();
    if (pubView(body, channels)) pubWire(body, channels);
  },
};
