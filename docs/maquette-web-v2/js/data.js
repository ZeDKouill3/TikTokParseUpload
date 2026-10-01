/* Donnees factices de la maquette. Formes calquees sur workspace/<id>/pipeline.json,
   moments.json, output/<id>/<clip>.json (SPEC-6a47) et llm_usage.jsonl.
   Maquette locale (research/, ignore par git) : exemple realiste autorise. */
"use strict";

const NOW = new Date(2026, 8, 30, 21, 34);

const STEPS = [
  { id: "download",   label: "Téléchargement", icon: "download",       mod: "clipper.download" },
  { id: "transcribe", label: "Transcription",  icon: "audio-waveform", mod: "clipper.transcribe" },
  { id: "scenes",     label: "Plans",          icon: "clapperboard",   mod: "clipper.scenes" },
  { id: "audio",      label: "Audio",          icon: "volume-2",       mod: "clipper.audio" },
  { id: "moments",    label: "Moments",        icon: "sparkles",       mod: "clipper.moments" },
  { id: "vision",     label: "Images",         icon: "eye",            mod: "clipper.vision" },
  { id: "parts",      label: "Découpage",      icon: "scissors",       mod: "clipper.parts" },
  { id: "captions",   label: "Légendes",       icon: "type",           mod: "clipper.captions" },
  { id: "reframe",    label: "Recadrage",      icon: "crop",           mod: "clipper.reframe" },
  { id: "subtitles",  label: "Sous-titres",    icon: "captions",       mod: "clipper.subtitles" },
  { id: "render",     label: "Rendu",          icon: "film",           mod: "clipper.render" },
  { id: "qa",         label: "Contrôle",       icon: "shield-check",   mod: "clipper.qa" },
];

const CHANNELS = [
  {
    id: "ma_chaine", name: "MaChaine", initial: "M", color: "#9146ff",
    platform: "twitch", handle: "twitch.tv/ma_chaine", genre: "Stream gaming · horreur, narratif",
    watch: true, lastCheck: "il y a 6 min", mode: "review",
    preset: "Stream split", layout: "split",
    tiktok: "@ma_chaine.clips", tiktokLinked: false,
    slots: ["12:30", "18:00"], cover: "img/frame_2400.jpg",
    stats: { videos: 14, clips: 63, pending: 7 },
  },
  {
    id: "contrepied", name: "Contre-Pied", initial: "C", color: "#e8bd4a",
    platform: "youtube", handle: "@contrepied.debat", genre: "Débats de société · plateau 4 invités",
    watch: true, lastCheck: "il y a 22 min", mode: "auto",
    preset: "Letterbox débat", layout: "letterbox",
    tiktok: "@contrepied.extraits", tiktokLinked: false,
    slots: ["19:00"], cover: null,
    stats: { videos: 9, clips: 41, pending: 0 },
  },
  {
    id: "filrouge", name: "Fil Rouge", initial: "F", color: "#5cc98a",
    platform: "youtube", handle: "@filrouge.podcast", genre: "Podcast long format · 1 invité",
    watch: false, lastCheck: "surveillance coupée", mode: "review",
    preset: "Letterbox podcast", layout: "letterbox",
    tiktok: null, tiktokLinked: false,
    slots: ["08:00", "21:00"], cover: null,
    stats: { videos: 3, clips: 11, pending: 2 },
  },
];

// statut d'etape : done | running | pending | failed | review | queued
function stepsFrom(pattern, durations) {
  return STEPS.map((s, i) => ({ id: s.id, status: pattern[i], d: durations ? durations[i] : null }));
}
const D = "done", R = "running", P = "pending", F = "failed", Q = "queued", V = "review";

