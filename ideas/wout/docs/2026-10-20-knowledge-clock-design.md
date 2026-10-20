# Knowledge clock: design

Owner: Wout. Lives in `ideas/wout/`, branch `idea/wout`. Hackathon final, 2026-10-20. Submissions close 16:00, pitch 16:15.

## Intent

The team builds a knowledge store linked to people: not documents, but what each person actually knows. Wout's part is the long-term vision and one working piece that makes it concrete.

The vision, 10 to 20 years out, when most work and questions go through Claude:

1. **Dormant knowledge.** A critical system (a mainframe, a payroll engine) runs for years. Nobody needs to touch it, people ask Claude. Then a security incident hits. The facts are traceable, but nobody understands it any more.
2. **AI slop loop.** Knowledge bases fill with AI-written Slack posts and mail summaries, which feed the next AI answers. Human knowledge gets diluted.
3. **Single points of knowledge.** One person holds all real understanding of a system. They go on holiday or retire and the organisation is stuck.
4. **The missing why.** Messages and docs record the what and the how. The reasoning behind decisions is rarely written down, and it is what gets lost first once AI writes the text.

Knowledge is not facts. A fact is traceable to a document or message. Knowledge is a human who can reason about it and knows why it is the way it is.

**Headline:** "Who still understands this?" Dormant knowledge is the problem. Threads 2 to 4 are how we measure it.

**Pitch line (Wout loved it):** "Claude answered 400 questions about the mainframe this year. A human reasoned about it zero times. The one person who did retires in March."

## What we build

A **knowledge clock** per critical system or topic, computed from signals that everyday work already creates (Claude sessions now, meeting notes later).

For each topic it shows:
- how often AI handled the work (`ai_count`)
- how often a human actually reasoned about it (`human_count`)
- time since a human last reasoned about it
- which people did, each with their own why
- a status: `dark`, `single_point`, `fading`, `healthy`

Rule that guards against slop: **only human reasoning resets the clock.** Claude-written text never does.

### User and moment (Wout handed this to me, my call)

An engineering lead at SD Worx who owns critical systems. Two moments:
- During an incident: "who do I call about this system?"
- The quiet check: "which systems are going dark?"

### Fit with the finals case

The jury's five questions:
1. *Automatic:* the clock is computed from Claude sessions and meetings people already have. Nobody documents anything.
2. *Human verification:* only when a human overrules Claude without saying why (stretch feature below). That is the moment a decision is made.
3. *Maintenance:* none. The clock moves by itself. Silence is the signal.
4. *Workflow:* reads the tools people already use. The lead looks at one screen.
5. *Understandable:* every status is explained by the signals behind it, with the person's own words. No score, no black box.

## Input: signals

One row per human turn that matters. Tristan builds the Claude-session ingestion and owns the real format. This shape was proposed to him in #hackathon-finale. **If his field names differ, his win and we adapt here.**

```json
{
  "id": "stable string, unique per row",
  "person": "wout",
  "topic": "aikido-security-scan",
  "source": "claude_session | meeting",
  "source_id": "session uuid or meeting id",
  "at": "2026-09-30T19:10:03Z",
  "human_role": "decided | corrected | explained_why | answered_question | accepted_as_is",
  "why": "the human's own words, or null",
  "actor": "human | agent | unknown"
}
```

Meaning of `human_role`:
- `decided`: the human makes a choice or sets direction with their own content.
- `corrected`: the human tells Claude it was wrong, or changes Claude's output.
- `explained_why`: the human gives a reason.
- `answered_question`: (meetings) a human answers another human's question.
- `accepted_as_is`: the human only asks or approves. The content came from Claude.

`actor` exists because of agent-to-agent use: a "user" turn in a Claude session can be another agent or pasted Claude output.

### Certainty (my call)

Labels, not numbers, so they are explainable:

| Signal | Certainty | Resets the clock |
|---|---|---|
| `source: meeting`, actor human, reasoning role | `confirmed` | yes |
| `source: claude_session`, actor human, reasoning role | `likely` | yes |
| any source, actor `unknown`, reasoning role | `uncertain` | no, shown only |
| actor `agent`, or role `accepted_as_is` | counts toward `ai_count` | no |

Reasoning roles: `decided`, `corrected`, `explained_why`, `answered_question`.

### Status per topic (my call)

Evaluated in this order:
- `dark`: `ai_count > 0` and no clock-resetting signal ever.
- `fading`: last clock-resetting signal is older than `FADING_DAYS`.
- `single_point`: exactly one person has clock-resetting signals.
- `healthy`: two or more people, recent.

`FADING_DAYS` is config. Demo value 14 (so round-1 topics from 30 Sep show as fading). A real deployment would use something like 180.

**Albéric's proficiency levels.** Albéric builds per-person proficiency that decays over time and rises with new evidence (asked in #hackathon-finale). His is the person view, the clock is the system view. When his levels exist, `fading` means every person's level on the topic is below his threshold, and `single_point` means only one person is above it. `FADING_DAYS` is the fallback until then. Proposed to him: only reasoning roles count as evidence, never `accepted_as_is`.

