#!/bin/sh
# Usage: ./patch-index.sh /path/to/index.html "App Name" /path/to/about.md
set -eu

INDEX="${1:?index.html required}"
APP_NAME="${2:?app name required}"
MD="${3:?markdown required}"

[ -f "$INDEX" ] || { echo "No $INDEX"; exit 1; }
[ -f "$MD" ]    || { echo "No $MD"; exit 1; }

# --- build one-line meta description (strip simple MD) ---
META_DESC="$(awk '
  {
    line=$0
    gsub(/`[^`]*`/, "", line)                         # code spans
    gsub(/!\[[^]]*\]\([^)]*\)/, "", line)             # images
    gsub(/\[[^]]*\]\([^)]*\)/, "", line)              # links
    gsub(/^[#>*-][[:space:]]*/, "", line)             # headings/lists/quotes
    gsub(/\*\*|\*|__|_|~~|>/, "", line)               # bold/italic/strike
    gsub(/[[:cntrl:]]/, " ", line)                    # control chars -> space
    if (line != "") { if (out) printf(" "); printf("%s", line); out=1 }
  }
' "$MD" | tr -s ' ' | cut -c1-300)"

# escape for sed replacement (& and /)
esc() { printf '%s' "$1" | sed 's/[&/]/\\&/g'; }

META_ESC="$(esc "$META_DESC")"
TITLE_ESC="$(esc "$APP_NAME")"

# --- upsert <title> (assumes </head> lowercase as usual) ---
if grep -q "<title>.*</title>" "$INDEX"; then
  sed -i "s|<title>.*</title>|<title>${TITLE_ESC}</title>|" "$INDEX"
else
  sed -i "s|</head>|  <title>${TITLE_ESC}</title>\n</head>|" "$INDEX"
fi

# --- upsert <meta name="description"> ---
if grep -qi '<meta[^>]*name="description"' "$INDEX"; then
  # replace existing description attribute
  sed -i "s|<meta[^>]*name=\"description\"[^>]*>|<meta name=\"description\" content=\"${META_ESC}\">|I" "$INDEX"
else
  sed -i "s|</head>|  <meta name=\"description\" content=\"${META_ESC}\">\n</head>|" "$INDEX"
fi

# --- inject tiny overlay before </body> (kept very small) ---
# Description block: wrap each non-empty MD line in <p>
DESC_HTML="$(awk '
  NF { gsub(/&/,"&amp;"); gsub(/</,"&lt;"); gsub(/>/,"&gt;"); printf("<p>%s</p>", $0) }
' "$MD")"
DESC_ESC="$(printf '%s' "$DESC_HTML" | sed -e 's/[&/]/\\&/g' -e 's#</script>#<\/script>#g')"

awk -v snippet="<script>(function(){var b=document.body;if(getComputedStyle(b).position==\"static\"){b.style.position=\"relative\";}var d=document.createElement(\"div\");d.id=\"atlas-info\";d.style.cssText=\"position:absolute;top:1rem;left:1rem;background:rgba(255,255,255,.85);padding:.6rem .8rem;border-radius:10px;box-shadow:0 2px 12px rgba(0,0,0,.08);max-width:360px;font:14px/1.45 system-ui,sans-serif;z-index:99999\";d.innerHTML=\"<strong>"$(esc "$APP_NAME")"</strong> " "${DESC_ESC}" "\";document.body.appendChild(d);}());</script>" '
  BEGIN{ inserted=0 }
  /<\/body>/ && !inserted { sub(/<\/body>/, snippet "\n</body>"); inserted=1 }
  { print }
  END { if(!inserted) print snippet }
' "$INDEX" > "$INDEX.tmp" && mv "$INDEX.tmp" "$INDEX"

echo "✓ Patched $INDEX"
