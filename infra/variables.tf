variable "environment" {
  type        = string
  description = "Deployment environment (staging or production)"

  validation {
    condition     = contains(["staging", "production"], var.environment)
    error_message = "environment must be either 'staging' or 'production'."
  }
}

variable "app_sg_id" {
  type        = string
  description = "Security group ID of the application layer (ECS tasks) permitted to connect to RDS on port 5432. Provided by a later infra feature."
  # No default — caller must supply this value
}

variable "subnet_ids" {
  type        = list(string)
  description = "List of subnet IDs for the RDS DB subnet group. Provided by the VPC infra feature."
  # No default — caller must supply this value
}

variable "vpc_id" {
  type        = string
  description = "VPC ID in which the RDS security group will be created. Provided by the VPC infra feature."
  # No default — caller must supply this value
}

variable "db_username" {
  type        = string
  sensitive   = true
  description = "RDS master username. Supply via TF_VAR_db_username CI/CD secret — never commit this value."
  # No default — caller must supply this value
}

variable "db_password" {
  type        = string
  sensitive   = true
  description = "RDS master password. Supply via TF_VAR_db_password CI/CD secret — never commit this value."
  # No default — caller must supply this value
}

# ---------------------------------------------------------------------------
# Variables required by the system prompt contract (ECS/container infra)
# These are declared here for future ECS modules; not used by cognito/rds.
# ---------------------------------------------------------------------------
variable "api_image" {
  type        = string
  description = "Full ECR image URI for the API, e.g. 123456789.dkr.ecr.us-east-1.amazonaws.com/nova-api:abc1234. Set by CI/CD pipeline via TF_VAR_api_image."
  default     = "placeholder/nova-api:latest" # overridden by CI/CD at deploy time
}

variable "private_subnet_ids" {
  type        = list(string)
  description = "Private subnet IDs for ECS task networking. Provided by the VPC infra feature."
  default     = []
}

variable "alb_sg_id" {
  type        = string
  description = "Security group ID of the Application Load Balancer. Provided by the networking infra feature."
  default     = ""
}
