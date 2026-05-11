# ─── User-assigned managed identity for the app ──────────────────────────────
resource "azurerm_user_assigned_identity" "app" {
  name                = local.uami_name
  resource_group_name = azurerm_resource_group.app.name
  location            = azurerm_resource_group.app.location
}

# Reader on the verifier target RG (for VerificationAgent's azure-mgmt-compute calls)
resource "azurerm_role_assignment" "uami_target_reader" {
  scope                = "/subscriptions/${var.subscription_id}/resourceGroups/${var.verifier_target_resource_group}"
  role_definition_name = "Reader"
  principal_id         = azurerm_user_assigned_identity.app.principal_id
}

# Azure AI User on the Foundry account so the UAMI can call the agents/responses APIs.
# Scoped to the Foundry account (which may live in a different RG than the app).
resource "azurerm_role_assignment" "uami_foundry_ai_user" {
  scope                = var.foundry_account_id
  role_definition_name = "Azure AI User"
  principal_id         = azurerm_user_assigned_identity.app.principal_id
}

# Note: GitHub OIDC deploy SP intentionally omitted.
# Images are built/pushed manually with `az acr build` and revisions updated
# with `az containerapp update`. See README "Deploy to Azure" section.
