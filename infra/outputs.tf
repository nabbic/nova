output "buyer_user_pool_id" {
  description = "Cognito User Pool ID for buyer (PE firm) users"
  value       = module.cognito.buyer_user_pool_id
}

output "seller_user_pool_id" {
  description = "Cognito User Pool ID for seller (target company) users"
  value       = module.cognito.seller_user_pool_id
}

output "buyer_client_id" {
  description = "Cognito User Pool Client ID for the buyer pool (used by the buyer SPA)"
  value       = module.cognito.buyer_client_id
}

output "seller_client_id" {
  description = "Cognito User Pool Client ID for the seller pool (used by the seller SPA)"
  value       = module.cognito.seller_client_id
}

output "db_endpoint" {
  description = "RDS PostgreSQL instance endpoint (host:port)"
  value       = module.rds.db_endpoint
}

output "db_name" {
  description = "RDS PostgreSQL database name"
  value       = module.rds.db_name
}

# db_username and db_password are intentionally NOT exposed as outputs
# (sensitive=true variables must never appear in outputs)
