#!/bin/sh
# Serve the web-app at /cat/ to match production path.
# Usage: ./dev.sh [port]   (default port: 8080)

PORT=${1:-8080}
APPDIR=$(cd "$(dirname "$0")" && pwd)

# config.js is gitignored (it holds credentials in real deployments)
if [ ! -f "$APPDIR/config.js" ]; then
  echo "Creating config.js from config.example.js"
  cp "$APPDIR/config.example.js" "$APPDIR/config.js"
fi

TMPDIR=$(mktemp -d)
ln -s "$APPDIR" "$TMPDIR/cat"

echo "Dev server: http://localhost:$PORT/cat/"
echo "Serving via $TMPDIR (Ctrl-C to stop)"

cd "$TMPDIR" && python3 -m http.server "$PORT"
rm -rf "$TMPDIR"
