resource "aws_ecr_repository" "validators" {
  name                 = "${local.name_prefix}-validators"
  image_tag_mutability = "MUTABLE"
  tags                 = local.common_tags
}

locals {
  validate_workspace_src_hash = sha256(join("", [
    filemd5("${path.module}/../../scripts/factory_lambdas/containers/validate_workspace/Dockerfile"),
    filemd5("${path.module}/../../scripts/factory_lambdas/containers/validate_workspace/validate_workspace.py"),
  ]))
}

resource "null_resource" "build_validate_workspace" {
  triggers = {
    src_hash = local.validate_workspace_src_hash
  }
  provisioner "local-exec" {
    interpreter = ["bash", "-c"]
    command     = "AWS_REGION=${var.aws_region} bash ${path.module}/../../scripts/factory_lambdas/containers/validate_workspace/build.sh"
  }
  depends_on = [aws_ecr_repository.validators]
}

resource "aws_lambda_function" "validate_workspace" {
  function_name = "${local.name_prefix}-validate-workspace"
  package_type  = "Image"
  image_uri     = "${aws_ecr_repository.validators.repository_url}:latest"
  role          = aws_iam_role.lambda_exec.arn
  timeout       = 600
  memory_size   = 3008
  ephemeral_storage { size = 4096 }
  tracing_config { mode = "Active" }
  environment {
    variables = {
      WORKSPACE_BUCKET = aws_s3_bucket.workspaces.bucket
      RUNS_TABLE       = aws_dynamodb_table.runs.name
    }
  }
  depends_on = [null_resource.build_validate_workspace]
  tags       = local.common_tags
}
