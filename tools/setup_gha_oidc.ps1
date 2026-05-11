param(
  [string]$AppName = "snowiac-gha-tf",
  [string]$Repo = "lindazhang2000/snowiac",
  [string]$Subscription = "69f14792-2272-4f1d-96ff-44da16ea5f8a",
  [string]$ResourceGroup = "snowiac-app-rg",
  [string]$StorageAccount = "snowiacstateehlgt"
)

$ErrorActionPreference = "Stop"

az account set --subscription $Subscription | Out-Null

$existing = az ad app list --display-name $AppName --query "[0].appId" -o tsv
if (-not $existing) {
  Write-Host "Creating app $AppName ..."
  $appId = az ad app create --display-name $AppName --query appId -o tsv
  az ad sp create --id $appId | Out-Null
} else {
  $appId = $existing
  Write-Host "Reusing app $AppName ($appId)"
}

$tenantId = az account show --query tenantId -o tsv
$spId = az ad sp show --id $appId --query id -o tsv

# Federated credential: branch main pushes
$body = @{
  name      = "gha-main"
  issuer    = "https://token.actions.githubusercontent.com"
  subject   = ("repo:" + $Repo + ":ref:refs/heads/main")
  audiences = @("api://AzureADTokenExchange")
} | ConvertTo-Json -Compress

$tmp = New-TemporaryFile
[IO.File]::WriteAllText($tmp.FullName, $body)
az ad app federated-credential create --id $appId --parameters "@$($tmp.FullName)" 2>&1 | Out-Host
Remove-Item $tmp.FullName

# Roles: Contributor on subscription, Storage Blob Data Contributor on tfstate SA
az role assignment create `
  --assignee-object-id $spId --assignee-principal-type ServicePrincipal `
  --role "Contributor" `
  --scope ("/subscriptions/" + $Subscription) 2>&1 | Out-Host

az role assignment create `
  --assignee-object-id $spId --assignee-principal-type ServicePrincipal `
  --role "Storage Blob Data Contributor" `
  --scope ("/subscriptions/" + $Subscription + "/resourceGroups/" + $ResourceGroup + "/providers/Microsoft.Storage/storageAccounts/" + $StorageAccount) 2>&1 | Out-Host

Write-Host ""
Write-Host "==== Add these as GitHub Actions secrets in $Repo ===="
Write-Host "AZURE_CLIENT_ID=$appId"
Write-Host "AZURE_TENANT_ID=$tenantId"
Write-Host "AZURE_SUBSCRIPTION_ID=$Subscription"
Write-Host ""
Write-Host "==== And these as repo variables ===="
Write-Host "TFSTATE_RESOURCE_GROUP=$ResourceGroup"
Write-Host "TFSTATE_STORAGE_ACCOUNT=$StorageAccount"
Write-Host "TFSTATE_CONTAINER=tfstate"
