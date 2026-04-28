# BankingBuddy — Root Terraform configuration
#
# Provisions shared infrastructure for the BankingBuddy demo:
#   • Resource Group
#   • Random suffix for globally-unique names
#   • Locals block deriving all resource names from `var.project_name`

terraform {
  required_version = ">= 1.5"

  # Configure the Azure Storage backend at `terraform init` time:
  #   terraform init \
  #     -backend-config="resource_group_name=<rg>" \
  #     -backend-config="storage_account_name=<sa>" \
  #     -backend-config="container_name=tfstate" \
  #     -backend-config="key=bankingbuddy.terraform.tfstate" \
  #     -backend-config="use_azuread_auth=true"
  backend "azurerm" {}

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "azurerm" {
  features {
    resource_group {
      prevent_deletion_if_contains_resources = false
    }
  }
  subscription_id = var.subscription_id
}

# Random suffix for globally-unique resource names (ACR, OpenAI).
# Persisted in Terraform state; regenerated only if the resource is tainted
# or name_suffix is changed.
resource "random_string" "suffix" {
  length  = 5
  upper   = false
  special = false
  numeric = true
}

locals {
  # Resolved suffix: user-supplied wins, else the auto-generated random string.
  suffix = var.name_suffix != "" ? var.name_suffix : random_string.suffix.result

  # Resource names
  # - Globally-unique resources (DNS namespace) use prefix + suffix.
  # - RG-scoped resources use prefix only (predictable names within your RG).
  resource_group_name = "${var.project_name}-rg"
  acr_name            = substr("${var.project_name}acr${local.suffix}", 0, 50) # alphanumeric only, max 50
  aca_env_name        = "${var.project_name}-env"
  log_analytics_name  = "${var.project_name}-logs"
  app_insights_name   = "${var.project_name}-insights"
  openai_account_name = "${var.project_name}-openai-${local.suffix}"

  # Default container app name
  app_name = var.project_name
}

resource "azurerm_resource_group" "this" {
  name     = local.resource_group_name
  location = var.location

  tags = var.tags
}
