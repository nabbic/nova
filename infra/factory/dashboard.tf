# NOTE: this file used to host the v1 dashboard, alarm, and Logs Insights
# queries. After v2 cutover (2026-05-04) those v1 pieces moved out:
#   - v1 dashboard          → deleted (replaced by dashboard-v2.tf)
#   - v1 execution-failures → deleted (replaced by alarms-v2.tf)
#   - v1 saved queries      → deleted (replaced by logs-insights-queries.tf)
# Only the SNS topic, email subscription, and $20 budget remain here as
# shared/v1-baseline resources used by both v1 fallback and v2.

resource "aws_sns_topic" "factory_alerts" {
  name = "${local.name_prefix}-alerts"
  tags = local.common_tags
}

resource "aws_sns_topic_subscription" "factory_alerts_email" {
  topic_arn = aws_sns_topic.factory_alerts.arn
  protocol  = "email"
  endpoint  = "nabbic@gmail.com"
}

resource "aws_budgets_budget" "factory_monthly" {
  name         = "${local.name_prefix}-monthly"
  budget_type  = "COST"
  limit_amount = "20"
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  cost_filter {
    name   = "TagKeyValue"
    values = ["user:Component$factory"]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = ["nabbic@gmail.com"]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = ["nabbic@gmail.com"]
  }
}
