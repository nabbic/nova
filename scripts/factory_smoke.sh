#!/usr/bin/env bash
# Smoke-test the Nova factory pipeline end-to-end.
# Usage: FEATURE_ID=<notion-page-id> bash scripts/factory_smoke.sh
#        bash scripts/factory_smoke.sh <notion-page-id>
set -euo pipefail

FEATURE_ID="${1:-${FEATURE_ID:-}}"
if [[ -z "$FEATURE_ID" ]]; then
  echo "ERROR: provide a Notion page ID as \$1 or FEATURE_ID env var" >&2
  exit 1
fi

REGION="${AWS_REGION:-us-east-1}"
SFN_ARN=$(aws stepfunctions list-state-machines \
  --query "stateMachines[?name=='nova-factory-pipeline'].stateMachineArn | [0]" \
  --output text --region "$REGION")

if [[ -z "$SFN_ARN" || "$SFN_ARN" == "None" ]]; then
  echo "ERROR: nova-factory-pipeline state machine not found in $REGION" >&2
  exit 1
fi

EXEC_NAME="smoke-$(date +%Y%m%d-%H%M%S)-${FEATURE_ID:0:8}"
echo "Starting execution: $EXEC_NAME"
echo "  State machine: $SFN_ARN"
echo "  Feature ID:    $FEATURE_ID"

EXEC_ARN=$(aws stepfunctions start-execution \
  --state-machine-arn "$SFN_ARN" \
  --name "$EXEC_NAME" \
  --input "{\"feature_id\": \"$FEATURE_ID\"}" \
  --query executionArn --output text --region "$REGION")

echo "  Execution ARN: $EXEC_ARN"
echo ""

POLL_INTERVAL=15
TIMEOUT=3600
START=$(date +%s)

while true; do
  NOW=$(date +%s)
  ELAPSED=$(( NOW - START ))
  if (( ELAPSED > TIMEOUT )); then
    echo "TIMEOUT after ${ELAPSED}s" >&2
    exit 2
  fi

  STATUS=$(aws stepfunctions describe-execution \
    --execution-arn "$EXEC_ARN" \
    --query status --output text --region "$REGION")

  printf "[%4ds] %s\n" "$ELAPSED" "$STATUS"

  case "$STATUS" in
    SUCCEEDED)
      echo ""
      echo "SMOKE PASS — $EXEC_NAME"
      exit 0
      ;;
    FAILED|TIMED_OUT|ABORTED)
      echo ""
      echo "SMOKE FAIL — $STATUS"
      aws stepfunctions get-execution-history \
        --execution-arn "$EXEC_ARN" \
        --query "events[?type=='ExecutionFailed' || type=='TaskFailed'].{type:type,details:executionFailedEventDetails}" \
        --output json --region "$REGION" | python3 -m json.tool
      exit 1
      ;;
    RUNNING)
      sleep "$POLL_INTERVAL"
      ;;
    *)
      echo "Unexpected status: $STATUS" >&2
      sleep "$POLL_INTERVAL"
      ;;
  esac
done
