// Voice: call the knowledge base. An ElevenLabs agent holds the voice; its two server tools call the endpoints below.
// The answers come from the shared knowledge graph (graph.js). The payroll-export topic is seeded, labeled demo data,
// scored offline by the same ranking (scripts/voice_demo.py writes voice/demo-answer.json).
// The API key and agent id live only in env vars on Cloud Run; the browser gets a short-lived signed URL.

const fs = require("fs");
const path = require("path");
const graph = require("./graph");

const API = "https://api.elevenlabs.io";
const KEY = process.env.ELEVENLABS_API_KEY || "";
const AGENT_ID = process.env.ELEVENLABS_AGENT_ID || "";
const DEMO = JSON.parse(fs.readFileSync(path.join(__dirname, "voice", "demo-answer.json"), "utf8"));
const DEMO_MATCH = /payroll|export|sftp|retr(y|ies)|bank/i;
const SDK = path.join(__dirname, "node_modules", "@elevenlabs", "client", "dist", "lib.iife.js");
const RECORDING = path.join(__dirname, "voice", "recorded-call.mp3");
const RECORDING_TIMES = path.join(__dirname, "voice", "recorded-call.json");

const name = (p) => (p ? p.charAt(0).toUpperCase() + p.slice(1) : p);
const ago = (iso) => {
  if (!iso) return "never";
  const d = Math.round((Date.now() - new Date(iso)) / 86400000);
  return d <= 0 ? "today" : d === 1 ? "yesterday" : `${d} days ago`;
};

// Who was most active on a topic: a plain count of rows, not a score.
function busiest(rows, topic) {
  const counts = {};
  for (const r of rows) if (r.topic === topic) counts[r.person] = (counts[r.person] || 0) + 1;
  const top = Object.entries(counts).sort((a, b) => b[1] - a[1])[0];
  return top ? top[0] : null;
}

async function lookup(topic) {
  if (DEMO_MATCH.test(topic)) {
    const answer = graph.shape(topic, DEMO.who_knows, DEMO.rows);
    return { demo: true, answer, rows: DEMO.rows, risks: DEMO.risks };
  }
  const answer = await graph.ask(topic);
  const [rows, risks] = answer.live
    ? await Promise.all([graph.rows(), graph.risks()]).catch(() => [[], []])
    : [[], []];
  return { demo: false, answer, rows, risks };
}

const rawTopic = (found) => (found.answer.source && found.answer.source.id) || null;

async function whoKnows(topic) {
  const found = await lookup(topic);
  const a = found.answer;
  const note = found.demo ? "Demo data: a seeded example topic, not a real colleague."
    : a.live === false ? "Sample data: the live knowledge base was unreachable." : "Live data from the team's real AI sessions.";
  if (!a.person) return { topic, data: note, nobody_knows: true, say: "Nobody has reasoned about this. The AI did all of it." };
  const t = rawTopic(found);
  const busy = t ? busiest(found.rows, t) : null;
  return {
    topic: a.source.topic,
    data: note,
    who_knows: {
      name: a.person,
      their_own_words: a.whys.map((w) => `${w.role}: "${w.why}"`),
      last_reasoned: ago(a.source.at),
      others_who_also_reasoned: a.others,
    },
    busiest_on_this: busy && name(busy) !== a.person
      ? { name: name(busy), note: "Most active on this topic, but mostly accepted the AI's answers as they were." }
      : { name: a.person, note: "The busiest person here is also the one who knows." },
  };
}

async function goingDark(topic) {
  const found = await lookup(topic);
  const a = found.answer;
  const t = rawTopic(found);
  const risk = t && found.risks.find((r) => r.topic === t);
  const status = risk ? risk.status : a.status;
  const label = (graph.STATUS[status] || graph.STATUS.dark);
  return {
    topic: a.source ? a.source.topic : topic,
    data: found.demo ? "Demo data: a seeded example topic." : "Live data.",
    going_dark: status !== "healthy",
    in_one_sentence: label.reason,
    people_who_still_reason: risk ? risk.people.length : (a.person ? 1 + (a.others || 0) : 0),
    last_human_reasoning: risk ? ago(risk.last_human_reasoning_at) : a.source ? ago(a.source.at) : "never",
  };
}

// Token endpoint limits: per caller and overall, because voice minutes are paid credits.
const hits = new Map();
let global = [];
function allowed(ip) {
  const now = Date.now();
  global = global.filter((t) => now - t < 3600e3);
  const mine = (hits.get(ip) || []).filter((t) => now - t < 600e3);
  if (mine.length >= 6 || global.length >= 60) return false;
  mine.push(now); global.push(now); hits.set(ip, mine);
  if (hits.size > 5000) hits.clear();
  return true;
}

async function signedUrl() {
  const headers = KEY ? { "xi-api-key": KEY } : {};
  const res = await fetch(`${API}/v1/convai/conversation/get-signed-url?agent_id=${encodeURIComponent(AGENT_ID)}`,
    { headers, signal: AbortSignal.timeout(8000) });
  if (!res.ok) throw new Error(`signed url ${res.status}`);
  return (await res.json()).signed_url;
}

function send(res, code, body, type = "application/json") {
  res.writeHead(code, { "Content-Type": type, "Cache-Control": "no-store" });
  res.end(typeof body === "string" || Buffer.isBuffer(body) ? body : JSON.stringify(body));
}

