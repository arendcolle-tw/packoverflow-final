const http = require("http");
const fs = require("fs");
const path = require("path");

// Paste the pitch video URL here (YouTube/Vimeo embed URL or a direct .mp4).
// VIDEO_URL env var on Cloud Run overrides it.
const VIDEO_URL = process.env.VIDEO_URL || "";

// app/slides/ holds the pitch deck once it is built (index.html plus assets); until then the Slides tab shows a placeholder.
const SLIDES_DIR = path.join(__dirname, "slides");
const CONNECTOR = "https://knowledge-mcp-323892475788.us-central1.run.app";
const graph = require("./graph");
const GRAPH_BOARD = graph.GRAPH_URL + "/gaps/board";
const voice = require("./voice");

// Story wording in one place, so the headline and demo role are easy to flip.
const HEADLINE = "Claude can tell you what. Your colleagues know why.";
const ROLE = "You just inherited a payroll client portfolio. Before you trust the agent, find who still understands the work.";
const ASK_DEFAULT = "How was the GitHub repo set up?";
const ASK_EXAMPLES = [ASK_DEFAULT, "Why did we narrow the idea scope?", "Who knows how our Aikido scan was set up?"];

const TYPES = {
  ".html": "text/html; charset=utf-8", ".css": "text/css", ".js": "text/javascript",
  ".json": "application/json", ".png": "image/png", ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg", ".svg": "image/svg+xml", ".webp": "image/webp",
  ".gif": "image/gif", ".mp4": "video/mp4", ".webm": "video/webm",
  ".woff": "font/woff", ".woff2": "font/woff2", ".pdf": "application/pdf", ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
};

const esc = (s) => String(s).replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function videoBlock() {
  if (!VIDEO_URL) {
    return `<div class="empty"><h2>Video coming soon</h2><p>The pitch recording lands here before 16:00.</p></div>`;
  }
  if (/\.(mp4|webm)(\?|$)/i.test(VIDEO_URL)) {
    return `<video class="frame" src="${esc(VIDEO_URL)}" controls playsinline></video>`;
  }
  return `<iframe class="frame" src="${esc(VIDEO_URL)}" allow="autoplay; fullscreen; picture-in-picture" allowfullscreen></iframe>`;
}

// The pitch deck as images (app/slides/slide-NN.jpg, rendered from Nobikos.pdf), so it works on phones too.
function slideViewer() {
  const files = fs.existsSync(SLIDES_DIR) ? fs.readdirSync(SLIDES_DIR).filter((f) => /^slide-\d+\.jpg$/.test(f)).sort() : [];
  if (!files.length) return "";
  const dl = ["Nobikos.pdf", "Nobikos.pptx"].filter((f) => fs.existsSync(path.join(SLIDES_DIR, f)));
  return `<div class="deck">
    <img id="slideimg" src="/slides/${files[0]}" alt="Slide 1" width="1600" height="900">
    <div class="deckbar">
      <button class="btn ghost" id="prev" aria-label="Previous slide">&larr;</button>
      <span id="slideno">1 / ${files.length}</span>
      <button class="btn ghost" id="next" aria-label="Next slide">&rarr;</button>
      <span class="hint">${dl.map((f) => `<a href="/slides/${f}" download>${f.endsWith(".pdf") ? "Download PDF" : "Download PowerPoint"}</a>`).join(" · ")}</span>
    </div>
  </div>
  <script>
  (function () {
    const files = ${JSON.stringify(files)};
    let i = 0;
    const img = document.getElementById("slideimg"), no = document.getElementById("slideno");
    files.forEach((f) => { const im = new Image(); im.src = "/slides/" + f; });
    function go(k) { i = Math.max(0, Math.min(files.length - 1, k)); img.src = "/slides/" + files[i]; img.alt = "Slide " + (i + 1); no.textContent = (i + 1) + " / " + files.length; }
    document.getElementById("prev").addEventListener("click", () => go(i - 1));
    document.getElementById("next").addEventListener("click", () => go(i + 1));
    img.addEventListener("click", (e) => go(e.offsetX > img.clientWidth / 3 ? i + 1 : i - 1));
    addEventListener("keydown", (e) => {
      if (document.getElementById("deck").hidden) return;
      if (["ArrowRight", "PageDown", " "].includes(e.key)) { e.preventDefault(); go(i + 1); }
      if (["ArrowLeft", "PageUp"].includes(e.key)) { e.preventDefault(); go(i - 1); }
    });
  })();
  </script>`;
}

function slidesBlock() {
  const viewer = slideViewer();
  if (viewer) return viewer;
  if (fs.existsSync(path.join(SLIDES_DIR, "deck.pdf"))) {
    return `<iframe class="frame" src="/slides/deck.pdf" title="Pitch deck"></iframe>
      <p class="hint"><a href="/slides/deck.pdf" target="_blank">Open the deck full screen</a>${fs.existsSync(path.join(SLIDES_DIR, "deck.pptx")) ? ` · <a href="/slides/deck.pptx">Download PowerPoint</a>` : ""}</p>`;
  }
  if (fs.existsSync(path.join(SLIDES_DIR, "deck.pptx"))) {
    return `<div class="empty"><h2>Pitch deck</h2><p><a class="btn" href="/slides/deck.pptx">Download the PowerPoint</a></p></div>`;
  }
  if (fs.existsSync(path.join(SLIDES_DIR, "index.html"))) {
    return `<iframe class="frame" src="/slides/index.html" allowfullscreen></iframe>
      <p class="hint"><a href="/slides/index.html" target="_blank">Open slides full screen</a></p>`;
  }
  return `<div class="empty"><h2>Slides coming soon</h2><p>The pitch deck lands here once it is built.</p></div>`;
}

