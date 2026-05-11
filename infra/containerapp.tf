# ─── Container Apps environment ──────────────────────────────────────────────
resource "azurerm_container_app_environment" "env" {
  name                       = local.env_name
  resource_group_name        = azurerm_resource_group.app.name
  location                   = azurerm_resource_group.app.location
  log_analytics_workspace_id = azurerm_log_analytics_workspace.law.id
}

# ─── Container App ───────────────────────────────────────────────────────────
locals {
  # Bootstrap with an unprivileged nginx that listens on 8080 (matches target_port)
  # so the first `terraform apply` succeeds before any image has been pushed.
  # The deploy workflow will replace this with the real ACR image.
  bootstrap_image = "nginxinc/nginx-unprivileged:1.27-alpine"
  app_image       = var.image_tag == "bootstrap" ? local.bootstrap_image : "${azurerm_container_registry.acr.login_server}/snowiac:${var.image_tag}"
}

resource "azurerm_container_app" "app" {
  name                         = local.app_name
  container_app_environment_id = azurerm_container_app_environment.env.id
  resource_group_name          = azurerm_resource_group.app.name
  revision_mode                = "Single"

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.app.id]
  }

  registry {
    server   = azurerm_container_registry.acr.login_server
    identity = azurerm_user_assigned_identity.app.id
  }

  # Secrets sourced from Key Vault via the UAMI
  secret {
    name                = "webhook-hmac-secret"
    key_vault_secret_id = azurerm_key_vault_secret.webhook_hmac.id
    identity            = azurerm_user_assigned_identity.app.id
  }
  secret {
    name                = "snow-password"
    key_vault_secret_id = azurerm_key_vault_secret.snow_password.id
    identity            = azurerm_user_assigned_identity.app.id
  }
  secret {
    name                = "github-token"
    key_vault_secret_id = azurerm_key_vault_secret.github_token.id
    identity            = azurerm_user_assigned_identity.app.id
  }
  secret {
    name                = "database-url"
    key_vault_secret_id = azurerm_key_vault_secret.database_url.id
    identity            = azurerm_user_assigned_identity.app.id
  }

  ingress {
    external_enabled = true
    target_port      = 8080
    transport        = "auto"
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas = 1
    max_replicas = 1

    container {
      name   = "snowiac"
      image  = local.app_image
      cpu    = 0.5
      memory = "1Gi"

      # Static config
      env {
        name  = "AZURE_CLIENT_ID"
        value = azurerm_user_assigned_identity.app.client_id
      }
      env {
        name  = "AZURE_SUBSCRIPTION_ID"
        value = var.subscription_id
      }
      env {
        name  = "SNOWIAC_USE_MOCKS"
        value = "false"
      }
      env {
        name  = "FOUNDRY_MODEL_DEPLOYMENT_NAME"
        value = var.foundry_model_deployment_name
      }
      env {
        name  = "SNOWIAC_DB_PATH"
        value = "/tmp/snowiac.db"
      }

      # Secret references
      env {
        name        = "WEBHOOK_HMAC_SECRET"
        secret_name = "webhook-hmac-secret"
      }
      env {
        name        = "SNOW_PASSWORD"
        secret_name = "snow-password"
      }
      env {
        name        = "GITHUB_TOKEN"
        secret_name = "github-token"
      }
      env {
        name        = "DATABASE_URL"
        secret_name = "database-url"
      }

      # Operator-overridable env vars (filled in via tfvars or Portal)
      env {
        name  = "FOUNDRY_PROJECT_ENDPOINT"
        value = var.foundry_project_endpoint
      }
      env {
        name  = "SNOW_INSTANCE_URL"
        value = var.snow_instance_url
      }
      env {
        name  = "SNOW_USER"
        value = var.snow_user
      }
      env {
        name  = "GITHUB_REPO"
        value = var.github_iac_repo
      }
    }
  }

  # `image_tag` is driven by deploys (az containerapp update), not Terraform.
  # Ignore drift so re-running `terraform apply` doesn't roll back to bootstrap.
  lifecycle {
    ignore_changes = [
      template[0].container[0].image,
    ]
  }

  depends_on = [
    azurerm_role_assignment.uami_acr_pull,
    azurerm_role_assignment.uami_kv_reader,
  ]
}
