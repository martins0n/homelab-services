#!/bin/sh
SERVICE="$1"
COMPOSE_FILE="/homelab/$SERVICE/docker-compose.yaml"
STATUS_FILE="/status/$SERVICE.html"
TIMESTAMP=$(date -u +"%Y-%m-%d %H:%M:%S UTC")

write_status() {
  mkdir -p /status
  cat > "$STATUS_FILE" <<EOF
<!DOCTYPE html><html><head><title>$SERVICE deploy</title>
<meta http-equiv="refresh" content="30">
<style>
body{font-family:monospace;padding:2rem;background:#111;color:#eee}
.ok{color:#4caf50}.fail{color:#f44336}
</style></head><body>
<h2>$SERVICE</h2>
<p>Status: <span class="$1"><strong>$2</strong></span></p>
<p>Time: $TIMESTAMP</p>
</body></html>
EOF
}

trap 'write_status fail "failed ✗"' ERR
set -e

write_status ok "deploying..."
echo "[$SERVICE] Starting deploy at $TIMESTAMP"
docker compose -f "$COMPOSE_FILE" up -d --pull always
write_status ok "success ✓"
echo "[$SERVICE] Deploy complete at $TIMESTAMP"
