/* Ecran « Chaînes » (SPEC-c100 E5, SPEC-74e9 §1). Liste des chaînes (nom,
   source, surveillance, mode, prochains créneaux) et formulaire d'un preset par
   sections. Le serveur fournit pour chaque section le preset brut (ce qui est
   redéfini), les valeurs effectives et les CONFIG_DEFAULTS commentés : un champ
   non redéfini affiche sa valeur héritée, grisée, avec « redéfinir ». Aucune
   logique de validation ici : les erreurs du serveur (422) reviennent au champ.
   Charge après screens.js dont il remplace l'entrée Screens.channels. */
"use strict";

// Sections du formulaire ; « only » restreint une section aux clés qui
// correspondent (le reste va dans « Autres réglages », replié).
const CHAN_SECTIONS = [
  { section: "channel", title: "Chaîne", sub: "Source, surveillance, mode et créneaux", open: true },
  { section: "reframe", title: "Agencement", sub: "Format du clip, webcam, jeu, zoom" },
  { section: "render", title: "Titre, appel à l'abonnement et badge", sub: "Titre d'écran, carte de fin, badge de chaîne", only: /^(title_|hook_|cta_|badge_|part_|emoji_)/ },
  { section: "subtitles", title: "Sous-titres", sub: "Police, couleurs, position" },
  { section: "moments", title: "Grille de notation et moments", sub: "Sélection des moments, grille et jury" },
];
const CHAN_DAYS = [["mon", "Lundi"], ["tue", "Mardi"], ["wed", "Mercredi"], ["thu", "Jeudi"], ["fri", "Vendredi"], ["sat", "Samedi"], ["sun", "Dimanche"]];
const CHAN_MODES = [["review", "review (tu valides les moments)"], ["auto", "auto (le jury décide)"]];
// Grilles de notation embarquées (SPEC-9216 R4) : valeur de [moments] rubric_path -> libellé.
// Toute autre valeur est un chemin de fichier (« Fichier personnalisé »).
const CHAN_RUBRICS = [["builtin", "Standard"], ["builtin:gaming", "Gaming"]];
const CHAN_RUBRIC_CUSTOM = "custom";
// Modèles proposés à la création d'une chaîne. « Standard » n'écrit rien de plus que [channel] ;
// « Stream gaming » écrit la grille gaming et l'agencement stream (webcam en haut, jeu en bas).
const CHAN_MODELS = [
  { id: "standard", label: "Standard", help: "Réglages par défaut de config.toml.", preset: {} },
  { id: "stream", label: "Stream gaming", help: "Grille de notation gaming et agencement stream (webcam en haut, jeu en bas).",
    preset: { moments: { rubric_path: "builtin:gaming" }, reframe: { layout: "stream_auto", stream_variant: "split" } } },
];
const CHAN_STALE_MS = 4000;
const CHAN_SLOTS_SHOWN = 3;

// Comptes du carnet (écran Comptes) proposés pour relier un compte TikTok à la chaîne ;
// list = null quand GET /api/accounts est refusé (console ouverte à distance) : le message
// d'erreur est alors affiché, jamais un champ libre de repli.
const chAccounts = { list: null, error: "" };
const chUi = { names: null, details: {}, slots: {}, errors: {}, at: 0, loading: null, edit: null, html: "" };

