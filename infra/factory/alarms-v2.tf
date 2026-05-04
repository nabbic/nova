resource "aws_cloudwatch_metric_alarm" "v2_executions_failed" {
  alarm_name          = "nova-factory-v2-execution-failures"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 3   # 3 consecutive 5-min periods
  datapoints_to_alarm = 3
  metric_name         = "ExecutionsFailed"
  namespace           = "AWS/States"
  period              = 300
  statistic           = "Sum"
  threshold           = 1
  alarm_description   = "3 consecutive nova-factory-v2 execution failures within 15 min."
  treat_missing_data  = "notBreaching"

  dimensions = {
    StateMachineArn = aws_sfn_state_machine.v2.arn
  }

  alarm_actions = [aws_sns_topic.factory_alerts.arn]
  ok_actions    = []

  tags = merge(local.common_tags, { Generation = "v2" })
}
