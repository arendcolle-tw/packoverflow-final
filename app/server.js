const http = require("http");
const fs = require("fs");
const path = require("path");

// Paste the pitch video URL here (YouTube/Vimeo embed URL or a direct .mp4).
// VIDEO_URL env var on Cloud Run overrides it.
const VIDEO_URL = process.env.VIDEO_URL || "";

// app/slides/ holds a starter deck. Replace it with the built deck (index.html plus assets).
const SLIDES_DIR = path.join(__dirname, "slides");
const CONNECTOR = "https://knowledge-mcp-323892475788.us-central1.run.app";
const graph = require("./graph");

// Story wording in one place, so the headline and demo role are easy to flip.
const HEADLINE = "Claude can tell you what. Your colleagues know why.";
const ROLE = "You just inherited a payroll client portfolio. Before you trust the agent, find who still understands the work.";
const ASK_DEFAULT = "Who knows how our Aikido scan was set up?";
const ASK_EXAMPLES = [ASK_DEFAULT, "Why did we narrow the idea scope?", "How was the GitHub repo set up?"];

const TYPES = {
  ".html": "text/html; charset=utf-8", ".css": "text/css", ".js": "text/javascript",
  ".json": "application/json", ".png": "image/png", ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg", ".svg": "image/svg+xml", ".webp": "image/webp",
  ".gif": "image/gif", ".mp4": "video/mp4", ".webm": "video/webm",
  ".woff": "font/woff", ".woff2": "font/woff2", ".pdf": "application/pdf",
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

function slidesBlock() {
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

function page() {
  return `<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PackOverflow</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,600;12..96,800&family=Inter:wght@400;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/theme.css">
<style>
  header { padding: 56px 20px 0; max-width: 1100px; margin: 0 auto; }
  h1 { font-size: clamp(2.6rem, 7vw, 5rem); font-weight: 800; margin: 12px 0 16px; }
  .tag { color: var(--muted); font-size: 1.15rem; max-width: 46ch; margin: 0 0 32px; }
  nav { display: inline-flex; gap: 4px; padding: 4px; }
  nav button { background: none; border: 0; border-radius: 999px; color: var(--muted); font: inherit; font-weight: 600; padding: 8px 20px; cursor: pointer; }
  nav button[aria-selected="true"] { color: var(--navy-950); background: var(--ai); }
  main { max-width: 1100px; margin: 0 auto; padding: 28px 20px 64px; }
  section[hidden] { display: none; }
  .card { padding: 28px; margin-bottom: 18px; }
  .card h2 { font-size: 1.5rem; margin-bottom: 8px; }
  .card p { color: var(--muted); margin: 0 0 18px; }
  ol { margin: 0; padding-left: 20px; } li { margin: 10px 0; }
  code.prompt { display: inline-block; background: rgba(0, 13, 58, 0.6); border: 1px solid var(--glass-line); border-radius: 10px; padding: 6px 12px; font: 0.95rem var(--mono); cursor: pointer; }
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
  @media (max-width: 720px) { .who, .topic { grid-template-columns: 1fr; } }
</style></head>
<body>
<header>
  <div class="kicker">Tectonic Hackathon final · SD Worx track</div>
  <h1>Pack<span class="grad-human">Overflow</span></h1>
  <p class="tag">${esc(HEADLINE)}</p>
  <nav class="glass" role="tablist">
    <button role="tab" data-tab="ask" aria-selected="true">Ask</button>
    <button role="tab" data-tab="map" aria-selected="false">Map</button>
    <button role="tab" data-tab="review" aria-selected="false">Review your day</button>
    <button role="tab" data-tab="demo" aria-selected="false">Connect</button>
    <button role="tab" data-tab="video" aria-selected="false">Video</button>
    <button role="tab" data-tab="slides" aria-selected="false">Slides</button>
  </nav>
</header>
<main>
  <section id="ask">
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
    if (!document.getElementById(name)) name = "ask";
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

const server = http.createServer((req, res) => {
  const urlPath = req.url.split("?")[0];
  if (urlPath === "/healthz") {
    res.writeHead(200, { "Content-Type": "text/plain" });
    return res.end("ok");
  }
  if (urlPath === "/api/ask" || urlPath === "/api/map") {
    const q = (new URL(req.url, "http://x").searchParams.get("q") || "").trim().slice(0, 300);
    const work = urlPath === "/api/map" ? graph.map() : graph.ask(q || ASK_DEFAULT);
    return work.then((body) => {
      res.writeHead(200, { "Content-Type": "application/json", "Cache-Control": "no-store" });
      res.end(JSON.stringify(body));
    });
  }
  if (urlPath === "/theme.css") {
    res.writeHead(200, { "Content-Type": TYPES[".css"] });
    return res.end(fs.readFileSync(path.join(__dirname, "theme.css")));
  }
  if (urlPath === "/slides" || urlPath.startsWith("/slides/")) {
    try { return serveSlide(urlPath, res); } catch { res.writeHead(400); return res.end(); }
  }
  res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
  res.end(page());
});

const port = process.env.PORT || 8080;
server.listen(port, () => console.log(`listening on ${port}`));