const VIDEOS = [
  {
    id: "mdj-0929", channel: "ma_chaine", title: "VOD du 29/09 · St. Amelia, partie 3",
    url: "https://www.twitch.tv/videos/2261847301", duration: "4:12:08", added: "30/09 17:05",
    thumb: "img/frame_5400.jpg", status: "running", step: 8, progress: 64, eta: 7,
    steps: stepsFrom([D, D, D, D, D, D, D, D, R, P, P, P], [412, 1386, 208, 96, 311, 184, 142, 88, null, null, null, null]),
    detail: "clip 5/8 · stream split (webcam vivante 94 %)", clips: 0, moments: 8,
  },
  {
    id: "cp-telephones", channel: "contrepied", title: "Faut-il interdire le téléphone au collège ?",
    url: "https://www.youtube.com/watch?v=Qm4yV0tLx8c", duration: "1:38:12", added: "30/09 20:48",
    thumb: null, poster: "debat", status: "running", step: 1, progress: 42, eta: 11,
    steps: stepsFrom([D, R, P, P, P, P, P, P, P, P, P, P], [64]),
    detail: "faster-whisper large-v3 · cuda · 41:10 / 1:38:12", clips: 0,
  },
  {
    id: "mdj-0928", channel: "ma_chaine", title: "VOD du 28/09 · St. Amelia, partie 2",
    url: "https://www.twitch.tv/videos/2260911554", duration: "3:47:30", added: "29/09 09:12",
    thumb: "img/frame_2400.jpg", status: "awaiting_review", step: 4,
    steps: stepsFrom([D, D, D, D, V, P, P, P, P, P, P, P], [388, 1240, 190, 88, 296]),
    detail: "6 moments proposés, 2 déjà traités", clips: 0, moments: 6,
  },
  {
    id: "cp-nucleaire", channel: "contrepied", title: "Nucléaire : on relance ou on arrête ?",
    url: "https://www.youtube.com/watch?v=7hKr2PzW1nE", duration: "2:04:51", added: "29/09 18:30",
    thumb: null, poster: "debat", status: "awaiting_review", step: 4,
    steps: stepsFrom([D, D, D, D, V, P, P, P, P, P, P, P], [102, 702, 96, 51, 244]),
    detail: "5 moments proposés (review forcé : veto conformité)", clips: 0, moments: 5,
  },
  {
    id: "mdj-0927", channel: "ma_chaine", title: "VOD du 27/09 · Just Chatting + Lethal Company",
    url: "https://www.twitch.tv/videos/2259870012", duration: "5:21:44", added: "28/09 11:40",
    thumb: "img/frame_8400.jpg", status: "queued", step: 8,
    steps: stepsFrom([D, D, D, D, D, D, D, D, Q, P, P, P], [520, 1712, 260, 121, 402, 233, 170, 104]),
    reason: "Rectangle de webcam figé sur 71 % des images clés du clip 3 (seuil 50 %) : format stream impossible. Choisir letterbox pour ce clip, ou vérifier la source (webcam coupée ?).",
    detail: "EXIT_QUEUED · reframe", clips: 0,
  },
  {
    id: "fr-56", channel: "filrouge", title: "Épisode 56 · « J'ai quitté la finance pour la menuiserie »",
    url: "https://www.youtube.com/watch?v=Zt0pF3aa9Lk", duration: "1:52:03", added: "28/09 08:02",
    thumb: null, poster: "cast", status: "failed", step: 0,
    steps: stepsFrom([F, P, P, P, P, P, P, P, P, P, P, P], [3]),
    reason: "download : HTTP 403, vidéo réservée aux membres de la chaîne. Fournir un cookie de session ou retirer la vidéo.",
    detail: "yt-dlp · ERROR: [youtube] Join this channel to get access", clips: 0,
  },
  {
    id: "fr-57", channel: "filrouge", title: "Épisode 57 · « Pourquoi on dort mal »",
    url: "https://www.youtube.com/watch?v=aP9s1LwQe2M", duration: "1:21:40", added: "30/09 21:02",
    thumb: null, poster: "cast", status: "pending", step: -1, position: 1,
    steps: stepsFrom([P, P, P, P, P, P, P, P, P, P, P, P]),
    detail: "1ʳᵉ dans la file · démarre après « Faut-il interdire… »", clips: 0,
  },
  {
    id: "cp-4jours", channel: "contrepied", title: "Semaine de 4 jours : fausse bonne idée ?",
    url: "https://www.youtube.com/watch?v=Lr3kVb82sQo", duration: "1:44:27", added: "30/09 21:03",
    thumb: null, poster: "debat", status: "pending", step: -1, position: 2,
    steps: stepsFrom([P, P, P, P, P, P, P, P, P, P, P, P]),
    detail: "2ᵉ dans la file", clips: 0,
  },
  {
    id: "mdj-0926", channel: "ma_chaine", title: "VOD du 26/09 · St. Amelia, partie 1",
    url: "https://www.twitch.tv/videos/2258992147", duration: "3:58:02", added: "27/09 10:15",
    thumb: "img/frame_180.jpg", status: "done", step: 11,
    steps: stepsFrom([D, D, D, D, D, D, D, D, D, D, D, D], [401, 1302, 201, 90, 318, 176, 138, 91, 612, 74, 1840, 66]),
    detail: "6 clips · 1 avertissement QA", clips: 6,
  },
  {
    id: "cp-smic", channel: "contrepied", title: "SMIC à 1 600 € net : qui paie ?",
    url: "https://www.youtube.com/watch?v=Hc8yRt1mPq0", duration: "1:36:55", added: "26/09 19:10",
    thumb: null, poster: "debat", status: "done", step: 11,
    steps: stepsFrom([D, D, D, D, D, D, D, D, D, D, D, D], [88, 598, 84, 44, 231, 140, 97, 70, 58, 49, 1122, 41]),
    detail: "4 clips · publiés en auto", clips: 4,
  },
];

