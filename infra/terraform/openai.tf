# BankingBuddy — Azure OpenAI Service
#
# Provisions an Azure Cognitive Services account (kind = OpenAI) and deploys
# a GPT model for the BankingBuddy agent to use.
#
# NOTE: This provisions the Azure OpenAI *resource* (model hosting).
# The AI Foundry *project* endpoint (https://xxx.services.ai.azure.com/api/projects/...)
# is created in the Azure AI Foundry portal and must be set manually in .env
# as FOUNDRY_PROJECT_ENDPOINT. Terraform does not yet fully manage Foundry projects.

resource "azurerm_cognitive_account" "openai" {
  name                  = local.openai_account_name
  resource_group_name   = azurerm_resource_group.this.name
  location              = azurerm_resource_group.this.location
  kind                  = "OpenAI"
  sku_name              = var.openai_sku
  custom_subdomain_name = local.openai_account_name

  tags = var.tags
}

resource "azurerm_cognitive_deployment" "gpt" {
  name                 = var.openai_model_name
  cognitive_account_id = azurerm_cognitive_account.openai.id

  model {
    format  = "OpenAI"
    name    = var.openai_model_name
    version = var.openai_model_version
  }

  sku {
    name     = "Standard"
    capacity = var.openai_deployment_capacity
  }
}
