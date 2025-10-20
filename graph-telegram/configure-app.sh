#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./configure-app.sh app.zip "My App Name" description.md
#
# Output:
#   app-configured.zip  (ready to serve)

ZIP_IN="${1:-}"
APP_NAME="${2:-}"
MD_IN="${3:-}"

if [[ -z "${ZIP_IN}" || -z "${APP_NAME}" || -z "${MD_IN}" ]]; then
  echo "Usage: $0 <app.zip> <APP_NAME> <description.md>"
  exit 1
fi
if [[ ! -f "$ZIP_IN" ]]; then
  echo "ZIP not found: $ZIP_IN" >&2; exit 1
fi
if [[ ! -f "$MD_IN" ]]; then
  echo "Markdown not found: $MD_IN" >&2; exit 1
fi

WORKDIR="$(mktemp -d)"
cleanup() { rm -rf "$WORKDIR"; }
trap cleanup EXIT

# 1) Unpack
unzip -q "$ZIP_IN" -d "$WORKDIR/site"

# 2) Normalize permissions (avoid 403)
find "$WORKDIR/site" -type d -exec chmod 755 {} \;
find "$WORKDIR/site" -type f -exec chmod 644 {} \;

INDEX="$WORKDIR/site/index.html"
if [[ ! -f "$INDEX" ]]; then
  # allow index without extension (rare)
  if [[ -f "$WORKDIR/site/index" ]]; then
    INDEX="$WORKDIR/site/index"
  else
    echo "index.html not found in ZIP root." >&2
    exit 1
  fi
fi

# 3) Tiny Markdown -> HTML (headings, lists, code fences, paragraphs, **bold**, *italic*, links)
MD_HTML="$WORKDIR/desc.html"
awk '
BEGIN { inlist=0;incode=0 }
function flush_p() {
  if (p != "") { print "<p>" p "</p>"; p="" }
}
function bolditalics(s,  t) {
  # escape & < >
  gsub(/\&/,"&amp;",s); gsub(/</,"&lt;",s); gsub(/>/,"&gt;",s)
  # **bold**
  while (match(s,/\*\*[^*]+\*\*/)) {
    t=substr(s,RSTART+2,RLENGTH-4); s=substr(s,1,RSTART-1) "<strong>" t "</strong>" substr(s,RSTART+RLENGTH)
  }
  # *italic*
  while (match(s,/\*[^*]+\*/)) {
    t=substr(s,RSTART+1,RLENGTH-2); s=substr(s,1,RSTART-1) "<em>" t "</em>" substr(s,RSTART+RLENGTH)
  }
  # [text](url)
  while (match(s,/\[[^]]+\]\([^()]+\)/)) {
    m=substr(s,RSTART,RLENGTH)
    # extract
    gsub(/^\[/,"",m); split(m, a, /\]\(/); txt=a[1]; url=a[2]; sub(/\)$/,"",url)
    s=substr(s,1,RSTART-1) "<a href=\"" url "\">" txt "</a>" substr(s,RSTART+RLENGTH)
  }
  return s
}
{
  line=$0

  # code fences ```
  if (match(line,/^```/)) {
    if (incode==0) { flush_p(); print "<pre><code>"; incode=1; next }
    else { print "</code></pre>"; incode=0; next }
  }
  if (incode==1) { gsub(/&/,"&amp;",line); gsub(/</,"&lt;",line); gsub(/>/,"&gt;",line); print line; next }

  # blank line => paragraph/list break
  if (line ~ /^[[:space:]]*$/) {
    flush_p();
    if (inlist==1) { print "</ul>"; inlist=0 }
    next
  }

  # headings
  if (match(line,/^#{1,6}[[:space:]]+/)) {
    flush_p(); if (inlist==1) { print "</ul>"; inlist=0 }
    n=RLENGTH-1; sub(/^#{1,6}[[:space:]]+/,"",line)
    print "<h" n ">" bolditalics(line) "</h" n ">"
    next
  }

  # unordered list
  if (match(line,/^[*-][[:space:]]+/)) {
    if (inlist==0) { flush_p(); print "<ul>"; inlist=1 }
    sub(/^[*-][[:space:]]+/,"",line)
    print "<li>" bolditalics(line) "</li>"
    next
  }

  # otherwise accumulate paragraph
  if (p == "") { p = bolditalics(line) } else { p = p " " bolditalics(line) }
}
END {
  if (p != "") print "<p>" p "</p>"
  if (inlist==1) print "</ul>"
}
' "$MD_IN" > "$MD_HTML"

# 4) Prepare injection block
INJECT="$WORKDIR/inject.html"
cat > "$INJECT" <<EOF
<!-- injected by configure-app.sh -->
<header id="app-banner" style="margin:1.25rem 0 1rem 0;border-bottom:1px solid #e5e7eb;padding-bottom:.5rem;">
  <h1 style="margin:0;font-size:1.75rem;line-height:1.2;">${APP_NAME}</h1>
</header>
<section id="app-description" style="max-width:70ch;color:#374151;font-size:1rem;line-height:1.6;">
$(cat "$MD_HTML")
</section>
<!-- /injected -->
EOF

# 5) Replace <title>…</title>
# (create if missing)
if grep -q "<title>" "$INDEX"; then
  sed -i.bak -E "s|<title>.*</title>|<title>${APP_NAME}</title>|" "$INDEX"
else
  sed -i.bak -E "s|</head>|  <title>${APP_NAME}</title>\n</head>|" "$INDEX"
fi

# 6) Inject header+desc right after opening <body> (or before </body> if no match)
if grep -qi "<body[^>]*>" "$INDEX"; then
  awk -v inj="$(sed 's/[&/\]/\\&/g' "$INJECT")" '
    BEGIN{ IGNORECASE=1; injected=0 }
    /<body[^>]*>/ && injected==0 { print; print inj; injected=1; next }
    { print }
    END { if (injected==0) print inj }
  ' "$INDEX" > "$INDEX.new" && mv "$INDEX.new" "$INDEX"
else
  # no body tag — append
  cat "$INJECT" >> "$INDEX"
fi

# 7) Repack
OUT="${ZIP_IN%.zip}-configured.zip"
(cd "$WORKDIR/site" && zip -qr "$OUT" .)
mv "$WORKDIR/site/$OUT" ./app-configured.zip

echo "✅ Done. Output: app-configured.zip"
