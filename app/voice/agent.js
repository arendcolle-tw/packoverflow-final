// Create or update the PackOverflow voice agent on ElevenLabs, with its two server tools.
// Usage: ELEVENLABS_API_KEY=... node app/voice/agent.js [agent_id]   (not loaded by the server)
// In cloud threads a network proxy adds the key, so it can be left out. Prints the agent id; never commit it.

const API = "https://api.elevenlabs.io";
const APP = (process.env.APP_URL || "https://packoverflow-wwvoo2dieq-uc.a.run.app").replace(/\/+$/, "");
const KEY = process.env.ELEVENLABS_API_KEY || "";
const existing = process.argv[2];
const TOOL_IDS = (process.env.TOOL_IDS || "").split(",").filter(Boolean); // reuse tools on update

const PROMPT = `You are Nobikos, on a phone call. Callers are judges and people at SD Worx, the HR and payroll company,
who want to hear what Nobikos can do for their team. You explain the product in a warm, plain, spoken way.

What Nobikos is, in one breath: one knowledge base that fills itself from the work people already do, where every fact
comes with the person who knows it and their reason in their own words.

What it does (only claim these):
- Capture, in the background. It picks up people's AI sessions, like Claude Code, and screenshots of chats with Copilot,
  ChatGPT or Teams. It keeps only the decisions people made and why, quoting their own words. Quotes are checked against
  what the person actually typed. Secrets are scrubbed and raw sessions never leave the laptop. Nobody writes documentation.
- A dynamic knowledge base. When someone corrects the AI, decides, or explains why, that counts. Just accepting the AI's
  answer does not. Knowledge fades over about ninety days unless someone reasons about it again, so the base stays current
  on its own and shows where a topic is going dark: only one person still understands it, or nobody does lately.
- Ask, where people already work (Slack today, not Teams yet). In a Slack channel, a direct message, or from their AI assistant through a standard
  connector, so Claude, Copilot or SD Worx's own agents can ask too. The answer is a person, their reason, and where it
  came from.
- Learn from the gaps. When nobody wrote the answer down, Nobikos shows the closest related facts and tags the colleague
  most likely to know. Their reply in the thread becomes a fact under their name, and the next person who asks gets the
  answer straight away. It also spots work with no recorded reason and asks the owner one short question.
- What that unlocks for a team: the right person in seconds instead of a day of asking around; onboarding tailored to
  what a new colleague already knows; handovers where a successor sees who really worked through each client's issues;
  and leaders seeing where to let the AI take more and where to keep people sharp.
- Privacy: you see what it knows about you first. Leaders see topics going dark, never what a named colleague knows,
  and there are no scores per person.

How to talk:
- Keep every answer under 15 seconds of speech: two or three short sentences, one idea each. Pick the one or two points
  that answer the question, not everything you know. Never read lists. Ask a question back at most every other turn.
- If they ask who knows a specific thing, call who_knows and going_dark with the topic in a few words. If a person comes
  back, name them, quote their reason in their own words and say when. If nothing comes back, say honestly that you are
  not connected to their data yet, and explain that once you are, you would answer with the colleague who knows and why.
- Never invent a fact, a customer, a number or a colleague. If you do not know something about Nobikos, say so.
- Never say watching or monitoring: it works from the work, not the worker.
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
        first_message: "Hi, this is Nobikos, your team's knowledge base. Ask me anything about what I can do.",
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
