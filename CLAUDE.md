# Packoverflow final

Goal is a live, working demo at the final. Working beats clean.

## Context

@context/HACKATHON.md
@context/SDWORX.md
@context/DESIGN.md

## Layout

- `app/` is the main product. It changes only through merged pull requests.
- `ideas/<name>/` is one person's experiments. Push to branch `idea/<name>`, or straight to `main` if you touch only your own folder. Stay in your own folder.
- `scripts/first-use.sh` checks that this Mac can work here.
- `context/` holds background on the hackathon and SD Worx, and the design rules.
- `.github/workflows/deploy.yml` deploys `app/` to Cloud Run on every merge to `main` that changes it. `app/` must build from source with Google buildpacks and listen on `$PORT`.
- Live app: https://packoverflow-wwvoo2dieq-uc.a.run.app (exists after the first merge that changes app/). Check it after each merge.

## First time in this repo

On a person's Mac, if `.first-use-ok` does not exist, run `bash scripts/first-use.sh`, fix every FAIL line and run it again. Cloud threads skip this.

## Hand an idea to the main thread

When an idea in `ideas/<name>` should go into `app/`, push its branch, then post this line to #hackathon-finale with the Slack connector:

`branch idea/<name>, folder ideas/<name>: <what it adds>, want it in main`

The project driver pastes it into the Claude project and replies in the Slack thread when it is picked up.

## Google Cloud from a thread

Never ask a person to run gcloud. Dispatch `.github/workflows/ops.yml` with the GitHub MCP `actions_run_trigger` (ref `main`) and read the job log: `describe` a service, `set-env` (copy an env var between services, masked), `admin-call` (knowledge-graph gaps scan or add member). Redeploy by dispatching `deploy.yml`. The deploy account cannot enable APIs or grant IAM roles, and key creation is blocked. Details in `docs/deploy.md`.

## Pull requests in cloud threads

Use the built-in GitHub tools. `gh pr` and `gh issue` fail with a 403 in cloud threads because the GitHub proxy blocks GraphQL.
