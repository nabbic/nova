resource "aws_cloudwatch_log_group" "sfn_v2_planonly" {
  name              = "/aws/states/nova-factory-v2-planonly"
  retention_in_days = 30
  tags              = merge(local.common_tags, { Generation = "v2" })
}

resource "aws_sfn_state_machine" "v2_planonly" {
  name     = "nova-factory-v2-planonly"
  role_arn = aws_iam_role.sfn_exec.arn
  type     = "STANDARD"

  definition = templatefile("${path.module}/state-machine-v2-planonly.json.tpl", {
    region      = var.aws_region
    account_id  = data.aws_caller_identity.current.account_id
    name_prefix = local.name_prefix
  })

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.sfn_v2_planonly.arn}:*"
    include_execution_data = true
    level                  = "ALL"
  }

  tracing_configuration { enabled = true }
  tags                  = merge(local.common_tags, { Generation = "v2" })

  depends_on = [aws_lambda_function.handlers_v2]
}

output "v2_planonly_state_machine_arn" {
  value       = aws_sfn_state_machine.v2_planonly.arn
  description = "Phase 2 stub state machine (Plan stage only). Phase 3 introduces nova-factory-v2."
}
