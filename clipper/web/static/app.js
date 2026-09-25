"use strict";

const STEP_LABELS = {
  download: "Telechargement", transcribe: "Transcription", scenes: "Plans",
  audio: "Audio", moments: "Moments", vision: "Images", parts: "Decoupage",
  captions: "Legendes", reframe: "Recadrage", subtitles: "Sous-titres",
  render: "Rendu", qa: "Controle qualite",
};
const STATUS_LABELS = {
  pending: "en attente", running: "en cours", done: "termine",
  awaiting_review: "en attente de revue", queued: "en file d'attente",
  failed: "echec",
};
const POLL_MS = 2000;

const videosList = document.getElementById("videos-list");
const submitForm = document.getElementById("submit-form");
const submitUrl = document.getElementById("submit-url");
const submitMessage = document.getElementById("submit-message");
const detailSection = document.getElementById("detail-section");
const detailStatus = document.getElementById("detail-status");
const detailSteps = document.getElementById("detail-steps");
const momentsBlock = document.getElementById("moments-block");
const momentsList = document.getElementById("moments-list");
const renderButton = document.getElementById("render-button");
const renderMessage = document.getElementById("render-message");
const clipsBlock = document.getElementById("clips-block");
const clipsList = document.getElementById("clips-list");
const videoItemTemplate = document.getElementById("video-item-template");
const momentItemTemplate = document.getElementById("moment-item-template");
const clipItemTemplate = document.getElementById("clip-item-template");

let selectedVideoId = null;
let pollHandle = null;

function showMessage(el, text, isError) {
  el.textContent = text;
  el.hidden = false;
  el.classList.toggle("error", Boolean(isError));
}

async function api(path, options) {
  const resp = await fetch(path, options);
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      detail = (await resp.json()).detail || detail;
    } catch (err) {
      // reponse sans corps JSON : on garde le statusText.
    }
    throw new Error(detail);
  }
  if (resp.status === 204) return null;
  return resp.json();
}

function renderVideosList(videos) {
  videosList.innerHTML = "";
  for (const video of videos) {
    const node = videoItemTemplate.content.cloneNode(true);
    const link = node.querySelector(".video-link");
    link.textContent = `${video.video_id} - ${video.source_url}`;
    link.addEventListener("click", () => selectVideo(video.video_id));
    node.querySelector(".video-status").textContent = STATUS_LABELS[video.status] || video.status;
    videosList.appendChild(node);
  }
}

async function refreshVideosList() {
  const videos = await api("/api/videos");
  renderVideosList(videos);
  return videos;
}

function renderSteps(state) {
  detailStatus.textContent = `Statut : ${STATUS_LABELS[state.status] || state.status}`
    + (state.reason ? ` (${state.reason})` : "");
  detailSteps.innerHTML = "";
  for (const [name, step] of Object.entries(state.steps || {})) {
    const li = document.createElement("li");
    li.textContent = `${STEP_LABELS[name] || name} : ${STATUS_LABELS[step.status] || step.status}`
      + (step.reason ? ` (${step.reason})` : "");
    li.className = `step step-${step.status}`;
    detailSteps.appendChild(li);
  }
}

function formatSeconds(value) {
  const m = Math.floor(value / 60);
  const s = (value % 60).toFixed(1);
  return `${m}:${s.padStart(4, "0")}`;
}

function attachPreview(video, start, end) {
  video.addEventListener("loadedmetadata", () => {
    video.currentTime = start;
  });
  video.addEventListener("timeupdate", () => {
    if (video.currentTime >= end) video.pause();
  });
  video.addEventListener("play", () => {
    if (video.currentTime < start || video.currentTime >= end) video.currentTime = start;
  });
}

async function decide(videoId, momentId, decision, extra) {
  renderMessage.hidden = true;
  try {
    await api(`/api/videos/${videoId}/moments/${momentId}/decide`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision, ...extra }),
    });
    await refreshMoments(videoId);
  } catch (err) {
    showMessage(renderMessage, `Decision refusee : ${err.message}`, true);
  }
}

