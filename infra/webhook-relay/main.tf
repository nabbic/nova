terraform {
  required_version = ">= 1.7"
  backend "s3" {
    bucket         = "nova-terraform-state-577638385116"
    key            = "webhook-relay/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "nova-terraform-locks"
    encrypt        = true
  }
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

data "terraform_remote_state" "factory" {
  backend = "s3"
  config = {
    bucket = "nova-terraform-state-577638385116"
    key    = "factory/terraform.tfstate"
    region = "us-east-1"
  }
}

data "archive_file" "lambda_zip" {
  type        = "zip"
  source_dir  = "${path.module}/lambda"
  output_path = "${path.module}/.build/webhook-relay.zip"
}

locals {
  # Notion webhook source IPs + developer IP for testing
  allowed_ips = [
    "131.149.232.0/21", # Notion (all regions)
    "208.103.161.0/24", # Notion (additional range)
    "108.235.54.160/32", # Developer
  ]
}

resource "aws_iam_role" "lambda_exec" {
  name = "nova-webhook-relay-exec"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })

  tags = {
    Project   = "nova"
    ManagedBy = "terraform"
  }
}

resource "aws_iam_role_policy_attachment" "lambda_logs" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "lambda_states" {
  name = "nova-webhook-relay-states"
  role = aws_iam_role.lambda_exec.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "states:StartExecution"
      Resource = data.terraform_remote_state.factory.outputs.state_machine_arn
    }]
  })
}

# Read /nova/factory/paused so the relay can short-circuit when paused.
resource "aws_iam_role_policy" "lambda_ssm" {
  name = "nova-webhook-relay-ssm"
  role = aws_iam_role.lambda_exec.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "ssm:GetParameter"
      Resource = "arn:aws:ssm:${var.aws_region}:*:parameter/nova/factory/paused"
    }]
  })
}

# Allow Lambda to read its own secrets from Secrets Manager
resource "aws_iam_role_policy" "lambda_secrets" {
  name = "nova-webhook-relay-secrets"
  role = aws_iam_role.lambda_exec.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "secretsmanager:GetSecretValue"
      Resource = [
        "arn:aws:secretsmanager:${var.aws_region}:*:secret:nova/webhook-relay/*",
      ]
    }]
  })
}

# Read secrets from Secrets Manager — no plaintext in Terraform variables or state
data "aws_secretsmanager_secret_version" "notion_api_key" {
  secret_id = "nova/webhook-relay/notion-api-key"
}

data "aws_secretsmanager_secret_version" "github_token" {
  secret_id = "nova/webhook-relay/github-token"
}

resource "aws_lambda_function" "webhook_relay" {
  function_name    = "nova-webhook-relay"
  filename         = data.archive_file.lambda_zip.output_path
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256
  runtime          = "nodejs20.x"
  handler          = "index.handler"
  role             = aws_iam_role.lambda_exec.arn
  timeout          = 10

  environment {
    variables = {
      GITHUB_OWNER      = var.github_owner
      GITHUB_REPO       = var.github_repo
      GITHUB_TOKEN      = data.aws_secretsmanager_secret_version.github_token.secret_string
      NOTION_API_KEY    = data.aws_secretsmanager_secret_version.notion_api_key.secret_string
      FACTORY_BACKEND   = "github-actions"  # flip to "step-functions" in Phase 8 cutover
      STATE_MACHINE_ARN = data.terraform_remote_state.factory.outputs.state_machine_arn
      PAUSED_PARAM      = "/nova/factory/paused"
    }
  }

  tags = {
    Project   = "nova"
    ManagedBy = "terraform"
  }
}

# API Gateway REST API with IP-based resource policy
# NON-FREE-TIER: API Gateway costs $3.50/million requests after free tier (1M/month for 12 months)
resource "aws_api_gateway_rest_api" "webhook_relay" {
  name = "nova-webhook-relay"

  endpoint_configuration {
    types = ["REGIONAL"]
  }

  # Allow only Notion IPs and developer IP; deny everything else
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = "*"
        Action    = "execute-api:Invoke"
        Resource  = "arn:aws:execute-api:${var.aws_region}:*:*/*/*"
        Condition = {
          IpAddress = {
            "aws:SourceIp" = local.allowed_ips
          }
        }
      },
      {
        Effect    = "Deny"
        Principal = "*"
        Action    = "execute-api:Invoke"
        Resource  = "arn:aws:execute-api:${var.aws_region}:*:*/*/*"
        Condition = {
          NotIpAddress = {
            "aws:SourceIp" = local.allowed_ips
          }
        }
      }
    ]
  })

  tags = {
    Project   = "nova"
    ManagedBy = "terraform"
  }
}

resource "aws_api_gateway_method" "webhook_post" {
  rest_api_id   = aws_api_gateway_rest_api.webhook_relay.id
  resource_id   = aws_api_gateway_rest_api.webhook_relay.root_resource_id
  http_method   = "POST"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "webhook_lambda" {
  rest_api_id             = aws_api_gateway_rest_api.webhook_relay.id
  resource_id             = aws_api_gateway_rest_api.webhook_relay.root_resource_id
  http_method             = aws_api_gateway_method.webhook_post.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.webhook_relay.invoke_arn
}

resource "aws_lambda_permission" "apigw" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.webhook_relay.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.webhook_relay.execution_arn}/*/*"
}

resource "aws_api_gateway_deployment" "webhook_relay" {
  depends_on  = [aws_api_gateway_integration.webhook_lambda]
  rest_api_id = aws_api_gateway_rest_api.webhook_relay.id

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_api_gateway_stage" "webhook_relay" {
  deployment_id = aws_api_gateway_deployment.webhook_relay.id
  rest_api_id   = aws_api_gateway_rest_api.webhook_relay.id
  stage_name    = "prod"

  tags = {
    Project   = "nova"
    ManagedBy = "terraform"
  }
}
