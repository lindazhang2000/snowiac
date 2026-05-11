output "container_app_fqdn" {
  description = "Public HTTPS endpoint for the SnowIaC server"
  value       = "https://${azurerm_container_app.app.ingress[0].fqdn}"
}

output "container_app_webhook_url" {
  description = "Use as SNOWIAC_WEBHOOK_URL in the IaC repo's GH Actions secrets"
  value       = "https://${azurerm_container_app.app.ingress[0].fqdn}/webhooks/github"
}

output "acr_login_server" {
  value = azurerm_container_registry.acr.login_server
}

output "acr_name" {
  value = azurerm_container_registry.acr.name
}

output "key_vault_name" {
  value = azurerm_key_vault.kv.name
}

output "uami_client_id" {
  description = "Client id of the app's user-assigned managed identity (used as AZURE_CLIENT_ID)"
  value       = azurerm_user_assigned_identity.app.client_id
}

output "webhook_hmac_secret" {
  description = "HMAC secret to set as SNOWIAC_WEBHOOK_SECRET in the IaC repo"
  value       = random_password.hmac.result
  sensitive   = true
}
