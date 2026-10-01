/* Routeur, chrome (nav, topbar), temps reel simule (SSE), palette, ajout de video. */
"use strict";

const NAV = [
  { group: "Production" },
  { id: "tableau", label: "Tableau de bord", icon: "layout-dashboard", href: "#/tableau" },
  { id: "videos", label: "Vidéos", icon: "film", href: "#/videos", count: () => VIDEOS.filter((v) => v.status === "running" || v.status === "pending").length },
  { id: "revue", label: "Revue", icon: "sparkles", href: "#/revue", count: () => MOMENTS.filter((m) => !m.decision).length + 5, hot: true },
  { id: "clips", label: "Clips", icon: "clapperboard", href: "#/clips", count: () => CLIPS.filter((c) => c.status === "review").length, hot: true },
  { id: "publication", label: "Publication", icon: "send", href: "#/publication" },
  { group: "Configuration" },
  { id: "chaines", label: "Chaînes", icon: "tv", href: "#/chaines" },
  { id: "stats", label: "Statistiques", icon: "chart-column", href: "#/stats" },
  { id: "reglages", label: "Réglages", icon: "settings", href: "#/reglages" },
];
const TABS = ["tableau", "videos", "revue", "clips", "publication"];

const App = {
  elapsed: 0,
  _ticks: [],
  _keys: [],
  _viewRoot: null,
  onTick(root, fn) { this._ticks.push({ root, fn }); },
  onKey(root, fn) { this._keys.push({ root, fn }); },

  setTheme(t, save) {
    document.documentElement.dataset.theme = t;
    if (save !== false) try { localStorage.setItem("clipper-maquette-theme", t); } catch (e) { /* stockage indisponible */ }
    $("#btn-theme").innerHTML = icon(t === "light" ? "moon" : "sun");
    $('meta[name="theme-color"]').content = t === "light" ? "#f4f2ec" : "#0e0e0c";
  },
  toggleTheme() {
    const next = document.documentElement.dataset.theme === "light" ? "dark" : "light";
    const run = () => this.setTheme(next);
    if (document.startViewTransition && !matchMedia("(prefers-reduced-motion: reduce)").matches) {
      const vt = document.startViewTransition(run);
      vt.ready.catch(() => {}); vt.finished.catch(() => {});
    } else run();
  },

  renderNav(active) {
    $("#nav").innerHTML = NAV.map((n) => {
      if (n.group) return `<div class="nav-group">${n.group}</div>`;
      const c = n.count ? n.count() : 0;
      return `<a href="${n.href}" class="${n.id === active ? "active" : ""}" ${n.id === active ? 'aria-current="page"' : ""}>${icon(n.icon)}<span>${n.label}</span>${c ? `<span class="count ${n.hot ? "hot" : ""}">${c}</span>` : ""}</a>`;
    }).join("");
    $("#tabbar").innerHTML = TABS.map((id) => {
      const n = NAV.find((x) => x.id === id);
      const c = n.count && n.hot ? n.count() : 0;
      return `<a href="${n.href}" class="${id === active ? "active" : ""}">${icon(n.icon)}<span>${n.id === "tableau" ? "Accueil" : n.label}</span>${c ? `<span class="count">${c}</span>` : ""}</a>`;
    }).join("");
  },
  refreshCounts() { this.renderNav(this._active); },

  renderMachine() {
    const m = MACHINE;
    $("#machine-mini").innerHTML = `
      <div class="machine-title">${icon("cpu", "i-xs")}Machine<span class="grow"></span><span class="chip ok plain" style="height:18px;font-size:11px">cuda</span></div>
      <div class="machine-row"><span class="lbl">VRAM</span><span class="gauge hot"><i style="width:${(m.vram[0] / m.vram[1]) * 100}%"></i></span><span class="val">${fr(m.vram[0], 1)} Go</span></div>
      <div class="machine-row"><span class="lbl">CPU</span><span class="gauge"><i style="width:${m.cpu}%"></i></span><span class="val">${m.cpu} %</span></div>
      <div class="machine-row"><span class="lbl">RAM</span><span class="gauge"><i style="width:${(m.ram[0] / m.ram[1]) * 100}%"></i></span><span class="val">${fr(m.ram[0], 1)} Go</span></div>
      <div class="machine-model">${icon("server", "i-xs")}<span>${m.model}</span></div>`;
  },

  parse() {
    const raw = location.hash.replace(/^#\/?/, "") || "tableau";
    const [path, qs] = raw.split("?");
    const parts = path.split("/");
    const params = {};
    (qs || "").split("&").filter(Boolean).forEach((kv) => { const [k, v] = kv.split("="); params[k] = decodeURIComponent(v || ""); });
    return { parts, params };
  },

  route() {
    const { parts, params } = this.parse();
    let view, active = parts[0];
    switch (parts[0]) {
      case "videos": view = parts[1] ? Views.video({ id: parts[1] }) : Views.videos(params); break;
      case "revue": view = parts[1] ? Views.review({ id: parts[1] }) : Views.reviewIndex(); break;
      case "clips": view = Views.clips(params); break;
      case "publication": view = Views.publication(); break;
      case "chaines": view = parts[1] ? Views.channel({ id: parts[1], tab: params.tab }) : Views.channels(); break;
      case "stats": view = Views.stats(); break;
      case "reglages": view = Views.settings(); break;
      default: view = Views.dashboard(); active = "tableau";
    }
    // Meme vue, meme page (ex. onglet de preset qui reecrit l'URL) : ne rien refaire.
    const key = location.hash.split("?")[0];
    if (this._lastKey === key && parts[0] === "chaines" && parts[1]) return;
    this._lastKey = key;
    this._active = active;
    const seq = (this._seq = (this._seq || 0) + 1);
    const swap = () => {
      if (seq !== this._seq) return; // rappel d'une transition annulee : ecran perime
      this._ticks = []; this._keys = [];
      // « Annuler » d'un toast vise l'ecran qui l'a cree : on le retire quand on en sort.
      $$("#toasts .toast[data-seq]").forEach((t) => { if (+t.dataset.seq !== seq) { const u = t.querySelector("[data-undo]"); if (u) u.remove(); } });
      if (closeCurrent) closeLayer();
      const el = $("#view");
      el.classList.remove("leaving");
      el.innerHTML = view.html;
      this.renderNav(active);
      $("#crumbs").innerHTML = `<a href="#/tableau">Clipper</a>` + view.crumbs.map((c, i) => `<span class="sep">/</span>${c[1] ? `<a href="${c[1]}">${esc(c[0])}</a>` : `<span class="cur">${esc(c[0])}</span>`}`).join("");
      document.title = `${view.crumbs[view.crumbs.length - 1][0]} · Clipper`;
      window.scrollTo(0, 0);
      view.mount && view.mount(el);
      countUp(el);
      $("#app .sidebar").classList.remove("open");
      // Etats ouvrables par URL (captures) : ?add=<url>, ?palette=1, ?notifs=1
      if (params.add != null) setTimeout(() => openAddVideo(params.add), 50);
      if (params.palette) setTimeout(openPalette, 50);
      if (params.notifs) setTimeout(toggleNotifs, 50);
    };
    const first = !this._booted;
    this._booted = true;
    const calm = first || this._vt || document.documentElement.classList.contains("shot") || matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (calm || !document.startViewTransition) {
      // Transition deja en cours (navigation rapide) : bascule directe, jamais de contenu perime.
      if (this._vt) this._vt.skipTransition();
      swap();
    } else {
      const vt = document.startViewTransition(swap);
      this._vt = vt;
      const clear = () => { if (this._vt === vt) this._vt = null; };
      vt.finished.then(clear, clear);
      vt.ready.catch(() => {});
      vt.updateCallbackDone.catch(() => {});
      vt.finished.catch(() => {});
    }
  },

  /* Temps reel simule : ce que ferait un flux SSE /api/events. */
  tick() {
    this.elapsed++;
    VIDEOS.filter((v) => v.status === "running").forEach((v) => {
      const speed = v.id === "mdj-0929" ? 3 : 1;
      v.progress = Math.min(100, v.progress + speed);
      if (this.elapsed % 6 === 0 && v.eta > 1) v.eta--;
      if (v.progress >= 100) {
        const s = v.steps[v.step];
        s.status = "done"; s.d = 380 + Math.round(Math.random() * 200);
        const doneLabel = STEPS[v.step].label;
        v.step++;
        if (v.step >= 12) { v.status = "done"; v.step = 11; toast({ kind: "ok", title: "Vidéo terminée", body: esc(v.title) }); }
        else {
          v.steps[v.step].status = "running"; v.progress = 0;
          v.detail = { subtitles: "8 fichiers .ass · Poppins ExtraBold", render: "x264 medium · clip 1/8", audio: "énergie et rires", scenes: "PySceneDetect" }[STEPS[v.step].id] || v.detail;
          toast({ kind: "ok", title: `${doneLabel} terminé`, body: `${esc(v.title)} · passe à ${STEPS[v.step].label.toLowerCase()}`, ms: 3600 });
        }
        if (this._active === "tableau" || this._active === "videos") { const y = window.scrollY; this.softRefresh(); window.scrollTo(0, y); }
      }
      $$(`[data-live-pct="${v.id}"]`).forEach((el) => (el.textContent = v.progress + " %"));
      $$(`[data-eta="${v.id}"]`).forEach((el) => (el.firstChild.nodeValue = v.eta + ""));
      $$(`[data-segs="${v.id}"] i.running`).forEach((el) => el.style.setProperty("--p", v.progress + "%"));
    });
    MACHINE.cpu = Math.max(38, Math.min(92, MACHINE.cpu + Math.round((Math.random() - 0.5) * 10)));
    MACHINE.ram[0] = Math.max(9.8, Math.min(13.4, MACHINE.ram[0] + (Math.random() - 0.5) * 0.3));
    if (this.elapsed % 2 === 0) this.renderMachine();
    this._ticks.forEach((t) => document.body.contains(t.root) && t.fn());
  },
  softRefresh() {
    // re-rendu sans transition (mise a jour de donnees, pas une navigation)
    const { parts, params } = this.parse();
    const view = parts[0] === "videos" && !parts[1] ? Views.videos(params) : parts[0] === "videos" ? null : Views.dashboard();
    if (!view) return;
    this._ticks = []; this._keys = [];
    const el = $("#view");
    el.innerHTML = view.html.replace(/class="([^"]*\b)reveal\b/g, 'class="$1');
    view.mount && view.mount(el);
    $$("[data-count]", el).forEach((n) => (n.textContent = fr(parseFloat(n.dataset.count), parseInt(n.dataset.dec || "0", 10))));
    this.renderNav(this._active);
  },
};

