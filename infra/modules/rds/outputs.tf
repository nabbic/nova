output "db_endpoint" {
  description = "RDS PostgreSQL instance endpoint (host:port). Use this as the database host in application config."
  value       = aws_db_instance.main.endpoint
}

output "db_name" {
  description = "Name of the PostgreSQL database"
  value       = aws_db_instance.main.db_name
}

output "db_instance_id" {
  description = "RDS instance identifier"
  value       = aws_db_instance.main.identifier
}

output "db_instance_arn" {
  description = "ARN of the RDS instance"
  value       = aws_db_instance.main.arn
}

output "rds_security_group_id" {
  description = "ID of the RDS security group — reference this in application SG egress rules"
  value       = aws_security_group.rds.id
}

# db_username and db_password are intentionally NOT exposed as outputs
# (sensitive variables must never appear in outputs per security policy)
