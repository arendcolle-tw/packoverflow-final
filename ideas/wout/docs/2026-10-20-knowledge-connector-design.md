# Knowledge connector: design

Owner: Wout. Lives in `ideas/wout/`, merged straight to `main`. Hackathon final 2026-10-20: submissions close 16:00, pitch 16:15. The pitch is slides plus a video. The hands-on part is judges trying it in their own Claude.

## Intent

Our product is a knowledge layer that knows which person actually understands what. Not who uploaded a document, and not what Claude did for them. The previous piece (knowledge clock, `2026-10-20-knowledge-clock-design.md`) is the long-term view. This piece is where people use it: **inside Claude**, as a remote MCP connector anyone can add.

Headline for the person using it: **"This is what you actually know. This is what you just prompt."**

## The judge's experience (Wout loved this flow)

1. **Add one URL** in their own Claude: claude.ai or Claude desktop (Settings, Connectors, Add custom connector) or Claude Code (`claude mcp add --transport http packoverflow <url>`). Claude opens our login page: "What's your name?" That is the whole sign-up. Their identity comes from this login, never from what Claude sends.
2. **Run the prompt "map my knowledge".** Claude looks through what it can see of their past work (past chats on claude.ai, its own session files in Claude Code) and records what it finds: decisions, corrections of Claude and reasons in the person's own words, and topics where they only prompted and accepted Claude's answer. Every record is a visible tool call.
3. **See what they know versus what they prompt.** "Claude handled 40 of your requests on its own. You reasoned 12 times." Then the topics they actually understand, with their whys, flagged where they are the only one, and the topics they only prompt.
4. **Ask "who knows X?"** The answer covers everyone connected: the four of us (installed and mapped before the pitch, so the graph starts with real people) plus the other judges, with each person's reasons.
5. **Keep working.** When they decide, correct Claude or explain why, Claude records it quietly.

After step 2 the judge is part of the graph, and the next person sees them in "who knows".

### Fit with the finals case

- *Automatic:* Claude does the capture from work people already do. Nobody writes documentation.
- *Human judgement where it matters:* only reasoning (decided, corrected, explained why) counts as knowledge. Prompting does not.
- *Fits the workflow:* it lives in Claude, where people already ask their questions.
- *Understandable:* every answer shows the person's own words and when they said them.
- SD Worx story: a developer at SD Worx asks Claude "how do we do this here, and who should I talk to?" (the finals brief's first example). Same connector works for the agents in agentic payroll.

## MCP surface

Server name `packoverflow`. Server instructions tell Claude: record a signal when the user decides something, corrects Claude, or explains why, using the user's own words, at most 200 characters; never record secrets, credentials or personal data about others; one short topic per signal.

### Tools (person always comes from the access token)

- `record_signals(items)`: 1 to 50 items `{topic, kind, why, happened_at}`.
  - `kind`: `decided | corrected | explained_why | prompted`. `prompted` becomes `human_role: accepted_as_is` with `why: null`.
  - `topic`: normalized to lowercase kebab-case, at most 60 chars.
  - `why`: required for the three reasoning kinds, the person's own words, at most 200 chars. Ignored for `prompted`.
  - `happened_at`: optional ISO time, default now. Lets the mapping prompt date past work correctly.
  - Rows become standard signal rows: `source: claude_session`, `actor: human`, a fresh `id`, `source_id: mcp-<person>-<topic>` (Albéric's ranking treats one `source_id` as one task, so this makes one task per person and topic). Invalid items are rejected with a reason, valid ones are stored.
  - Returns what was stored and, per topic, how many people now reason about it.
- `what_i_know()`: the personal view for the logged-in person: reasoning count vs prompted count, topics they reason about (with their latest why, and `only_you: true` when nobody else does), topics they only prompt.
- `who_knows(question)`: Albéric's `who_knows(query, signals)` over all rows: ranked people, their evidence whys, status. If his package is missing, fall back to topic-name matching through the clock.
- `knowledge_risks()`: the clock's topics sorted by risk (dark, single point, fading).
- `list_topics()`: existing topic names with how many people reason about each. Claude reuses one when it fits, so different people's Claudes don't invent different names for the same thing (otherwise every topic looks known by one person). `record_signals` also returns the closest existing names.

### Prompt

`map_my_knowledge`: tells Claude to search the user's past chats (claude.ai) or read its session files under `~/.claude/projects` (Claude Code), extract reasoning and prompting per topic, send them through `record_signals` in batches with `happened_at`, then call `what_i_know` and present "what you actually know vs what you just prompt". Only the user's own words go into `why`. It starts with `list_topics`. When Claude cannot see past chats (free plan, or chat search turned off), it asks the user three short questions about their recent work instead and records from the answers.

## Login (my call, revised after research)

Research (claude.ai connector docs, MCP SDK docs): every Claude plan can add a connector with no sign-in. Free plans allow one custom connector. On Team plans only owners can add one, so judges on a company Team or Enterprise plan may need a personal account or Claude Code. Running our own OAuth issuer is heavy, and the SDK's current docs advise against it. So:

- **Primary: personal connector URL.** `/join` shows one field, "Your name". Submitting it creates a random unguessable token and shows the person's URL `https://<host>/u/<token>/mcp`, with a copy button, the claude.ai steps and the `claude mcp add` command. The token maps to the person server-side. The person key is the lowercased trimmed name, so "Wout" maps onto the existing `wout` rows. Same-name collisions merge, accepted for a demo.
- **Stretch: OAuth** with the same name-only page, only if everything else is done.

Step 1 of the judge's experience becomes: open `/join`, type your name, copy your URL into Claude.

## Data layer (my call)

One store of signal rows (the existing row shape), shared by the connector, the clock page and Albéric's ranking:
- Seeded from `data/signals.json` (the 51 real rows).
- Live rows appended through `record_signals`.
- Backend behind one small interface: a JSONL file locally, Firestore on Cloud Run if Arend can enable it (rows and OAuth state then survive redeploys and multiple instances). Until then: one Cloud Run instance, and no redeploys once judges start using it.

Tristan's offline session rows load into the same store when they exist.

## Hosting (my call, aligning with Arend)

Separate Cloud Run service `knowledge-mcp`, built from `ideas/wout/`, through the deploy workflow's manual trigger. Public HTTPS. MCP at `/mcp`, login at `/login`, the existing clock page at `/` showing the live graph. Arend may take over the hosting side.

## Goals

- A judge adds the URL, logs in with a name, runs "map my knowledge" and sees "what you know vs what you prompt" from their own history.
- "Who knows X?" returns real people from the four of us and other judges.
- Works in claude.ai and Claude Code.
- Live before 14:45 so the team can record the video.

## Non-goals

- Meeting notes (parked, optional, Wout decides later).
- Passwords, email verification, SSO.
- Any AI call on our server. The user's Claude does the labelling.
- Editing or deleting rows through the connector.

## Anti-goals

- Storing conversations. Only topic, kind, a short why and a time leave the user's Claude.
- Identity taken from tool arguments.
- A web app judges have to click around in. The experience is in Claude.

## Constraints

- Python 3.13, FastAPI, the official `mcp` SDK. Reuse `knowledge_clock` (clock, store validation).
- No secrets in git. A signing secret, if needed, comes from an env var.
- Stay in `ideas/wout/`. Albéric's package is copied into `ideas/wout/vendor/` (asked him in Slack), never edited in his folder.

## Left to the builder

- Exact tool output wording, as long as the headline and `only_you` are there.
- File layout inside `ideas/wout/`.
- Login page styling.
