resource "aws_api_gateway_rest_api" "factory_callback" {
  name = "${local.name_prefix}-callback"
  endpoint_configuration { types = ["REGIONAL"] }
  tags = local.common_tags
}

resource "aws_api_gateway_resource" "callback" {
  rest_api_id = aws_api_gateway_rest_api.factory_callback.id
  parent_id   = aws_api_gateway_rest_api.factory_callback.root_resource_id
  path_part   = "callback"
}

resource "aws_api_gateway_method" "callback_post" {
  rest_api_id      = aws_api_gateway_rest_api.factory_callback.id
  resource_id      = aws_api_gateway_resource.callback.id
  http_method      = "POST"
  authorization    = "NONE"
  api_key_required = true
}

resource "aws_api_gateway_integration" "callback_lambda" {
  rest_api_id             = aws_api_gateway_rest_api.factory_callback.id
  resource_id             = aws_api_gateway_resource.callback.id
  http_method             = aws_api_gateway_method.callback_post.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.handlers["handle_quality_gate_callback"].invoke_arn
}

resource "aws_lambda_permission" "callback_apigw" {
  statement_id  = "AllowAPIGatewayInvokeCallback"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.handlers["handle_quality_gate_callback"].function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.factory_callback.execution_arn}/*/*"
}

resource "aws_api_gateway_deployment" "callback" {
  depends_on  = [aws_api_gateway_integration.callback_lambda]
  rest_api_id = aws_api_gateway_rest_api.factory_callback.id
  lifecycle { create_before_destroy = true }
}

resource "aws_api_gateway_stage" "callback" {
  deployment_id = aws_api_gateway_deployment.callback.id
  rest_api_id   = aws_api_gateway_rest_api.factory_callback.id
  stage_name    = "prod"
  tags          = local.common_tags
}

resource "aws_api_gateway_api_key" "callback" {
  name = "${local.name_prefix}-callback-key"
}

resource "aws_api_gateway_usage_plan" "callback" {
  name = "${local.name_prefix}-callback-plan"
  api_stages {
    api_id = aws_api_gateway_rest_api.factory_callback.id
    stage  = aws_api_gateway_stage.callback.stage_name
  }
  throttle_settings {
    rate_limit  = 10
    burst_limit = 20
  }
}

resource "aws_api_gateway_usage_plan_key" "callback" {
  key_id        = aws_api_gateway_api_key.callback.id
  key_type      = "API_KEY"
  usage_plan_id = aws_api_gateway_usage_plan.callback.id
}

output "callback_url" {
  value = "${aws_api_gateway_stage.callback.invoke_url}/callback"
}

output "callback_api_key_id" {
  value       = aws_api_gateway_api_key.callback.id
  description = "Use: aws apigateway get-api-key --api-key <id> --include-value to retrieve the key value"
}
