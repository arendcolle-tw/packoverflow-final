// Server-side reads from the shared knowledge graph (ideas/alberic). Reads are public, so app/ holds no token.
// Only topics, counts and the owner's own words leave this file: no scores, no per-person views.

const GRAPH_URL = (process.env.GRAPH_URL || "https://knowledge-graph-323892475788.us-central1.run.app").replace(/\/+$/, "");
const TIMEOUT_MS = 5000;

async function get(path) {
  const res = await fetch(GRAPH_URL + path, { signal: AbortSignal.timeout(TIMEOUT_MS) });
  if (!res.ok) throw new Error(`graph ${path} answered ${res.status}`);
  return res.json();
}

let rowsCache = { at: 0, rows: [] };
async function rows() {
  if (Date.now() - rowsCache.at > 30000) rowsCache = { at: Date.now(), rows: await get("/rows") };
  return rowsCache.rows;
}

const name = (p) => (p ? p.charAt(0).toUpperCase() + p.slice(1) : p);
const topicLabel = (t) => (t ? (t.charAt(0).toUpperCase() + t.slice(1)).replace(/-/g, " ") : "unknown topic");
const words = (s) => new Set(String(s).toLowerCase().match(/[a-z0-9]{4,}/g) || []);

// dark, single_point and fading all read as "going dark" on stage; the reason says which.
const STATUS = {
  healthy: { label: "Healthy", reason: "Several people still reason about this." },
  single_point: { label: "Going dark", reason: "Only one person still reasons about this." },
  fading: { label: "Going dark", reason: "Nobody has reasoned about this lately." },
  dark: { label: "Going dark", reason: "No human ever reasoned about this. Only the AI did." },
};

function whysFor(person, question) {
  const q = words(question);
  const all = person.evidence.flatMap((e) => e.whys.map((w) => ({ ...w, at: e.at, source_id: e.source_id })));
  const overlap = (w) => [...words(w.why)].filter((x) => q.has(x)).length;
  const matching = all.filter((w) => overlap(w) > 0).sort((a, b) => overlap(b) - overlap(a));
  return matching.length ? matching.slice(0, 2) : all.slice(0, 1);
}

async function ask(question) {
  const [answer, allRows] = await Promise.all([get("/who_knows?q=" + encodeURIComponent(question)), rows()]);
  const reasoned = answer.people.filter((p) => p.evidence.length);
  const top = reasoned.find((p) => p.person === answer.owner) || reasoned[0];
  const status = STATUS[answer.status] || STATUS.dark;
  if (!top) return { live: true, question, status: "dark", ...status, person: null, whys: [] };

  const whys = whysFor(top, question);
  const src = whys[0] || { source_id: top.evidence[0].source_id, at: top.evidence[0].at };
  const row = allRows.find((r) => r.source_id === src.source_id);
  return {
    live: true,
    question,
    status: answer.status,
    ...status,
    person: name(top.person),
    owner: Boolean(answer.owner),
    others: reasoned.length - 1,
    whys: whys.map((w) => ({ role: w.role.replace(/_/g, " "), why: w.why })),
    source: { kind: row ? row.source.replace(/_/g, " ") : "claude session", at: src.at, topic: topicLabel(row && row.topic) },
  };
}

async function map() {
  const risks = await get("/risks");
  return {
    live: true,
    topics: risks.map((t) => ({
      topic: topicLabel(t.topic),
      status: t.status,
      ...(STATUS[t.status] || STATUS.dark),
      people: t.people.length,
      human: t.human_count,
      ai: t.ai_count,
      days: t.days_since,
    })),
  };
}

// Shown when the graph cannot be reached, always labeled as a sample. Same shape as the live answers.
const SAMPLE_ASK = {
  live: false,
  question: "Who knows how our Aikido scan was set up?",
  status: "single_point",
  ...STATUS.single_point,
  person: "Wout",
  owner: true,
  others: 0,
  whys: [{ role: "decided", why: "so someone who checks our screenshots of how we used aikido sees this" }],
  source: { kind: "claude session", at: "2026-09-30T20:26:49Z", topic: "Aikido security scan" },
};
const SAMPLE_MAP = {
  live: false,
  topics: [
    ["knowledge-clock", "dark", 0, 0, 1, null],
    ["idea-and-scope", "single_point", 1, 8, 15, 0],
    ["pitch-and-submission", "single_point", 1, 1, 9, 0],
    ["aikido-security-scan", "single_point", 1, 3, 6, 19],
    ["github-repo-setup", "single_point", 1, 3, 2, 19],
  ].map(([topic, status, people, human, ai, days]) => ({ topic: topicLabel(topic), status, ...STATUS[status], people, human, ai, days })),
};

async function safe(fn, sample, label) {
  try {
    return await fn();
  } catch (err) {
    console.error(`${label}: ${err.message}`);
    return sample;
  }
}

module.exports = {
  GRAPH_URL,
  ask: (q) => safe(() => ask(q), { ...SAMPLE_ASK, asked: q }, "ask"),
  map: () => safe(map, SAMPLE_MAP, "map"),
};