// Seeded "review your day" items for the demo role (consultant on an inherited PC 200 portfolio).
const REVIEW_SEED = [
  { kind: "Procedure from your screen", human: true, title: "Apply the PC 200 indexation (2.21% on 1 November)",
    steps: ["Open the Legal Watch mail on PC 200 indexation", "Export October salaries from mysdworx to Excel", "Filter on joint committee 200", "Raise the base by 2.21% and check against the scale", "Import the new base in mysdworx before the November run"] },
  { kind: "You corrected Claude", human: true, title: "\"Keep E-1002 on the old base: PC 124 does not index on 1 November.\"",
    note: "Your reason, in your words. Sharing it lets the next consultant on this portfolio find you." },
  { kind: "You accepted Claude's answer", human: false, title: "Reply to the client about payslip timing",
    note: "Claude drafted it and you sent it unchanged. That is fine, it just is not evidence you know this, so it stays private." },
];

// The main page: one end-to-end flow. Data in, ask, answer, call. The older tabbed page stays at /full.
// Tristan's Slack demo recording. Drop it at app/video/demo.mp4 (or set VIDEO_URL); the slot stays hidden until then.
const DEMO_VIDEO = path.join(__dirname, "video", "demo.mp4");

function demoVideo() {
  if (fs.existsSync(DEMO_VIDEO)) return `<video class="frame demo" src="/video/demo.mp4" poster="/video/demo-poster.jpg" controls playsinline preload="metadata"></video>`;
  return VIDEO_URL ? videoBlock() : "";
}


// What Nobikos is and its use cases, shown under the call. Status per item is kept honest.
const DESCRIPTION = "Facts are not knowledge. AI can tell you what was done and how, but only a person knows why, and the why is what matters. And now that AI writes most of the text, we have to tell what the AI generated apart from what a human actually reasoned. Nobikos keeps only the human reasoning. It picks up the decisions people make in their AI sessions, the moments they correct the AI or explain why, and stores each one with the person behind it and their reason in their own words. Anyone can ask in Slack or from their AI assistant and get the answer, who knows it and why. When nobody has recorded it yet, Nobikos tags the person most likely to know, and their reply becomes the next answer.";
const USE_CASES = [
  ["For the employee", [
    ["Find who knows", "Live", "Ask \"who knows X\" in Slack or any assistant. You get the colleague who actually worked it out, with their reason in their own words. An \"Ask\" button opens the chat with them."],
    ["Call the knowledge base", "Live", "Ask by voice instead of interrupting a senior. The call above is this use case."],
    ["Get the steps when starting a task", "Prototype", "The recorder learns how colleagues did a manual task and turns it into a step list. You review it before anything is shared. Works on sample data only, not merged yet."],
    ["Close a gap without writing a doc", "Built", "When the system spots work nobody ever explained, the owner gets a message to answer in a line or take a 60-second call. The answer becomes knowledge in their own words. Tested with mocks; the message to the owner is still missing."],
  ]],
  ["For the employer", [
    ["See where knowledge is at risk", "Live", "Shows topics that one person or nobody holds."],
    ["Watch gaps close", "Built", "A board shows each gap, the draft and the owner's real answer side by side."],
    ["Keep knowledge when people leave", "Follows from the same data", "Handovers and departures don't wipe out the why, because each reason is stored with the person who gave it."],
  ]],
  ["On the same knowledge base (roadmap)", [
    ["Onboarding path", "Roadmap", "Built around what a newcomer already knows."],
    ["Personal skill view", "Roadmap", "Visible only to the person."],
    ["Portfolio handover", "Roadmap", "See who really worked through a client's questions before you take it over."],
    ["Private fact note in meetings", "Roadmap", "A quiet note only you see when a meeting drifts from what was decided."],
    ["Any agent can ask it", "Roadmap", "Including SD Worx's own agents."],
  ]],
];

function aboutBlock() {
  return `<section class="about">
    <p class="desc">${esc(DESCRIPTION)}</p>
    ${USE_CASES.map(([group, items]) => `<h2>${esc(group)}</h2>` + items.map(([title, status, detail]) =>
      `<details class="glass uc"><summary><span>${esc(title)}</span><span class="badge s-${esc(status.split(" ")[0].toLowerCase())}">${esc(status)}</span></summary><p>${esc(detail)}</p></details>`).join("")).join("")}
    <p class="close">Less asking how, more talking why.</p>
  </section>`;
}

// The main page: only the call, plus the demo video when there is one. The longer pages stay at /flow and /full, unlinked.
// QR code of this site for the audience. Static SVGs in app/icons (made with the qrcode Python package);
// the nobikos service shows its own link, every other host the packoverflow one.
const QR = {
  nobikos: { svg: fs.readFileSync(path.join(__dirname, "icons", "qr-nobikos.svg"), "utf8"), url: "nobikos-323892475788.us-central1.run.app" },
  packoverflow: { svg: fs.readFileSync(path.join(__dirname, "icons", "qr-packoverflow.svg"), "utf8"), url: "packoverflow-wwvoo2dieq-uc.a.run.app" },
};

