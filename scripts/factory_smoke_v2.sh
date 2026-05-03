#!/usr/bin/env bash
# Factory v2 smoke runner.
# Usage: bash scripts/factory_smoke_v2.sh <fixture_name>
# Where <fixture_name> matches a file at scripts/factory_smoke_fixtures/<name>.json

set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: $0 <trivial|medium|oversized>" >&2
  exit 2
fi

FIXTURE="$1"
HERE=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$HERE/.." && pwd)
FIXTURE_PATH="$REPO_ROOT/scripts/factory_smoke_fixtures/${FIXTURE}.json"
ENV_FILE="$REPO_ROOT/.env"

if [[ ! -f "$FIXTURE_PATH" ]]; then
  echo "fixture not found: $FIXTURE_PATH" >&2
  exit 2
fi

source <(sed 's/^/export /' "$ENV_FILE")
: "${NOTION_API_KEY:?NOTION_API_KEY missing}"
: "${NOTION_FEATURES_DB_ID:?NOTION_FEATURES_DB_ID missing}"

EXPECTED=$(jq -r .expected_outcome "$FIXTURE_PATH")
TITLE=$(jq -r .title "$FIXTURE_PATH")
DESCRIPTION=$(jq -r .description "$FIXTURE_PATH")
TECH=$(jq -r .tech_notes "$FIXTURE_PATH")
ACCEPT=$(jq -r .acceptance_criteria "$FIXTURE_PATH")
OOS=$(jq -r .out_of_scope "$FIXTURE_PATH")

echo "==> Creating synthetic Notion page: $TITLE"
PAGE_PAYLOAD=$(jq -n \
  --arg db "$NOTION_FEATURES_DB_ID" \
  --arg t "$TITLE" \
  --arg d "$DESCRIPTION" \
  --arg n "$TECH" \
  --arg a "$ACCEPT" \
  --arg o "$OOS" \
  '{
     parent: {database_id: $db},
     properties: {
       Title:                 {title:    [{text: {content: $t}}]},
       Status:                {status:   {name: "Ready to Build"}},
       Description:           {rich_text:[{text: {content: $d}}]},
       "Tech Notes":          {rich_text:[{text: {content: $n}}]},
       "Acceptance Criteria": {rich_text:[{text: {content: $a}}]},
       "Out of Scope":        {rich_text:[{text: {content: $o}}]}
     }
   }')

PAGE_RESP=$(curl -s -X POST https://api.notion.com/v1/pages \
  -H "Authorization: Bearer $NOTION_API_KEY" \
  -H "Notion-Version: 2022-06-28" \
  -H "Content-Type: application/json" \
  -d "$PAGE_PAYLOAD")
FEATURE_ID=$(echo "$PAGE_RESP" | jq -r .id)
if [[ -z "$FEATURE_ID" || "$FEATURE_ID" == "null" ]]; then
  echo "Notion page creation failed:" >&2
  echo "$PAGE_RESP" >&2
  exit 1
fi
echo "    feature_id = $FEATURE_ID"

SM_ARN=$(terraform -chdir="$REPO_ROOT/infra/factory" output -raw v2_planonly_state_machine_arn)
EXEC_NAME="smoke-${FIXTURE}-$(date +%s)"
EXEC_ARN=$(aws stepfunctions start-execution \
  --state-machine-arn "$SM_ARN" \
  --name "$EXEC_NAME" \
  --input "{\"feature_id\":\"$FEATURE_ID\"}" \
  --query executionArn --output text)
echo "==> Started execution $EXEC_NAME"

# Poll
for _ in $(seq 1 60); do
  STATUS=$(aws stepfunctions describe-execution --execution-arn "$EXEC_ARN" --query status --output text)
  if [[ "$STATUS" != "RUNNING" ]]; then break; fi
  sleep 5
done
echo "==> Execution status: $STATUS"

# Fetch the Notion page state
NOTION_STATUS=$(curl -s -H "Authorization: Bearer $NOTION_API_KEY" \
  -H "Notion-Version: 2022-06-28" \
  "https://api.notion.com/v1/pages/$FEATURE_ID" \
  | jq -r '.properties.Status.status.name // .properties.Status.select.name // "unknown"')
echo "==> Notion page status: $NOTION_STATUS"

case "$EXPECTED" in
  plan_passes_no_blockers)
    if [[ "$STATUS" == "SUCCEEDED" ]]; then
      echo "OK — execution succeeded as expected"; exit 0
    fi
    echo "FAIL — expected SUCCEEDED, got $STATUS" >&2; exit 1
    ;;
  plan_blocks_with_feature_too_large)
    if [[ "$STATUS" == "SUCCEEDED" && "$NOTION_STATUS" == "Failed" ]]; then
      echo "OK — feature was blocked at Plan as expected"; exit 0
    fi
    echo "FAIL — expected SUCCEEDED + Notion=Failed, got SFN=$STATUS Notion=$NOTION_STATUS" >&2; exit 1
    ;;
  *)
    echo "Unknown expected_outcome: $EXPECTED" >&2; exit 2 ;;
esac
