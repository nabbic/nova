# v2 Lambdas — live alongside v1 in the same module. Distinct function names
# (suffixed in `handlers_v2` keys), shared IAM role, shared S3 bucket and
# DDB tables.

locals {
  handlers_v2 = {
    load_feature        = { timeout = 60,  memory = 512  }
    plan                = { timeout = 120, memory = 1024 }
    mark_blocked        = { timeout = 30,  memory = 256  }
    review              = { timeout = 180, memory = 1024 }
    commit_and_push_v2  = { timeout = 300, memory = 1024 }
    probe_staging       = { timeout = 60,  memory = 512  }
    revert_merge        = { timeout = 120, memory = 512  }
    auto_pause          = { timeout = 30,  memory = 256  }
  }
}

resource "aws_lambda_function" "handlers_v2" {
  for_each = local.handlers_v2

  function_name    = "${local.name_prefix}-${replace(each.key, "_", "-")}"
  filename         = "${path.module}/../../scripts/factory_lambdas/dist/${each.key}.zip"
  source_code_hash = filebase64sha256("${path.module}/../../scripts/factory_lambdas/dist/${each.key}.zip")
  role             = aws_iam_role.lambda_exec.arn
  handler          = "${each.key}.handler"
  runtime          = "python3.12"
  timeout          = each.value.timeout
  memory_size      = each.value.memory
  layers           = [aws_lambda_layer_version.shared.arn]

  tracing_config { mode = "Active" }

  environment {
    variables = {
      WORKSPACE_BUCKET = aws_s3_bucket.workspaces.bucket
      LOCKS_TABLE      = aws_dynamodb_table.locks.name
      RUNS_TABLE       = aws_dynamodb_table.runs.name
      GITHUB_OWNER     = var.github_owner
      GITHUB_REPO      = var.github_repo
      PLAN_MODEL       = "claude-haiku-4-5"
      STAGING_URL      = var.staging_url
      PAUSED_PARAM     = aws_ssm_parameter.factory_paused.name
    }
  }

  depends_on = [null_resource.build_handlers, aws_lambda_layer_version.shared]
  tags = merge(local.common_tags, { Generation = "v2" })
}

resource "aws_cloudwatch_log_group" "handlers_v2" {
  for_each          = local.handlers_v2
  name              = "/aws/lambda/${local.name_prefix}-${replace(each.key, "_", "-")}"
  retention_in_days = 30
  tags              = merge(local.common_tags, { Generation = "v2" })
}
