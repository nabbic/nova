output "webhook_url" {
  description = "URL to register as the Notion webhook endpoint"
  value       = "${aws_api_gateway_stage.webhook_relay.invoke_url}/"
}
