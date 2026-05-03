resource "aws_cloudwatch_log_group" "sfn" {
  name              = "/aws/states/nova-factory-pipeline"
  retention_in_days = 30
  tags              = local.common_tags
}

resource "aws_sfn_state_machine" "pipeline" {
  name     = "nova-factory-pipeline"
  role_arn = aws_iam_role.sfn_exec.arn
  type     = "STANDARD"

  definition = templatefile("${path.module}/state-machine.json.tpl", {
    region      = var.aws_region
    account_id  = data.aws_caller_identity.current.account_id
    name_prefix = local.name_prefix
  })

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.sfn.arn}:*"
    include_execution_data = true
    level                  = "ALL"
  }

  tracing_configuration { enabled = true }
  tags                  = local.common_tags
}

output "state_machine_arn" { value = aws_sfn_state_machine.pipeline.arn }
