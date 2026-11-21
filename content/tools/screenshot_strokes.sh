#!/bin/zsh
# Renders content/tools/stroke_preview.html for every language with headless Chrome into content/review/strokes_{lang}.png
# Needs the backend running (default http://127.0.0.1:8000). Usage: content/tools/screenshot_strokes.sh [base_url]
cd "${0:A:h}/../.." || exit 1
BASE=${1:-http://127.0.0.1:8000}
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PROFILE=$(mktemp -d)
for l in mandarin hindi arabic russian hebrew greek; do
  "$CHROME" --headless=new --disable-gpu --hide-scrollbars --user-data-dir="$PROFILE" --window-size=1500,2600 \
    --virtual-time-budget=6000 --screenshot="content/review/strokes_$l.png" \
    "$BASE/static/content/tools/stroke_preview.html?lang=$l" 2>/dev/null && echo "content/review/strokes_$l.png"
done
rm -rf "$PROFILE"
