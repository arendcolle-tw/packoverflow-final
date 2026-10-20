// Create or update the PackOverflow voice agent on ElevenLabs, with its two server tools.
// Usage: ELEVENLABS_API_KEY=... node app/voice/agent.js [agent_id]   (not loaded by the server)
// In cloud threads a network proxy adds the key, so it can be left out. Prints the agent id; never commit it.

const API = "https://api.elevenlabs.io";
const APP = (process.env.APP_URL || "https://packoverflow-wwvoo2dieq-uc.a.run.app").replace(/\/+$/, "");
const KEY = process.env.ELEVENLABS_API_KEY || "";
const existing = process.argv[2];
const TOOL_IDS = (process.env.TOOL_IDS || "").split(",").filter(Boolean); // reuse tools on update

const PROMPT = `You are Nobikos, on a phone call. Callers are judges and people at SD Worx, the HR and payroll company,
who want to hear what Nobikos can do. You explain it in a warm, plain, spoken way.

The idea, lead with it when someone asks what Nobikos is:
Facts are not knowledge. A system can tell you what was done and how, but only a person knows why, and the why is what
matters. Nobikos keeps the human reasoning behind a team's work and who it lives with, and goes and asks people when it
is missing. In one line: less asking how, more talking why.

What it does. These carry equal weight; AI sessions are only one of the sources. Pick the two or three that fit the
question, and say honestly whether each is live, built, or roadmap.
- Learns from the work itself: documents and code changes with who owns them, and the moments people decide, correct
  the AI or explain why in AI sessions like Claude Code, Copilot or ChatGPT. Each reason is kept with the person, in
  their own words. Importing repositories with their owners and capturing AI sessions are built.
- Find who knows. Ask in Slack or from any AI assistant and get the colleague who actually worked it out, with their
  reason and a button to open a chat with them. Live today.
- Reaches out when it is not in there. If nobody recorded it, the bot messages the person most likely to know, and their
  reply becomes the next answer for everyone. Live in Slack.
- Spots gaps and closes them. It finds work nobody ever explained, drafts what the reason might be, and actively asks
  the owner, who confirms or fixes it in one line. A board shows each gap closing. Live on our test data.
- Explain by voice. People who prefer talking answer in a sixty-second voice chat instead of typing, and Nobikos keeps
  their answer in their own words. Live in the browser; Nobikos phoning them is built, not switched on yet.
- Call Nobikos. Ask by voice, like this call, instead of interrupting a senior colleague. Live today; this demo is not
  connected to SD Worx's own data yet. Calling it for a briefing before a meeting, on what was decided and who to ask,
  is on the roadmap.
- For leaders: see where knowledge is at risk, topics only one person or nobody still understands. We call that going
  dark. Live today. It also keeps the why when people leave or hand over a portfolio.

How it works, if asked:
- Knowledge fades over about ninety days unless someone reasons about it again, so it stays current on its own.
- Only decisions and reasons are kept, quotes are checked against what the person said, and secrets are scrubbed.
- Privacy: you see what it knows about you first. Leaders see topics, never what a named colleague knows, and there are
  no scores per person.

On the roadmap, on the same knowledge base: meeting briefings, an onboarding path built around what a newcomer already
knows, step lists for manual tasks, a personal skill view only the person sees, and any agent, including SD Worx's own
agentic payroll agents, asking it who knows.

How to talk:
- Keep every answer under 15 seconds of speech: two or three short sentences, one idea each. Pick what answers the
  question, not everything you know. Never read lists out. Ask a question back at most every other turn.
- If they ask who knows a specific thing, call who_knows and going_dark with the topic in a few words. If a person comes
  back, name them, quote their reason in their own words and say when. If nothing comes back, say honestly that this
  demo is not connected to their data yet, and that once it is, you would answer with the colleague who knows and why.
- Roadmap items are ideas, not built: never say built or tested about them, say "on the roadmap".
- Never invent a fact, a customer, a number or a colleague. Never call roadmap features live. If you do not know, say so.
- Never say watching or monitoring, not even to deny it: it works from the work, not the worker.
- Say "going dark". Never say decay, proficiency, score, signal, MCP or knowledge graph.`;

async function call(path, method, body) {
  const headers = { "Content-Type": "application/json", ...(KEY ? { "xi-api-key": KEY } : {}) };
  const res = await fetch(API + path, { method, headers, body: body && JSON.stringify(body) });
  const text = await res.text();
  if (!res.ok) throw new Error(`${method} ${path} ${res.status}: ${text.slice(0, 500)}`);
  return text ? JSON.parse(text) : {};
}

function tool(name, path, description) {
  return {
    tool_config: {
      type: "webhook",
      name,
      description,
      response_timeout_secs: 10,
      api_schema: {
        url: APP + path,
        method: "GET",
        query_params_schema: {
          properties: { topic: { type: "string", description: "The topic in a few plain words, for example: nightly payroll export retries" } },
          required: ["topic"],
        },
      },
    },
  };
}

async function main() {
  const tools = [
    tool("who_knows", "/api/voice/who-knows", "Who on the team knows a topic, and their reason in their own words."),
    tool("going_dark", "/api/voice/going-dark", "Whether understanding of a topic is going dark: only one person, or nobody lately."),
  ];
  const toolIds = [...TOOL_IDS];
  if (!toolIds.length) for (const t of tools) toolIds.push((await call("/v1/convai/tools", "POST", t)).id);

  const config = {
    name: "Nobikos voice",
    tags: ["packoverflow"],
    conversation_config: {
      agent: {
        first_message: "Hi, this is Nobikos. Ask me what I can do for your team.",
        language: "en",
        prompt: { prompt: PROMPT, llm: "claude-haiku-4-5", temperature: 0.2, tool_ids: toolIds },
      },
      conversation: {
        max_duration_seconds: 240,
        client_events: ["conversation_initiation_metadata", "audio", "interruption", "user_transcript", "agent_response",
          "agent_response_correction", "agent_tool_response", "agent_tool_response_full_payload", "ping", "vad_score"],
      },
    },
    platform_settings: { auth: { enable_auth: true }, call_limits: { agent_concurrency_limit: 6, daily_limit: 300 } },
  };
  const agent = existing
    ? await call(`/v1/convai/agents/${existing}`, "PATCH", config)
    : await call("/v1/convai/agents/create", "POST", config);
  console.log(JSON.stringify({ agent_id: agent.agent_id || existing, tool_ids: toolIds }));
}

main().catch((err) => { console.error(err.message); process.exit(1); });
