# Remote backend — state is shared between the local SnowIaC server and the
# GitHub Actions runner that executes `terraform apply` after PR merge.
#
# Container + key are passed via `-backend-config` in CI:
#   terraform init \
#     -backend-config="resource_group_name=<rg>" \
#     -backend-config="storage_account_name=<sa>" \
#     -backend-config="container_name=tfstate" \
#     -backend-config="key=RITM0010005.tfstate"
terraform {
  backend "azurerm" {}
}
