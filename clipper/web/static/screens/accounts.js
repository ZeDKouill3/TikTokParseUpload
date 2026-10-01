/* Ecran « Comptes » (SPEC-6fa4 R6). Pense-bete local des comptes (TikTok, YouTube,
   e-mail...) : la liste vient de GET /api/accounts et ne porte JAMAIS de mot de
   passe (has_password seulement). Un mot de passe n'est demandé à
   GET /api/accounts/<id>/password qu'au clic (Copier ou Afficher) ; il n'est ni
   mémorisé dans le navigateur (aucun stockage local), ni gardé après son
   masquage (30 s). Le générateur est côté serveur (POST /api/accounts/generate).
   Aucune logique de coffre ici : les erreurs du serveur (403, 422, 503) sont
   affichées telles quelles. Charge après screens.js dont il complète Screens. */
"use strict";

const ACC_REVEAL_MS = 30 * 1000; // un mot de passe affiché est masqué à nouveau après 30 s
const ACC_COPIED_MS = 1500;
const ACC_LOCAL_HOSTS = ["127.0.0.1", "localhost"];
const ACC_PLATFORMS = ["TikTok", "YouTube", "Twitch", "E-mail"];

// revealed : id -> { value, timer } ; gen : état du générateur autonome.
const accUi = { list: null, error: null, loading: null, revealed: {}, gen: { length: "", symbols: false, ambiguous: false, value: "" } };

const accIsRemote = () => !ACC_LOCAL_HOSTS.includes(location.hostname);

/* ---------- Données ---------- */

function accLoad() {
  if (accUi.loading) return accUi.loading;
  accUi.loading = (async () => {
    try {
      accUi.list = await api("/api/accounts");
      accUi.error = null;
    } catch (err) {
      accUi.error = err;
    } finally {
      accUi.loading = null;
    }
    if (currentScreen === "accounts") renderCurrent();
  })();
  return accUi.loading;
}

function accHide(id) {
  const shown = accUi.revealed[id];
  if (shown) clearTimeout(shown.timer);
  delete accUi.revealed[id];
}

function accHideAll() {
  Object.keys(accUi.revealed).forEach(accHide);
  accUi.gen.value = "";
}

