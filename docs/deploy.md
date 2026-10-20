# How the live deploy works

Live app: https://packoverflow-wwvoo2dieq-uc.a.run.app (exists after the first merge that changes `app/`).

## What triggers it

Merging a change in `app/` to `main` runs `.github/workflows/deploy.yml`. It deploys `app/` from source to Cloud Run service `packoverflow` in `us-central1`. The URL is in the run's summary on the Actions tab.

Threads never deploy themselves and have no Google Cloud access.

## Where it runs

- Google Cloud project `qwiklabs-gcp-04-61c2ca7d9c86` (number 323892475788). This is a hackathon lab project, valid for one week.
- GitHub signs in through Workload Identity Federation: pool `github`, provider `github-oidc`, limited to the repo `arendcolle-tw/packoverflow-final`.
- It acts as the service account `github-deployer@qwiklabs-gcp-04-61c2ca7d9c86.iam.gserviceaccount.com`, which has `run.admin`, `cloudbuild.builds.editor`, `artifactregistry.admin`, `storage.admin`, `iam.serviceAccountUser` and `serviceusage.serviceUsageConsumer`.
- No keys are stored anywhere.

## What app/ needs

`app/` must build with Google buildpacks (a `package.json` with a `start` script, or Python with `requirements.txt`) and listen on `$PORT`.

## Manual run

Actions tab > "Deploy to Cloud Run" > Run workflow (inputs: source folder, service name, and optional min and max instances; blank leaves them unchanged). For `knowledge-mcp` use source `ideas/wout`, min 1, max 1, so its in-memory data is not split or dropped.

## Troubleshooting

"Permission iam.serviceAccounts.getAccessToken denied" right after a setup change is IAM propagation. Wait 3 to 5 minutes and rerun.

## API keys

API keys for the live app, such as ElevenLabs, go on the Cloud Run service as env vars. Arend sets them from his Mac with the gcloud configuration `tectonic`. Never commit them.

In cloud threads, ElevenLabs works through a network secret on the `default` environment for `api.elevenlabs.io`.
