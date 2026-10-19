# Packoverflow final

Goal is a live, working demo at the final. Working beats clean.

## Layout

- `app/` is the main product. It changes only through merged pull requests.
- `ideas/<name>/` is one person's experiments, on branch `idea/<name>`. Stay in your own folder.
- `scripts/first-use.sh` checks that this Mac can work here.

## First time in this repo

On a person's Mac, if `.first-use-ok` does not exist, run `bash scripts/first-use.sh`, fix every FAIL line and run it again. Cloud threads skip this.

## Hand an idea to the main thread

When an idea in `ideas/<name>` should go into `app/`, push its branch, then post this line to #hackathon-finale with the Slack connector:

`branch idea/<name>, folder ideas/<name>: <what it adds>, want it in main`

The project driver pastes it into the Claude project and replies in the Slack thread when it is picked up.

## Pull requests in cloud threads

Use the built-in GitHub tools. `gh pr` and `gh issue` fail with a 403 in cloud threads because the GitHub proxy blocks GraphQL.