const STATUS = {
  running: { label: "En cours", cls: "running" },
  pending: { label: "En file", cls: "pending" },
  awaiting_review: { label: "À revoir", cls: "review" },
  queued: { label: "En attente", cls: "queued" },
  failed: { label: "Échec", cls: "failed" },
  done: { label: "Terminé", cls: "done" },
};

// Revue : moments de mdj-0928 (moments.json + jury). Bornes en secondes.
const MOMENTS = [
  {
    id: "m1", start: 2412.4, end: 2468.9, score: 87, frame: "img/frame_2400.jpg",
    hook: "Elle lit la carte… et comprend qu'elle tourne en rond depuis 40 min",
    title: "Moi, j'vois", parts: 1, decision: null,
    transcript: [["MaChaine", "attends attends attends, on est où là ? Non. Non non non."], ["MaChaine", "moi, j'vois le parc, j'vois la grand-place… <mark>on est passés devant trois fois</mark>."], ["Chat", "(le chat spamme « KEKW »)"], ["MaChaine", "quarante minutes. QUARANTE. Je vais me coucher."]],
    judges: [
      ["retention", 91, "Chute nette à 0:38 (« quarante minutes ») : tient jusqu'au bout."],
      ["spectateur", 84, "Compréhensible sans le contexte du jeu, la carte suffit."],
      ["monteur", 88, "Réaction visage lisible dans la webcam, bon cadre split."],
      ["avocat", 79, "Un peu long avant le déclic (8 s d'hésitation)."],
      ["conformite", 100, "Rien à signaler."],
    ],
    crit: { hook: 4, standalone: 5, payoff: 5, emotion: 4, value: 2 },
  },
  {
    id: "m2", start: 5391.0, end: 5452.5, score: 81, frame: "img/frame_5400.jpg",
    hook: "« Le 79 c'est mon score de peur » : le chat la piège en direct",
    title: "79, mon score de peur", parts: 1, decision: "accepted",
    transcript: [["MaChaine", "c'est quoi le 79 en rouge ? C'est… <mark>c'est mon score de peur ?</mark>"], ["MaChaine", "vous l'avez mis à jour vous-mêmes ? Mais vous êtes des monstres."]],
    judges: [
      ["retention", 83, "Relance toutes les 10 s, bonne boucle."],
      ["spectateur", 76, "Il faut comprendre le compteur, expliqué à 0:05."],
      ["monteur", 82, "Compteur visible dans la webcam : à garder dans le cadre."],
      ["avocat", 74, "Blague interne au chat, public restreint."],
      ["conformite", 100, "Rien à signaler."],
    ],
    crit: { hook: 4, standalone: 3, payoff: 4, emotion: 4, value: 1 },
  },
  {
    id: "m3", start: 8402.0, end: 8521.0, score: 76, frame: "img/frame_8400.jpg",
    hook: "Le jump scare du phare, en deux parties",
    title: "Le phare", parts: 2, decision: null,
    transcript: [["MaChaine", "bon, le phare. On y va doucement. Doucement…"], ["MaChaine", "<mark>AAAAH NON</mark>. Non. J'éteins. J'éteins le stream."]],
    judges: [
      ["retention", 80, "Montée longue mais payante ; la partie 2 démarre sur le cri."],
      ["spectateur", 78, "Universel : un cri, pas besoin de contexte."],
      ["monteur", 71, "Scène sombre, sous-titres à remonter dans la zone sûre."],
      ["avocat", 69, "2 parties pour un seul cri : risque de perte entre les deux."],
      ["conformite", 100, "Rien à signaler."],
    ],
    crit: { hook: 3, standalone: 4, payoff: 5, emotion: 5, value: 1 },
  },
  {
    id: "m4", start: 1204.0, end: 1251.2, score: 68, frame: "img/frame_2400.jpg",
    hook: "Elle explique pourquoi elle joue toujours sans son",
    title: "Toujours sans le son", parts: 1, decision: "rejected",
    transcript: [["MaChaine", "non mais moi je joue sans le son parce que sinon je dors pas, c'est tout."]],
    judges: [
      ["retention", 61, "Pas de chute, ça s'arrête à plat."],
      ["spectateur", 72, "Relatable."],
      ["monteur", 70, "Plan fixe, peu d'action."],
      ["avocat", 58, "Trop anecdotique pour un clip seul."],
      ["conformite", 100, "Rien à signaler."],
    ],
    crit: { hook: 2, standalone: 4, payoff: 2, emotion: 3, value: 2 },
  },
  {
    id: "m5", start: 10988.0, end: 11040.0, score: 64, frame: "img/frame_5400.jpg",
    hook: "Elle rate trois fois la même énigme de la balance",
    title: "La balance", parts: 1, decision: null,
    transcript: [["MaChaine", "la balance… trois poids… <mark>pourquoi ça marche pas</mark> ?!"]],
    judges: [
      ["retention", 66, "Répétitif, la 3ᵉ tentative porte le clip."],
      ["spectateur", 58, "Énigme incompréhensible sans le jeu."],
      ["monteur", 70, "La carte bouge beaucoup, recadrage jeu à revoir."],
      ["avocat", 55, "Faible."],
      ["conformite", 100, "Rien à signaler."],
    ],
    crit: { hook: 2, standalone: 2, payoff: 3, emotion: 3, value: 1 },
  },
  {
    id: "m6", start: 12790.0, end: 12844.0, score: 58, frame: "img/frame_180.jpg",
    hook: "Fin de stream : elle lit les messages des abonnés",
    title: "Merci les subs", parts: 1, decision: null,
    transcript: [["MaChaine", "merci Ghostbox pour les 12 mois, merci Lina…"]],
    judges: [
      ["retention", 49, "Liste de pseudos : décroche vite."],
      ["spectateur", 52, "Sans intérêt hors communauté."],
      ["monteur", 64, "Correct."],
      ["avocat", 40, "Pas un clip."],
      ["conformite", 90, "Pseudos de spectateurs à l'écran : à flouter si publié."],
    ],
    crit: { hook: 1, standalone: 2, payoff: 1, emotion: 3, value: 1 },
  },
];
const REVIEW_VIDEO = { id: "mdj-0928", total: 13650 };

