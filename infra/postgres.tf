# ─── Postgres Flexible Server (ticket store) ──────────────────────────────────
# This server is imported from a pre-existing resource. The admin password is
# managed out-of-band (Key Vault `snow-password` / `database-url`); we keep
# `lifecycle.ignore_changes` so Terraform does not try to rotate it.
#
# Import (one-time):
#   terraform import azurerm_postgresql_flexible_server.tickets \
#     /subscriptions/<SUB>/resourceGroups/snowiac-app-rg/providers/Microsoft.DBforPostgreSQL/flexibleServers/snowiac-pg2-ehlgt
#   terraform import azurerm_postgresql_flexible_server_database.snowiac \
#     /subscriptions/<SUB>/resourceGroups/snowiac-app-rg/providers/Microsoft.DBforPostgreSQL/flexibleServers/snowiac-pg2-ehlgt/databases/snowiac
#   terraform import azurerm_postgresql_flexible_server_firewall_rule.allow_azure \
#     /subscriptions/<SUB>/resourceGroups/snowiac-app-rg/providers/Microsoft.DBforPostgreSQL/flexibleServers/snowiac-pg2-ehlgt/firewallRules/allow-azure

resource "azurerm_postgresql_flexible_server" "tickets" {
  name                          = "snowiac-pg2-${local.suffix}"
  resource_group_name           = azurerm_resource_group.app.name
  location                      = "centralus"
  version                       = "16"
  sku_name                      = "B_Standard_B1ms"
  storage_mb                    = 32768
  administrator_login           = var.postgres_admin_login
  administrator_password        = var.postgres_admin_password
  backup_retention_days         = 7
  public_network_access_enabled = true
  zone                          = "1"

  lifecycle {
    ignore_changes = [
      administrator_password,
      zone,
      high_availability,
    ]
  }
}

resource "azurerm_postgresql_flexible_server_database" "snowiac" {
  name      = "snowiac"
  server_id = azurerm_postgresql_flexible_server.tickets.id
  collation = "en_US.utf8"
  charset   = "UTF8"

  lifecycle {
    prevent_destroy = true
  }
}

# Allows all Azure-internal services (Container App egress) to reach the server.
resource "azurerm_postgresql_flexible_server_firewall_rule" "allow_azure" {
  name             = "allow-azure"
  server_id        = azurerm_postgresql_flexible_server.tickets.id
  start_ip_address = "0.0.0.0"
  end_ip_address   = "0.0.0.0"
}
