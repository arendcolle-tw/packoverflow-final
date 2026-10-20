// Create or update the PackOverflow voice agent on ElevenLabs, with its two server tools.
// Usage: ELEVENLABS_API_KEY=... node app/voice/agent.js [agent_id]   (not loaded by the server)
// In cloud threads a network proxy adds the key, so it can be left out. Prints the agent id; never commit it.

const API = "https://api.elevenlabs.io";
const APP = (process.env.APP_URL || "https://packoverflow-wwvoo2dieq-uc.a.run.app").replace(/\/+$/, "");
const KEY = process.env.ELEVENLABS_API_KEY || "";
const existing = process.argv[2];
const TOOL_IDS = (process.env.TOOL_IDS || "").split(",").filter(Boolean); // reuse tools on update

const PROMPT = `You are the team's knowledge base, answering a phone call from an SD Worx payroll consultant. The caller is busy,
often walking into a meeting, and wants to know who on the team knows a topic and what that person decided.

How to answer:
- If the topic is unclear, ask one short clarifying question, at most once. Otherwise go straight to the tools.
- Call who_knows and going_dark with the topic in a few words, for example "nightly payroll export retries".
- When the tools return a person, answer in under 20 seconds of speech, in this order:
  1. Who knows it: say their name, quote their single most important reason in their own words (prefer what they
     corrected), and say when they last reasoned about it. Keep any other reasons for follow-up questions.
  2. Whether it is going dark: only one person understands it, or nobody has reasoned about it lately.
  3. End with one short offer: "Want me to ping them?" If they say yes, say you would send it, but nothing is sent in this demo.
- When the tools say there is nothing in the knowledge base, be honest in one sentence: you are not connected to their
  real data on that yet. Then say in one or two sentences what you could do once you are: tell them who on the team
  actually knows it and in their own words why, build an onboarding path tailored to what a person already knows, or
  connect them with the right colleague to talk to. Then offer one of the topics you do have in this demo: the nightly
  payroll export, the PC 200 indexation, sick leave, onboarding a new hire, the DmfA filing, contract changes or pay
  transparency. Never invent a fact, a rule or a colleague.
- Follow-ups like "and who else?" or "what did they correct?" come from the same tool results. Do not make anything up.
- If asked what you are: you learn from the work people already do, like their AI sessions, so nobody has to write
  documentation, and you always answer with a person and their reason.

Rules:
- Say clock times the way people do: "six in the evening", not "eighteen hundred".
- Speak in plain, warm sentences. Never lists, numbers as scores, ids or field names.
- Say "going dark". Never say decay, proficiency, score or signal.
- Always name the person and quote their reason in their own words.
- The colleagues in this demo are made-up examples. If the data note says demo data and the caller asks, say so plainly.
  Never call demo data the team's live data.
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
    tool("who_knows", "/api/voice/who-knows", "Who on the team knows a topic, and their reason in their own words."),
    tool("going_dark", "/api/voice/going-dark", "Whether understanding of a topic is going dark: only one person, or nobody lately."),
  ];
  const toolIds = [...TOOL_IDS];
  if (!toolIds.length) for (const t of tools) toolIds.push((await call("/v1/convai/tools", "POST", t)).id);

  const config = {
    name: "PackOverflow voice",
    tags: ["packoverflow"],
    conversation_config: {
      agent: {
        first_message: "Hi, this is your team's knowledge base. What do you need to know?",
        language: "en",
        prompt: { prompt: PROMPT, llm: "claude-haiku-4-5", temperature: 0.2, tool_ids: toolIds },
      },
      conversation: {
        max_duration_seconds: 180,
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
