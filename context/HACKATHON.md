# Tectonic Hackathon Final — Ghent

Context only: how we're judged and what we learned from round 1.

Prize: €10,000, winner takes all. 15 teams in our track (SD Worx). Judged on a live pitch with a demo.

## How we're scored (assumed same as round 1)

| Criterion | What it means in practice |
|---|---|
| **Creativity** | Is the idea original? Can a jury member get it in 5 seconds? |
| **Technical ability** | Does it actually work, live, end to end? |
| **Fit** | Does it solve SD Worx's case, for a real role at SD Worx? |
| **Security (10%)** | Aikido AI Code Audit: business logic, IDOR, authentication, authorization. Score = issues left after fixes. Before/after screenshots. |

Rules (round 1): built during the event only · repo public until judging ends · README with what it is, how to run, what's unfinished · no secrets in git · final means final.

## What round 1 taught us

We read ~23 public round-1 repos from the SD Worx track (plus ~10 from KBC) and matched 5 to the finalist list.
Caveat: matched on lead names, selection was top ~20% per city, and the cutoff was soft (we got in from the waitlist).

**Finalists we could identify**

| Team | Idea in one line | AI | Security |
|---|---|---|---|
| Vulcan Kinetics | Gmail extension notices you hesitating while typing a client reply and suggests the colleague who knows | none | good |
| Maze Runners | Every source gets an A–G grade like the EU energy label; expert confirms by voice; works in Teams | extraction only | best |
| Les Flammand | Google Drive clone that blocks saving a doc that contradicts another, plus a "handover radar" | external model | none |
| GenHomies | Knowledge graph: "popular is not reliable" — the most-linked doc is the wrong one | parse question only | none |
| Team 2 | Full portal with real Belgian payroll detail (joint committees, flexi-jobs) and a tamper-proof audit log | none | story-driven |

**What finalists had in common**
- An idea you understand in 5 seconds (a label, Drive, Gmail, a counter-intuitive one-liner).
- It lives where people already work (Gmail, Drive, Teams), not in yet another chat window.
- People are central: who knows this, who is outdated, who to ask. 4 of 5.
- It visibly worked, even if the logic underneath was simple.

**What did NOT decide it**
- Using AI: 2 finalists had none. Rules-based logic is fine.
- Security: 2 finalists had no login at all. The two best-secured repos didn't make it.
- Technical depth and metrics: the most sophisticated, best-measured repo (multi-agent, eval vs RAG) did not make it. Probably too complex to grasp in 3 minutes.
- Team size: most finalists were effectively one coder plus Claude.

**What most non-finalists had in common**
- The generic build: chat + trust score + "ask the document owner". About half the field built exactly this, from SD Worx's own example story.
- Wrong user (owner dashboards, an intern onboarding manager) or too technical (clever search engineering nobody sees).
- Too wide (6 tabs on 17 fake docs) or too thin (hard-coded answers behind a fake loading spinner).
- AI quota ran out mid-event (Gemini free tier) for at least two teams.

## Do's and don'ts

**Creativity**
- Do have a one-sentence idea and a 5-second visual.
- Do pick one role, one moment of doubt, one workflow. SD Worx's brief asked for exactly that.
- Don't build "chat with your docs + trust score". That's the baseline now.

**Technical ability**
- Do make one end-to-end happy path work before adding breadth.
- Do keep a demo mode: seeded data, a reset button, a fixed demo date, no dependency on a live API.
- If AI is in the loop, plan for quota limits with caching and a fallback.
- Don't fake core logic. Judges and other teams read repos.

**Fit**
- Do use real SD Worx vocabulary: payroll consultant, client portfolio, joint committee (PC 200…), mysdworx, Legal Watch, indexation.
- Do show how it plugs into what SD Worx already runs (see context/SDWORX.md), not replaces it.
- Don't drift to a different user than the one in the case.

**Security (10%)**
- Do the basics: real login, user id from the session (never from the request), users only see their own clients, no secrets in git.
- Do keep the Aikido before/after screenshots; the audit can sit in a queue for a long time.
- Don't over-invest. It's 10%, and round 1 shows it didn't make or break teams.

**Pitch (live)**
- Do open with the moment of doubt, demo the fix, end with why SD Worx should care. One number if you have an honest one.
- Do have a recorded screen capture of the happy path as a backup if the live demo fails.
