#!/usr/bin/env bash
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
rm -rf "$HERE/python" "$HERE/layer.zip"
mkdir -p "$HERE/python"
# Build inside Docker to produce Linux x86_64 binaries compatible with Lambda
if command -v docker &>/dev/null; then
  # Convert path for Docker mount (handles Windows git-bash /c/... paths)
  HOST_PATH=$(cygpath -w "$HERE" 2>/dev/null || echo "$HERE")
  docker run --rm -v "${HOST_PATH}:/layer" python:3.12-slim \
    bash -c "pip install --target /layer/python -r /layer/requirements.txt --quiet --root-user-action=ignore"
else
  pip install --target "$HERE/python" -r "$HERE/requirements.txt" --quiet
fi
cd "$HERE" && 7z a -tzip layer.zip python/ -bso0 -bsp0 2>/dev/null || zip -r layer.zip python/ -q
echo "layer.zip built ($(du -h layer.zip | cut -f1))"
