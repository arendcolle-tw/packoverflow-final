# Tectonic Hackathon Final — Ghent

Context only: how we're judged and what we learned from round 1.

Prize: €10,000, winner takes all, one winner across the KBC and SD Worx tracks. 16 teams in our track (SD Worx), 8 per room. Judged on a live pitch with a demo.

## How we're scored (finals guide)

| Criterion | Weight | What it means in practice |
|---|---|---|
| **Creativity** | 25% | Is the idea original? Can a jury member get it in 5 seconds? |
| **Technical ability** | 20% | Does it actually work, live, end to end? |
| **Fit** | 20% | Does it solve SD Worx's case, for a real role at SD Worx? |
| **Pitch quality** | 25% | How well did we present? 3 minutes, then 5 minutes of questions, cut off on time. |
| **Security** | 10% | Aikido AI Code Audit: business logic, IDOR, authentication, authorization. Score = issues left after fixes. Submit screenshots of the final scan with the repo name and the remaining issues. |

Rules (finals guide): built during the event only · one project per team · repo public until judging ends · README with what it is, how to run, what's unfinished · no secrets in git · final means final, no code or submission changes after submitting · pitch deck as PPT or PDF.

## Finals day

| Time | What | Where |
|---|---|---|
| 08:00 | Arrival and breakfast | Vooruit Concertzaal |
| 08:40 | Welcome by partners | Vooruit Concertzaal |
| 09:00 to 16:00 | Hacking, lunch at 12:30. Partner staff answer questions and give feedback. | Vooruit Concertzaal |
| **16:00** | **Submissions close** | Builderbase |
| **16:15 to 16:25** | **Our pitch, SD Worx Room 4, first slot. Be there by 16:05.** | Wintercircus |
| 18:25 | SD Worx winner announced, then pitches again at 18:30 | Vooruit Theaterzaal |
| 19:00 | Overall winner announced | Vooruit Theaterzaal |

In Room 4 we pitch against ProstoPizdetz, SkepTech, Sssst… hier hackt den AI, Team 2, Tekst, The Four Loops and Vulcan Kinetics. Two of those, Team 2 and Vulcan Kinetics, were round 1 finalists. Room 3 has Aleida.ai, Algoholics, "Arno, Rune & Aeon", CDN, GenHomies, Les Flammand, Maze Runners and OpStudio.

We pitch on the organisers' device, not ours. The demo has to run from the deck: a live URL plus screenshots or a recording in the PDF.

**Submit by 16:00 on Builderbase.** One teammate logs in and fills in the Overview fields:
- a short description
- the pitch deck (under 3 minutes, PPT or PDF)
- the GitHub repo link (the repo must be public)
- screenshots of the final Aikido scan, showing the repo name and the remaining vulnerabilities

## Partner tools

- **Aikido.** Create a free account at app.aikido.dev with GitHub, connect this repo and let it scan. Fix the findings, push, and wait for a scan of the latest code before taking the screenshots. Start early, because the final scan must finish before 16:00. Aikido staff are on site.
- **Google Cloud.** Our team (table F1) gets shared credentials, valid for one week. The team link is in Builderbase and stays out of this repo, because it grants access. Each teammate who enters their email there joins the team and gets the credentials.
- **ElevenLabs** (text to speech). Get credits in the coupon-codes channel of their Discord (discord.com/invite/VnBvbbcdEC): click Start Redemption and use the email you registered with.
- **Cursor.** Credits come the same way through discord.gg/5UwpfTF7M. We build with Claude Code, so we skip it.

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
