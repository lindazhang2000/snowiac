$ErrorActionPreference = "Stop"
$repo = "lindazhang2000/iac-ai-agents"
$webhookUrl = "https://snowiac-app.wittyflower-d82ff27c.eastus.azurecontainerapps.io/webhooks/github"
$hmac = $env:SNOWIAC_WEBHOOK_SECRET  # export before running; do NOT hardcode

gh secret set AZURE_CLIENT_ID       -R $repo -b $env:AZURE_CLIENT_ID
gh secret set AZURE_TENANT_ID       -R $repo -b $env:AZURE_TENANT_ID
gh secret set AZURE_SUBSCRIPTION_ID -R $repo -b $env:AZURE_SUBSCRIPTION_ID
gh secret set SNOWIAC_WEBHOOK_URL   -R $repo -b $webhookUrl
gh secret set SNOWIAC_WEBHOOK_SECRET -R $repo -b $hmac

gh variable set TFSTATE_RESOURCE_GROUP  -R $repo -b "snowiac-app-rg"
gh variable set TFSTATE_STORAGE_ACCOUNT -R $repo -b "snowiacstateehlgt"
gh variable set TFSTATE_CONTAINER       -R $repo -b "tfstate"

Write-Host "===== secrets ====="
gh secret list -R $repo
Write-Host "===== variables ====="
gh variable list -R $repo
