output "state_bucket_name" {
  description = "Name of the S3 bucket holding Terraform state for all Nova modules."
  value       = aws_s3_bucket.state.id
}

output "lock_table_name" {
  description = "Name of the DynamoDB table used for Terraform state locking."
  value       = aws_dynamodb_table.locks.name
}

output "aws_region" {
  description = "Region in which the state bucket and lock table live."
  value       = var.aws_region
}
