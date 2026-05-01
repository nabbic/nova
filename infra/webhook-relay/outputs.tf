output "webhook_url" {
  description = "URL to register as the Notion webhook endpoint"
  value       = aws_lambda_function_url.webhook_relay.function_url
}
