# Operator-supplied app config (passed straight to the container)
variable "foundry_project_endpoint" {
  type        = string
  description = "Microsoft Foundry project endpoint URL"
}

variable "foundry_account_id" {
  type        = string
  description = "Full ARM resource id of the Foundry (Cognitive Services) account, used to scope the UAMI role assignment"
}

variable "foundry_model_deployment_name" {
  type        = string
  description = "Name of the deployed model in the Foundry account (e.g. eval-gpt41-mini)"
  default     = "gpt-5.4"
}

variable "snow_instance_url" {
  type        = string
  description = "ServiceNow instance URL, e.g. https://devXXXXX.service-now.com"
}

variable "snow_user" {
  type    = string
  default = "admin"
}

variable "github_iac_repo" {
  type        = string
  description = "GitHub repo where SnowIaC opens PRs, e.g. owner/iac-repo"
}
