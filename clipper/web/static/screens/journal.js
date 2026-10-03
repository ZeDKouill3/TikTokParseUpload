/* Écran « Journal » (TASK-8067, menu Configuration). Lecture seule de
   GET /api/journal (dernières lignes du journal global de toutes les
   actions, tous les processus, un fichier par jour) ; rafraîchissement
   manuel seulement, jamais automatique. Aucune logique de traitement ici
   (ADR-09ad) : le filtrage texte/niveau est délégué au serveur à chaque
   rafraîchissement. Charge après screens.js dont il remplace l'entrée
   Screens.journal. */
"use strict";

const JRN_LEVELS = ["", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"];
const JRN_LINES = 300;

const jrnUi = { data: null, loading: null, error: null, q: "", level: "" };

function jrnQuery() {
  const params = new URLSearchParams({ lines: String(JRN_LINES) });
  if (jrnUi.q) params.set("q", jrnUi.q);
  if (jrnUi.level) params.set("level", jrnUi.level);
  return params.toString();
}

function jrnLoad() {
  if (jrnUi.loading) return jrnUi.loading;
  jrnUi.loading = (async () => {
    try {
      jrnUi.data = await api(`/api/journal?${jrnQuery()}`);
      jrnUi.error = null;
    } catch (err) {
      jrnUi.error = err;
      jrnUi.data = jrnUi.data || { failed: true };
    } finally {
      jrnUi.loading = null;
    }
    if (currentScreen === "journal") renderCurrent();
  })();
  return jrnUi.loading;
}

const JRN_LEVEL_CHIP = { ERROR: "bad", CRITICAL: "bad", WARNING: "warn" };

function jrnRow(line) {
  const level = line.level || "";
  return `<tr>
    <td class="mono">${esc(line.timestamp || "")}</td>
    <td class="mono">${esc(line.process || "")}</td>
    <td><span class="chip ${esc(JRN_LEVEL_CHIP[level] || "plain")}">${esc(level)}</span></td>
    <td class="mono">${esc(line.logger || "")}</td>
    <td>${esc(line.message || line.raw || "")}</td>
  </tr>`;
}

function jrnHtml() {
  const data = jrnUi.data;
  if (!data) return `<div class="skeleton skeleton-line"></div><div class="skeleton skeleton-card"></div>`;
  if (data.failed) return emptyState("circle-alert", "Journal indisponible", jrnUi.error ? jrnUi.error.message : "");
  const toolbar = `<div class="panel-head">
      <input class="input mono" id="jrn-q" placeholder="Filtrer le texte..." value="${esc(jrnUi.q)}">
      <select class="input" id="jrn-level" aria-label="Niveau">${JRN_LEVELS.map((l) => `<option value="${esc(l)}"${l === jrnUi.level ? " selected" : ""}>${l ? esc(l) : "Tous les niveaux"}</option>`).join("")}</select>
      <button type="button" class="btn btn-sm" id="jrn-refresh">${icon("refresh-cw", "i-xs")}Rafraîchir</button>
    </div>`;
  if (!data.available) {
    return toolbar + emptyState("activity", "Aucune action journalisée", data.reason || "");
  }
  const rows = data.lines.slice().reverse(); // plus récent en haut
  if (!rows.length) {
    return toolbar + `<div class="list-item muted">Aucune ligne ne correspond au filtre.</div>`;
  }
  return `${toolbar}<table class="table"><thead><tr>
      <th>Horodatage (Paris)</th><th>Processus</th><th>Niveau</th><th>Logger</th><th>Message</th>
    </tr></thead><tbody>${rows.map(jrnRow).join("")}</tbody></table>
    <p class="muted">${esc(data.path || "")}</p>`;
}

function jrnWire(root) {
  root.onclick = (e) => {
    if (e.target.closest("#jrn-refresh")) {
      jrnUi.q = $("#jrn-q", root).value.trim();
      jrnUi.level = $("#jrn-level", root).value;
      jrnLoad();
    }
  };
  root.onkeydown = (e) => {
    if (e.key === "Enter" && e.target.id === "jrn-q") $("#jrn-refresh", root).click();
  };
}

Screens.journal = {
  render(body) {
    if (jrnUi.data === null) jrnLoad();
    if (body.resetHtmlGuard) body.resetHtmlGuard(); // les champs de filtre ne doivent jamais etre ecrases par un rendu identique
    body.innerHTML = jrnHtml();
    jrnWire(body);
  },
};
