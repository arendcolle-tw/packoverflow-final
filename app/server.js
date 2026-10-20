const http = require("http");
const fs = require("fs");
const path = require("path");

// Paste the pitch video URL here (YouTube/Vimeo embed URL or a direct .mp4).
// VIDEO_URL env var on Cloud Run overrides it.
const VIDEO_URL = process.env.VIDEO_URL || "";

// app/slides/ holds a starter deck. Replace it with the built deck (index.html plus assets).
const SLIDES_DIR = path.join(__dirname, "slides");
const CONNECTOR = "https://knowledge-mcp-323892475788.us-central1.run.app";

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
</style></head>
<body>
<header>
  <div class="kicker">Tectonic Hackathon final · SD Worx track</div>
  <h1>Pack<span class="grad-human">Overflow</span></h1>
  <p class="tag">Who actually knows this, not who only prompted it.</p>
  <nav class="glass" role="tablist">
    <button role="tab" data-tab="demo" aria-selected="true">Demo</button>
    <button role="tab" data-tab="video" aria-selected="false">Video</button>
    <button role="tab" data-tab="slides" aria-selected="false">Slides</button>
  </nav>
</header>
<main>
  <section id="demo">
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
    if (!document.getElementById(name)) name = "demo";
    tabs.forEach((b) => b.setAttribute("aria-selected", b.dataset.tab === name));
    document.querySelectorAll("main section").forEach((s) => (s.hidden = s.id !== name));
  }
  tabs.forEach((b) => b.addEventListener("click", () => { history.replaceState(null, "", "#" + b.dataset.tab); show(b.dataset.tab); }));
  addEventListener("hashchange", () => show(location.hash.slice(1)));
  show(location.hash.slice(1));
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
