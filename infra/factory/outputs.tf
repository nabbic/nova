output "workspace_bucket"        { value = aws_s3_bucket.workspaces.bucket }
output "locks_table"             { value = aws_dynamodb_table.locks.name }
output "runs_table"              { value = aws_dynamodb_table.runs.name }
output "lambda_exec_role_arn"    { value = aws_iam_role.lambda_exec.arn }
output "sfn_exec_role_arn"       { value = aws_iam_role.sfn_exec.arn }