/* ---------- Ajout de video ---------- */
function openAddVideo(prefill) {
  let chosen = null;
  openPanel("modal", `
    <div class="modal-head"><h2>Ajouter une vidéo</h2><p class="muted" style="margin-top:4px">YouTube ou VOD Twitch. Elle passe en file avec le preset de sa chaîne.</p></div>
    <div class="modal-body">
      <div class="field"><label for="add-url">URL</label><input class="input" id="add-url" placeholder="https://www.twitch.tv/videos/… ou https://youtube.com/watch?v=…" value="${esc(prefill || "")}" autocomplete="off"></div>
      <div class="url-detect" id="add-detect">${icon("link", "i-sm")}Colle une URL : la chaîne et le preset sont reconnus.</div>
      <div class="field"><span class="field-label">Chaîne et preset</span><div class="choice-grid" id="add-ch">${CHANNELS.map((c) => `<button class="choice" data-c="${c.id}"><span class="c-title">${srcIcon(c.platform)}${esc(c.name)}</span><span class="c-sub">${esc(c.preset)} · ${c.mode}</span></button>`).join("")}</div></div>
      <label class="row" style="gap:12px;font-size:14px"><span class="switch"><input type="checkbox" id="add-front"><span></span></span>Passer devant la file</label>
    </div>
    <div class="modal-foot"><span class="muted" style="margin-right:auto;font-size:12px;align-self:center"><kbd>Entrée</kbd> pour lancer</span><button class="btn btn-ghost" data-dismiss>Annuler</button><button class="btn btn-primary" id="add-go" disabled>${icon("plus")}Mettre en file</button></div>`,
  (el) => {
    const url = $("#add-url", el), det = $("#add-detect", el), go = $("#add-go", el);
    const pick = (id) => { chosen = id; $$(".choice", el).forEach((b) => b.classList.toggle("on", b.dataset.c === id)); go.disabled = !(chosen && /^https?:\/\//.test(url.value)); };
    $$(".choice", el).forEach((b) => (b.onclick = () => pick(b.dataset.c)));
    const detect = () => {
      const u = url.value.trim();
      if (/twitch\.tv\/videos\/\d+/.test(u)) {
        det.className = "url-detect found";
        det.innerHTML = `<img src="img/frame_180.jpg" alt=""><div><b style="color:var(--text)">VOD du 30/09 · St. Amelia, partie 4</b><div class="muted">MaChaine · 4:31:02 · 1080p60</div></div>`;
        pick("ma_chaine");
      } else if (/youtu\.?be/.test(u)) {
        det.className = "url-detect found";
        det.innerHTML = `<div style="width:72px;aspect-ratio:16/9;border-radius:4px;background:radial-gradient(circle at 30% 30%,#e8bd4a66,transparent 70%),#151513"></div><div><b style="color:var(--text)">Les écrans rendent-ils nos enfants idiots ?</b><div class="muted">Contre-Pied · 1:52:40 · 1080p</div></div>`;
        pick("contrepied");
      } else {
        det.className = "url-detect";
        det.innerHTML = u ? `${icon("circle-alert", "i-sm")}URL non reconnue : YouTube ou twitch.tv/videos/… uniquement.` : `${icon("link", "i-sm")}Colle une URL : la chaîne et le preset sont reconnus.`;
        go.disabled = true;
      }
    };
    url.addEventListener("input", detect);
    if (prefill) detect();
    setTimeout(() => url.focus(), 60);
    const submit = () => {
      if (go.disabled) return;
      const c = chan(chosen);
      const front = $("#add-front", el).checked;
      closeLayer();
      toast({ kind: "ok", title: "Vidéo mise en file", body: `${esc(c.name)} · ${esc(c.preset)} · position ${front ? 1 : 3}`, action: { label: "Voir", run: () => (location.hash = "#/videos?f=pending") } });
    };
    go.onclick = submit;
    el.addEventListener("keydown", (e) => { if (e.key === "Enter") submit(); });
  });
}

/* ---------- Palette Ctrl+K ---------- */
function openPalette() {
  const items = [
    ...NAV.filter((n) => n.id).map((n) => ({ g: "Aller à", icon: n.icon, label: n.label, href: n.href })),
    { g: "Actions", icon: "plus", label: "Ajouter une vidéo", run: () => openAddVideo(), hint: "N" },
    { g: "Actions", icon: "sun", label: "Changer de thème", run: () => App.toggleTheme() },
    { g: "Actions", icon: "sparkles", label: "Revoir les moments de la VOD du 28/09", href: "#/revue/mdj-0928" },
    ...VIDEOS.map((v) => ({ g: "Vidéos", icon: "film", label: v.title, href: "#/videos/" + v.id, hint: STATUS[v.status].label })),
    ...CLIPS.map((c) => ({ g: "Clips", icon: "clapperboard", label: c.screen_title, href: "#/clips?f=all&open=" + c.id, hint: chan(c.channel).name })),
    ...CHANNELS.map((c) => ({ g: "Chaînes", icon: "tv", label: c.name, href: "#/chaines/" + c.id, hint: c.preset })),
  ];
  let sel = 0, shown = [];
  openPanel("modal palette", `
    <div class="palette-input">${icon("search")}<input id="pal-q" placeholder="Rechercher une vidéo, un clip, une chaîne, une action…" autocomplete="off"><kbd>Échap</kbd></div>
    <div class="palette-list" id="pal-list"></div>`, (el) => {
    const q = $("#pal-q", el), list = $("#pal-list", el);
    const norm = (s) => s.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
    const render = () => {
      const t = norm(q.value.trim());
      shown = items.filter((i) => !t || norm(i.label).includes(t) || norm(i.g).includes(t)).slice(0, 14);
      sel = Math.min(sel, Math.max(0, shown.length - 1));
      if (!shown.length) { list.innerHTML = `<div class="palette-empty">Rien pour « ${esc(q.value)} ». Essaie un titre de vidéo ou le nom d'une chaîne.</div>`; return; }
      let g = "", h = "";
      shown.forEach((i, k) => {
        if (i.g !== g) { g = i.g; h += `<div class="palette-group">${g}</div>`; }
        h += `<div class="palette-item ${k === sel ? "on" : ""}" data-k="${k}">${icon(i.icon, "i-sm")}<span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(i.label)}</span>${i.hint ? `<span class="hint">${esc(i.hint)}</span>` : ""}</div>`;
      });
      list.innerHTML = h;
      $$(".palette-item", list).forEach((it) => { it.onmousemove = () => { if (sel !== +it.dataset.k) { sel = +it.dataset.k; render(); } }; it.onclick = () => run(+it.dataset.k); });
    };
    const run = (k) => { const i = shown[k]; if (!i) return; closeLayer(); if (i.href) location.hash = i.href; else setTimeout(i.run, 60); };
    q.addEventListener("input", () => { sel = 0; render(); });
    q.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown") { sel = (sel + 1) % shown.length; render(); e.preventDefault(); }
      else if (e.key === "ArrowUp") { sel = (sel - 1 + shown.length) % shown.length; render(); e.preventDefault(); }
      else if (e.key === "Enter") run(sel);
    });
    render();
    setTimeout(() => q.focus(), 40);
  });
}

