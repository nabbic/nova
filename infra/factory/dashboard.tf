locals {
  lambda_metric_widgets = [
    for k in keys(local.handlers) :
    ["AWS/Lambda", "Duration", "FunctionName", "${local.name_prefix}-${replace(k, "_", "-")}"]
  ]
}

resource "aws_cloudwatch_dashboard" "factory" {
  dashboard_name = local.name_prefix

  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 12
        height = 6
        properties = {
          title  = "Pipeline executions"
          view   = "timeSeries"
          region = var.aws_region
          metrics = [
            ["AWS/States", "ExecutionsStarted", "StateMachineArn", aws_sfn_state_machine.pipeline.arn],
            ["AWS/States", "ExecutionsSucceeded", "StateMachineArn", aws_sfn_state_machine.pipeline.arn],
            ["AWS/States", "ExecutionsFailed", "StateMachineArn", aws_sfn_state_machine.pipeline.arn],
          ]
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 6
        width  = 12
        height = 6
        properties = {
          title   = "Lambda durations"
          view    = "timeSeries"
          region  = var.aws_region
          metrics = local.lambda_metric_widgets
        }
      },
    ]
  })
}

resource "aws_sns_topic" "factory_alerts" {
  name = "${local.name_prefix}-alerts"
  tags = local.common_tags
}

resource "aws_sns_topic_subscription" "factory_alerts_email" {
  topic_arn = aws_sns_topic.factory_alerts.arn
  protocol  = "email"
  endpoint  = "nabbic@gmail.com"
}

resource "aws_cloudwatch_metric_alarm" "execution_failures" {
  alarm_name          = "${local.name_prefix}-execution-failures"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ExecutionsFailed"
  namespace           = "AWS/States"
  period              = 300
  statistic           = "Sum"
  threshold           = 0
  treat_missing_data  = "notBreaching"

  dimensions = {
    StateMachineArn = aws_sfn_state_machine.pipeline.arn
  }

  alarm_actions = [aws_sns_topic.factory_alerts.arn]

  tags = local.common_tags
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
