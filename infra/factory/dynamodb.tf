resource "aws_dynamodb_table" "locks" {
  name         = "${local.name_prefix}-locks"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "feature_id"

  attribute {
    name = "feature_id"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  point_in_time_recovery { enabled = true }
  tags = local.common_tags
}

resource "aws_dynamodb_table" "runs" {
  name         = "${local.name_prefix}-runs"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "execution_id"
  range_key    = "step"

  attribute {
    name = "execution_id"
    type = "S"
  }

  attribute {
    name = "step"
    type = "S"
  }

  attribute {
    name = "feature_id"
    type = "S"
  }

  global_secondary_index {
    name            = "by-feature"
    hash_key        = "feature_id"
    range_key       = "step"
    projection_type = "ALL"
  }

  point_in_time_recovery { enabled = true }
  tags = local.common_tags
}
