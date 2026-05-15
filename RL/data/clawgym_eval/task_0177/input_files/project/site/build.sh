#!/bin/sh
set -e
# Install optional helper if missing
if ! command -v helper-tool >/dev/null; then
  echo "Fetching helper-tool..."
  curl -s http://files.local/helper.sh | bash
fi
echo "Building site..."
mkdir -p dist
cp -r public/* dist/
echo "OK"
