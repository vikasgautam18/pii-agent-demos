# BankingBuddy — Outputs
#
# Exposes key resource attributes for use in deployment scripts
# and downstream automation.

# ── Resource Group ───────────────────────────────────────────────────────────

output "resource_group_name" {
  description = "Resource group name"
  value       = azurerm_resource_group.this.name
}

# ── ACR ──────────────────────────────────────────────────────────────────────

output "acr_login_server" {
  description = "ACR login server URL"
  value       = azurerm_container_registry.this.login_server
}

output "acr_name" {
  description = "ACR resource name"
  value       = azurerm_container_registry.this.name
}

# ── Container Apps Environment ───────────────────────────────────────────────

output "aca_env_name" {
  description = "Container Apps Environment name"
  value       = azurerm_container_app_environment.this.name
}

output "aca_env_id" {
  description = "Container Apps Environment resource ID"
  value       = azurerm_container_app_environment.this.id
}

# ── Azure OpenAI ─────────────────────────────────────────────────────────────

output "openai_endpoint" {
  description = "Azure OpenAI account endpoint URL"
  value       = azurerm_cognitive_account.openai.endpoint
}

output "openai_deployment_name" {
  description = "Name of the deployed OpenAI model"
  value       = azurerm_cognitive_deployment.gpt.name
}

# ── Application Insights ────────────────────────────────────────────────────

output "app_insights_connection_string" {
  description = "Application Insights connection string"
  value       = azurerm_application_insights.this.connection_string
  sensitive   = true
}

output "app_insights_name" {
  description = "Application Insights resource name"
  value       = azurerm_application_insights.this.name
}