function qrBlock(host) {
  const q = /^nobikos/.test(host || "") ? QR.nobikos : QR.packoverflow;
  return `<div class="qr"><div class="qrimg">${q.svg}</div><p>Scan to try it<br><span>${esc(q.url)}</span></p></div>`;
}

function callPage(host) {
  const video = demoVideo();
  return `<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Nobikos</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,600;12..96,800&family=Inter:wght@400;600&display=swap" rel="stylesheet">
<link rel="icon" href="/favicon.svg" type="image/svg+xml"><link rel="icon" href="/favicon.ico" sizes="32x32"><link rel="apple-touch-icon" href="/apple-touch-icon.png">
<link rel="stylesheet" href="/theme.css">
<style>
  main { max-width: 900px; margin: 0 auto; padding: 40px 20px 64px; }
  h1 { font-size: 2.6rem; font-weight: 800; margin: 0 0 24px; }
  .card { padding: 20px; } .name { font: 800 1.8rem var(--display); margin: 6px 0; }
  .label { font-size: 0.8rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); }
  .meta { color: var(--muted); font-size: 0.9rem; }
  blockquote { margin: 8px 0; padding-left: 14px; border-left: 3px solid var(--amber); font-size: 1.05rem; }
  .sample { display: inline-block; font-size: 0.8rem; font-weight: 600; color: var(--navy-950); background: var(--amber); border-radius: 999px; padding: 2px 10px; margin-bottom: 8px; }
  .frame.demo { aspect-ratio: auto; height: auto; }
  .frame { width: 100%; aspect-ratio: 16 / 9; border: 0; border-radius: 18px; background: #000; margin-top: 28px; }
  nav { display: inline-flex; gap: 4px; padding: 4px; margin-bottom: 24px; }
  nav button { background: none; border: 0; border-radius: 999px; color: var(--muted); font: inherit; font-weight: 600; padding: 8px 20px; cursor: pointer; }
  nav button[aria-selected="true"] { color: var(--navy-950); background: var(--ai); }
  .view[hidden] { display: none; }
  .qr { display: flex; align-items: center; gap: 28px; margin-top: 28px; flex-wrap: wrap; justify-content: center; }
  .qrimg { width: min(360px, 80vw); background: #fff; border-radius: 18px; padding: 10px; }
  .qrimg svg { display: block; width: 100%; height: auto; }
  .qr p { font: 800 1.8rem var(--display); margin: 0; }
  .qr p span { font: 400 1rem var(--mono); color: var(--muted); word-break: break-all; }
  .about { margin-top: 36px; }
  .about h2 { font-size: 1.3rem; margin: 28px 0 10px; }
  .desc { font-size: 1.05rem; line-height: 1.6; }
  .uc { margin-bottom: 8px; padding: 0 18px; }
  .uc summary { cursor: pointer; padding: 14px 0; font-weight: 600; display: flex; justify-content: space-between; gap: 12px; align-items: center; }
  .uc p { color: var(--muted); margin: 0 0 14px; }
  .badge { font-size: 0.75rem; font-weight: 600; border-radius: 999px; padding: 2px 10px; white-space: nowrap; background: rgba(255,255,255,0.08); color: var(--muted); }
  .badge.s-live { background: rgba(35,219,193,0.15); color: var(--teal); }
  .badge.s-built, .badge.s-prototype { background: rgba(158,210,255,0.15); color: var(--sky-300); }
  .close { font: 800 1.6rem var(--display); margin-top: 32px; }
  .empty { text-align: center; padding: 80px 16px; border: 2px dashed var(--glass-line); border-radius: 18px; }
  .empty p, .hint { color: var(--muted); }
  .deck img { width: 100%; height: auto; border-radius: 12px; display: block; cursor: pointer; background: #000; }
  .deckbar { display: flex; align-items: center; gap: 12px; margin-top: 12px; flex-wrap: wrap; }
  .deckbar button { cursor: pointer; font: inherit; font-weight: 600; padding: 8px 18px; }
  .deckbar .hint { margin-left: auto; }
${voice.STYLE}
</style></head>
<body><main>
  <h1>Nobikos</h1>
  <nav class="glass" role="tablist">
    <button role="tab" data-view="home" aria-selected="true">Call</button>
    <button role="tab" data-view="deck" aria-selected="false">Slides</button>
    ${video ? `<button role="tab" data-view="demo" aria-selected="false">Demo</button>` : ""}
  </nav>
  <div class="view" id="home">
${voice.SECTION}
${qrBlock(host)}
${video}
${aboutBlock()}
  </div>
  <div class="view" id="deck" hidden>${slidesBlock()}</div>
  ${video ? `<div class="view" id="demo" hidden><p class="hint">Asking "who knows" in Slack: the answer, the person behind it, and what happens when nobody recorded it yet.</p>${video}</div>` : ""}
</main>
<script>
  document.getElementById("call").hidden = false;
  const views = document.querySelectorAll("nav button");
  function view(name) {
    if (!document.getElementById(name) || !["deck", "demo"].includes(name)) name = "home";
    document.querySelectorAll("video").forEach((v) => v.pause());
    views.forEach((b) => b.setAttribute("aria-selected", b.dataset.view === name));
    document.querySelectorAll(".view").forEach((v) => (v.hidden = v.id !== name));
  }
  views.forEach((b) => b.addEventListener("click", () => { history.replaceState(null, "", b.dataset.view === "deck" ? "#slides" : b.dataset.view === "demo" ? "#demo" : "#"); view(b.dataset.view); }));
  view(location.hash === "#slides" ? "deck" : location.hash === "#demo" ? "demo" : "home");
</script>
${voice.SCRIPTS}
</body></html>`;
}

