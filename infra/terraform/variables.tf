# BankingBuddy — Input variables
#
# All resource names are derived from `project_name` + an optional suffix.
# The suffix is required for globally-unique resources (ACR, OpenAI).
# If `name_suffix` is left empty, a random 5-character suffix is generated
# and persisted in the Terraform state.

# ── Core naming ──────────────────────────────────────────────────────────────

variable "project_name" {
  description = "Short project name used as a prefix for all resources (3-16 lowercase alphanumeric chars)"
  type        = string
  default     = "bankingbuddy"

  validation {
    condition     = can(regex("^[a-z0-9]{3,16}$", var.project_name))
    error_message = "project_name must be 3-16 characters, lowercase letters and digits only."
  }
}

variable "name_suffix" {
  description = "Optional suffix for globally-unique resource names. Leave empty to auto-generate a random 5-char suffix."
  type        = string
  default     = ""

  validation {
    condition     = var.name_suffix == "" || can(regex("^[a-z0-9]{2,8}$", var.name_suffix))
    error_message = "name_suffix must be empty or 2-8 lowercase alphanumeric chars."
  }
}

# ── General ──────────────────────────────────────────────────────────────────

variable "subscription_id" {
  description = "Azure subscription ID"
  type        = string
}

variable "location" {
  description = "Azure region for all resources (eastus recommended for Azure OpenAI availability)"
  type        = string
  default     = "eastus"
}

variable "tags" {
  description = "Tags applied to all resources"
  type        = map(string)
  default = {
    project    = "bankingbuddy"
    managed_by = "terraform"
  }
}

# ── Azure Container Registry ────────────────────────────────────────────────

variable "acr_sku" {
  description = "ACR SKU tier"
  type        = string
  default     = "Basic"
}

# ── Azure OpenAI ─────────────────────────────────────────────────────────────

variable "openai_sku" {
  description = "Azure Cognitive Services (OpenAI) SKU"
  type        = string
  default     = "S0"
}

variable "openai_model_name" {
  description = "OpenAI model to deploy (e.g. gpt-4o, gpt-4)"
  type        = string
  default     = "gpt-5.1"
}

variable "openai_model_version" {
  description = "Model version string for the OpenAI deployment"
  type        = string
  default     = "2025-11-13"
}

variable "openai_deployment_capacity" {
  description = "TPM in thousands — deployment capacity for the OpenAI model"
  type        = number
  default     = 10
}