/* ---------- Notifications ---------- */
function toggleNotifs() {
  const p = $("#notif-panel");
  if (!p.hidden) { p.classList.remove("show"); setTimeout(() => (p.hidden = true), 200); return; }
  p.innerHTML = `<div class="panel-head" style="padding:12px 16px"><h2>Notifications</h2><div class="right"><button class="btn btn-xs btn-ghost" id="n-read">Tout marquer lu</button></div></div>` +
    NOTIFS.map((n) => `<a class="list-item" href="${n.href}"><span style="color:var(--${n.kind === "info" ? "accent" : n.kind})">${icon(n.icon, "i-sm")}</span><div class="li-main"><div class="li-title">${esc(n.title)}</div><div class="li-sub">${esc(n.body)}</div></div><span class="faint" style="font-size:11px;white-space:nowrap">${n.when}</span></a>`).join("");
  p.hidden = false;
  requestAnimationFrame(() => p.classList.add("show"));
  $("#n-read").onclick = () => { $("#notif-count").style.display = "none"; toggleNotifs(); };
  $$("a", p).forEach((a) => a.addEventListener("click", () => toggleNotifs()));
}
// Lignes cliquables (div[data-href]) : pas de lien imbrique dans un lien.
document.addEventListener("click", (e) => {
  const row = e.target.closest("[data-href]");
  if (row && !e.target.closest("a, button, input, select, label")) location.hash = row.dataset.href;
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && e.target.matches && e.target.matches("[data-href]")) location.hash = e.target.dataset.href;
});
document.addEventListener("click", (e) => {
  const p = $("#notif-panel");
  if (!p.hidden && !e.target.closest("#notif-panel") && !e.target.closest("#btn-notif")) toggleNotifs();
});