function simplePage() {
  return `<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Nobikos</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,600;12..96,800&family=Inter:wght@400;600&display=swap" rel="stylesheet">
<link rel="icon" href="/favicon.svg" type="image/svg+xml"><link rel="icon" href="/favicon.ico" sizes="32x32"><link rel="apple-touch-icon" href="/apple-touch-icon.png">
<link rel="stylesheet" href="/theme.css">
<style>
  main { max-width: 900px; margin: 0 auto; padding: 40px 20px 64px; }
  h1 { font-size: 2.6rem; font-weight: 800; margin: 0 0 6px; }
  .tag { color: var(--muted); margin: 0 0 28px; }
  .step { padding: 24px; margin-bottom: 18px; }
  .step h2 { font-size: 1.35rem; margin: 4px 0 12px; }
  .meta, .card p { color: var(--muted); font-size: 0.9rem; }
  .stats { display: flex; gap: 28px; flex-wrap: wrap; margin-bottom: 14px; }
  .stats b { display: block; font: 800 2rem var(--display); color: var(--text); }
  .stats span { color: var(--muted); font-size: 0.9rem; }
  .row { border-top: 1px solid var(--glass-line); padding: 10px 0; }
  .row q { display: block; margin-top: 2px; }
  .askbar { display: flex; gap: 8px; }
  .askbar input { flex: 1; min-width: 0; background: rgba(0,13,58,0.6); border: 1px solid var(--glass-line); border-radius: 12px; color: var(--text); font: 1.05rem var(--sans); padding: 10px 14px; }
  .askbar .btn, .call .btn { border: 0; cursor: pointer; font: inherit; font-weight: 600; }
  .person { font: 800 2rem var(--display); margin: 14px 0 6px; }
  blockquote { margin: 8px 0; padding-left: 14px; border-left: 3px solid var(--amber); font-size: 1.05rem; }
  blockquote small { display: block; color: var(--muted); font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.08em; }
  .sample { display: inline-block; font-size: 0.8rem; font-weight: 600; color: var(--navy-950); background: var(--amber); border-radius: 999px; padding: 2px 10px; margin-bottom: 8px; }
  .card { padding: 20px; } .name { font: 800 1.8rem var(--display); margin: 6px 0; }
  .label { font-size: 0.8rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); }
${voice.STYLE}
  #call .call { padding: 0; text-align: left; } #call .call h2 { margin: 4px 0 16px; max-width: none; }
  #call .callbtns { justify-content: flex-start; }
  #call .who .ai, #call .call .kicker { display: none; }
  #call .glass { background: none; border: 0; backdrop-filter: none; }
  #callnames { margin-top: 14px; }
  .more { color: var(--muted); font-size: 0.9rem; }
</style></head>
<body><main>
  <h1>Nobikos</h1>
  <p class="tag">Ask who knows. Get the person and the reason in their own words, straight from the work they already do.</p>

  <section class="glass step">
    <div class="kicker">1 · The moment of doubt</div>
    <h2>The agent did the job. Something looks off. Who here still knows how this works?</h2>
    <p class="meta">The doc owner or the busiest person is often not the one who knows.</p>
  </section>

  <section class="glass step">
    <div class="kicker">2 · Nobody documents anything</div>
    <h2>It reads the AI sessions people already have</h2>
    <div id="feed" class="meta">Loading...</div>
  </section>

  <section class="glass step">
    <div class="kicker">3 · Ask</div>
    <h2>Who knows?</h2>
    <form id="askform" class="askbar">
      <input id="q" value="${esc(ASK_DEFAULT)}" maxlength="300" aria-label="Your question" autocomplete="off">
      <button class="btn" type="submit">Ask</button>
    </form>
    <div id="answer" aria-live="polite"></div>
  </section>

  <div class="glass step">
    <div class="kicker">4 · In a rush? Call it</div>
${voice.SECTION}
  </div>

  <section class="glass step">
    <div class="kicker">5 · Why SD Worx</div>
    <ul>
      <li>500 consultants run agentic payroll: find the person who knows a payroll topic in seconds.</li>
      <li>Portfolio handovers: see who really worked through a client's issues, not who is listed as owner.</li>
      <li>No knowledge base to maintain: it learns from work people already do.</li>
    </ul>
  </section>

</main>
<script>
  document.getElementById("call").hidden = false;
  const h = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const ago = (iso) => { const d = Math.round((Date.now() - new Date(iso)) / 86400000); return d <= 0 ? "today" : d === 1 ? "yesterday" : d + " days ago"; };
  const sample = (live, what) => live === false ? '<div class="sample">' + what + ': the live knowledge graph is unreachable right now</div>' : "";

  fetch("/api/feed").then((r) => r.json()).then((f) => {
    document.getElementById("feed").innerHTML = sample(f.live, "No data") +
      '<div class="stats"><div><b>' + f.rows + '</b><span>' + (f.rows === 1 ? "row" : "rows") + '</span></div><div><b>' + f.sessions + '</b><span>' + (f.sessions === 1 ? "session" : "sessions") + '</span></div><div><b>' + f.topics + '</b><span>' + (f.topics === 1 ? "topic" : "topics") + '</span></div><div><b>' + f.people + '</b><span>' + (f.people === 1 ? "person" : "people") + '</span></div></div>' +
      f.latest.map((r) => '<div class="row">' + h(r.topic) + ' · ' + h(r.source) + ' · ' + h(r.role) + ' · ' + h(ago(r.at)) + '<q>' + h(r.why) + '</q></div>').join("");
  }).catch(() => { document.getElementById("feed").textContent = "Could not load."; });

  async function ask(q) {
    const box = document.getElementById("answer");
    box.innerHTML = '<p class="meta">Asking the knowledge graph...</p>';
    let a = null;
    try { a = await (await fetch("/api/ask?q=" + encodeURIComponent(q))).json(); } catch {}
    if (!a) { box.innerHTML = '<p class="meta">Could not reach the server.</p>'; return; }
    if (!a.person) { box.innerHTML = sample(a.live, "Sample answer") + '<p class="person">Nobody yet</p><p class="meta">No one has explained or decided anything about this in their sessions.</p>'; return; }
    box.innerHTML = sample(a.live, "Sample answer") +
      '<div class="person">' + h(a.person) + '</div>' +
      a.whys.map((w) => '<blockquote><small>' + h(w.role) + '</small>"' + h(w.why) + '"</blockquote>').join("") +
      '<p class="meta">From a ' + h(a.source.kind) + ' on ' + h(a.source.topic) + ', ' + h(ago(a.source.at)) + '.</p>' +
      '<p>Want the why behind it? Ask ' + h(a.person) + ' for 20 minutes.</p>';
  }
  document.getElementById("askform").addEventListener("submit", (e) => { e.preventDefault(); const q = document.getElementById("q").value.trim(); if (q) ask(q); });
  ask(document.getElementById("q").value);
</script>
${voice.SCRIPTS}
</body></html>`;
}

