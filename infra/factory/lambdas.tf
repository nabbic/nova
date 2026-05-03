locals {
  handlers = {
    acquire_lock                 = { timeout = 30,  memory = 256  }
    release_lock                 = { timeout = 30,  memory = 256  }
    load_spec                    = { timeout = 60,  memory = 512  }
    load_project_context         = { timeout = 30,  memory = 256  }
    run_orchestrator             = { timeout = 300, memory = 2048 }
    run_agent                    = { timeout = 600, memory = 2048 }
    evaluate_security            = { timeout = 30,  memory = 256  }
    commit_and_push              = { timeout = 300, memory = 1024 }
    update_notion                = { timeout = 30,  memory = 256  }
    trigger_quality_gates        = { timeout = 30,  memory = 256  }
    handle_quality_gate_callback = { timeout = 30,  memory = 256  }
  }
}

resource "null_resource" "build_handlers" {
  triggers = {
    src_hash = sha256(join("", [
      for f in fileset("${path.module}/../../scripts/factory_lambdas", "**") :
      filemd5("${path.module}/../../scripts/factory_lambdas/${f}")
      if !startswith(f, "dist/") && !startswith(f, "agent_prompts/") && !startswith(f, "containers/")
    ]))
  }
  provisioner "local-exec" {
    command = "bash ${path.module}/../../scripts/factory_lambdas/build.sh"
  }
}

resource "aws_lambda_function" "handlers" {
  for_each = local.handlers

  function_name    = "${local.name_prefix}-${replace(each.key, "_", "-")}"
  filename         = "${path.module}/../../scripts/factory_lambdas/dist/${each.key}.zip"
  source_code_hash = filebase64sha256("${path.module}/../../scripts/factory_lambdas/dist/${each.key}.zip")
  role             = aws_iam_role.lambda_exec.arn
  handler          = "${each.key}.handler"
  runtime          = "python3.12"
  timeout          = each.value.timeout
  memory_size      = each.value.memory
  layers           = [aws_lambda_layer_version.shared.arn]

  dynamic "ephemeral_storage" {
    for_each = lookup(each.value, "ephemeral", null) != null ? [each.value.ephemeral] : []
    content { size = ephemeral_storage.value }
  }

  tracing_config { mode = "Active" }

  environment {
    variables = {
      WORKSPACE_BUCKET = aws_s3_bucket.workspaces.bucket
      LOCKS_TABLE      = aws_dynamodb_table.locks.name
      RUNS_TABLE       = aws_dynamodb_table.runs.name
      GITHUB_OWNER     = var.github_owner
      GITHUB_REPO      = var.github_repo
    }
  }

  depends_on = [null_resource.build_handlers, aws_lambda_layer_version.shared]
  tags       = local.common_tags
}

resource "aws_cloudwatch_log_group" "handlers" {
  for_each          = local.handlers
  name              = "/aws/lambda/${local.name_prefix}-${replace(each.key, "_", "-")}"
  retention_in_days = 30
  tags              = local.common_tags
}