/* ---------- Demarrage ---------- */
(function boot() {
  $("#btn-menu").innerHTML = icon("menu");
  $("#btn-notif").insertAdjacentHTML("afterbegin", icon("bell"));
  $(".search-ico").outerHTML = icon("search", "i-sm");
  $("#btn-add").innerHTML = `${icon("plus")}<span class="lbl">Ajouter une vidéo</span>`;
  App.setTheme(document.documentElement.dataset.theme === "light" ? "light" : "dark", false);
  App.renderMachine();

  $("#btn-theme").onclick = () => App.toggleTheme();
  $("#btn-add").onclick = () => openAddVideo();
  $("#btn-search").onclick = openPalette;
  $("#btn-notif").onclick = toggleNotifs;
  $("#btn-menu").onclick = () => {
    const sb = $(".sidebar");
    sb.classList.add("open");
    showOverlay(() => sb.classList.remove("open"));
  };
  $("#live").onclick = () => toast({ kind: "info", title: "Connecté au flux d'événements", body: "Progression poussée par le serveur (SSE), sans rechargement.", ms: 3000 });

  let gPending = false;
  document.addEventListener("keydown", (e) => {
    const typing = /INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName) || document.activeElement.isContentEditable;
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); if (!closeCurrent) openPalette(); return; }
    if (closeCurrent) return;
    for (const h of App._keys) if (document.body.contains(h.root) && h.fn(e)) { e.preventDefault(); return; }
    if (typing || e.ctrlKey || e.metaKey || e.altKey) return;
    const k = e.key.toLowerCase();
    if (gPending) {
      gPending = false;
      const map = { d: "#/tableau", v: "#/videos", c: "#/clips", r: "#/revue", p: "#/publication", s: "#/stats" };
      if (map[k]) { location.hash = map[k]; e.preventDefault(); }
      return;
    }
    if (k === "g") { gPending = true; setTimeout(() => (gPending = false), 900); return; }
    if (k === "n") { e.preventDefault(); openAddVideo(); }
  });

  window.addEventListener("hashchange", () => App.route());
  App.route();
  setInterval(() => App.tick(), 1000);
  if (/[?&]selftest=1/.test(location.hash)) { const sc = document.createElement("script"); sc.src = "js/selftest.js"; document.body.appendChild(sc); }

  // Une notification arrive peu apres l'ouverture : montre le toast + la cloche.
  const shot = document.documentElement.classList.contains("shot");
  if (!shot || /[?&]toast=1/.test(location.hash)) setTimeout(() => {
    const n = $("#notif-count");
    n.textContent = "4";
    n.classList.remove("bump"); void n.offsetWidth; n.classList.add("bump");
    toast({ kind: "warn", title: "VOD du 27/09 en attente", body: "Webcam figée sur le clip 3. Choisis letterbox ou ignore le clip.", action: { label: "Décider", run: () => (location.hash = "#/videos/mdj-0927") }, ms: 7000 });
  }, 2600);
})();
