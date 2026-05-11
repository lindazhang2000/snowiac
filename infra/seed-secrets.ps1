# Seeds Key Vault placeholder secrets from your local .env
# Usage: cd infra; .\seed-secrets.ps1

$ErrorActionPreference = "Stop"
$kv = (terraform output -raw key_vault_name)
Write-Host "Seeding secrets into Key Vault: $kv"

function Get-EnvVar([string]$name) {
    $line = Select-String -Path ..\.env -Pattern "^$name=" -ErrorAction SilentlyContinue
    if (-not $line) { throw "Missing $name in ../.env" }
    return $line.Line.Split('=', 2)[1].Trim()
}

$snowPwd = Get-EnvVar "SNOW_PASSWORD"
$ghToken = Get-EnvVar "GITHUB_TOKEN"

az keyvault secret set --vault-name $kv --name snow-password --value $snowPwd  | Out-Null
az keyvault secret set --vault-name $kv --name github-token  --value $ghToken | Out-Null

Write-Host "Done. Restart the Container App revision to pick up new secrets:"
Write-Host "  az containerapp revision restart --name snowiac-app --resource-group snowiac-app-rg --revision (az containerapp revision list -n snowiac-app -g snowiac-app-rg --query '[0].name' -o tsv)"
