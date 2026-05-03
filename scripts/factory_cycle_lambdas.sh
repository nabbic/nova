#!/usr/bin/env bash
# Rebuild and redeploy all factory Lambda functions.
# Run this after any handler code change to ensure warm containers pick up new code.
# Usage: bash scripts/factory_cycle_lambdas.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LAMBDAS_DIR="$REPO_ROOT/scripts/factory_lambdas"
REGION="${AWS_REGION:-us-east-1}"
PREFIX="nova-factory"

echo "=== Building Lambda zips ==="
bash "$LAMBDAS_DIR/build.sh"

echo ""
echo "=== Updating zip-based Lambda functions ==="
for ZIP in "$LAMBDAS_DIR/dist"/*.zip; do
  HANDLER=$(basename "$ZIP" .zip)
  FUNC="${PREFIX}-${HANDLER//_/-}"
  # Check the function exists before trying to update
  if aws lambda get-function --function-name "$FUNC" --region "$REGION" \
       --query 'Configuration.FunctionName' --output text 2>/dev/null | grep -q "$FUNC"; then
    aws lambda update-function-code \
      --function-name "$FUNC" \
      --zip-file "fileb://$ZIP" \
      --region "$REGION" \
      --output json \
      --query '{FunctionName:FunctionName,CodeSha256:CodeSha256}' &
  else
    echo "  SKIP $FUNC (not found)"
  fi
done
wait
echo "  All zip updates dispatched."

echo ""
echo "=== Rebuilding and pushing validate_workspace container ==="
AWS_REGION="$REGION" bash "$LAMBDAS_DIR/containers/validate_workspace/build.sh"

echo ""
echo "=== Waiting for all Lambda updates to stabilise ==="
sleep 5
for ZIP in "$LAMBDAS_DIR/dist"/*.zip; do
  HANDLER=$(basename "$ZIP" .zip)
  FUNC="${PREFIX}-${HANDLER//_/-}"
  aws lambda wait function-updated \
    --function-name "$FUNC" \
    --region "$REGION" 2>/dev/null || true
done
aws lambda wait function-updated \
  --function-name "${PREFIX}-validate-workspace" \
  --region "$REGION" 2>/dev/null || true

echo ""
echo "=== Done — all Lambda functions updated ==="
