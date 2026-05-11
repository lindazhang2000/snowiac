$ErrorActionPreference = "Stop"
$repo = "lindazhang2000/snowiac"
$webhookUrl = "https://snowiac-app.wittyflower-d82ff27c.eastus.azurecontainerapps.io/webhooks/github"
$hmac = "KdmjD5gxZhSCPaKcEolTgfHUKqkZ8W6xHf8DIlbSe2IDhdGi"

gh secret set AZURE_CLIENT_ID       -R $repo -b "dd7455ca-6e7e-42de-bb06-dcf6ed96750c"
gh secret set AZURE_TENANT_ID       -R $repo -b "ed8832e2-fbd1-443f-8640-12fb0cb6c69d"
gh secret set AZURE_SUBSCRIPTION_ID -R $repo -b "69f14792-2272-4f1d-96ff-44da16ea5f8a"
gh secret set SNOWIAC_WEBHOOK_URL   -R $repo -b $webhookUrl
gh secret set SNOWIAC_WEBHOOK_SECRET -R $repo -b $hmac

gh variable set TFSTATE_RESOURCE_GROUP  -R $repo -b "snowiac-app-rg"
gh variable set TFSTATE_STORAGE_ACCOUNT -R $repo -b "snowiacstateehlgt"
gh variable set TFSTATE_CONTAINER       -R $repo -b "tfstate"

Write-Host "===== secrets ====="
gh secret list -R $repo
Write-Host "===== variables ====="
gh variable list -R $repo