const JUDGES = {
  retention: { label: "Rétention", model: "strong" },
  spectateur: { label: "Spectateur", model: "fast" },
  monteur: { label: "Monteur", model: "strong" },
  avocat: { label: "Avocat du diable", model: "strong" },
  conformite: { label: "Conformité", model: "fast", veto: true },
};
const CRITERIA = { hook: ["Accroche", 3], standalone: ["Autonomie", 3], payoff: ["Chute", 2], emotion: ["Émotion", 2], value: ["Valeur", 2], trend: ["Tendance", 0] };

// Clips : output/<video_id>/<clip_id>.json (SPEC-6a47)
const CLIPS = [
  { id: "mdj-0926_c01", video: "mdj-0926", channel: "ma_chaine", img: "img/rendu-2400.jpg", screen_title: "Moi, j'vois", duration: 41.2, score: 87, status: "review",
    description: "Quarante minutes à tourner en rond sur la même île 😭 la carte ne ment pas", hashtags: ["#stamelia", "#horreur", "#twitchfr", "#gaming"], parts: [1, 1], qa: [] },
  { id: "mdj-0926_c02", video: "mdj-0926", channel: "ma_chaine", img: "img/clip-duo2.jpg", screen_title: "La carte de St. Amelia", duration: 58.4, score: 82, status: "review",
    description: "Quand tu comprends enfin la carte (non)", hashtags: ["#stamelia", "#twitchfr", "#streameuse"], parts: [1, 2], qa: ["Silence initial 0,8 s (seuil 1,0 s) : limite."] },
  { id: "mdj-0926_c03", video: "mdj-0926", channel: "ma_chaine", img: "img/clip-carte.jpg", screen_title: "La carte de St. Amelia", duration: 52.1, score: 82, status: "review",
    description: "Partie 2 : elle trouve la sortie… ou pas", hashtags: ["#stamelia", "#twitchfr", "#streameuse"], parts: [2, 2], qa: [] },
  { id: "mdj-0926_c04", video: "mdj-0926", channel: "ma_chaine", img: "img/rendu-5400.jpg", screen_title: "Dynamiser l'île", duration: 37.9, score: 74, status: "approved",
    description: "Le lore du jeu lu avec toute la conviction du monde", hashtags: ["#stamelia", "#lore", "#twitchfr"], parts: [1, 1], qa: [] },
  { id: "cp-smic_c01", video: "cp-smic", channel: "contrepied", poster: "debat", screen_title: "Qui paie la hausse du SMIC ?", sub: "« Ce n'est <em>pas</em> l'État »", duration: 49.0, score: 85, status: "published",
    description: "Échange tendu sur le financement d'un SMIC à 1 600 € net. Et vous, vous en pensez quoi ?", hashtags: ["#debat", "#smic", "#economie", "#politique"], parts: [1, 1], qa: [] },
  { id: "cp-smic_c02", video: "cp-smic", channel: "contrepied", poster: "debat", screen_title: "Les PME peuvent-elles suivre ?", sub: "« 3 salariés, <em>zéro</em> marge »", duration: 44.6, score: 79, status: "published",
    description: "Une gérante de PME fait ses comptes en direct.", hashtags: ["#debat", "#smic", "#pme"], parts: [1, 1], qa: [] },
  { id: "cp-smic_c03", video: "cp-smic", channel: "contrepied", poster: "debat", screen_title: "Le chiffre qui fâche", sub: "« <em>17 %</em> des salariés »", duration: 33.2, score: 76, status: "scheduled",
    description: "D'où vient ce chiffre ? Les sources en commentaire.", hashtags: ["#debat", "#smic", "#chiffres"], parts: [1, 1], qa: [] },
  { id: "cp-smic_c04", video: "cp-smic", channel: "contrepied", poster: "debat", screen_title: "Il quitte le plateau", sub: "« Je ne <em>peux pas</em> laisser dire ça »", duration: 28.7, score: 88, status: "scheduled",
    description: "Le moment où tout bascule.", hashtags: ["#debat", "#clash", "#smic"], parts: [1, 1], qa: [] },
  { id: "mdj-0926_c05", video: "mdj-0926", channel: "ma_chaine", img: "img/rendu-2400.jpg", screen_title: "Moi, j'vois (version courte)", duration: 21.5, score: 71, status: "rejected",
    description: "Version courte", hashtags: ["#twitchfr"], parts: [1, 1], qa: ["Doublon probable de mdj-0926_c01 (78 % du texte commun)."] },
  { id: "fr-55_c01", video: "fr-55", channel: "filrouge", poster: "cast", screen_title: "Le sommeil, ça s'apprend ?", sub: "« On dort <em>90 minutes</em> par cycle »", duration: 55.8, score: 80, status: "review",
    description: "Une chercheuse du sommeil démonte trois idées reçues.", hashtags: ["#podcast", "#sommeil", "#sante"], parts: [1, 1], qa: ["Sous-titres : 2 mots coupés en fin de ligne à 0:31."] },
  { id: "fr-55_c02", video: "fr-55", channel: "filrouge", poster: "cast", screen_title: "Le réveil de 3 h du matin", sub: "« C'est <em>normal</em> »", duration: 46.3, score: 77, status: "review",
    description: "Se réveiller la nuit n'est pas forcément un problème.", hashtags: ["#podcast", "#sommeil"], parts: [1, 1], qa: [] },
  { id: "mdj-0926_c06", video: "mdj-0926", channel: "ma_chaine", img: "img/clip-duo2.jpg", screen_title: "Le compteur de peur", duration: 44.0, score: 69, status: "review",
    description: "Le chat a inventé un compteur de peur et elle le découvre en live", hashtags: ["#twitchfr", "#horreur"], parts: [1, 1], qa: [] },
];

