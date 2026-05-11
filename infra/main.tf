terraform {
  required_version = ">= 1.5.0"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
    azuread = {
      source  = "hashicorp/azuread"
      version = "~> 3.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "azurerm" {
  features {
    key_vault {
      purge_soft_delete_on_destroy    = true
      recover_soft_deleted_key_vaults = true
    }
  }
}

provider "azuread" {}

data "azurerm_client_config" "current" {}

# ─── Resource group ───────────────────────────────────────────────────────────
resource "azurerm_resource_group" "app" {
  name     = var.resource_group_name
  location = var.location
}

# Random suffix for globally-unique names
resource "random_string" "suffix" {
  length  = 5
  upper   = false
  special = false
  numeric = true
}

locals {
  prefix    = var.name_prefix
  suffix    = random_string.suffix.result
  acr_name  = replace("${local.prefix}acr${local.suffix}", "-", "")
  kv_name   = "${local.prefix}-kv-${local.suffix}"
  uami_name = "${local.prefix}-uami"
  app_name  = "${local.prefix}-app"
  env_name  = "${local.prefix}-env"
  law_name  = "${local.prefix}-law"
}
