resource "aws_cloudwatch_dashboard" "v2" {
  dashboard_name = "nova-factory-v2"

  dashboard_body = jsonencode({
    widgets = [
      {
        type = "metric", x = 0, y = 0, width = 12, height = 6,
        properties = {
          title  = "v2 SFN executions (started / succeeded / failed)",
          metrics = [
            ["AWS/States", "ExecutionsStarted",   "StateMachineArn", aws_sfn_state_machine.v2.arn],
            [".",          "ExecutionsSucceeded", ".",                "."],
            [".",          "ExecutionsFailed",    ".",                "."]
          ],
          view = "timeSeries", stat = "Sum", period = 300, region = var.aws_region
        }
      },
      {
        type = "metric", x = 12, y = 0, width = 12, height = 6,
        properties = {
          title  = "RalphTurn invocations (success/error/throttle)",
          metrics = [
            ["AWS/Lambda", "Invocations", "FunctionName", aws_lambda_function.ralph_turn.function_name],
            [".",          "Errors",      ".",            "."],
            [".",          "Throttles",   ".",            "."]
          ],
          view = "timeSeries", stat = "Sum", period = 300, region = var.aws_region
        }
      },
      {
        type = "metric", x = 0, y = 6, width = 12, height = 6,
        properties = {
          title  = "Validate-v2 invocations + duration (avg)",
          metrics = [
            ["AWS/Lambda", "Invocations", "FunctionName", aws_lambda_function.validate_v2.function_name],
            [".",          "Duration",    ".",            ".",  {stat = "Average"}],
            [".",          "Errors",      ".",            "."]
          ],
          view = "timeSeries", stat = "Sum", period = 300, region = var.aws_region
        }
      },
      {
        type = "metric", x = 12, y = 6, width = 12, height = 6,
        properties = {
          title  = "Plan / Review duration (sum, proxy for token cost)",
          metrics = [
            ["AWS/Lambda", "Duration", "FunctionName", aws_lambda_function.handlers_v2["plan"].function_name,   {stat = "Sum"}],
            [".",          ".",        ".",            aws_lambda_function.handlers_v2["review"].function_name, {stat = "Sum"}]
          ],
          view = "timeSeries", period = 300, region = var.aws_region
        }
      },
      {
        type = "log", x = 0, y = 12, width = 24, height = 6,
        properties = {
          title  = "RalphTurn outcomes (last 1h)",
          query  = "SOURCE '${aws_cloudwatch_log_group.ralph_turn.name}' | fields @timestamp, @message | filter @message like /completion_signal/ | sort @timestamp desc | limit 50",
          region = var.aws_region,
          view   = "table"
        }
      }
    ]
  })
}

output "v2_dashboard_url" {
  value = "https://${var.aws_region}.console.aws.amazon.com/cloudwatch/home?region=${var.aws_region}#dashboards:name=nova-factory-v2"
}
