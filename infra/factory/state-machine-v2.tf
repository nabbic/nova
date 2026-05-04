resource "aws_cloudwatch_log_group" "sfn_v2" {
  name              = "/aws/states/nova-factory-v2"
  retention_in_days = 30
  tags              = merge(local.common_tags, { Generation = "v2" })
}

resource "aws_sfn_state_machine" "v2" {
  name     = "nova-factory-v2"
  role_arn = aws_iam_role.sfn_exec.arn
  type     = "STANDARD"

  definition = templatefile("${path.module}/state-machine-v2.json.tpl", {
    region      = var.aws_region
    account_id  = data.aws_caller_identity.current.account_id
    name_prefix = local.name_prefix
  })

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.sfn_v2.arn}:*"
    include_execution_data = true
    level                  = "ALL"
  }
  tracing_configuration { enabled = true }
  tags                  = merge(local.common_tags, { Generation = "v2" })

  depends_on = [
    aws_lambda_function.handlers_v2,
    aws_lambda_function.ralph_turn,
    aws_lambda_function.validate_v2,
  ]
}

output "v2_state_machine_arn" {
  value = aws_sfn_state_machine.v2.arn
}
