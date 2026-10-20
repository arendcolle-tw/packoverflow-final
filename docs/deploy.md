# How the live deploy works

Live app: https://packoverflow-wwvoo2dieq-uc.a.run.app (exists after the first merge that changes `app/`).

## What triggers it

Merging a change in `app/` to `main` runs `.github/workflows/deploy.yml`. It deploys `app/` from source to Cloud Run service `packoverflow` in `us-central1`. The URL is in the run's summary on the Actions tab.

Threads have no Google Cloud login of their own. They act on Cloud Run by dispatching GitHub workflows (GitHub MCP `actions_run_trigger`), which sign in as the deploy account below. See Ops from a thread.

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

API keys live in GitHub repository secrets (Settings > Secrets and variables > Actions). Every deploy, automatic or manual, copies them onto the Cloud Run service with `--update-env-vars`, so a redeploy keeps the keys. A secret that is not set is skipped, so it never blanks a key already on the service.

| Service | Env vars it gets |
|---|---|
| `packoverflow` | `ELEVENLABS_API_KEY`, plus `ELEVENLABS_AGENT_ID` (not secret, fixed in the workflow) |
| `knowledge-graph` | `ELEVENLABS_API_KEY`, `ANTHROPIC_API_KEY`, `KG_ADMIN_TOKEN` |

To add or rotate a key: update the repository secret, then rerun "Deploy to Cloud Run" for that service. Never commit keys.

In cloud threads, ElevenLabs works through a network secret on the `default` environment for `api.elevenlabs.io`.

## Ops from a thread

`.github/workflows/ops.yml` ("Cloud Run ops") gives threads a fixed set of Cloud Run operations with no keys. Dispatch it with `actions_run_trigger` (workflow `ops.yml`, ref `main`) and read the result in the run summary or job log. Service account key creation is blocked by the lab's IAM deny policy, so this is the route from the cloud.

| `op` | Inputs | What it does |
|---|---|---|
| `describe` | `service` | Prints URL, ready revision, traffic, min and max instances, and env var names (never values). |
| `set-env` | `service`, `name`, `from_service` or `value` | Sets one env var. `from_service` copies the value from that service's env, masked in logs (e.g. copy `ELEVENLABS_API_KEY` from `packoverflow` to `knowledge-graph`). `value` is for non-secret values only and is refused for names containing KEY, TOKEN, SECRET, PASS or CRED. |
| `admin-call` | `call=gaps-scan`, `claude` (0 to 50) | Calls knowledge-graph `POST /gaps/scan?claude=N` with `KG_ADMIN_TOKEN` read from the knowledge-graph service env at run time and masked. |
| `admin-call` | `call=add-member`, `person`, `pubkey` | Mints a member token with `POST /members`. The token is printed only encrypted (RSA-OAEP-SHA256) to `pubkey`, the base64 of an RSA public key PEM: `openssl genpkey -algorithm RSA -out k.pem; openssl pkey -in k.pem -pubout \| base64 -w0`. Decrypt with `base64 -d \| openssl pkeyutl -decrypt -inkey k.pem -pkeyopt rsa_padding_mode:oaep -pkeyopt rsa_oaep_md:sha256`. |

To redeploy a service, dispatch "Deploy to Cloud Run" (`deploy.yml`) the same way.

Not possible from a thread: enabling a Google API or granting an IAM role. The deploy account has `serviceusage.serviceUsageConsumer`, not `serviceUsageAdmin`, and no `resourcemanager.projectIamAdmin`, so those still need the lab owner's login once.
