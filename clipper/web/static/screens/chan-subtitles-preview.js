/* Aperçu du style des sous-titres de l'écran « Styles » (SPEC-c100 E5, SPEC-76dc).
   Le PNG est rendu par le pipeline (GET /api/channels/{nom}/subtitles-preview) :
   aucun rendu de texte ici. Chaque changement d'un champ de style est envoyé
   tel quel (brouillon non enregistré) après PREVIEW_DELAY_MS sans nouvelle
   frappe ; une erreur 422 du serveur s'affiche sous l'aperçu.
   Charge après channels.js, dont chSectionHtml / chWireEdit appellent ces fonctions. */
"use strict";

const PREVIEW_DELAY_MS = 300;
const CHAN_PREVIEW_TEXT = "Salut tout le monde, bienvenue sur mon live";

function chSubsPreviewHtml() {
  return `<div class="chan-preview" data-subs-preview>
    <div class="chan-preview-frame"><img alt="Aperçu du style des sous-titres" hidden><span class="chan-preview-wait muted">Aperçu en cours…</span></div>
    <div class="chan-preview-side">
      <label class="field"><span class="mono">phrase d'exemple</span>
        <input class="input" type="text" data-subs-text value="${esc(CHAN_PREVIEW_TEXT)}" autocomplete="off"></label>
      <p class="field-error chan-preview-error" data-subs-error role="alert"></p>
      <span class="hint">Aperçu rendu par le pipeline avec les réglages de ce formulaire, enregistrés ou non.</span>
    </div></div>`;
}

/* Tables du brouillon qui décident du style : [subtitles] et [reframe] (variante stream_variant). */
function chSubsDraft(ed) {
  return { subtitles: ed.draft.subtitles || {}, reframe: ed.draft.reframe || {} };
}

async function chSubsPreviewFetch(root, ed) {
  const box = $("[data-subs-preview]", root);
  if (!box) return;
  const img = $("img", box), wait = $(".chan-preview-wait", box), error = $("[data-subs-error]", box);
  const ticket = (ed.previewTicket = (ed.previewTicket || 0) + 1);
  const query = new URLSearchParams({ text: $("[data-subs-text]", box).value, draft: JSON.stringify(chSubsDraft(ed)) });
  try {
    const resp = await fetch(`/api/channels/${encodeURIComponent(ed.name)}/subtitles-preview?${query}`, { credentials: "same-origin" });
    if (ticket !== ed.previewTicket) return;   // une réponse plus récente est déjà en route
    if (!resp.ok) {
      let detail = resp.statusText;
      try { detail = (await resp.json()).detail || detail; } catch (err) { /* corps non JSON : statusText */ }
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    const url = URL.createObjectURL(await resp.blob());
    if (ticket !== ed.previewTicket) { URL.revokeObjectURL(url); return; }
    if (img.src.startsWith("blob:")) URL.revokeObjectURL(img.src);
    img.src = url;
    img.hidden = false;
    wait.hidden = true;
    error.textContent = "";
    box.classList.remove("invalid");
  } catch (err) {
    if (ticket !== ed.previewTicket) return;
    wait.hidden = true;
    error.textContent = err.message;
    box.classList.add("invalid");
  }
}

/* À appeler à chaque changement d'un champ de style : un seul rendu, 300 ms après le dernier. */
function chSubsPreview(root, ed) {
  clearTimeout(ed.previewTimer);
  ed.previewTimer = setTimeout(() => chSubsPreviewFetch(root, ed), PREVIEW_DELAY_MS);
}

function chSubsPreviewWire(root, ed) {
  const text = $("[data-subs-text]", root);
  if (text) text.addEventListener("input", () => chSubsPreview(root, ed));
  chSubsPreview(root, ed);
}