const CLIP_STATUS = {
  review: { label: "À valider", cls: "warn" },
  approved: { label: "Approuvé", cls: "ok" },
  scheduled: { label: "Planifié", cls: "info" },
  published: { label: "Publié", cls: "ok" },
  rejected: { label: "Refusé", cls: "bad" },
};

// Semaine du lundi 28/09 au dimanche 04/10, aujourd'hui mercredi 30/09.
const WEEK = [
  { d: "lun", n: 28 }, { d: "mar", n: 29 }, { d: "mer", n: 30, today: true },
  { d: "jeu", n: 1 }, { d: "ven", n: 2 }, { d: "sam", n: 3 }, { d: "dim", n: 4 },
];
const CAL_SLOTS = ["08:00", "12:30", "18:00", "19:00", "21:00"];
const POSTS = [
  { clip: "cp-smic_c01", day: 0, slot: "19:00", status: "published" },
  { clip: "cp-smic_c02", day: 1, slot: "19:00", status: "published" },
  { clip: "mdj-0926_c04", day: 1, slot: "18:00", status: "failed", why: "Upload manuel non confirmé" },
  { clip: "cp-smic_c03", day: 3, slot: "19:00", status: "scheduled" },
  { clip: "cp-smic_c04", day: 4, slot: "19:00", status: "scheduled" },
];
const QUEUE = ["mdj-0926_c01", "mdj-0926_c02", "mdj-0926_c03", "fr-55_c01"];

