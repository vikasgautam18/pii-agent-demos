# BankingBuddy — Azure Container Registry
#
# Stores Docker images for the BankingBuddy container app.
# Admin access is disabled; use managed identity or RBAC for pulls.

resource "azurerm_container_registry" "this" {
  name                = local.acr_name
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  sku                 = var.acr_sku
  admin_enabled       = false

  tags = var.tags
}
