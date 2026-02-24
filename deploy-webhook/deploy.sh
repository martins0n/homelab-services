#!/bin/sh
SERVICE="$1"
COMPOSE_FILE="/homelab/$SERVICE/docker-compose.yaml"
STATUS_DIR="/status"
STATUS_FILE="$STATUS_DIR/$SERVICE.json"
LOCK_FILE="/tmp/deploy-${SERVICE}.lock"
TIMESTAMP=$(date -u +"%Y-%m-%d %H:%M:%S UTC")

# Prevent concurrent deploys for the same service
if [ -f "$LOCK_FILE" ]; then
  echo "[$SERVICE] Deploy already in progress, skipping"
  exit 0
fi
trap 'rm -f "$LOCK_FILE"' EXIT
echo $$ > "$LOCK_FILE"

write_status() {
  mkdir -p "$STATUS_DIR"
  printf '{"service":"%s","status":"%s","time":"%s"}\n' \
    "$SERVICE" "$1" "$TIMESTAMP" > "$STATUS_FILE"
  generate_index
}

generate_index() {
  ROWS=""
  for f in "$STATUS_DIR"/*.json; do
    [ -f "$f" ] || continue
    SVC=$(awk -F'"' '{print $4}' "$f")
    STATUS=$(awk -F'"' '{print $8}' "$f")
    TIME=$(awk -F'"' '{print $12}' "$f")
    case "$STATUS" in
      success*) COLOR="ok" ;;
      fail*)    COLOR="fail" ;;
      *)        COLOR="deploying" ;;
    esac
    ROWS="${ROWS}<tr><td>${SVC}</td><td class='${COLOR}'>${STATUS}</td><td class='utc'>${TIME}</td></tr>"
  done
  UPDATED=$(date -u +"%Y-%m-%d %H:%M:%S UTC")
  cat > "$STATUS_DIR/index.html" <<EOF
<!DOCTYPE html><html><head><title>Deploy Status</title>
<style>
body{font-family:monospace;padding:2rem;background:#111;color:#eee;max-width:800px}
h2{margin-bottom:.25rem}
p{color:#666;font-size:.85rem;margin:.25rem 0 1rem}
table{border-collapse:collapse;width:100%}
th,td{padding:.6rem 1rem;text-align:left;border-bottom:1px solid #222}
th{color:#555;font-size:.8rem;text-transform:uppercase}
.ok{color:#4caf50}.fail{color:#f44336}.deploying{color:#ff9800}
</style></head><body>
<h2>Deploy Status</h2>
<p>Last deploy: $UPDATED &mdash; local time: <span id="lc"></span></p>
<table><tr><th>Service</th><th>Status</th><th>Time</th></tr>
${ROWS}
</table>
<script>
function fmt(d){return d.toLocaleString();}
document.querySelectorAll('td.utc').forEach(function(td){
  var s=td.textContent.trim().replace(' UTC','Z').replace(' ','T');
  var d=new Date(s);
  if(!isNaN(d)){td.title=td.textContent;td.textContent=fmt(d);}
});
function tick(){document.getElementById('lc').textContent=fmt(new Date());}
tick();setInterval(tick,1000);
</script>
</body></html>
EOF
}

trap 'write_status "failed ✗"' ERR
set -e

write_status "deploying..."
echo "[$SERVICE] Starting deploy at $TIMESTAMP"
docker compose -f "$COMPOSE_FILE" up -d --pull always
write_status "success ✓"
echo "[$SERVICE] Deploy complete at $TIMESTAMP"
