resource "aws_iam_role" "sfn_postdeploy" {
  name = "${local.name_prefix}-sfn-postdeploy"
  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Effect = "Allow",
      Principal = { Service = "states.amazonaws.com" },
      Action = "sts:AssumeRole",
    }]
  })
  tags = merge(local.common_tags, { Generation = "v2" })
}

resource "aws_iam_role_policy" "sfn_postdeploy_inline" {
  role = aws_iam_role.sfn_postdeploy.id
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Effect = "Allow",
        Action = ["lambda:InvokeFunction"],
        Resource = [
          aws_lambda_function.handlers_v2["probe_staging"].arn,
          aws_lambda_function.handlers_v2["revert_merge"].arn,
          # update-notion is a v1 Lambda (kept) — referenced by name in the SFN template
          "arn:aws:lambda:${var.aws_region}:${data.aws_caller_identity.current.account_id}:function:${local.name_prefix}-update-notion",
        ]
      },
      {
        Effect = "Allow",
        Action = ["sns:Publish"],
        Resource = [aws_sns_topic.factory_alerts.arn]
      },
      {
        Effect = "Allow",
        Action = [
          "logs:CreateLogDelivery", "logs:GetLogDelivery", "logs:UpdateLogDelivery",
          "logs:DeleteLogDelivery", "logs:ListLogDeliveries",
          "logs:PutResourcePolicy", "logs:DescribeResourcePolicies", "logs:DescribeLogGroups",
        ],
        Resource = "*"
      },
      {
        Effect = "Allow",
        Action = ["xray:PutTraceSegments", "xray:PutTelemetryRecords"],
        Resource = "*"
      }
    ]
  })
}

resource "aws_cloudwatch_log_group" "sfn_postdeploy" {
  name              = "/aws/states/nova-factory-postdeploy"
  retention_in_days = 30
  tags              = merge(local.common_tags, { Generation = "v2" })
}

resource "aws_sfn_state_machine" "postdeploy" {
  name     = "nova-factory-postdeploy"
  role_arn = aws_iam_role.sfn_postdeploy.arn
  type     = "STANDARD"

  definition = templatefile("${path.module}/state-machine-postdeploy.json.tpl", {
    region          = var.aws_region
    account_id      = data.aws_caller_identity.current.account_id
    name_prefix     = local.name_prefix
    sns_alerts_arn  = aws_sns_topic.factory_alerts.arn
  })

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.sfn_postdeploy.arn}:*"
    include_execution_data = true
    level                  = "ALL"
  }
  tracing_configuration { enabled = true }
  tags                  = merge(local.common_tags, { Generation = "v2" })
}

output "postdeploy_state_machine_arn" {
  value = aws_sfn_state_machine.postdeploy.arn
}
