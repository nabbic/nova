output "buyer_user_pool_id" {
  description = "ID of the buyer Cognito User Pool"
  value       = aws_cognito_user_pool.buyer.id
}

output "buyer_user_pool_arn" {
  description = "ARN of the buyer Cognito User Pool"
  value       = aws_cognito_user_pool.buyer.arn
}

output "buyer_client_id" {
  description = "Client ID for the buyer User Pool app client"
  value       = aws_cognito_user_pool_client.buyer.id
}

output "seller_user_pool_id" {
  description = "ID of the seller Cognito User Pool"
  value       = aws_cognito_user_pool.seller.id
}

output "seller_user_pool_arn" {
  description = "ARN of the seller Cognito User Pool"
  value       = aws_cognito_user_pool.seller.arn
}

output "seller_client_id" {
  description = "Client ID for the seller User Pool app client"
  value       = aws_cognito_user_pool_client.seller.id
}
