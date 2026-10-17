#!/bin/bash
# ci/e2e.sh [EDITOR_BUILD_DIR] : run hatd --sim with an editor build and run the B3 Playwright tests.
# PYTHON selects the interpreter for hatd (default python3); Playwright's Chromium must be installed.
set -euo pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
build=$(cd "${1:-$repo/editor/packages/scratch-gui/build-b3}" && pwd)
python=${PYTHON:-python3}
case $python in */*) python=$(cd "$(dirname "$python")" && pwd)/$(basename "$python") ;; esac
work=$(mktemp -d)
cat > "$work/config.toml" <<EOF
pin = "1234"
data_dir = "$work/data"
static_dir = "$build"
http_host = "127.0.0.1"
http_port = 8090
EOF
(cd "$repo/hatd" && exec "$python" -m b3hatd --config "$work/config.toml" --sim) > "$work/hatd.log" 2>&1 &
hatd=$!
trap 'kill $hatd 2>/dev/null; wait $hatd 2>/dev/null; rm -rf "$work"' EXIT
for _ in $(seq 1 40); do
    curl -sf -o /dev/null http://127.0.0.1:8090/ && break
    sleep 0.25
done
cd "$repo/editor/packages/scratch-gui"
B3_URL=http://127.0.0.1:8090 B3_MOTOR=A npx playwright test -c test/b3-e2e/playwright.config.mjs || {
    echo "--- hatd log ---"; cat "$work/hatd.log"; exit 1; }
