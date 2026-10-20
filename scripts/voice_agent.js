// Create or update the PackOverflow voice agent on ElevenLabs, with its two server tools.
// Usage: ELEVENLABS_API_KEY=... node scripts/voice_agent.js [agent_id]
// In cloud threads a network proxy adds the key, so it can be left out. Prints the agent id; never commit it.

const API = "https://api.elevenlabs.io";
const APP = (process.env.APP_URL || "https://packoverflow-wwvoo2dieq-uc.a.run.app").replace(/\/+$/, "");
const KEY = process.env.ELEVENLABS_API_KEY || "";
const existing = process.argv[2];

const PROMPT = `You are PackOverflow, the caller's assistant for their team's knowledge, on a phone call. The caller is busy,
often walking into a meeting, and wants to know who on the team actually understands a topic.

How to answer:
- If the topic is unclear, ask one short clarifying question, at most once. Otherwise go straight to the tools.
- Call who_knows and going_dark with the topic in a few words, for example "nightly payroll export retries".
- Then answer in under 20 seconds of speech, in this order:
  1. Who actually knows it: say their name, quote their reason in their own words, and say when they last reasoned about it.
  2. Contrast them with the busiest person on the topic, who mostly accepted what the AI wrote, when that is a different person.
  3. Whether it is going dark: only one person understands it, or nobody has reasoned about it lately.
  4. End with one short offer: "Want me to ping them?" If they say yes, say you would send it, but nothing is sent in this demo.
- Follow-ups like "and who else?" or "what did they correct?" come from the same tool results. Do not make anything up.

Rules:
- Speak in plain, warm sentences. Never lists, numbers as scores, ids or field names.
- Say "going dark". Never say decay, proficiency, score or signal.
- Always name the person and quote their reason in their own words.
- If the tool says nobody knows or returns nothing, say so in one sentence instead of guessing.
- If the data note says demo data, you may say "in this demo example" once. Never call demo data the team's live data.
- Never describe what a named colleague knows beyond this topic.`;

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
    tool("who_knows", "/api/voice/who-knows", "Who on the team actually knows a topic, in their own words, and who is merely the busiest on it."),
    tool("going_dark", "/api/voice/going-dark", "Whether understanding of a topic is going dark: only one person, or nobody lately."),
  ];
  const toolIds = [];
  for (const t of tools) toolIds.push((await call("/v1/convai/tools", "POST", t)).id);

  const config = {
    name: "PackOverflow voice",
    tags: ["packoverflow"],
    conversation_config: {
      agent: {
        first_message: "PackOverflow here. What do you need to know?",
        language: "en",
        prompt: { prompt: PROMPT, llm: "claude-haiku-4-5", temperature: 0.2, tool_ids: toolIds },
      },
      conversation: {
        max_duration_seconds: 180,
        client_events: ["conversation_initiation_metadata", "audio", "interruption", "user_transcript", "agent_response",
          "agent_response_correction", "agent_tool_response", "agent_tool_response_full_payload", "ping", "vad_score"],
      },
    },
    platform_settings: { auth: { enable_auth: true }, call_limits: { agent_concurrency_limit: 3, daily_limit: 200 } },
  };
  const agent = existing
    ? await call(`/v1/convai/agents/${existing}`, "PATCH", config)
    : await call("/v1/convai/agents/create", "POST", config);
  console.log(JSON.stringify({ agent_id: agent.agent_id || existing, tool_ids: toolIds }));
}

main().catch((err) => { console.error(err.message); process.exit(1); });
