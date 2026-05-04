# $50 (warning) and $100 (hard ceiling) budget tripwires.
# The existing $20 budget (dashboard.tf) stays — it sends email-only.
# The $100 budget routes ALARM notifications to the SNS topic so auto_pause
# flips /nova/factory/paused = true.

resource "aws_budgets_budget" "factory_monthly_50" {
  name         = "${local.name_prefix}-monthly-50"
  budget_type  = "COST"
  limit_amount = "50"
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  cost_filter {
    name   = "TagKeyValue"
    values = ["user:Component$factory"]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = ["nabbic@gmail.com"]
    subscriber_sns_topic_arns  = [aws_sns_topic.factory_alerts.arn]
  }
}

resource "aws_budgets_budget" "factory_monthly_100" {
  name         = "${local.name_prefix}-monthly-100"
  budget_type  = "COST"
  limit_amount = "100"
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  cost_filter {
    name   = "TagKeyValue"
    values = ["user:Component$factory"]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = ["nabbic@gmail.com"]
    subscriber_sns_topic_arns  = [aws_sns_topic.factory_alerts.arn]
  }
}
