# deploy-webhook

Webhook listener that auto-deploys services when their Docker image is successfully built on GitHub Actions.

## How it works

1. GitHub Actions builds and pushes a multi-platform image to GHCR on push to `main`
2. GitHub fires a `workflow_run` webhook when the build completes
3. The webhook listener verifies the HMAC-SHA256 signature and runs `deploy.sh <service>`
4. `deploy.sh` runs `docker compose up -d --pull always` which pulls the new image and recreates the container
5. The status page at `http://localhost:9000` updates with the result

## Adding a new service

1. **Open `hooks.json`** and copy the existing hook block:

```json
{
  "id": "deploy-YOUR-SERVICE",
  "execute-command": "/bin/sh",
  "command-working-directory": "/deploy-webhook",
  "pass-arguments-to-command": [
    { "source": "string", "name": "/deploy-webhook/deploy.sh" },
    { "source": "string", "name": "YOUR-SERVICE" }
  ],
  "response-message": "Deploying YOUR-SERVICE...",
  "trigger-rule": {
    "and": [
      {
        "match": {
          "type": "payload-hmac-sha256",
          "secret": "$WEBHOOK_SECRET",
          "parameter": { "source": "header", "name": "X-Hub-Signature-256" }
        }
      },
      {
        "match": {
          "type": "value",
          "value": "completed",
          "parameter": { "source": "payload", "name": "action" }
        }
      },
      {
        "match": {
          "type": "value",
          "value": "success",
          "parameter": { "source": "payload", "name": "workflow_run.conclusion" }
        }
      },
      {
        "match": {
          "type": "value",
          "value": "main",
          "parameter": { "source": "payload", "name": "workflow_run.head_branch" }
        }
      }
    ]
  }
}
```

Replace `YOUR-SERVICE` with the directory name of the service under `homelab-services/` (e.g. `graph-telegram`). That's the only thing that changes.

2. **Add the service to the GitHub Actions matrix** in `.github/workflows/build.yml`:

```yaml
matrix:
  dockerfile:
    - {"name": "YOUR-SERVICE", "path": "YOUR-SERVICE/Dockerfile"}
```

3. **Add a GitHub webhook** in the repo settings for the new hook ID:

   - Payload URL: `https://YOUR-DOMAIN/hooks/deploy-YOUR-SERVICE`
   - Content type: `application/json`
   - Secret: same as `WEBHOOK_SECRET` in `.env`
   - Events: **Workflow runs**

4. **Restart the webhook container** on the server to pick up the new hook:

```bash
cd ~/projects/homelab-services/deploy-webhook
git pull
docker compose restart webhook
```

## Server setup

`.env` file (gitignored, lives only on the server):

```
WEBHOOK_SECRET=<generate with: openssl rand -hex 32>
```

## File layout

| File | Purpose |
|---|---|
| `Dockerfile` | Alpine + webhook binary (arm64) + docker CLI + envsubst |
| `entrypoint.sh` | Substitutes `$WEBHOOK_SECRET` into hooks.json at startup |
| `hooks.json` | One hook entry per service |
| `deploy.sh` | Generic deploy script — takes service name as argument |
| `nginx.conf` | Reverse proxy: `/hooks/` → webhook, `/` → status page |
| `docker-compose.yaml` | webhook + nginx on port 9000 |
| `.env` | `WEBHOOK_SECRET` (gitignored) |