const chHash = () => decodeURIComponent((location.hash.replace(/^#\/?/, "").split("/")[1] || "").split("?")[0]);
const chSame = (a, b) => JSON.stringify(a) === JSON.stringify(b);

/* ---------- Liste ---------- */

function chLoadList() {
  if (chUi.loading) return chUi.loading;
  chUi.loading = (async () => {
    try {
      chUi.names = await api("/api/channels");
      store.channels = chUi.names;
      await Promise.all(chUi.names.map(async (name) => {
        try {
          chUi.details[name] = await api(`/api/channels/${encodeURIComponent(name)}`);
          chUi.slots[name] = await api(`/api/channels/${encodeURIComponent(name)}/slots`);
          delete chUi.errors[name];
        } catch (err) {
          chUi.errors[name] = err;
        }
      }));
    } catch (err) {
      chUi.names = chUi.names || [];
      toastError("Chaînes indisponibles", err);
    } finally {
      chUi.loading = null;
      chUi.at = Date.now();
    }
    if (currentScreen === "channels" && !chHash()) renderCurrent();
  })();
  return chUi.loading;
}

function chSlotLabel(iso, tz) {
  return new Date(iso).toLocaleString("fr-FR", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: tz });
}

function chCard(name) {
  const err = chUi.errors[name];
  const detail = chUi.details[name];
  const head = `<div class="ch-avatar">${esc(name.charAt(0).toUpperCase())}</div>`;
  if (!err && !detail) {
    return `<article class="panel ch-card chan-card" data-chan="${esc(name)}">${head}<div class="ch-body">
      <div><div class="ch-name">${esc(name)}</div></div><div class="skeleton skeleton-line"></div><div class="skeleton skeleton-line"></div></div></article>`;
  }
  if (err || !detail) {
    return `<article class="panel ch-card chan-card" data-chan="${esc(name)}">${head}<div class="ch-body">
      <div><div class="ch-name">${esc(name)}</div></div>
      <p class="reason bad">Preset illisible : ${esc(err.message)}</p>
      <div class="ch-foot"><a class="btn btn-sm grow" href="#/channels/${encodeURIComponent(name)}">${icon("sliders-horizontal")}Ouvrir</a></div></div></article>`;
  }
  const c = detail.effective.channel;
  const info = chUi.slots[name];
  const slots = info ? info.slots : [];
  const shown = slots.slice(0, CHAN_SLOTS_SHOWN).map((s) => `<span class="mono">${esc(chSlotLabel(s, info.timezone))}</span>`).join(" ");
  const more = slots.length > CHAN_SLOTS_SHOWN ? `<span class="faint" title="${esc(slots.map((s) => chSlotLabel(s, info.timezone)).join(" · "))}">+${slots.length - CHAN_SLOTS_SHOWN}</span>` : "";
  const watch = c.watch
    ? `<span class="chip running plain">surveillée</span><span class="muted">toutes les ${esc(fr(Math.round(c.watch_interval_s / 60)))} min · VOD ≥ ${esc(fr(Math.round(c.watch_min_duration_s / 60)))} min</span>`
    : `<span class="chip pending plain">coupée</span>`;
  return `<article class="panel ch-card chan-card" data-chan="${esc(name)}">${head}
    <div class="ch-body">
      <div><div class="ch-name">${esc(c.display_name)}</div><div class="ch-handle mono">${esc(name)}</div></div>
      <dl class="ch-props">
        <dt>Source</dt><dd>${c.source_url ? `<span class="mono chan-url">${esc(c.source_url)}</span>` : `<span class="faint">aucune source (ajout de vidéos à la main)</span>`}</dd>
        <dt>Surveillance</dt><dd>${watch}</dd>
        <dt>Mode</dt><dd><span class="chip ${c.mode === "auto" ? "running" : "info"} plain">${esc(c.mode)}</span></dd>
        <dt>Prochains créneaux</dt><dd>${slots.length ? shown + more : `<span class="faint">${esc(info && info.reason ? info.reason : "créneaux indisponibles")}</span>`}</dd>
      </dl>
      <div class="ch-foot"><a class="btn btn-sm grow" href="#/channels/${encodeURIComponent(name)}">${icon("sliders-horizontal")}Éditer le preset</a></div>
    </div></article>`;
}

function chListHtml() {
  const names = chUi.names || [];
  const add = `<button type="button" class="btn btn-primary" data-chan-new>${icon("plus")}Nouvelle chaîne</button>`;
  if (!names.length) {
    return emptyState("tv", "Aucune chaîne", "Crée une chaîne, par exemple « ma_chaine », pour lui donner son agencement et ses créneaux.", add);
  }
  return `<div class="toolbar"><span class="muted">${names.length} chaîne${names.length > 1 ? "s" : ""}</span><span class="grow"></span>${add}</div>
    <div class="channels">${names.map(chCard).join("")}</div>`;
}

function chOpenNew() {
  openPanel("modal", `
    <div class="modal-head"><h2>Nouvelle chaîne</h2><p class="muted" style="margin-top:4px">Le nom est celui du fichier presets/&lt;nom&gt;.toml : minuscules, chiffres, _ ou -, jamais renommé ensuite.</p></div>
    <form id="chan-new-form"><div class="modal-body">
      <div class="field"><label for="chan-new-name">Nom</label><input class="input mono" id="chan-new-name" name="name" required maxlength="40" placeholder="ma_chaine" autocomplete="off"><span class="field-error" id="chan-new-error" role="alert"></span></div>
      <div class="field"><label for="chan-new-url">Adresse de la chaîne (YouTube ou Twitch, facultatif)</label><input class="input" id="chan-new-url" name="source_url" type="url" placeholder="https://…" autocomplete="off"></div>
      <fieldset class="field chan-models"><legend>Modèle</legend>
        ${CHAN_MODELS.map((m, i) => `<label class="chan-model"><input type="radio" name="model" value="${m.id}"${i === 0 ? " checked" : ""}><span><b>${esc(m.label)}</b><span class="hint">${esc(m.help)}</span></span></label>`).join("")}
      </fieldset>
    </div>
    <div class="modal-foot"><button type="button" class="btn btn-ghost" data-dismiss>Annuler</button><button type="submit" class="btn btn-primary">Créer la chaîne</button></div></form>`,
  (el) => {
    setTimeout(() => $("#chan-new-name", el).focus(), 60);
    $("#chan-new-form", el).onsubmit = async (e) => {
      e.preventDefault();
      const name = $("#chan-new-name", el).value.trim();
      const url = $("#chan-new-url", el).value.trim();
      const model = CHAN_MODELS.find((m) => m.id === $('input[name="model"]:checked', el).value);
      const preset = { channel: url ? { source_url: url } : {}, ...JSON.parse(JSON.stringify(model.preset)) };
      try {
        await api("/api/channels", jsonBody("POST", { name, preset }));
      } catch (err) {
        $("#chan-new-error", el).textContent = err.message;
        return;
      }
      closeLayer();
      toast({ kind: "ok", title: "Chaîne créée", body: name });
      chUi.at = 0;
      chUi.edit = null;
      location.hash = `#/channels/${encodeURIComponent(name)}`;
    };
  });
}

/* ---------- Formulaire d'un preset ---------- */

function chKind(key, section, def) {
  if (section === "channel" && key === "slots") return "slots";
  if (section === "channel" && key === "mode") return "mode";
  if (section === "channel" && key === "tiktok_account") return "account";
  if (section === "moments" && key === "rubric_path") return "rubric";
  if (typeof def === "boolean") return "bool";
  if (typeof def === "number") return "number";
  if (typeof def === "string") return "text";
  return "json";
}

function chSlotsEditor(value, dis) {
  const rows = (value || []).map((s, i) => `<div class="chan-slot" data-slot="${i}">
    <select class="input" data-slot-day aria-label="Jour"${dis}>${CHAN_DAYS.map(([k, l]) => `<option value="${k}"${k === s.day ? " selected" : ""}>${l}</option>`).join("")}</select>
    <input class="input mono" type="time" data-slot-time aria-label="Heure" value="${esc(s.time)}"${dis}>
    <button type="button" class="icon-btn" data-slot-del="${i}" aria-label="Retirer ce créneau"${dis}>${icon("x", "i-xs")}</button></div>`).join("");
  return `<div class="chan-slots">${rows || `<span class="muted">Aucun créneau.</span>`}
    <button type="button" class="btn btn-xs" data-slot-add${dis}>${icon("plus", "i-xs")}Ajouter un créneau</button></div>`;
}

/* Libellé provisoire de la grille pour une valeur de rubric_path ; le serveur (/api/rubric-label)
   donne le vrai : un fichier au contenu identique à la grille standard ou gaming n'est pas « personnalisé ». */
function chRubricLabel(value) {
  const known = CHAN_RUBRICS.find(([k]) => k === value);
  return known ? `${known[1]} (${value})` : `Fichier personnalisé (${value})`;
}

let chRubricTimer = null;
/* Relit le libellé auprès du serveur et le pose sur le champ si la valeur n'a pas changé entre-temps. */
function chRubricRefresh(field, value) {
  clearTimeout(chRubricTimer);
  chRubricTimer = setTimeout(async () => {
    try {
      const info = await api(`/api/rubric-label?path=${encodeURIComponent(value)}`);
      const now = $("[data-rubric-now]", field);
      if (!now || !field.isConnected || (chRubricValue(field) !== value)) return;
      now.textContent = `Grille en vigueur : ${info.label}`;
      const custom = $(`[data-rubric-select] option[value="${CHAN_RUBRIC_CUSTOM}"]`, field);
      if (custom) custom.textContent = info.kind === "standard" || info.kind === "gaming" ? info.label : "Fichier personnalisé";
    } catch (err) {
      const now = $("[data-rubric-now]", field);
      if (now) now.textContent = `Grille en vigueur : ${chRubricLabel(value)} (libellé indisponible : ${err.message})`;
    }
  }, 250);
}

function chRubricValue(field) {
  const choice = $("[data-rubric-select]", field).value;
  return choice === CHAN_RUBRIC_CUSTOM ? $("[data-rubric-path]", field).value.trim() : choice;
}

function chRubricEditor(id, value, dis, info) {
  const known = CHAN_RUBRICS.some(([k]) => k === value);
  const shown = info && info.value === value ? info : null;
  const customLabel = shown && (shown.kind === "standard" || shown.kind === "gaming") ? shown.label : "Fichier personnalisé";
  const options = [...CHAN_RUBRICS, [CHAN_RUBRIC_CUSTOM, customLabel]]
    .map(([k, l]) => `<option value="${k}"${(known ? k === value : k === CHAN_RUBRIC_CUSTOM) ? " selected" : ""}>${esc(l)}</option>`).join("");
  return `<div class="chan-rubric">
    <select class="input" id="${id}" data-rubric-select aria-label="Grille de notation"${dis}>${options}</select>
    <input class="input mono" type="text" data-rubric-path aria-label="Chemin du fichier de grille" placeholder="ma_grille.toml" value="${known ? "" : esc(value)}" autocomplete="off"${known ? " hidden" : ""}${dis}>
    <span class="hint" data-rubric-now>Grille en vigueur : ${esc(shown ? shown.label : chRubricLabel(value))}</span></div>`;
}

function chAccountEditor(id, value, dis) {
  if (chAccounts.list === null) {
    return `<select class="input" id="${id}" aria-label="Compte TikTok relié" disabled><option value="${esc(value)}" selected>${esc(value || "Aucun compte")}</option></select>
      <span class="hint">Comptes indisponibles : ${esc(chAccounts.error || "chargement impossible")}</span>`;
  }
  const known = chAccounts.list.some((a) => a.id === value);
  const options = [`<option value=""${value ? "" : " selected"}>Aucun compte</option>`]
    .concat(chAccounts.list.map((a) => `<option value="${esc(a.id)}"${a.id === value ? " selected" : ""}>${esc(a.label)}${a.platform ? ` (${esc(a.platform)})` : ""}</option>`))
    .concat(value && !known ? [`<option value="${esc(value)}" selected>${esc(value)} (compte inconnu)</option>`] : []);
  return `<select class="input" id="${id}" aria-label="Compte TikTok relié"${dis}>${options.join("")}</select>
    <span class="hint">Compte TikTok relié à la chaîne, créé dans l'écran Comptes ; « Se connecter dans le navigateur » s'y trouve aussi.</span>`;
}

function chControl(id, kind, value, locked) {
  const dis = locked ? " disabled" : "";
  switch (kind) {
    case "slots": return chSlotsEditor(value, dis);
    case "rubric": return chRubricEditor(id, value, dis);
    case "account": return chAccountEditor(id, value, dis);
function chControl(id, kind, value, locked, rubric) {
  const dis = locked ? " disabled" : "";
  switch (kind) {
    case "slots": return chSlotsEditor(value, dis);
    case "rubric": return chRubricEditor(id, value, dis, rubric);
    case "mode": return `<select class="input" id="${id}"${dis}>${CHAN_MODES.map(([k, l]) => `<option value="${k}"${k === value ? " selected" : ""}>${esc(l)}</option>`).join("")}</select>`;
    case "bool": return `<label class="switch"><input type="checkbox" id="${id}"${value ? " checked" : ""}${dis}><span></span></label>`;
    case "number": return `<input class="input mono" id="${id}" type="number" step="any" value="${esc(value)}"${dis}>`;
    case "text": return `<input class="input" id="${id}" type="text" value="${esc(value)}" autocomplete="off"${dis}>`;
    default: return `<textarea class="input mono chan-json" id="${id}" rows="2" spellcheck="false"${dis}>${esc(JSON.stringify(value))}</textarea>`;
  }
}

function chField(section, key, info, ed) {
  const raw = ed.draft[section] || {};
  const redefined = key in raw;
  const kind = chKind(key, section, info.default);
  const value = redefined ? raw[key] : ed.detail.effective[section][key];
  const id = `chan-${section}-${key}`;
  const origin = chSame(ed.detail.effective[section][key], info.default) ? "valeur par défaut" : (section === "channel" ? "valeur déduite" : "hérité de config.toml");
  const state = redefined
    ? `<button type="button" class="btn btn-xs btn-ghost" data-reset>Rétablir l'héritage</button>`
    : `<span class="chan-origin">${esc(origin)}</span><button type="button" class="btn btn-xs" data-redefine>redéfinir</button>`;
  const logo = section === "channel" && key === "logo"
    ? `<div class="chan-logo"><input type="file" accept="image/png" data-logo-file aria-label="Fichier PNG du logo"><button type="button" class="btn btn-xs" data-logo-send>${icon("upload", "i-xs")}Envoyer le logo</button></div>` : "";
  return `<div class="field chan-field ${redefined ? "redefined" : "inherited"}" data-section="${esc(section)}" data-key="${esc(key)}" data-kind="${kind}">
    <div class="chan-head"><label for="${id}"${kind === "rubric" ? "" : ` class="mono"`}>${esc(kind === "rubric" ? "Grille de notation" : key)}</label><span class="grow"></span>${state}</div>
    ${chControl(id, kind, value, !redefined, ed.detail.rubric)}${logo}
    ${info.comment ? `<span class="hint">${esc(info.comment)}</span>` : ""}${info.details ? `<details class="chan-help"><summary>détails</summary><p class="hint">${esc(info.details)}</p></details>` : ""}
    <span class="field-error" role="alert"></span></div>`;
}

function chSectionHtml(spec, ed) {
  const docs = ed.detail.defaults[spec.section];
  const keys = Object.keys(docs);
  // La grille de notation est tout en haut de la section Chaîne : pas répétée dans « moments ».
  const main = (spec.only ? keys.filter((k) => spec.only.test(k)) : keys).filter((k) => k !== "rubric_path");
  const rest = spec.only ? keys.filter((k) => !spec.only.test(k)) : [];
  const redefinedCount = Object.keys(ed.draft[spec.section] || {}).length;
  const open = spec.open || ed.open.has(spec.section) ? " open" : "";
  return `<details class="panel chan-sec" data-sec="${esc(spec.section)}"${open}>
    <summary><div><h3>${esc(spec.title)}</h3><span class="muted">${esc(spec.sub)}</span></div><span class="mono muted">[${esc(spec.section)}]</span>
      <span class="chip ${redefinedCount ? "info" : "pending"} plain" data-count>${redefinedCount ? `${redefinedCount} redéfini${redefinedCount > 1 ? "s" : ""}` : "hérité"}</span></summary>
    <p class="field-error chan-sec-error" data-sec-error role="alert"></p>
    ${spec.section === "subtitles" ? chSubsPreviewHtml(ed) : ""}
    <div class="chan-fields">${spec.section === "channel" ? chField("moments", "rubric_path", ed.detail.defaults.moments.rubric_path, ed) : ""}${main.map((k) => chField(spec.section, k, docs[k], ed)).join("")}</div>
    ${rest.length ? `<details class="chan-more" data-more="${esc(spec.section)}"><summary>Autres réglages de [${esc(spec.section)}] (${rest.length})</summary><div class="chan-fields">${rest.map((k) => chField(spec.section, k, docs[k], ed)).join("")}</div></details>` : ""}
  </details>`;
}

function chEditHtml(ed) {
  const c = ed.detail.effective.channel;
  return `<div class="chan-edit">
    <div class="toolbar"><a class="btn btn-sm btn-ghost" href="#/channels">${icon("chevron-left", "i-xs")}Toutes les chaînes</a>
      <h2 class="chan-title">${esc(c.display_name)} <span class="mono muted">${esc(ed.name)}</span></h2><span class="grow"></span>
      <a class="btn btn-sm" href="#/channels/${encodeURIComponent(ed.name)}/layout">${icon("layers", "i-xs")}Éditeur d'agencement</a>
      <button type="button" class="btn btn-sm btn-bad" data-chan-delete>${icon("trash-2", "i-xs")}Supprimer</button>
      <button type="button" class="btn btn-primary" data-chan-save>Enregistrer</button></div>
    <p class="reason bad" data-form-error role="alert" hidden></p>
    <p class="muted chan-intro">Un champ grisé n'est pas redéfini : il prend la valeur de config.toml (ou le défaut du module). « redéfinir » le copie dans ce preset pour le modifier.</p>
    <div class="chan-sections">${CHAN_SECTIONS.map((s) => chSectionHtml(s, ed)).join("")}</div></div>`;
}

/* Preset à envoyer : le brut du serveur, sections du formulaire remplacées par le brouillon. */
function chPreset(ed) {
  const preset = JSON.parse(JSON.stringify(ed.detail.raw));
  CHAN_SECTIONS.forEach(({ section }) => {
    const table = ed.draft[section] || {};
    if (Object.keys(table).length || section === "channel") preset[section] = table; else delete preset[section];
  });
  return preset;
}

function chReadField(field) {
  const kind = field.dataset.kind;
  if (kind === "slots") {
    return $$(".chan-slot", field).map((row) => ({ day: $("[data-slot-day]", row).value, time: $("[data-slot-time]", row).value }));
  }
  if (kind === "rubric") {
    const choice = $("[data-rubric-select]", field).value;
    const pathEl = $("[data-rubric-path]", field);
    pathEl.hidden = choice !== CHAN_RUBRIC_CUSTOM;
    if (choice !== CHAN_RUBRIC_CUSTOM) return choice;
    const path = pathEl.value.trim();
    if (!path) throw new Error("indique le chemin du fichier de grille");
    return path;
  }
  const el = $("input, select, textarea", field);
  if (kind === "bool") return el.checked;
  if (kind === "number") {
    const text = el.value.trim();
    return text !== "" && Number.isFinite(Number(text)) ? Number(text) : text;
  }
  if (kind === "json") {
    try { return JSON.parse(el.value); } catch (err) { throw new Error(`JSON invalide (${err.message})`); }
  }
  return el.value;
}

function chClearErrors(root) {
  $$(".field-error", root).forEach((e) => { e.textContent = ""; });
  $$(".chan-field.invalid", root).forEach((f) => f.classList.remove("invalid"));
  const top = $("[data-form-error]", root);
  if (top) top.hidden = true;
}

/* Place une erreur du serveur (« … [section] … cle … ») sur le champ visé ;
   à défaut sur la section, puis en tête de formulaire : jamais perdue. */
function chShowError(root, ed, message) {
  chClearErrors(root);
  const sec = (message.match(/\[(\w+)\]/) || [])[1];
  const docs = sec && ed.detail.defaults[sec];
  const key = docs ? Object.keys(docs).filter((k) => new RegExp(`(^|[^\\w])${k}($|[^\\w])`).test(message)).sort((a, b) => b.length - a.length)[0] : null;
  const field = key ? $(`.chan-field[data-section="${sec}"][data-key="${key}"]`, root) : null;
  if (field) {
    const det = field.closest("details.chan-sec");
    det.open = true;
    const more = field.closest("details.chan-more");
    if (more) more.open = true;
    field.classList.add("invalid");
    $(".field-error", field).textContent = message;
    field.scrollIntoView({ block: "center", behavior: "smooth" });
    return;
  }
  const det = sec ? $(`details.chan-sec[data-sec="${sec}"]`, root) : null;
  if (det) {
    det.open = true;
    $("[data-sec-error]", det).textContent = message;
    return;
  }
  const top = $("[data-form-error]", root);
  top.textContent = message;
  top.hidden = false;
}

function chRepaintField(root, ed, section, key) {
  const old = $(`.chan-field[data-section="${section}"][data-key="${key}"]`, root);
  const tpl = document.createElement("div");
  tpl.innerHTML = chField(section, key, ed.detail.defaults[section][key], ed);
  old.replaceWith(tpl.firstElementChild);
  const det = $(`details.chan-sec[data-sec="${section}"]`, root);
  const n = Object.keys(ed.draft[section] || {}).length;
  const chip = $("[data-count]", det);
  chip.textContent = n ? `${n} redéfini${n > 1 ? "s" : ""}` : "hérité";
  chip.className = `chip ${n ? "info" : "pending"} plain`;
  if (section === "subtitles" || section === "reframe") chSubsPreview(root, ed);
}

async function chSave(root, ed) {
  const button = $("[data-chan-save]", root);
  button.disabled = true;
  try {
    ed.detail = await api(`/api/channels/${encodeURIComponent(ed.name)}`, jsonBody("PUT", { preset: chPreset(ed) }));
    ed.draft = chDraft(ed.detail.raw);
    chUi.details[ed.name] = ed.detail;
    chUi.at = 0;
    chClearErrors(root);
    toast({ kind: "ok", title: "Chaîne enregistrée", body: ed.name });
    CHAN_SECTIONS.forEach(({ section }) => $$(`.chan-field[data-section="${section}"]`, root).forEach((f) => chRepaintField(root, ed, section, f.dataset.key)));
  } catch (err) {
    chShowError(root, ed, err.message);
    toast({ kind: "bad", title: "Enregistrement refusé", body: "Corrige le champ signalé.", ms: 5200 });
  } finally {
    button.disabled = false;
  }
}

async function chDelete(ed) {
  if (!(await confirmDialog({ title: "Supprimer la chaîne ?", body: `Le preset ${ed.name} sera effacé. Les vidéos déjà traitées restent, mais ne seront plus rattachées à cette chaîne.`, confirmLabel: "Supprimer la chaîne" }))) return;
  try {
    await api(`/api/channels/${encodeURIComponent(ed.name)}?confirm=true`, { method: "DELETE" });
  } catch (err) {
    toastError("Suppression impossible", err);
    return;
  }
  toast({ kind: "ok", title: "Chaîne supprimée", body: ed.name });
  delete chUi.details[ed.name];
  delete chUi.slots[ed.name];
  chUi.at = 0;
  chUi.edit = null;
  location.hash = "#/channels";
}

async function chSendLogo(root, ed, field) {
  const file = $("[data-logo-file]", field).files[0];
  if (!file) { toast({ kind: "warn", title: "Aucun fichier", body: "Choisis d'abord une image PNG.", ms: 3200 }); return; }
  const form = new FormData();
  form.append("file", file);
  try {
    const sent = await api(`/api/channels/${encodeURIComponent(ed.name)}/logo`, { method: "POST", body: form });
    (ed.draft.channel = ed.draft.channel || {}).logo = sent.logo;
    chRepaintField(root, ed, "channel", "logo");
    toast({ kind: "ok", title: "Logo envoyé", body: `${sent.logo} : enregistre la chaîne pour l'appliquer.` });
  } catch (err) {
    toastError("Envoi du logo impossible", err);
  }
}

function chWireEdit(root, ed) {
  root.onclick = (e) => {
    const t = e.target.closest("button");
    if (!t) return;
    const field = t.closest(".chan-field");
    if (t.hasAttribute("data-chan-save")) chSave(root, ed);
    else if (t.hasAttribute("data-chan-delete")) chDelete(ed);
    else if (field && t.hasAttribute("data-redefine")) {
      const { section, key } = field.dataset;
      (ed.draft[section] = ed.draft[section] || {})[key] = JSON.parse(JSON.stringify(ed.detail.effective[section][key]));
      chRepaintField(root, ed, section, key);
    } else if (field && t.hasAttribute("data-reset")) {
      const { section, key } = field.dataset;
      delete ed.draft[section][key];
      chRepaintField(root, ed, section, key);
    } else if (field && t.hasAttribute("data-slot-add")) {
      const { section, key } = field.dataset;
      ed.draft[section][key] = [...ed.draft[section][key], { day: "mon", time: "18:00" }];
      chRepaintField(root, ed, section, key);
    } else if (field && t.hasAttribute("data-slot-del")) {
      const { section, key } = field.dataset;
      ed.draft[section][key] = ed.draft[section][key].filter((_, i) => i !== Number(t.dataset.slotDel));
      chRepaintField(root, ed, section, key);
    } else if (field && t.hasAttribute("data-logo-send")) chSendLogo(root, ed, field);
  };
  const changed = (e) => {
    const field = e.target.closest(".chan-field");
    if (!field || field.classList.contains("inherited") || e.target.type === "file") return;
    const { section, key } = field.dataset;
    try {
      ed.draft[section][key] = chReadField(field);
      field.classList.remove("invalid");
      $(".field-error", field).textContent = "";
      if (field.dataset.kind === "rubric") {
        $("[data-rubric-now]", field).textContent = `Grille en vigueur : ${chRubricLabel(ed.draft[section][key])}`;
        chRubricRefresh(field, ed.draft[section][key]);
      }
      if (section === "subtitles" || section === "reframe") chSubsPreview(root, ed);
    } catch (err) {
      field.classList.add("invalid");
      $(".field-error", field).textContent = `[${section}] ${key} : ${err.message}`;
    }
  };
  root.oninput = changed;
  root.onchange = changed;
  root.addEventListener("toggle", (e) => {
    const det = e.target.closest && e.target.closest("details.chan-sec");
    if (det && e.target === det) { if (det.open) ed.open.add(det.dataset.sec); else ed.open.delete(det.dataset.sec); }
  }, true);
}

const chDraft = (raw) => {
  const draft = {};
  CHAN_SECTIONS.forEach(({ section }) => { draft[section] = JSON.parse(JSON.stringify(raw[section] || {})); });
  return draft;
};

async function chOpenEdit(body, name) {
  body.innerHTML = `<div class="skeleton skeleton-line"></div><div class="skeleton skeleton-card"></div><div class="skeleton skeleton-card"></div>`;
  const edit = { name, detail: null, draft: null, open: new Set(), pending: true };
  chUi.edit = edit;
  try {
    edit.detail = await api(`/api/channels/${encodeURIComponent(name)}`);
  } catch (err) {
    if (chUi.edit === edit) body.innerHTML = emptyState("circle-alert", "Chaîne illisible", err.message);
    edit.failed = true;
    return;
  }
  try {
    chAccounts.list = await api("/api/accounts");
    chAccounts.error = "";
  } catch (err) {
    chAccounts.list = null;
    chAccounts.error = String(err.message || err);
  }
  edit.pending = false;
  edit.draft = chDraft(edit.detail.raw);
  if (chUi.edit !== edit || currentScreen !== "channels") return;
  body.innerHTML = chEditHtml(edit);
  chWireEdit(body, edit);
  chSubsPreviewWire(body, edit);
}

Screens.channels = {
  render(body) {
    const name = chHash();
    if (name) {
      if (!chUi.edit || chUi.edit.name !== name || chUi.edit.failed) { chUi.html = ""; chOpenEdit(body, name); }
      return;
    }
    chUi.edit = null;
    body.onclick = null; body.oninput = null; body.onchange = null;
    if (chUi.names === null || Date.now() - chUi.at > CHAN_STALE_MS) chLoadList();
    if (chUi.names === null) {
      body.innerHTML = `<div class="skeleton skeleton-line"></div><div class="skeleton skeleton-card"></div>`;
      return;
    }
    const html = chListHtml();
    if (chUi.html !== html || !body.childElementCount) { chUi.html = html; body.innerHTML = html; }
    $$("[data-chan-new]", body).forEach((b) => (b.onclick = chOpenNew));
  },
};
