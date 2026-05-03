#!/usr/bin/env bash
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
rm -rf "$HERE/python" "$HERE/layer.zip"
mkdir -p "$HERE/python"
pip install --target "$HERE/python" -r "$HERE/requirements.txt" --quiet
cd "$HERE" && 7z a -tzip layer.zip python/ -bso0 -bsp0 2>/dev/null || zip -r layer.zip python/ -q
echo "layer.zip built ($(du -h layer.zip | cut -f1))"