### Topics, duplicates, agents (my calls)

- **Topic keys.** Tristan's ingestion assigns `topic`. Albéric and the clock reuse the same keys (proposed in #hackathon-finale). The clock keeps a small alias map, `{alias: topic}`, so stand-in topics can be merged onto his keys without touching rows.
- **Duplicates.** Row `id` is `<source_id>:<message uuid>`. When Tristan's rows arrive, they replace all stand-in rows with the same `source_id`.
- **Subagents.** A subagent run is agent-to-agent work. It counts as **one** `actor: agent` row toward `ai_count`, topic taken from its prompt, not one row per turn. This keeps the headline number honest, and topics that only AI ever touched show up as `dark` from real data.

"Now" is config too: real time by default, fixed demo time `2026-10-20T16:15:00+02:00` in demo mode.

## Output: API and page

FastAPI service, run with `uv run`:
- `GET /api/summary`: totals across topics, for the headline ("Claude handled X requests. Humans reasoned Y times.").
- `GET /api/topics`: every topic with status, counts, last human reasoning time, days since, reasoners. Sorted by risk: dark, single_point, fading, healthy.
- `GET /api/topics/{topic}`: the same plus its signals, each with person, why, certainty and source.
- `GET /`: one page. Headline line on top, topic list below, click a topic to see who reasoned about it and why.

Core logic is a pure function `signals -> topics` with no web or file code in it, so whoever builds `app/` can call or port it.

### Stand-in for Tristan's ingestion (throwaway)

Until his rows exist, a script turns our real Claude session files (`~/.claude/projects/*packoverflow*/*.jsonl` on Wout's Mac, round 1 and today) into rows in the shape above. Wout approved using today's sessions as real demo data.
- Rows must come from real turns with real timestamps, classified by a model or rules. No hand-written rows.
- Only Wout's sessions are on this Mac, so every topic will have one reasoner until Tristan's multi-person batch arrives. That is expected for development.
- If Tristan sends raw turns instead of classified rows, this classifier becomes the real one and gets the time.
- Fallback if his batch is late: teammates hand their session `.jsonl` files to Wout directly (not through the repo) and the stand-in runs on them. Without multi-person data there is no `healthy` topic and the bridge line is weaker, so this is worth chasing by 14:00.
- The output file is the only thing committed. Raw sessions never enter the repo, because the repo goes public. Scrub anything key-like from `why`.

### At the pitch (my call)

- Runs standalone from `ideas/wout/` with demo mode on (fixed "now", signals loaded from the committed file). A reload of the page is the reset.
- Screenshots of the page go into the deck as backup, since we pitch on the organisers' device.
- Handed to `app/` through the hand-off line once `app/` has a stack. If that stack is not Python, the pure function and the API shape are what carry over.

### Stretch: ask for the why

When someone `corrected` or `decided` in a Claude session with `why: null`, they get one line to fill in. The only time the system asks a human anything.
- `GET /api/questions?person=wout` lists those rows.
- `POST /api/why` with `{id, why}` stores the answer and the row then counts with its why.
- Only if the core is done and demoed.

## Deliverables

1. The knowledge clock service and page above, in `ideas/wout/`.
2. A short vision text for the pitch: the 30-second beat and the slide with the mainframe line. The bridge from demo to vision: "That's four people after one day. Now picture SD Worx after ten years."

## Goals

- The clock runs end to end on real session data and the page shows it.
- One honest, striking line from our own data for the pitch.
- A shape that takes Tristan's rows and later meeting rows without code changes beyond an adapter.

## Non-goals

- Ingesting Claude sessions properly. Tristan owns it.
- A real meeting-notes integration. The shape leaves room, owner not decided.
- The people-knowledge store itself.
- Login and authorization in `ideas/`. Security happens in `app/`.
- Chat or Q&A over knowledge.

## Anti-goals (a failure even if it works)

- Fake mainframe or SD Worx data inside the app. The mainframe lives on a slide.
- Anything that reads as "chat with your docs + trust score".
- Raw sessions or secrets in the public repo.
- Claude-written text counted as human knowledge.

## Constraints

- Done well before 16:00. Working beats clean.
- Stay in `ideas/wout/`. Merge to `app/` goes through the hand-off line in #hackathon-finale.
- Python, FastAPI, plain HTML and vanilla JS, started with `uv run --with fastapi --with uvicorn` (my call: nothing to install, and `app/` has no stack yet).
- No secrets in git.

## Left to the builder

- How the stand-in classifies turns (`claude -p` headless, rules, or both), as long as rows come from real turns.
- How topics are named and merged in the stand-in.
- Page layout and styling, within: headline on top, topic list sorted by risk, detail with whys.
- File layout inside `ideas/wout/`.
