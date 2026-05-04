resource "aws_cloudwatch_query_definition" "v2_ralph_turn_summary" {
  name = "nova-factory-v2/ralph-turn-summary"
  log_group_names = [
    aws_cloudwatch_log_group.ralph_turn.name,
  ]
  query_string = <<-EOT
    fields @timestamp, @message
    | parse @message /completion_signal=(?<done>true|false), input_tokens=(?<inp>\d+), output_tokens=(?<out>\d+)/
    | filter ispresent(done)
    | stats count() as turns, sum(inp) as total_input, sum(out) as total_output by bin(1h)
    | sort @timestamp desc
  EOT
}

resource "aws_cloudwatch_query_definition" "v2_validation_failures" {
  name = "nova-factory-v2/validation-failures"
  log_group_names = [
    aws_cloudwatch_log_group.validate_v2.name,
  ]
  query_string = <<-EOT
    fields @timestamp, @message
    | filter @message like /"passed":\s*false/
    | sort @timestamp desc
    | limit 100
  EOT
}

resource "aws_cloudwatch_query_definition" "v2_execution_trace" {
  name = "nova-factory-v2/execution-trace"
  log_group_names = [
    aws_cloudwatch_log_group.sfn_v2.name,
    aws_cloudwatch_log_group.ralph_turn.name,
    aws_cloudwatch_log_group.validate_v2.name,
  ]
  query_string = <<-EOT
    fields @timestamp, @log, @message
    | filter @message like /<execution-id>/
    | sort @timestamp asc
    | limit 200
  EOT
}
