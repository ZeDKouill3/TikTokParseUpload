/* Surveillance des VOD (TASK-7508, SPEC-fc0c §5.3) : lignes « VOD à confirmer »
   du tableau de bord, avec Confirmer (mise en file) et Ignorer. */

function watchVodRow(vod) {
  const minutes = vod.duration_s != null ? ` · ${fr(Math.round(vod.duration_s / 60))} min` : "";
  return `<div class="list-item watch-vod" data-vod="${esc(vod.video_id)}" data-channel="${esc(vod.channel)}">
    <div class="li-main"><div class="li-title">${esc(vod.title || vod.video_id)}</div>
      <div class="li-sub">${esc(vod.channel)}${minutes} · repérée le ${esc(dashDate(vod.found_at))}</div></div>
    <div class="watch-actions">
      <a class="btn btn-xs btn-ghost" href="${esc(vod.url)}" target="_blank" rel="noopener">Voir la VOD</a>
      <button type="button" class="btn btn-xs btn-ghost" data-vod-ignore>Ignorer</button>
      <button type="button" class="btn btn-xs btn-primary" data-vod-confirm>Confirmer</button>
    </div>
  </div>`;
}


async function watchRefresh() {
  dash.at = 0;
  await loadDashboard();
}

/* Branche les boutons des lignes rendues sous ``root``. */
function wireWatch(root) {
  $$("[data-vod-confirm]", root).forEach((b) => (b.onclick = async () => {
    const row = b.closest("[data-vod]");
    b.disabled = true;
    try {
      await api(`/api/watch/${encodeURIComponent(row.dataset.channel)}/${encodeURIComponent(row.dataset.vod)}/confirm`, { method: "POST" });
      toast({ kind: "ok", title: "VOD mise en file", body: row.dataset.vod });
      await watchRefresh();
    } catch (err) {
      b.disabled = false;
      toastError("Impossible de confirmer la VOD", err);
    }
  }));
  $$("[data-vod-ignore]", root).forEach((b) => (b.onclick = async () => {
    const row = b.closest("[data-vod]");
    if (!(await confirmDialog({ title: "Ignorer cette VOD ?", body: `${row.dataset.vod} ne sera pas traitée et ne sera plus proposée.`, confirmLabel: "Ignorer" }))) return;
    try {
      await api(`/api/watch/${encodeURIComponent(row.dataset.channel)}/${encodeURIComponent(row.dataset.vod)}/ignore`, { method: "POST" });
      await watchRefresh();
    } catch (err) { toastError("Impossible d'ignorer la VOD", err); }
  }));
}