function renderMoments(videoId, moments) {
  momentsList.innerHTML = "";
  for (const moment of moments) {
    const node = momentItemTemplate.content.cloneNode(true);
    const video = node.querySelector("video");
    video.src = moment.preview_url;
    attachPreview(video, moment.start, moment.end);

    node.querySelector(".moment-hook").textContent = moment.hook_text || "";
    node.querySelector(".score-value").textContent = moment.score != null ? moment.score : "?";
    node.querySelector(".moment-justification").textContent = moment.justification || "";

    const decisionEl = node.querySelector(".moment-decision");
    decisionEl.textContent = moment.decision
      ? `Decision : ${moment.decision.decision} (${formatSeconds(moment.decision.start)} - ${formatSeconds(moment.decision.end)})`
      : `Debut ${formatSeconds(moment.start)}, fin ${formatSeconds(moment.end)} : aucune decision`;

    node.querySelector(".decide-accept").addEventListener("click", () => decide(videoId, moment.id, "accepted"));
    node.querySelector(".decide-reject").addEventListener("click", () => decide(videoId, moment.id, "rejected"));

    const startInput = node.querySelector(".adjust-start");
    const endInput = node.querySelector(".adjust-end");
    startInput.value = moment.start;
    endInput.value = moment.end;
    node.querySelector(".decide-adjust").addEventListener("click", () => decide(videoId, moment.id, "adjusted", {
      start: parseFloat(startInput.value), end: parseFloat(endInput.value),
    }));

    momentsList.appendChild(node);
  }
}

async function refreshMoments(videoId) {
  try {
    const moments = await api(`/api/videos/${videoId}/moments`);
    momentsBlock.hidden = false;
    renderMoments(videoId, moments);
  } catch (err) {
    momentsBlock.hidden = true;
  }
}

function renderClips(clips) {
  clipsList.innerHTML = "";
  for (const clip of clips) {
    const node = clipItemTemplate.content.cloneNode(true);
    node.querySelector("video").src = clip.video_url;
    node.querySelector(".clip-title").textContent = clip.title;
    node.querySelector(".clip-caption").textContent = clip.caption;
    node.querySelector(".clip-hashtags").textContent = (clip.hashtags || []).join(" ");
    node.querySelector(".clip-qa").textContent = `Controle qualite : ${clip.qa.status}`;
    clipsList.appendChild(node);
  }
}

async function refreshClips(videoId) {
  const clips = await api(`/api/videos/${videoId}/clips`);
  clipsBlock.hidden = clips.length === 0;
  renderClips(clips);
}

async function refreshDetail(videoId) {
  const state = await api(`/api/videos/${videoId}`);
  renderSteps(state);
  await refreshMoments(videoId);
  await refreshClips(videoId);
}

function selectVideo(videoId) {
  selectedVideoId = videoId;
  detailSection.hidden = false;
  if (pollHandle) clearInterval(pollHandle);
  refreshDetail(videoId).catch((err) => showMessage(detailStatus, err.message, true));
  pollHandle = setInterval(() => {
    refreshDetail(videoId).catch(() => {});
  }, POLL_MS);
}

renderButton.addEventListener("click", async () => {
  if (!selectedVideoId) return;
  try {
    await api(`/api/videos/${selectedVideoId}/render`, { method: "POST" });
    showMessage(renderMessage, "Rendu lance.", false);
  } catch (err) {
    showMessage(renderMessage, `Impossible de lancer le rendu : ${err.message}`, true);
  }
});

submitForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  submitMessage.hidden = true;
  try {
    await api("/api/videos", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: submitUrl.value }),
    });
    showMessage(submitMessage, "Traitement lance.", false);
    submitUrl.value = "";
    await refreshVideosList();
  } catch (err) {
    showMessage(submitMessage, `Echec de la soumission : ${err.message}`, true);
  }
});

refreshVideosList().catch((err) => showMessage(submitMessage, err.message, true));
setInterval(() => {
  refreshVideosList().catch(() => {});
}, POLL_MS);
