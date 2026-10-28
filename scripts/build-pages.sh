#!/usr/bin/env bash
# Copies the real dashboard into docs/demo/ in demo mode so the GitHub Pages
# preview always matches the app. Run after changing anything in app/static/.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$ROOT/docs/demo"
sed 's#^<script>$#<script>window.HLS_DEMO = true;</script>\n<script src="demo.js"></script>\n<script>#' \
  "$ROOT/app/static/index.html" > "$ROOT/docs/demo/index.html"
cp "$ROOT/app/static/demo.js" "$ROOT/docs/demo/demo.js"
touch "$ROOT/docs/.nojekyll"
echo "docs/demo updated"