const NOTIFS = [
  { kind: "warn", icon: "circle-pause", title: "VOD du 27/09 en attente", body: "Webcam figée sur le clip 3 : choisir le format.", when: "il y a 18 min", href: "#/videos/mdj-0927" },
  { kind: "info", icon: "sparkles", title: "6 moments à revoir", body: "VOD du 28/09 · MaChaine", when: "il y a 2 h", href: "#/revue/mdj-0928" },
  { kind: "bad", icon: "circle-x", title: "Épisode 56 a échoué", body: "download : HTTP 403 (membres).", when: "hier 08:03", href: "#/videos/fr-56" },
  { kind: "ok", icon: "circle-check", title: "4 clips prêts", body: "SMIC à 1 600 € net · Contre-Pied", when: "27/09", href: "#/clips" },
];

const MACHINE = { gpu: "RTX 3050 Laptop", vram: [3.1, 4.0], cpu: 62, ram: [11.2, 16], model: "faster-whisper large-v3" };

// llm_usage.jsonl agrege. Backend claude-cli (abonnement) : le cout affiche est
// un equivalent API, indicatif.
const LLM_USAGE = [
  ["moments", 431000, 4.19], ["jury_retention", 188000, 1.71], ["jury_avocat", 171000, 1.55],
  ["jury_monteur", 166000, 1.49], ["vision", 94000, 1.12], ["captions", 61000, 0.38],
  ["parts", 58000, 0.36], ["jury_spectateur", 142000, 0.21], ["jury_conformite", 131000, 0.19],
];
const CLIPS_PER_DAY = [
  ["17/09", 3], ["18/09", 0], ["19/09", 5], ["20/09", 8], ["21/09", 2], ["22/09", 0], ["23/09", 6],
  ["24/09", 11], ["25/09", 7], ["26/09", 4], ["27/09", 6], ["28/09", 0], ["29/09", 9], ["30/09", 3],
];
// minutes de calcul par heure de video source (moyenne 7 jours)
const STEP_TIME = [
  ["download", 1.7], ["transcribe", 5.6], ["scenes", 0.9], ["audio", 0.4], ["moments", 1.3], ["vision", 0.8],
  ["parts", 0.6], ["captions", 0.4], ["reframe", 2.6], ["subtitles", 0.3], ["render", 7.9], ["qa", 0.3],
];

const LOG_LINES = [
  ["21:26:02", "i", "reframe", "layout=split (SPEC-76dc) · facecam localisée x=0 y=346 w=354 h=252 (visage 88 % des images clés)"],
  ["21:26:04", "i", "reframe", "clip 1/8 m1 · webcam vivante 97 % · stream split"],
  ["21:27:31", "i", "reframe", "clip 2/8 m2 · webcam vivante 95 % · stream split"],
  ["21:28:55", "i", "reframe", "clip 3/8 m3 partie 1/2 · webcam vivante 91 % · stream split"],
  ["21:30:12", "w", "reframe", "clip 3/8 m3 partie 2/2 · scène sombre, luminance moyenne 0,08 : cadre conservé"],
  ["21:31:40", "i", "reframe", "clip 4/8 m7 · webcam vivante 94 % · stream split"],
  ["21:33:07", "i", "gpu", "mediapipe blaze_face_short_range · cpu (un seul modèle lourd en VRAM : whisper sur l'autre vidéo)"],
];
