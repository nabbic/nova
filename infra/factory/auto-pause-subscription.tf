# Subscribe the auto_pause Lambda to the existing alerts SNS topic.
resource "aws_sns_topic_subscription" "auto_pause_to_alerts" {
  topic_arn = aws_sns_topic.factory_alerts.arn
  protocol  = "lambda"
  endpoint  = aws_lambda_function.handlers_v2["auto_pause"].arn
}

resource "aws_lambda_permission" "auto_pause_from_sns" {
  statement_id  = "AllowSNSInvokeAutoPause"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.handlers_v2["auto_pause"].function_name
  principal     = "sns.amazonaws.com"
  source_arn    = aws_sns_topic.factory_alerts.arn
}
