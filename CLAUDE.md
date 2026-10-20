# Packoverflow final

Goal is a live, working demo at the final. Working beats clean.

Tectonic Hackathon final, SD Worx track. A team of four, each with their own Claude session. The humans decide what to build, who does what and when. Help your human with the task they give you, using the context below.

## Context

@context/HACKATHON.md
@context/SDWORX.md

## Layout

- `app/` is the main product. It changes only through merged pull requests.
- `ideas/<name>/` is one person's experiments. Push to branch `idea/<name>`, or straight to `main` if you touch only your own folder. Stay in your own folder.
- `scripts/first-use.sh` checks that this Mac can work here.
- `context/` holds background on the hackathon and SD Worx.
- `.github/workflows/deploy.yml` deploys `app/` to Cloud Run on every merge to `main` that changes it. `app/` must build from source with Google buildpacks and listen on `$PORT`.
- Live app: https://packoverflow-wwvoo2dieq-uc.a.run.app (exists after the first merge that changes app/). Check it after each merge.

## First time in this repo

On a person's Mac, if `.first-use-ok` does not exist, run `bash scripts/first-use.sh`, fix every FAIL line and run it again. Cloud threads skip this.

## #hackathon-finale is the source of truth

The private channel is where the team and our Claude sessions share live information. Where it disagrees with the files in `context/`, the channel wins.

What gets posted there: facts heard on the day (exact case brief, scoring, what SD Worx people said), team decisions (idea, user, scope, what we won't do), changes to shared pieces (API endpoints, data shapes, file ownership), and requests for someone else's part.

- Read the channel when you start a task, before changing anything others build on (APIs, types, shared data), and every so often during longer work.
- If a message affects your work, tell your human and adjust.
- If a request is for the part your human owns, tell your human. Don't act on it without them.
- Post a short message when you change something others depend on, with what changed and where. Post anything else only when your human asks.
- Prefix posts so they're easy to scan: `FACT:` · `DECISION:` · `CHANGE:` · `REQUEST @name:` · `DONE:`
- Never post secrets, API keys or passwords.

## Hand an idea to the main thread

When an idea in `ideas/<name>` should go into `app/`, push its branch, then post this line to #hackathon-finale with the Slack connector:

`branch idea/<name>, folder ideas/<name>: <what it adds>, want it in main`

The project driver pastes it into the Claude project and replies in the Slack thread when it is picked up.

## Pull requests in cloud threads

Use the built-in GitHub tools. `gh pr` and `gh issue` fail with a 403 in cloud threads because the GitHub proxy blocks GraphQL.
