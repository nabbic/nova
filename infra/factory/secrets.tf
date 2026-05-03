# Application-runtime secrets used by the factory Lambdas.
# Create these manually before first apply (one-time bootstrap):
#   aws secretsmanager create-secret --name nova/factory/anthropic-api-key --secret-string "$ANTHROPIC_API_KEY"
#   aws secretsmanager create-secret --name nova/factory/notion-api-key --secret-string "$NOTION_API_KEY"
#   aws secretsmanager create-secret --name nova/factory/github-token --secret-string "$GH_TOKEN"
#   aws secretsmanager create-secret --name nova/factory/notion-features-db-id --secret-string "$NOTION_FEATURES_DB_ID"
#   aws secretsmanager create-secret --name nova/factory/notion-runs-db-id --secret-string "$NOTION_RUNS_DB_ID"
#   aws secretsmanager create-secret --name nova/factory/notion-decisions-db-id --secret-string "$NOTION_DECISIONS_DB_ID"

data "aws_secretsmanager_secret" "anthropic_api_key"      { name = "nova/factory/anthropic-api-key" }
data "aws_secretsmanager_secret" "notion_api_key"         { name = "nova/factory/notion-api-key" }
data "aws_secretsmanager_secret" "github_token"           { name = "nova/factory/github-token" }
data "aws_secretsmanager_secret" "notion_features_db_id"  { name = "nova/factory/notion-features-db-id" }
data "aws_secretsmanager_secret" "notion_runs_db_id"      { name = "nova/factory/notion-runs-db-id" }
data "aws_secretsmanager_secret" "notion_decisions_db_id" { name = "nova/factory/notion-decisions-db-id" }