window.addEventListener("hashchange", () => {
  if (!/^#\/?accounts/.test(location.hash)) accHideAll(); // plus aucun secret en mémoire hors de l'écran
});

/* ---------- Presse-papiers ---------- */

async function accCopy(text, button) {
  if (!navigator.clipboard) {
    toastError("Copie impossible", new Error("le presse-papiers n'est disponible que sur 127.0.0.1 ou localhost"));
    return;
  }
  try {
    await navigator.clipboard.writeText(text);
  } catch (err) {
    toastError("Copie impossible", err);
    return;
  }
  if (!button) return;
  const label = button.innerHTML;
  button.innerHTML = `${icon("check", "i-xs")}Copié`;
  button.classList.add("acc-copied");
  setTimeout(() => { button.innerHTML = label; button.classList.remove("acc-copied"); }, ACC_COPIED_MS);
}

async function accFetchPassword(id) {
  return (await api(`/api/accounts/${encodeURIComponent(id)}/password`)).password;
}

/* ---------- Générateur (côté serveur) ---------- */

function accGenOptions(root) {
  const raw = $("[data-gen-length]", root).value.trim();
  const body = { symbols: $("[data-gen-symbols]", root).checked, avoid_ambiguous: $("[data-gen-ambiguous]", root).checked };
  if (raw !== "") body.length = Number(raw);
  return body;
}

async function accGenerate(root) {
  try {
    return (await api("/api/accounts/generate", jsonBody("POST", accGenOptions(root)))).password;
  } catch (err) {
    toastError("Génération impossible", err);
    return null;
  }
}

function accGenControls(state) {
  return `<div class="acc-gen-opts">
    <div class="field acc-gen-length"><label>Longueur<input class="input" data-gen-length type="number" min="12" max="64" step="1" placeholder="défaut" value="${esc(state.length)}"></label></div>
    <label class="acc-check"><input type="checkbox" data-gen-symbols${state.symbols ? " checked" : ""}> Symboles</label>
    <label class="acc-check"><input type="checkbox" data-gen-ambiguous${state.ambiguous ? " checked" : ""}> Sans caractères ambigus</label>
  </div>`;
}

function accGenPanel() {
  const g = accUi.gen;
  return `<section class="panel acc-gen">
    <div class="panel-head"><h2>Générateur de mot de passe</h2></div>
    <div class="acc-gen-body">${accGenControls(g)}
      <div class="acc-gen-out">
        <input class="input mono" data-gen-out type="text" readonly value="${esc(g.value)}" placeholder="12 à 64 caractères" aria-label="Mot de passe généré" autocomplete="off">
        <button type="button" class="btn" data-gen-make>${icon("refresh-cw")}Générer</button>
        <button type="button" class="btn" data-gen-copy${g.value ? "" : " disabled"}>${icon("copy")}Copier</button>
      </div></div></section>`;
}

function accWireGenPanel(body) {
  const root = $(".acc-gen", body);
  const sync = () => {
    accUi.gen.length = $("[data-gen-length]", root).value;
    accUi.gen.symbols = $("[data-gen-symbols]", root).checked;
    accUi.gen.ambiguous = $("[data-gen-ambiguous]", root).checked;
  };
  $$("input", root).forEach((el) => el.addEventListener("change", sync));
  $("[data-gen-make]", root).onclick = async () => {
    sync();
    const value = await accGenerate(root);
    if (value === null) return;
    accUi.gen.value = value;
    $("[data-gen-out]", root).value = value;
    $("[data-gen-copy]", root).disabled = false;
  };
  $("[data-gen-copy]", root).onclick = (e) => accCopy(accUi.gen.value, e.currentTarget);
}

/* ---------- Liste ---------- */

function accRow(a) {
  const shown = accUi.revealed[a.id];
  const pass = !a.has_password
    ? `<span class="faint">aucun</span>`
    : shown ? `<code class="mono acc-pass">${esc(shown.value)}</code>` : `<span class="mono acc-pass" aria-label="Mot de passe masqué">••••</span>`;
  const copyPass = a.has_password
    ? `<button type="button" class="btn btn-xs" data-acc-copy-pass="${esc(a.id)}">${icon("lock", "i-xs")}Copier le mot de passe</button>
       <button type="button" class="btn btn-xs" data-acc-show="${esc(a.id)}">${icon(shown ? "eye-off" : "eye", "i-xs")}${shown ? "Masquer" : "Afficher"}</button>`
    : "";
  return `<div class="list-item acc-row" data-acc="${esc(a.id)}">
    <div class="acc-main">
      <div class="li-title">${a.platform ? `<span class="tag">${esc(a.platform)}</span> ` : ""}${esc(a.label)}</div>
      <div class="li-sub muted mono">${a.username ? esc(a.username) : "—"}</div>
      ${a.notes ? `<div class="li-sub faint">${esc(a.notes)}</div>` : ""}
    </div>
    <div class="acc-pass-cell">${pass}</div>
    <div class="acc-actions">
      ${a.username ? `<button type="button" class="btn btn-xs" data-acc-copy-user="${esc(a.id)}">${icon("copy", "i-xs")}Copier l'identifiant</button>` : ""}
      ${copyPass}
      <button type="button" class="btn btn-xs" data-acc-edit="${esc(a.id)}">${icon("pencil", "i-xs")}Modifier</button>
      <button type="button" class="btn btn-xs btn-bad" data-acc-delete="${esc(a.id)}">${icon("trash-2", "i-xs")}Supprimer</button>
    </div>
  </div>`;
}

function accWireList(body) {
  const find = (id) => accUi.list.find((a) => a.id === id);
  $$("[data-acc-copy-user]", body).forEach((b) => (b.onclick = () => accCopy(find(b.dataset.accCopyUser).username, b)));
  $$("[data-acc-copy-pass]", body).forEach((b) => (b.onclick = async () => {
    try {
      await accCopy(await accFetchPassword(b.dataset.accCopyPass), b);
    } catch (err) { toastError("Mot de passe indisponible", err); }
  }));
  $$("[data-acc-show]", body).forEach((b) => (b.onclick = async () => {
    const id = b.dataset.accShow;
    if (accUi.revealed[id]) { accHide(id); renderCurrent(); return; }
    try {
      const value = await accFetchPassword(id);
      accUi.revealed[id] = { value, timer: setTimeout(() => { accHide(id); if (currentScreen === "accounts") renderCurrent(); }, ACC_REVEAL_MS) };
      renderCurrent();
    } catch (err) { toastError("Mot de passe indisponible", err); }
  }));
  $$("[data-acc-edit]", body).forEach((b) => (b.onclick = () => accOpenForm(find(b.dataset.accEdit))));
  $$("[data-acc-delete]", body).forEach((b) => (b.onclick = async () => {
    const account = find(b.dataset.accDelete);
    const ok = await confirmDialog({
      title: "Supprimer ce compte ?",
      body: `« ${account.label} » sera supprimé${account.has_password ? ", ainsi que son mot de passe dans le coffre de l'OS" : ""}. Cette action est définitive.`,
      confirmLabel: "Supprimer",
    });
    if (!ok) return;
    try {
      await api(`/api/accounts/${encodeURIComponent(account.id)}`, jsonBody("DELETE", {}));
      accHide(account.id);
      toast({ kind: "ok", title: "Compte supprimé", body: account.label });
      await accLoad();
    } catch (err) { toastError("Suppression impossible", err); }
  }));
  $("[data-acc-add]", body).onclick = () => accOpenForm(null);
}

/* ---------- Formulaire Ajouter / Modifier ---------- */

function accOpenForm(account) {
  const editing = Boolean(account);
  const a = account || { label: "", platform: "", username: "", notes: "", has_password: false };
  openPanel("modal acc-modal", `
    <div class="modal-head"><h2>${editing ? "Modifier le compte" : "Ajouter un compte"}</h2>
      <p class="muted" style="margin-top:4px">Le mot de passe est rangé dans le coffre de l'OS, jamais dans un fichier du projet.</p></div>
    <form id="acc-form" autocomplete="off"><div class="modal-body acc-form">
      <div class="field"><label for="acc-label">Libellé</label><input class="input" id="acc-label" name="label" required maxlength="120" value="${esc(a.label)}" placeholder="Compte principal"></div>
      <div class="field"><label for="acc-platform">Plateforme</label><input class="input" id="acc-platform" name="platform" maxlength="60" list="acc-platforms" value="${esc(a.platform)}" placeholder="TikTok">
        <datalist id="acc-platforms">${ACC_PLATFORMS.map((p) => `<option value="${esc(p)}">`).join("")}</datalist></div>
      <div class="field"><label for="acc-username">E-mail ou identifiant</label><input class="input" id="acc-username" name="username" maxlength="254" value="${esc(a.username)}" placeholder="exemple@example.com"></div>
      <div class="field"><label for="acc-password">Mot de passe</label>
        <input class="input mono" id="acc-password" name="password" type="password" maxlength="512" autocomplete="new-password" placeholder="${editing && a.has_password ? "laisser vide pour ne pas le changer" : ""}">
        ${editing && a.has_password ? `<label class="acc-check"><input type="checkbox" id="acc-clear"> Retirer le mot de passe du coffre</label>` : ""}</div>
      <div class="acc-gen-inline">${accGenControls({ length: "", symbols: false, ambiguous: false })}
        <div class="acc-gen-out"><button type="button" class="btn btn-sm" data-gen-fill>${icon("wand-sparkles")}Générer et remplir</button>
          <button type="button" class="btn btn-sm" data-gen-copy-only>${icon("copy")}Générer et copier</button></div></div>
      <div class="field"><label for="acc-notes">Notes</label><textarea class="input" id="acc-notes" name="notes" rows="2" maxlength="2000" placeholder="ma_chaine, usage, rappel...">${esc(a.notes)}</textarea></div>
    </div>
    <div class="modal-foot"><button type="button" class="btn btn-ghost" data-dismiss>Annuler</button><button type="submit" class="btn btn-primary">${editing ? "Enregistrer" : "Ajouter"}</button></div></form>`,
  (el) => {
    setTimeout(() => $("#acc-label", el).focus(), 60);
    const box = $(".acc-gen-inline", el);
    $("[data-gen-fill]", el).onclick = async () => {
      const value = await accGenerate(box);
      if (value === null) return;
      const field = $("#acc-password", el);
      field.type = "text"; // visible pour que le mot de passe généré soit lisible avant l'enregistrement
      field.value = value;
      const clear = $("#acc-clear", el);
      if (clear) clear.checked = false;
    };
    $("[data-gen-copy-only]", el).onclick = async (e) => {
      const value = await accGenerate(box);
      if (value !== null) accCopy(value, e.currentTarget);
    };
    $("#acc-form", el).onsubmit = async (e) => {
      e.preventDefault();
      const payload = { label: $("#acc-label", el).value, platform: $("#acc-platform", el).value, username: $("#acc-username", el).value, notes: $("#acc-notes", el).value };
      const password = $("#acc-password", el).value;
      const clear = $("#acc-clear", el);
      if (password) payload.password = password;
      else if (clear && clear.checked) payload.password = "";
      try {
        await api(editing ? `/api/accounts/${encodeURIComponent(a.id)}` : "/api/accounts", jsonBody(editing ? "PUT" : "POST", payload));
      } catch (err) { toastError(editing ? "Modification impossible" : "Ajout impossible", err); return; }
      closeLayer();
      if (editing) accHide(a.id);
      toast({ kind: "ok", title: editing ? "Compte modifié" : "Compte ajouté", body: payload.label });
      await accLoad();
    };
  });
}

/* ---------- Écran ---------- */

function accNotice() {
  return `<div class="banner" role="status">${icon("triangle-alert")}<p><b>Console ouverte à distance.</b> Les comptes ne sont accessibles que depuis le PC qui héberge la console, via 127.0.0.1 ou localhost : le serveur refuse toute autre adresse.</p></div>`;
}

Screens.accounts = {
  render(body) {
    if (accIsRemote()) {
      body.innerHTML = accNotice();
      return;
    }
    if (accUi.list === null && !accUi.loading) accLoad();
    if (accUi.list === null) {
      body.innerHTML = accUi.error
        ? emptyState("circle-alert", "Comptes indisponibles", String(accUi.error.message || accUi.error))
        : `<div class="skeleton skeleton-line"></div><div class="skeleton skeleton-card"></div>`;
      return;
    }
    const list = accUi.list.length
      ? accUi.list.map(accRow).join("")
      : `<div class="list-item muted">Aucun compte. Ajoute-en un, par exemple « ma_chaine » avec exemple@example.com.</div>`;
    body.innerHTML = `
      <div class="acc-toolbar"><span class="muted">${fr(accUi.list.length)} compte${accUi.list.length > 1 ? "s" : ""} · mots de passe dans le coffre de l'OS</span>
        <button type="button" class="btn btn-primary" data-acc-add>${icon("plus")}Ajouter un compte</button></div>
      ${accUi.error ? `<p class="reason bad">Actualisation impossible : ${esc(accUi.error.message)}</p>` : ""}
      <div class="panel acc-list">${list}</div>
      ${accGenPanel()}`;
    accWireList(body);
    accWireGenPanel(body);
  },
};
