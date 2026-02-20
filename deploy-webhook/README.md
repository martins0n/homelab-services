# deploy-webhook

Webhook listener that auto-deploys services when their Docker image is successfully built on GitHub Actions.

## How it works

1. GitHub Actions builds and pushes a multi-platform image to GHCR on push to `main`
2. GitHub fires a `workflow_run` webhook to this server when the build completes
3. The webhook listener verifies the HMAC-SHA256 signature and runs `deploy.sh <service>`
4. `deploy.sh` runs `docker compose up -d --pull always` which pulls the new image and recreates the container
5. The status page at `http://localhost:9000` updates with the result

## Adding a new service

### 1. Add an entry to `hooks.json`

`hooks.json` is a JSON array — one object per service. Open it and add a new entry for your service, changing only the three places marked with `←`:

```json
[
  {
    "id": "deploy-support-bot-py",
    "execute-command": "/bin/sh",
    "command-working-directory": "/deploy-webhook",
    "pass-arguments-to-command": [
      { "source": "string", "name": "/deploy-webhook/deploy.sh" },
      { "source": "string", "name": "support-bot-py" }
    ],
    "response-message": "Deploying support-bot-py...",
    "trigger-rule": { "and": [ ... ] }
  },
  {
    "id": "deploy-graph-telegram",           ← change this
    "execute-command": "/bin/sh",
    "command-working-directory": "/deploy-webhook",
    "pass-arguments-to-command": [
      { "source": "string", "name": "/deploy-webhook/deploy.sh" },
      { "source": "string", "name": "graph-telegram" }  ← and this (must match the service directory name)
    ],
    "response-message": "Deploying graph-telegram...", ← and this
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
]
```

The service directory name (second `pass-arguments-to-command` entry) must match the subdirectory under `homelab-services/` that contains the service's `docker-compose.yaml`.

### 2. Add the service to GitHub Actions

In `.github/workflows/build.yml`, add a line to the matrix:

```yaml
matrix:
  dockerfile:
    - {"name": "support-bot-py", "path": "support-bot-py/Dockerfile"}
    - {"name": "graph-telegram", "path": "graph-telegram/Dockerfile"}  ← add this
```

### 3. Add a GitHub webhook for the new hook

In GitHub repo **Settings → Webhooks → Add webhook**:

| Field | Value |
|---|---|
| Payload URL | `https://YOUR-DOMAIN/hooks/deploy-graph-telegram` |
| Content type | `application/json` |
| Secret | same as `WEBHOOK_SECRET` in `.env` |
| Events | **Workflow runs** |

Each service needs its own webhook entry in GitHub because each has a different URL (`/hooks/deploy-<service>`).

### 4. Restart the webhook container

```bash
cd ~/projects/homelab-services/deploy-webhook
git pull
docker compose restart webhook
```

That's it. `deploy.sh` is generic — no changes needed there.

---

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
