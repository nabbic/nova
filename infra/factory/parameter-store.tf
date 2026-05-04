resource "aws_ssm_parameter" "factory_paused" {
  name        = "/nova/factory/paused"
  description = "Boolean flag — when 'true', webhook deliveries 200-OK without dispatching."
  type        = "String"
  value       = "false"

  lifecycle {
    ignore_changes = [value]  # auto_pause Lambda flips this; Terraform owns existence only.
  }

  tags = merge(local.common_tags, { Generation = "v2" })
}

output "factory_paused_param_name" {
  value = aws_ssm_parameter.factory_paused.name
}
