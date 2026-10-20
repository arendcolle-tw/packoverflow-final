# Get set up for the hackathon repo

This repo holds the final's live demo. The main app is in `app/`, and each person experiments in their own folder under `ideas/`. Run `bash scripts/first-use.sh` once on your Mac, push your ideas on a branch, and post one line in Slack when an idea should go into the app.

## First time on your Mac

1. Install and log in to the GitHub CLI: `brew install gh`, then `gh auth login --hostname github.com --git-protocol https --web`.
2. Clone the repo: `gh repo clone arendcolle-tw/packoverflow-final`.
3. Run `bash scripts/first-use.sh` inside the clone.
4. Fix every line marked FAIL and run the script again. A WARN line does not block you.

The script checks that git, `gh` and your GitHub login work, that your git name and email are set, that you can reach and push to this repo, and that `gcloud` is logged in.

## Where things go

- `app/` is the main product. It changes only through merged pull requests.
- `ideas/your_name/` is yours. Put experiments here and push them to a branch named `idea/your_name`, or straight to `main` when you touch only your own folder. Leave other people's folders alone.
- `scripts/` holds the first-use check.
- `context/` holds background for the case: how we're judged and what round 1 taught us (`HACKATHON.md`), SD Worx's products, beliefs and the round-1 brief (`SDWORX.md`), and the pitch story with what we show and what we leave out (`PITCH.md`). `CLAUDE.md` loads them, so every Claude session has them.
- `docs/` holds the text the project driver pastes into the Claude project settings.

## Hand an idea to the main thread

Push your branch, then post this line in #hackathon-finale:

`branch idea/your_name, folder ideas/your_name: what it adds, want it in main`

Write `branch main` if you pushed straight to `main`.

If you use Claude Code with the Slack connector, ask it to post the line for you. The project driver pastes the line into the Claude project, which opens a pull request. The driver replies in the Slack thread when the idea is picked up, so you know it arrived.

## Deploy

Every merge to `main` that changes `app/` deploys it to Google Cloud Run in `us-central1`, through `.github/workflows/deploy.yml`. The live URL is in the summary of the latest run on the Actions tab. Cloud Run builds from source, so `app/` needs a start command Google buildpacks recognise (a `package.json` with a `start` script, or a Python app with `requirements.txt`) and must listen on the `PORT` env var.
