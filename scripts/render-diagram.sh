#!/usr/bin/env bash
# Render the mermaid diagram in docs/diagram.md to docs/diagram.png.
#
# Requires mermaid-cli (`npm install -g @mermaid-js/mermaid-cli`) and a local
# Chrome/Chromium for its headless renderer. Run from anywhere:
#   scripts/render-diagram.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/docs/diagram.md"
OUT="$ROOT/docs/diagram.png"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# Extract the first ```mermaid fenced block from the markdown.
awk '/^```mermaid$/{f=1;next} /^```$/{f=0} f' "$SRC" > "$TMP/diagram.mmd"
[ -s "$TMP/diagram.mmd" ] || { echo "✗ no mermaid block found in $SRC" >&2; exit 1; }

# Point puppeteer at a system browser so it doesn't try to download one.
CHROME=""
for c in \
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  "/Applications/Chromium.app/Contents/MacOS/Chromium" \
  "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"; do
  [ -x "$c" ] && CHROME="$c" && break
done

ARGS=(-i "$TMP/diagram.mmd" -o "$OUT" -w 1600 -b white)
if [ -n "$CHROME" ]; then
  printf '{"executablePath": "%s"}\n' "$CHROME" > "$TMP/pptr.json"
  ARGS+=(-p "$TMP/pptr.json")
fi

mmdc "${ARGS[@]}"
echo "✓ rendered $OUT"
