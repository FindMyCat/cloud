#!/usr/bin/env bash
# Deploy the FindMyCat web app to the server.
# Usage: ./deploy-webapp.sh user@your-server

set -euo pipefail

SERVER="${1:?Usage: $0 user@your-server}"
REMOTE_DIR="/var/docker/traccar/web/cat"
LOCAL_DIR="$(dirname "$0")/web-app"

echo "==> Creating remote directory..."
ssh "$SERVER" "mkdir -p $REMOTE_DIR"

echo "==> Syncing web app files..."
rsync -av --delete \
  --exclude='config.js' \
  --exclude='*.md' \
  --exclude='nginx-local.conf' \
  --exclude='dev.sh' \
  "$LOCAL_DIR/" "$SERVER:$REMOTE_DIR/"

echo ""
echo "==> Done. Checking config.js on server..."
if ssh "$SERVER" "test -f $REMOTE_DIR/config.js"; then
  echo "    config.js exists — no changes made."
else
  echo "    config.js MISSING. Creating from template..."
  scp "$LOCAL_DIR/config.example.js" "$SERVER:$REMOTE_DIR/config.js"
  echo ""
  echo "    *** ACTION REQUIRED ***"
  echo "    Edit config.js on the server and fill in your Hologram credentials:"
  echo "      ssh $SERVER"
  echo "      nano $REMOTE_DIR/config.js"
fi

echo ""
echo "==> Web app live at: https://<your-domain>/cat/"
