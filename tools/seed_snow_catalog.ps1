<#
.SYNOPSIS
  Create two SnowIaC catalog items in ServiceNow with their required variables.

.DESCRIPTION
  Creates (idempotently) the catalog item 'Azure Cloud Infrastructure Change'
  under the default Service Catalog, then attaches the variables expected by
  the SnowIaC intake agent.

.EXAMPLE
  ./tools/seed_snow_catalog.ps1
#>
param(
  [string]$EnvFile = ".env",
  [string]$Category  # optional sys_id of category; if omitted, uses first found
)

$ErrorActionPreference = "Stop"

# ── Load creds ───────────────────────────────────────────────────────────────
if (-not (Test-Path $EnvFile)) { throw "$EnvFile not found" }
$envMap = @{}
Get-Content $EnvFile | ForEach-Object {
  if ($_ -match '^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*)$') { $envMap[$Matches[1]] = $Matches[2] }
}
$base = $envMap.SNOW_INSTANCE_URL.TrimEnd('/')
$pair  = "$($envMap.SNOW_USER):$($envMap.SNOW_PASSWORD)"
$basic = "Basic " + [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($pair))
$hdr   = @{ Authorization = $basic; Accept = "application/json"; "Content-Type" = "application/json" }

function SnowGet($path) {
  Invoke-RestMethod -Uri "$base/api/now/$path" -Headers $hdr -Method GET
}
function SnowPost($path, $body) {
  Invoke-RestMethod -Uri "$base/api/now/$path" -Headers $hdr -Method POST -Body ($body | ConvertTo-Json -Depth 10)
}

# ── Resolve Service Catalog sys_id ───────────────────────────────────────────
$catalog = (SnowGet "table/sc_catalog?sysparm_query=title=Service Catalog&sysparm_limit=1").result[0]
if (-not $catalog) { $catalog = (SnowGet "table/sc_catalog?sysparm_limit=1").result[0] }
if (-not $catalog) { throw "No Service Catalog found" }
$catalogSysId = $catalog.sys_id
Write-Host "Service Catalog: $($catalog.title) [$catalogSysId]"

# ── Resolve a Category ───────────────────────────────────────────────────────
if (-not $Category) {
  $cat = (SnowGet "table/sc_category?sysparm_query=sc_catalog=$catalogSysId&sysparm_limit=1").result[0]
  if (-not $cat) { $cat = (SnowGet "table/sc_category?sysparm_limit=1").result[0] }
  $Category = $cat.sys_id
  Write-Host "Category: $($cat.title) [$Category]"
} else {
  Write-Host "Category override: $Category"
}

# ── Helpers ──────────────────────────────────────────────────────────────────
function Get-OrCreateCatItem([string]$Name) {
  $existing = (SnowGet ("table/sc_cat_item?sysparm_query=name=" + [uri]::EscapeDataString($Name) + "&sysparm_limit=1")).result
  if ($existing -and $existing.Count -gt 0) {
    Write-Host "  ✓ Catalog item '$Name' already exists [$($existing[0].sys_id)]"
    return $existing[0].sys_id
  }
  $body = @{
    name         = $Name
    short_description = $Name
    sc_catalogs  = $catalogSysId
    category     = $Category
    active       = "true"
  }
  $res = (SnowPost "table/sc_cat_item" $body).result
  Write-Host "  + Created catalog item '$Name' [$($res.sys_id)]"
  return $res.sys_id
}

# Variable types: 6=Single Line Text, 2=Multi Line Text
function Add-Variable([string]$CatItemSysId, [string]$Name, [string]$Label, [int]$Type, [int]$Order) {
  $existing = (SnowGet ("table/item_option_new?sysparm_query=cat_item=" + $CatItemSysId + "^name=" + [uri]::EscapeDataString($Name) + "&sysparm_limit=1")).result
  if ($existing -and $existing.Count -gt 0) {
    Write-Host "    ✓ Variable '$Label' already exists"
    return
  }
  $body = @{
    cat_item      = $CatItemSysId
    name          = $Name
    question_text = $Label
    type          = "$Type"
    order         = "$Order"
    active        = "true"
    mandatory     = "true"
  }
  SnowPost "table/item_option_new" $body | Out-Null
  Write-Host "    + Variable '$Label' added"
}

# ── Item 1: Azure Cloud Infrastructure Change ────────────────────────────────
Write-Host ""
Write-Host "=== Azure Cloud Infrastructure Change ==="
$azureSys = Get-OrCreateCatItem "Azure Cloud Infrastructure Change"
Add-Variable $azureSys "business_application" "Business Application" 6 100
Add-Variable $azureSys "description"          "Enter a detailed description of the request" 2 200
Add-Variable $azureSys "comments"             "Comments" 2 300

Write-Host ""
Write-Host "✅ Done. Submit the item from the Service Catalog UI:"
Write-Host "   $base/sp?id=sc_cat_item&sys_id=$azureSys"
Write-Host ""
Write-Host "Or create a RITM via REST and ingest it with:"
Write-Host "   ./tools/ingest_from_snow.ps1 -Ritm RITMxxxxxxx"
