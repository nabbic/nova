#!/usr/bin/env bash
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$HERE/../.." && pwd)
DIST="$HERE/dist"
PROMPTS_SRC="$REPO_ROOT/.claude/agents"
PROMPTS_DST="$HERE/agent_prompts"

rm -rf "$DIST" "$PROMPTS_DST"
mkdir -p "$DIST" "$PROMPTS_DST"
cp "$PROMPTS_SRC"/*.md "$PROMPTS_DST/"

# Prefer system zip, fall back to 7z (Windows), then Python zipfile
_zip() {
  local out="$1"; shift
  if command -v zip &>/dev/null; then
    (cd "$1" && zip -r "$out" . -q)
  elif command -v 7z &>/dev/null; then
    (cd "$1" && 7z a -tzip "$out" . -bso0 -bsp0)
  else
    python3 -c "
import sys, zipfile, os, pathlib
out, src = sys.argv[1], pathlib.Path(sys.argv[2])
with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as zf:
    for f in src.rglob('*'):
        if f.is_file():
            zf.write(f, f.relative_to(src))
" "$out" "$1"
  fi
}

for handler in "$HERE"/handlers/*.py; do
  name=$(basename "$handler" .py)
  STAGE=$(mktemp -d)
  cp -r "$HERE/common" "$STAGE/"
  cp -r "$PROMPTS_DST" "$STAGE/agent_prompts"
  # v2: ship the canonical PRD schema and system prompts in every zip
  mkdir -p "$STAGE/.factory"
  cp "$REPO_ROOT/.factory/prd.schema.json"        "$STAGE/.factory/"
  cp "$REPO_ROOT/.factory/implementer-system.md"  "$STAGE/.factory/" 2>/dev/null || true
  cp "$REPO_ROOT/.factory/reviewer-system.md"     "$STAGE/.factory/" 2>/dev/null || true
  cp "$handler" "$STAGE/$name.py"
  _zip "$DIST/$name.zip" "$STAGE"
  rm -rf "$STAGE"
  echo "built dist/$name.zip"
done
echo "All handlers built."
