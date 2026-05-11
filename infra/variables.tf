variable "subscription_id" {
  description = "Azure subscription id (also set ARM_SUBSCRIPTION_ID env var)"
  type        = string
}

variable "tenant_id" {
  description = "Azure tenant id"
  type        = string
}

variable "location" {
  description = "Azure region"
  type        = string
  default     = "eastus"
}

variable "resource_group_name" {
  description = "Resource group for the SnowIaC app infra"
  type        = string
  default     = "snowiac-app-rg"
}

variable "name_prefix" {
  description = "Prefix for all resource names"
  type        = string
  default     = "snowiac"
}

variable "github_repo" {
  description = "GitHub repo for the deploy workflow federated credential, e.g. owner/repo"
  type        = string
}

variable "image_tag" {
  description = "Container image tag to deploy"
  type        = string
  default     = "bootstrap"
}

variable "verifier_target_resource_group" {
  description = "RG that the VerificationAgent reads (Reader role granted)"
  type        = string
  default     = "MultiAgentSnow"
}