function page() {
  return `<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Nobikos</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,600;12..96,800&family=Inter:wght@400;600&display=swap" rel="stylesheet">
<link rel="icon" href="/favicon.svg" type="image/svg+xml"><link rel="icon" href="/favicon.ico" sizes="32x32"><link rel="apple-touch-icon" href="/apple-touch-icon.png">
<link rel="stylesheet" href="/theme.css">
<style>
  header { padding: 56px 20px 0; max-width: 1100px; margin: 0 auto; }
  h1 { font-size: clamp(2.6rem, 7vw, 5rem); font-weight: 800; margin: 12px 0 16px; }
  .tag { color: var(--muted); font-size: 1.15rem; max-width: 46ch; margin: 0 0 32px; }
  nav { display: inline-flex; gap: 4px; padding: 4px; }
  nav button { background: none; border: 0; border-radius: 999px; color: var(--muted); font: inherit; font-weight: 600; padding: 8px 20px; cursor: pointer; }
  nav .navlink { color: var(--muted); font-weight: 600; padding: 8px 20px; text-decoration: none; border-radius: 999px; }
  nav .navlink:hover { color: var(--text); }
  nav { flex-wrap: wrap; }
  nav button[aria-selected="true"] { color: var(--navy-950); background: var(--ai); }
  main { max-width: 1100px; margin: 0 auto; padding: 28px 20px 64px; }
  section[hidden] { display: none; }
  .card { padding: 28px; margin-bottom: 18px; }
  .card h2 { font-size: 1.5rem; margin-bottom: 8px; }
  .card p { color: var(--muted); margin: 0 0 18px; }
  ol { margin: 0; padding-left: 20px; } li { margin: 10px 0; }
  code.prompt { display: inline-block; background: rgba(0, 13, 58, 0.6); border: 1px solid var(--glass-line); border-radius: 10px; padding: 6px 12px; font: 0.95rem var(--mono); cursor: pointer; }
  .frame.demo { aspect-ratio: auto; height: auto; }
  .frame { width: 100%; aspect-ratio: 16 / 9; border: 0; border-radius: 18px; background: #000; }
  .empty { text-align: center; padding: 80px 16px; border: 2px dashed var(--glass-line); border-radius: 18px; }
  .empty h2 { margin: 0 0 8px; } .empty p, .hint { color: var(--muted); }
  .role { color: var(--muted); max-width: 60ch; margin: 0 0 16px; }
  .askbar { display: flex; gap: 8px; padding: 8px; }
  .askbar input { flex: 1; min-width: 0; background: none; border: 0; color: var(--text); font: 1.1rem var(--sans); padding: 8px 12px; outline: none; }
  .askbar .btn { border: 0; cursor: pointer; font: inherit; font-weight: 600; }
  .chips { display: flex; flex-wrap: wrap; gap: 8px; margin: 12px 0 24px; }
  .chip { background: none; border: 1px solid var(--glass-line); border-radius: 999px; color: var(--muted); font: 0.9rem var(--sans); padding: 6px 14px; cursor: pointer; }
  .chip:hover { color: var(--text); border-color: var(--sky-300); }
  .sample { display: inline-block; font-size: 0.8rem; font-weight: 600; color: var(--navy-950); background: var(--amber); border-radius: 999px; padding: 2px 10px; margin-bottom: 12px; }
  .who { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
  .who .card { margin: 0; }
  .who .label { font-size: 0.85rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em; }
  .who .ai .label { color: var(--sky-300); } .who .human .label { color: var(--amber); }
  .who .name { font: 800 2.4rem/1.1 var(--display); margin: 8px 0 12px; }
  blockquote { margin: 0 0 12px; padding-left: 14px; border-left: 3px solid var(--amber); font-size: 1.1rem; }
  blockquote small { display: block; color: var(--muted); font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.08em; }
  .meta { color: var(--muted); font-size: 0.9rem; }
  .nudge { margin-top: 18px; display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
  .nudge p { margin: 0; font: 600 1.25rem var(--display); color: var(--text); flex: 1; min-width: 240px; }
  .nudge .btn { border: 0; cursor: pointer; font: inherit; font-weight: 600; }
  .status { display: inline-block; font-size: 0.8rem; font-weight: 600; border-radius: 999px; padding: 3px 12px; }
  .status.healthy { background: rgba(35, 219, 193, 0.15); color: var(--teal); }
  .status.dark { background: rgba(218, 51, 0, 0.18); color: #ff8a66; }
  .topic { display: grid; grid-template-columns: 1.4fr 1fr 1.4fr; gap: 16px; align-items: center; padding: 18px 24px; margin-bottom: 10px; }
  .topic h3 { font-size: 1.2rem; }
  .topic.risk { border-color: rgba(218, 51, 0, 0.45); }
  .bar { display: flex; height: 10px; border-radius: 999px; overflow: hidden; background: rgba(255,255,255,0.06); margin-top: 6px; }
  .bar .h { background: var(--human); } .bar .a { background: var(--ai); }
  .intro { margin-bottom: 18px; }
  .item { padding: 22px 24px; margin-bottom: 12px; }
  .item h3 { font-size: 1.15rem; margin: 6px 0 8px; }
  .item ol { color: var(--muted); margin-bottom: 14px; }
  .item .actions { display: flex; gap: 8px; }
  .item .actions button { border: 0; cursor: pointer; font: inherit; font-weight: 600; }
  .item.done { opacity: 0.55; }
  .item .result { font-weight: 600; color: var(--sky-300); }
${voice.STYLE}
  @media (max-width: 720px) { .who, .topic { grid-template-columns: 1fr; } }
</style></head>
<body>
<header>
  <div class="kicker">Tectonic Hackathon final · SD Worx track</div>
  <h1>Nobi<span class="grad-human">kos</span></h1>
  <p class="tag">${esc(HEADLINE)}</p>
  <nav class="glass" role="tablist">
    <button role="tab" data-tab="call" aria-selected="true">Call</button>
    <button role="tab" data-tab="ask" aria-selected="false">Ask</button>
    <button role="tab" data-tab="map" aria-selected="false">Map</button>
    <button role="tab" data-tab="review" aria-selected="false">Review your day</button>
    <a class="navlink" href="${GRAPH_BOARD}" target="_blank" rel="noopener">Gaps board</a>
    <button role="tab" data-tab="demo" aria-selected="false">Connect</button>
    <button role="tab" data-tab="video" aria-selected="false">Video</button>
    <button role="tab" data-tab="slides" aria-selected="false">Slides</button>
  </nav>
</header>
<main>
${voice.SECTION}
  <section id="ask" hidden>
    <p class="role">${esc(ROLE)}</p>
    <form id="askform" class="glass askbar">
      <input id="q" name="q" value="${esc(ASK_DEFAULT)}" maxlength="300" aria-label="Your question" autocomplete="off">
      <button class="btn" type="submit">Who knows?</button>
    </form>
    <div class="chips">${ASK_EXAMPLES.map((e) => `<button type="button" class="chip">${esc(e)}</button>`).join("")}</div>
    <div id="answer" aria-live="polite"></div>
  </section>
  <section id="map" hidden>
    <div class="card glass intro">
      <div class="kicker">Team coverage</div>
      <h2>Where our understanding is going dark</h2>
      <p>Topics, not people. Counts come from moments a human decided, corrected or explained why, fading over 90 days.</p>
    </div>
    <div id="maplist"></div>
  </section>
  <section id="review" hidden>
    <div class="card glass intro">
      <div class="kicker">Seeded demo data</div>
      <h2>Review your day</h2>
      <p>Anything the system knows about you, you see first. Nothing below leaves your laptop until you press Share.</p>
      <button type="button" class="btn ghost" id="reset">Reset demo</button>
    </div>
    <div id="reviewlist"></div>
  </section>
  <section id="demo" hidden>
    <div class="card glass">
      <h2>Try it in Claude</h2>
      <p>Get your personal connector URL and add it to Claude (claude.ai, desktop or Claude Code).</p>
      <a class="btn" href="${CONNECTOR}/join" target="_blank">Get my connector</a>
      <a class="btn ghost" href="${CONNECTOR}/" target="_blank">See the live knowledge map</a>
    </div>
    <div class="card glass">
      <h2>Then ask Claude</h2>
      <ol>
        <li><code class="prompt">Map my knowledge with Packoverflow</code></li>
        <li><code class="prompt">Who knows how our Aikido scan was set up?</code></li>
      </ol>
      <p class="hint" style="margin-top:12px">Click a prompt to copy it.</p>
    </div>
  </section>
  <section id="video" hidden>${videoBlock()}</section>
  <section id="slides" hidden>${slidesBlock()}</section>
</main>
<script>
  const tabs = document.querySelectorAll("nav button");
  function show(name) {
    if (!document.getElementById(name)) name = "call";
    tabs.forEach((b) => b.setAttribute("aria-selected", b.dataset.tab === name));
    document.querySelectorAll("main section").forEach((s) => (s.hidden = s.id !== name));
  }
  tabs.forEach((b) => b.addEventListener("click", () => { history.replaceState(null, "", "#" + b.dataset.tab); show(b.dataset.tab); }));
  addEventListener("hashchange", () => show(location.hash.slice(1)));
  show(location.hash.slice(1));

  const h = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const ago = (iso) => { const d = Math.round((Date.now() - new Date(iso)) / 86400000); return d <= 0 ? "today" : d === 1 ? "yesterday" : d + " days ago"; };
  const sampleTag = (live) => live ? "" : '<div class="sample">Sample answer: the live knowledge graph is unreachable right now</div>';

  async function ask(q) {
    const box = document.getElementById("answer");
    box.innerHTML = '<p class="meta">Looking for who reasoned about this...</p>';
    let a;
    try { a = await (await fetch("/api/ask?q=" + encodeURIComponent(q))).json(); } catch { a = null; }
    if (!a) { box.innerHTML = '<div class="empty"><h2>No answer</h2><p>The site could not reach its server.</p></div>'; return; }
    if (!a.person) {
      box.innerHTML = sampleTag(a.live) + '<div class="card glass"><span class="status dark">' + h(a.label) + '</span><h2 style="margin-top:12px">Nobody here can tell you why.</h2><p>' + h(a.reason) + ' Claude can still answer what. This is a topic to pair someone up on.</p></div>';
      return;
    }
    const quotes = a.whys.map((w) => '<blockquote><small>' + h(w.role) + '</small>"' + h(w.why) + '"</blockquote>').join("");
    box.innerHTML = sampleTag(a.live) +
      '<div class="who">' +
        '<div class="card glass ai"><div class="label">Who you would ask</div><div class="name grad-ai">The author</div>' +
          '<p>Claude wrote most of this work. The author of the doc or the busiest person in the thread is often the one who only prompted it.</p></div>' +
        '<div class="card glass human"><div class="label">' + (a.owner ? "Who actually knows" : "Last human who reasoned") + '</div><div class="name grad-human">' + h(a.person) + '</div>' +
          (quotes || '<p>Reasoned about this, no reason written down.</p>') +
          '<div class="meta">' + h(a.source.kind) + ' · ' + h(a.source.topic) + ' · ' + h(ago(a.source.at)) + '</div></div>' +
      '</div>' +
      '<div class="card glass nudge"><span class="status ' + (a.status === "healthy" ? "healthy" : "dark") + '" title="' + h(a.reason) + '">' + h(a.label) + '</span>' +
        '<p>Claude can tell you <span class="grad-ai">what</span>. <span class="grad-human">' + h(a.person) + '</span> knows <span class="grad-human">why</span>. 20 minutes?</p>' +
        '<button class="btn" id="book">Ask ' + h(a.person) + ' for 20 minutes</button></div>' +
      '<p class="meta">' + h(a.reason) + '</p>';
    document.getElementById("book").addEventListener("click", (e) => { e.target.textContent = "Demo: request drafted, nothing sent"; e.target.disabled = true; });
  }
  document.getElementById("askform").addEventListener("submit", (e) => { e.preventDefault(); const q = document.getElementById("q").value.trim(); if (q) ask(q); });
  document.querySelectorAll(".chip").forEach((c) => c.addEventListener("click", () => { document.getElementById("q").value = c.textContent; ask(c.textContent); }));
  ask(document.getElementById("q").value);

  async function loadMap() {
    const box = document.getElementById("maplist");
    let m;
    try { m = await (await fetch("/api/map")).json(); } catch { m = { topics: [] }; }
    box.innerHTML = (m.live === false ? '<div class="sample">Sample data: the live knowledge graph is unreachable right now</div>' : "") +
      m.topics.map((t) => {
        const total = Math.max(t.human + t.ai, 1);
        return '<div class="glass topic' + (t.status === "healthy" ? "" : " risk") + '">' +
          '<div><h3>' + h(t.topic) + '</h3><span class="status ' + (t.status === "healthy" ? "healthy" : "dark") + '">' + h(t.label) + '</span></div>' +
          '<div class="meta"><strong style="color:var(--text);font-size:1.4rem">' + t.people + '</strong> ' + (t.people === 1 ? "person reasons" : "people reason") + ' about this<br>' +
            (t.days == null ? "never by a human" : "last human reasoning " + (t.days === 0 ? "today" : t.days + " days ago")) + '</div>' +
          '<div class="meta">' + h(t.reason) + '<div class="bar"><div class="h" style="width:' + (100 * t.human / total) + '%"></div><div class="a" style="width:' + (100 * t.ai / total) + '%"></div></div>' +
            '<span class="grad-human">' + t.human + ' human</span> · <span class="grad-ai">' + t.ai + ' AI only</span></div>' +
        '</div>';
      }).join("");
  }
  loadMap();

  const SEED = ${JSON.stringify(REVIEW_SEED)};
  function renderReview() {
    document.getElementById("reviewlist").innerHTML = SEED.map((it, i) =>
      '<div class="glass item" data-i="' + i + '"><div class="kicker" style="color:' + (it.human ? "var(--amber)" : "var(--sky-300)") + '">' + h(it.kind) + '</div>' +
      '<h3>' + h(it.title) + '</h3>' + (it.steps ? '<ol>' + it.steps.map((s) => '<li>' + h(s) + '</li>').join("") + '</ol>' : '<p class="meta">' + h(it.note) + '</p>') +
      '<div class="actions"><button class="btn" data-a="Shared with your team">Share</button><button class="btn ghost" data-a="Skipped, stays on your laptop">Skip</button><button class="btn ghost" data-a="Forgotten, deleted from your laptop">Forget</button></div></div>').join("");
    document.querySelectorAll(".item .actions button").forEach((b) => b.addEventListener("click", () => {
      const item = b.closest(".item"); item.classList.add("done");
      b.parentElement.outerHTML = '<div class="result">' + h(b.dataset.a) + '</div>';
    }));
  }
  document.getElementById("reset").addEventListener("click", renderReview);
  renderReview();
  document.querySelectorAll("code.prompt").forEach((c) => c.addEventListener("click", () => {
    navigator.clipboard && navigator.clipboard.writeText(c.textContent);
    const t = c.textContent; c.textContent = "Copied"; setTimeout(() => (c.textContent = t), 900);
  }));
</script>
${voice.SCRIPTS}
</body></html>`;
}

