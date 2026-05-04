# Container Lambdas: ralph_turn (RalphTurn) and validate_v2 (Validate-v2)

resource "aws_ecr_repository" "ralph_turn" {
  name                 = "nova-factory-ralph-turn"
  image_tag_mutability = "MUTABLE"
  tags                 = merge(local.common_tags, { Generation = "v2" })
}

resource "aws_ecr_repository" "validate_v2" {
  name                 = "nova-factory-validator"
  image_tag_mutability = "MUTABLE"
  tags                 = merge(local.common_tags, { Generation = "v2" })
}

# Hash-triggered builds
locals {
  ralph_turn_src_hash = sha256(join("", [
    filemd5("${path.module}/../../scripts/factory_lambdas/containers/ralph_turn/Dockerfile"),
    filemd5("${path.module}/../../scripts/factory_lambdas/containers/ralph_turn/ralph_turn.py"),
    filemd5("${path.module}/../../scripts/factory_lambdas/containers/ralph_turn/allowlist.py"),
    filemd5("${path.module}/../../scripts/factory_lambdas/containers/ralph_turn/git_io.py"),
    filemd5("${path.module}/../../.factory/implementer-system.md"),
  ]))
  validate_v2_src_hash = sha256(join("", [
    filemd5("${path.module}/../../scripts/factory_lambdas/containers/validate_v2/Dockerfile"),
    filemd5("${path.module}/../../scripts/factory_lambdas/containers/validate_v2/validate_v2.py"),
  ]))
}

resource "null_resource" "build_ralph_turn" {
  triggers = { src_hash = local.ralph_turn_src_hash }
  provisioner "local-exec" {
    interpreter = ["bash", "-c"]
    command     = "AWS_REGION=${var.aws_region} bash ${path.module}/../../scripts/factory_lambdas/containers/ralph_turn/build.sh"
  }
  depends_on = [aws_ecr_repository.ralph_turn]
}

resource "null_resource" "build_validate_v2" {
  triggers = { src_hash = local.validate_v2_src_hash }
  provisioner "local-exec" {
    interpreter = ["bash", "-c"]
    command     = "AWS_REGION=${var.aws_region} bash ${path.module}/../../scripts/factory_lambdas/containers/validate_v2/build.sh"
  }
  depends_on = [aws_ecr_repository.validate_v2]
}

# Look up the digest of the latest image so Lambda picks up new pushes
data "aws_ecr_image" "ralph_turn_latest" {
  repository_name = aws_ecr_repository.ralph_turn.name
  image_tag       = "latest"
  depends_on      = [null_resource.build_ralph_turn]
}

data "aws_ecr_image" "validate_v2_latest" {
  repository_name = aws_ecr_repository.validate_v2.name
  image_tag       = "latest"
  depends_on      = [null_resource.build_validate_v2]
}

resource "aws_lambda_function" "ralph_turn" {
  function_name = "${local.name_prefix}-ralph-turn"
  package_type  = "Image"
  image_uri     = "${aws_ecr_repository.ralph_turn.repository_url}@${data.aws_ecr_image.ralph_turn_latest.id}"
  role          = aws_iam_role.ralph_turn_exec.arn
  timeout       = 840   # 14 minutes (1-min headroom under Lambda's 15-min cap)
  memory_size   = 3008
  ephemeral_storage { size = 10240 }
  tracing_config { mode = "Active" }
  environment {
    variables = {
      WORKSPACE_BUCKET = aws_s3_bucket.workspaces.bucket
      RALPH_MODEL      = "claude-sonnet-4-6"
      GITHUB_OWNER     = var.github_owner
      GITHUB_REPO      = var.github_repo
    }
  }
  depends_on = [null_resource.build_ralph_turn]
  tags       = merge(local.common_tags, { Generation = "v2" })
}

resource "aws_lambda_function" "validate_v2" {
  function_name = "${local.name_prefix}-validate-v2"
  package_type  = "Image"
  image_uri     = "${aws_ecr_repository.validate_v2.repository_url}@${data.aws_ecr_image.validate_v2_latest.id}"
  role          = aws_iam_role.lambda_exec.arn
  timeout       = 600
  memory_size   = 3008
  ephemeral_storage { size = 4096 }
  tracing_config { mode = "Active" }
  environment {
    variables = {
      WORKSPACE_BUCKET = aws_s3_bucket.workspaces.bucket
    }
  }
  depends_on = [null_resource.build_validate_v2]
  tags       = merge(local.common_tags, { Generation = "v2" })
}

resource "aws_cloudwatch_log_group" "ralph_turn" {
  name              = "/aws/lambda/${local.name_prefix}-ralph-turn"
  retention_in_days = 30
  tags              = merge(local.common_tags, { Generation = "v2" })
}

resource "aws_cloudwatch_log_group" "validate_v2" {
  name              = "/aws/lambda/${local.name_prefix}-validate-v2"
  retention_in_days = 30
  tags              = merge(local.common_tags, { Generation = "v2" })
}
