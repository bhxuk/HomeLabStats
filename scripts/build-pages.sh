#!/usr/bin/env bash
# Builds the GitHub Pages demo in docs/demo/ from the real app in app/static/,
# so the public demo always matches the dashboard. Run after changing anything
# in app/static/ or CHANGELOG.md.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
python3 - "$ROOT" <<'PY'
import json, re, shutil, sys
from pathlib import Path

root = Path(sys.argv[1])
static, out = root / "app" / "static", root / "docs" / "demo"
version = (root / "app" / "VERSION").read_text().strip()

# Same parser as app/updater.py
text = (root / "CHANGELOG.md").read_text()
heads = list(re.finditer(r"^##\s+\[?v?(\d+\.\d+\.\d+)\]?(?:\s*[-–]\s*(.+?))?\s*$", text, re.M))
changelog = []
for i, m in enumerate(heads):
    end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
    changelog.append({"version": m.group(1), "date": (m.group(2) or "").strip(), "body": text[m.end():end].strip(),
                      "installed": m.group(1) == version, "new": False})

if out.exists():
    shutil.rmtree(out)
out.mkdir(parents=True)
shutil.copytree(static, out / "assets", ignore=shutil.ignore_patterns("index.html"))
demo = out / "assets" / "demo.js"
demo.write_text(re.sub(r'VERSION = "[^"]+"', f'VERSION = "{version}"', demo.read_text(), count=1))

inject = ('<script>window.HLS_DEMO = true; window.HLS_CHANGELOG = ' + json.dumps(changelog).replace("</", "<\\/") + ';</script>\n'
          '<script src="assets/demo.js"></script>\n')
html = (static / "index.html").read_text()
html = html.replace('<script src="assets/js/core.js"></script>', inject + '<script src="assets/js/core.js"></script>', 1)
(out / "index.html").write_text(html)
(root / "docs" / ".nojekyll").touch()
print(f"docs/demo updated (v{version}, {len(changelog)} changelog entries)")
PY
