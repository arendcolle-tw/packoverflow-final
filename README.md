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
- `ideas/your_name/` is yours. Put experiments here, on a branch named `idea/your_name`, and leave other people's folders alone.
- `scripts/` holds the first-use check.
- `docs/` holds the text the project driver pastes into the Claude project settings.

## Hand an idea to the main thread

Push your branch, then post this line in #hackathon-finale:

`branch idea/your_name, folder ideas/your_name: what it adds, want it in main`

If you use Claude Code with the Slack connector, ask it to post the line for you. The project driver pastes the line into the Claude project, which opens a pull request. The driver replies in the Slack thread when the idea is picked up, so you know it arrived.

## Deploy

The live deploy is not set up yet. It will run from GitHub Actions to Google Cloud once we choose the stack.