// Returns true when it handled the request.
function handle(req, res, urlPath) {
  if (!urlPath.startsWith("/api/voice/") && !urlPath.startsWith("/voice/")) return false;
  const params = new URL(req.url, "http://x").searchParams;
  const topic = (params.get("topic") || "").trim().slice(0, 300);

  if (urlPath === "/api/voice/who-knows" || urlPath === "/api/voice/going-dark") {
    if (!topic) { send(res, 400, { error: "topic is required" }); return true; }
    (urlPath === "/api/voice/who-knows" ? whoKnows(topic) : goingDark(topic))
      .then((body) => send(res, 200, body))
      .catch((err) => { console.error(`voice: ${err.message}`); send(res, 200, { topic, nobody_knows: true, say: "I could not reach the knowledge base just now." }); });
    return true;
  }
  if (urlPath === "/api/voice/session" && req.method === "POST") {
    if (!AGENT_ID) { send(res, 503, { error: "Live calling is not set up on this server. Play the recorded call instead." }); return true; }
    const fwd = String(req.headers["x-forwarded-for"] || "").split(",").map((s) => s.trim()).filter(Boolean);
    const ip = fwd[fwd.length - 1] || req.socket.remoteAddress || "?";
    if (!allowed(ip)) { send(res, 429, { error: "Too many calls. Wait a few minutes, or play the recorded call." }); return true; }
    signedUrl()
      .then((url) => send(res, 200, { signedUrl: url }))
      .catch((err) => { console.error(`voice session: ${err.message}`); send(res, 502, { error: "Could not start a call. Play the recorded call instead." }); });
    return true;
  }
  if (urlPath === "/voice/call.js") {
    fs.readFile(path.join(__dirname, "voice", "call.js"), (err, data) => (err ? send(res, 404, "missing", "text/plain") : send(res, 200, data, "text/javascript")));
    return true;
  }
  if (urlPath === "/voice/sdk.js") {
    fs.readFile(SDK, (err, data) => (err ? send(res, 404, "sdk missing", "text/plain") : send(res, 200, data, "text/javascript")));
    return true;
  }
  if (urlPath === "/voice/recorded-call.mp3" || urlPath === "/voice/recorded-call.json") {
    const file = urlPath.endsWith(".mp3") ? RECORDING : RECORDING_TIMES;
    fs.readFile(file, (err, data) => (err ? send(res, 404, "not recorded yet", "text/plain")
      : send(res, 200, data, file.endsWith(".mp3") ? "audio/mpeg" : "application/json")));
    return true;
  }
  return false;
}

const STYLE = `
  .call { text-align: center; padding: 32px 24px; }
  .call h2 { font-size: clamp(1.6rem, 3.4vw, 2.3rem); max-width: 26ch; margin: 8px auto 26px; }
  .callbtns { display: flex; gap: 14px; justify-content: center; flex-wrap: wrap; }
  #callbtn { border: 0; cursor: pointer; font: 800 1.6rem var(--display); padding: 22px 64px; border-radius: 999px; }
  #callbtn.live { background: var(--coral); color: var(--text); }
  #playbtn { border: 0; cursor: pointer; font: 600 1.05rem var(--sans); padding: 22px 28px; border-radius: 999px; }
  #callstate { color: var(--muted); margin: 18px 0 0; min-height: 1.5em; }
  #captions { max-width: 760px; margin: 18px auto 0; text-align: left; }
  #captions .line { margin: 6px 0; font-size: 1.05rem; color: var(--muted); }
  #captions .line.agent { color: var(--text); }
  #captions .line.you::before { content: "You: "; color: var(--sky-300); font-weight: 600; }
  #captions .line.agent::before { content: "PackOverflow: "; color: var(--amber); font-weight: 600; }
  #datatag[hidden] { display: none; }
  #callnames { opacity: 0.25; transition: opacity 0.6s; margin-top: 18px; }
  #callnames.on { opacity: 1; }
`;

const SECTION = `
  <section id="call" hidden>
    <div class="card glass call">
      <div class="kicker">In a rush? Call it.</div>
      <h2>"What do I need to know before my meeting about the nightly payroll export?"</h2>
      <div class="callbtns">
        <button class="btn" id="callbtn">Call</button>
        <button class="btn ghost" id="playbtn">Play recorded call</button>
      </div>
      <p id="callstate">Press Call and ask out loud. You can interrupt it any time.</p>
      <audio id="recorded" src="/voice/recorded-call.mp3" preload="auto"></audio>
    </div>
    <div id="callnames">
      <div class="sample" id="datatag" hidden></div>
      <div class="who">
        <div class="card glass ai"><div class="label">Who you would ask</div><div class="name grad-ai" id="busyname">...</div>
          <p>The busiest person on this topic. Mostly accepted what the AI wrote.</p></div>
        <div class="card glass human"><div class="label">Who actually knows</div><div class="name grad-human" id="knowname">...</div>
          <blockquote id="knowwhy"></blockquote><div class="meta" id="knowwhen"></div></div>
      </div>
    </div>
    <div id="captions"></div>
  </section>`;

const SCRIPTS = `<script src="/voice/sdk.js"></script><script src="/voice/call.js"></script>`;

module.exports = { handle, whoKnows, goingDark, STYLE, SECTION, SCRIPTS };
