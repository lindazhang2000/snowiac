# ─── Key Vault (RBAC mode) ───────────────────────────────────────────────────
resource "azurerm_key_vault" "kv" {
  name                       = local.kv_name
  resource_group_name        = azurerm_resource_group.app.name
  location                   = azurerm_resource_group.app.location
  tenant_id                  = var.tenant_id
  sku_name                   = "standard"
  rbac_authorization_enabled    = true
  soft_delete_retention_days    = 7
  purge_protection_enabled      = false
  public_network_access_enabled = true

  network_acls {
    default_action = "Allow"
    bypass         = "AzureServices"
  }
}

# Operator (whoever runs `terraform apply`) needs to write secrets
resource "azurerm_role_assignment" "tf_kv_admin" {
  scope                = azurerm_key_vault.kv.id
  role_definition_name = "Key Vault Administrator"
  principal_id         = data.azurerm_client_config.current.object_id
}

# Container App UAMI needs to read secrets at runtime
resource "azurerm_role_assignment" "uami_kv_reader" {
  scope                = azurerm_key_vault.kv.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.app.principal_id
}

# Auto-managed: HMAC secret for the GitHub Actions webhook
resource "random_password" "hmac" {
  length  = 48
  special = false
}

resource "azurerm_key_vault_secret" "webhook_hmac" {
  name         = "webhook-hmac-secret"
  value        = random_password.hmac.result
  key_vault_id = azurerm_key_vault.kv.id
  depends_on   = [azurerm_role_assignment.tf_kv_admin]
}

# ─── Placeholders for secrets the operator must seed ────────────────────────
# These are created empty/placeholder so the Container App can reference them;
# run `infra/seed-secrets.ps1` to populate from your local .env, or set in the
# Azure Portal.
resource "azurerm_key_vault_secret" "snow_password" {
  name         = "snow-password"
  value        = "REPLACE_ME"
  key_vault_id = azurerm_key_vault.kv.id
  depends_on   = [azurerm_role_assignment.tf_kv_admin]
  lifecycle { ignore_changes = [value] }
}

resource "azurerm_key_vault_secret" "github_token" {
  name         = "github-token"
  value        = "REPLACE_ME"
  key_vault_id = azurerm_key_vault.kv.id
  depends_on   = [azurerm_role_assignment.tf_kv_admin]
  lifecycle { ignore_changes = [value] }
}

# PostgreSQL connection string for the ticket store. Seeded out-of-band
# (see seed-secrets.ps1 / `az keyvault secret set --name database-url`).
resource "azurerm_key_vault_secret" "database_url" {
  name         = "database-url"
  value        = "REPLACE_ME"
  key_vault_id = azurerm_key_vault.kv.id
  depends_on   = [azurerm_role_assignment.tf_kv_admin]
  lifecycle { ignore_changes = [value] }
}
