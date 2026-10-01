/* Autotest de la maquette (charge seulement avec ?selftest=1) : parcourt les
   ecrans, declenche les interactions, journalise les erreurs dans la console. */
"use strict";
(async function selftest() {
  const errors = [];
  window.addEventListener("error", (e) => errors.push(`${e.message} @${e.filename}:${e.lineno}`));
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const key = (k, extra) => document.dispatchEvent(new KeyboardEvent("keydown", Object.assign({ key: k, bubbles: true }, extra)));
  const step = async (name, fn) => {
    try { await fn(); console.log("SELFTEST step ok: " + name); }
    catch (e) { errors.push(`${name}: ${e.message}`); console.log("SELFTEST step FAIL: " + name + " " + e.stack); }
  };
  const go = async (h) => { location.hash = h; await wait(60); for (let k = 0; k < 40 && App._vt; k++) await wait(50); await wait(300); };
  const must = (sel) => { const el = document.querySelector(sel); if (!el) throw new Error("absent: " + sel); return el; };

  await step("tableau", async () => {
    await go("#/tableau");
    must(".kpis"); must("[data-fix]").click(); await wait(300);
    must("#toasts .toast [data-undo]").click();
  });
  await step("videos filtre + recherche", async () => {
    await go("#/videos");
    await wait(500);
    must('#vf button[data-v="attention"]').click(); await wait(50);
    if (document.querySelectorAll("#vlist .job").length !== 2) throw new Error("filtre attention != 2");
    const q = must("#vq"); q.value = "zzz"; q.dispatchEvent(new Event("input"));
    must("#vlist .empty");
    must("#vlist [data-href], #vlist .empty");
  });
  await step("ligne cliquable", async () => {
    await go("#/videos?f=all"); await wait(500);
    must("#vlist .job .job-title").click(); await wait(450);
    if (!location.hash.startsWith("#/videos/")) throw new Error("pas de navigation: " + location.hash);
  });
  await step("fiche video + frise + relance", async () => {
    await go("#/videos/mdj-0926");
    if (document.querySelectorAll(".fstep").length !== 12) throw new Error("frise != 12");
    document.querySelectorAll(".fstep")[4].click(); await wait(50);
    must("[data-force]").click(); await wait(100);
    must("#go-force").click(); await wait(350);
  });
  await step("fiche video en cours + annuler", async () => {
    await go("#/videos/mdj-0929");
    must("[data-cancel]").click(); await wait(100); must("#go-cancel").click(); await wait(300);
  });
  await step("revue : A, R, J, K, [ ], undo", async () => {
    await go("#/revue/mdj-0928");
    key("j"); key("k"); key("["); key("]", { shiftKey: true }); key(" "); key(" ");
    key("a"); await wait(50); key("r"); await wait(50); key("z", { ctrlKey: true }); await wait(50);
    must("#rv-render").click(); await wait(100); must("#go-render").click(); await wait(300);
  });
  await step("clips : fiche, approuver, undo, copier", async () => {
    await go("#/clips?f=all");
    must("[data-clip]").click(); await wait(400);
    must("#d-copy").click(); must("#d-ok").click(); await wait(350);
    const undos = document.querySelectorAll("#toasts .toast [data-undo]");
    if (!undos.length) throw new Error("pas de toast annulable");
    undos[undos.length - 1].click();
    if (document.querySelectorAll("#toasts .toast[data-seq]").length && [...document.querySelectorAll("#toasts .toast[data-seq] [data-undo]")].some((u) => +u.closest(".toast").dataset.seq !== App._seq)) throw new Error("undo perime encore present");
  });
  await step("publication : planifier par drop + remplir", async () => {
    await go("#/publication");
    const id = must("#queue [data-post]").dataset.post;
    const cell = must('.cal-c[data-day="5"][data-slot="12:30"]');
    const dt = new DataTransfer();
    must(`#queue [data-post="${id}"]`).dispatchEvent(new DragEvent("dragstart", { bubbles: true, dataTransfer: dt }));
    cell.dispatchEvent(new DragEvent("dragover", { bubbles: true, cancelable: true, dataTransfer: dt }));
    cell.dispatchEvent(new DragEvent("drop", { bubbles: true, cancelable: true, dataTransfer: dt }));
    await wait(100);
    if (!document.querySelector(`.cal-c[data-day="5"][data-slot="12:30"] [data-post="${id}"]`)) throw new Error("drop sans effet");
    must("#auto-fill").click(); await wait(100);
  });
  await step("stats", async () => { await go("#/stats"); must("#ch-day svg"); must("#ch-cost svg"); });
  await step("chaines : surveillance", async () => {
    await go("#/chaines");
    const sw = must("[data-watch=filrouge]"); sw.checked = true; sw.dispatchEvent(new Event("change"));
  });
  await step("preset : formats, calques, onglets", async () => {
    await go("#/chaines/ma_chaine");
    must('#lp button[data-l="letterbox"]').click(); await wait(500);
    must('#lp button[data-l="top"]').click(); await wait(500);
    must("[data-eye=endcard]").click();
    must(".layer[data-id=title]").click();
    const x = must("#c-dest input"); x.value = "200"; x.dispatchEvent(new Event("input"));
    must('#frames button[data-f="img/frame_8400.jpg"]').click();
    for (const t of ["subs", "title", "rubric", "source", "layout"]) { must(`#ch-tabs button[data-v="${t}"]`).click(); await wait(250); }
    must("#ed-save").click();
  });
  await step("reglages : dirty + save", async () => {
    await go("#/reglages");
    const s = must("#s-llm select"); s.value = "ollama"; s.dispatchEvent(new Event("change", { bubbles: true }));
    if (!must("#save-bar").classList.contains("show")) throw new Error("barre d'enregistrement absente");
    must("#s-save").click();
  });
  await step("ajout video + palette + notifs + theme", async () => {
    openAddVideo("https://www.youtube.com/watch?v=abc"); await wait(150);
    if (must("#add-go").disabled) throw new Error("bouton ajout desactive");
    must("#add-go").click(); await wait(350);
    key("k", { ctrlKey: true }); await wait(150);
    const q = must("#pal-q"); q.value = "nucleaire"; q.dispatchEvent(new Event("input"));
    if (!document.querySelector(".palette-item")) throw new Error("palette sans resultat (accents)");
    q.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter" })); await wait(500);
    must("#btn-notif").click(); await wait(100); must("#btn-notif").click();
    App.toggleTheme(); App.toggleTheme();
  });
  await wait(300);
  console.log(errors.length ? "SELFTEST ERRORS " + JSON.stringify(errors) : "SELFTEST OK");
})();
