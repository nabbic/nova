variable "environment" {
  type        = string
  description = "Deployment environment (staging or production)"
}

variable "tags" {
  type        = map(string)
  description = "Tags to apply to all Cognito resources"
  default     = {}
}