function serveSlide(urlPath, res) {
  const rel = decodeURIComponent(urlPath.replace(/^\/slides\/?/, "")) || "index.html";
  const file = path.resolve(SLIDES_DIR, rel);
  if (!file.startsWith(SLIDES_DIR + path.sep)) {
    res.writeHead(403); return res.end();
  }
  fs.readFile(file, (err, data) => {
    if (err) { res.writeHead(404); return res.end("not found"); }
    res.writeHead(200, { "Content-Type": TYPES[path.extname(file).toLowerCase()] || "application/octet-stream" });
    res.end(data);
  });
}

// Sent on every response. The mic is for the Call tab; frames only from this site (the slides tab).
const SECURITY_HEADERS = {
  "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "SAMEORIGIN",
  "Content-Security-Policy": "frame-ancestors 'self'; base-uri 'self'; object-src 'none'; form-action 'self'",
  "Referrer-Policy": "strict-origin-when-cross-origin",
  "Permissions-Policy": "microphone=(self), camera=(), geolocation=()",
};

const server = http.createServer((req, res) => {
  for (const [k, v] of Object.entries(SECURITY_HEADERS)) res.setHeader(k, v);
  const urlPath = req.url.split("?")[0];
  if (urlPath === "/healthz") {
    res.writeHead(200, { "Content-Type": "text/plain" });
    return res.end("ok");
  }
  if (urlPath === "/api/feed") {
    return graph.feed().then((body) => {
      res.writeHead(200, { "Content-Type": "application/json", "Cache-Control": "no-store" });
      res.end(JSON.stringify(body));
    });
  }
  if (urlPath === "/api/ask" || urlPath === "/api/map") {
    const q = (new URL(req.url, "http://x").searchParams.get("q") || "").trim().slice(0, 300);
    const work = urlPath === "/api/map" ? graph.map() : graph.ask(q || ASK_DEFAULT);
    return work.then((body) => {
      res.writeHead(200, { "Content-Type": "application/json", "Cache-Control": "no-store" });
      res.end(JSON.stringify(body));
    });
  }
  if (voice.handle(req, res, urlPath)) return;
  const ICONS = { "/favicon.svg": "image/svg+xml", "/favicon.ico": "image/x-icon", "/apple-touch-icon.png": "image/png" };
  if (ICONS[urlPath]) {
    return fs.readFile(path.join(__dirname, "icons", urlPath.slice(1)), (err, data) => {
      if (err) { res.writeHead(404); return res.end(); }
      res.writeHead(200, { "Content-Type": ICONS[urlPath], "Cache-Control": "public, max-age=86400" });
      res.end(data);
    });
  }
  if (urlPath === "/video/demo-poster.jpg") {
    return fs.readFile(path.join(__dirname, "video", "demo-poster.jpg"), (err, data) => {
      if (err) { res.writeHead(404); return res.end(); }
      res.writeHead(200, { "Content-Type": "image/jpeg" }); res.end(data);
    });
  }
  if (urlPath === "/video/demo.mp4") {
    fs.stat(DEMO_VIDEO, (err, st) => {
      if (err) { res.writeHead(404); return res.end("no video yet"); }
      // Range support, so browsers can seek and Safari plays it.
      const m = /bytes=(\d*)-(\d*)/.exec(req.headers.range || "");
      let start = 0, end = st.size - 1;
      if (m && (m[1] || m[2])) {
        start = m[1] ? Number(m[1]) : Math.max(0, st.size - Number(m[2]));
        end = m[1] && m[2] ? Math.min(Number(m[2]), st.size - 1) : st.size - 1;
        if (start > end) { res.writeHead(416, { "Content-Range": `bytes */${st.size}` }); return res.end(); }
        res.writeHead(206, { "Content-Type": "video/mp4", "Accept-Ranges": "bytes", "Content-Range": `bytes ${start}-${end}/${st.size}`, "Content-Length": end - start + 1 });
      } else {
        res.writeHead(200, { "Content-Type": "video/mp4", "Accept-Ranges": "bytes", "Content-Length": st.size });
      }
      fs.createReadStream(DEMO_VIDEO, { start, end }).pipe(res);
    });
    return;
  }
  if (urlPath === "/theme.css") {
    res.writeHead(200, { "Content-Type": TYPES[".css"] });
    return res.end(fs.readFileSync(path.join(__dirname, "theme.css")));
  }
  if (urlPath === "/slides" || urlPath.startsWith("/slides/")) {
    try { return serveSlide(urlPath, res); } catch { res.writeHead(400); return res.end(); }
  }
  res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
  res.end(urlPath === "/full" ? page() : urlPath === "/flow" ? simplePage() : callPage(req.headers.host));
});

const port = process.env.PORT || 8080;
server.listen(port, () => console.log(`listening on ${port}`));
