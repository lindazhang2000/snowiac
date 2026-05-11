<#
.SYNOPSIS
  Submit a Service Catalog request in ServiceNow via REST (creating a real RITM),
  then ingest it into the SnowIaC dashboard.

.EXAMPLE
  ./tools/submit_and_ingest.ps1 -Item Azure
#>
param(
  [Parameter(Mandatory=$true)][ValidateSet("Azure")][string]$Item,
  [string]$AppUrl = "https://snowiac-app.wittyflower-d82ff27c.eastus.azurecontainerapps.io",
  [string]$EnvFile = ".env"
)

$ErrorActionPreference = "Stop"

# ── Load creds ───────────────────────────────────────────────────────────────
$envMap = @{}
Get-Content $EnvFile | ForEach-Object {
  if ($_ -match '^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*)$') { $envMap[$Matches[1]] = $Matches[2] }
}
$base  = $envMap.SNOW_INSTANCE_URL.TrimEnd('/')
$pair  = "$($envMap.SNOW_USER):$($envMap.SNOW_PASSWORD)"
$basic = "Basic " + [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($pair))
$hdr   = @{ Authorization = $basic; Accept = "application/json"; "Content-Type" = "application/json" }

function SnowGet($path)        { Invoke-RestMethod -Uri "$base/api/now/$path" -Headers $hdr -Method GET }
function SnowPost($path, $body){ Invoke-RestMethod -Uri "$base/api/now/$path" -Headers $hdr -Method POST -Body ($body | ConvertTo-Json -Depth 10) }

# ── Pick catalog item & sample variable values ───────────────────────────────
$itemName = "Azure Cloud Infrastructure Change"
$vars = @{
  business_application = "DBAPortal"
  description          = "Migrating Oracle to SQL Server on Azure VMs. Premium V2 throughput is bottlenecking the workload — please raise IOPS from 3000 to 5000 and throughput from 125 MB/s to 350 MB/s on disk sql1-data."
  comments             = "Please assign to Nancy Jones."
}

# ── Resolve catalog item sys_id ──────────────────────────────────────────────
$ci = (SnowGet ("table/sc_cat_item?sysparm_query=name=" + [uri]::EscapeDataString($itemName) + "&sysparm_limit=1")).result
if (-not $ci -or $ci.Count -eq 0) { throw "Catalog item '$itemName' not found. Run ./tools/seed_snow_catalog.ps1 first." }
$ciSysId = $ci[0].sys_id
Write-Host "Catalog item: $itemName [$ciSysId]"

# ── Submit via Service Catalog REST API ──────────────────────────────────────
$orderUrl = "$base/api/sn_sc/servicecatalog/items/$ciSysId/order_now"
$payload  = @{ sysparm_quantity = "1"; variables = $vars }
Write-Host "Submitting order ..."
$resp = Invoke-RestMethod -Uri $orderUrl -Headers $hdr -Method POST -Body ($payload | ConvertTo-Json -Depth 6)
$reqSysId = $resp.result.sys_id
$reqNumber = $resp.result.request_number
Write-Host "Created REQ: $reqNumber [$reqSysId]"

# ── Find the RITM that was created under this request ───────────────────────
Start-Sleep -Seconds 2
$ritms = (SnowGet ("table/sc_req_item?sysparm_query=request=" + $reqSysId + "&sysparm_fields=number,sys_id&sysparm_limit=1")).result
if (-not $ritms -or $ritms.Count -eq 0) { throw "No RITM found for REQ $reqNumber" }
$ritm = $ritms[0].number
Write-Host "Created RITM: $ritm"
Write-Host ""

# ── Ingest into SnowIaC ──────────────────────────────────────────────────────
& "$PSScriptRoot/ingest_from_snow.ps1" -Ritm $ritm -AppUrl $AppUrl -EnvFile $EnvFile
