<#
.SYNOPSIS
  Pull a RITM from ServiceNow, reshape it into the SnowIaC ticket payload,
  and POST it to the deployed app's /tickets/intake endpoint.

.EXAMPLE
  ./tools/ingest_from_snow.ps1 -Ritm RITM0010001
  ./tools/ingest_from_snow.ps1 -Ritm RITM0010001 -AppUrl https://snowiac-app.wittyflower-d82ff27c.eastus.azurecontainerapps.io
#>
param(
  [Parameter(Mandatory=$true)][string]$Ritm,
  [string]$AppUrl = "https://snowiac-app.wittyflower-d82ff27c.eastus.azurecontainerapps.io",
  [string]$EnvFile = ".env",
  [string]$Catalog = ""   # Override Catalog name (e.g. 'Azure Cloud Infrastructure Change')
)

$ErrorActionPreference = "Stop"

# ── Load Snow creds from .env ────────────────────────────────────────────────
if (-not (Test-Path $EnvFile)) { throw "$EnvFile not found" }
$envMap = @{}
Get-Content $EnvFile | ForEach-Object {
  if ($_ -match '^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*)$') { $envMap[$Matches[1]] = $Matches[2] }
}
$snowUrl  = $envMap.SNOW_INSTANCE_URL.TrimEnd('/')
$snowUser = $envMap.SNOW_USER
$snowPwd  = $envMap.SNOW_PASSWORD
if (-not $snowUrl -or -not $snowUser -or -not $snowPwd) { throw "SNOW_* missing in $EnvFile" }
$pair  = "${snowUser}:${snowPwd}"
$basic = "Basic " + [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($pair))
$hdr   = @{ Authorization = $basic; Accept = "application/json" }

function Get-Snow($path) {
  $u = "$snowUrl/api/now/$path"
  Invoke-RestMethod -Uri $u -Headers $hdr -Method GET
}

# ── Fetch the RITM with display values so refs resolve to names ──────────────
Write-Host "Fetching $Ritm from $snowUrl ..."
# sysparm_display_value=all → each ref field has both .value (sys_id) and .display_value (label)
$ritmResp = Get-Snow ("table/sc_req_item?sysparm_display_value=all&sysparm_query=number=" + $Ritm + "&sysparm_limit=1")
if (-not $ritmResp.result -or $ritmResp.result.Count -eq 0) { throw "RITM '$Ritm' not found" }
$rRaw = $ritmResp.result[0]
function _dv($v) {
  if ($null -eq $v) { return "" }
  if ($v -is [string]) { return $v }
  $dv = $null; $vv = $null
  try { $dv = $v.display_value } catch {}
  try { $vv = $v.value } catch {}
  if ($dv) { return [string]$dv }
  if ($vv) { return [string]$vv }
  return ""
}
$r = [pscustomobject]@{
  request          = _dv $rRaw.request
  number           = _dv $rRaw.number
  requested_for    = _dv $rRaw.requested_for
  state            = _dv $rRaw.state
  stage            = _dv $rRaw.stage
  cat_item         = _dv $rRaw.cat_item
  short_description= _dv $rRaw.short_description
  sys_created_on   = _dv $rRaw.sys_created_on
  sys_created_by   = _dv $rRaw.sys_created_by
  closed_at        = _dv $rRaw.closed_at
}
$ritmSysId = (Get-Snow ("table/sc_req_item?sysparm_query=number=" + $Ritm + "&sysparm_fields=sys_id&sysparm_limit=1")).result[0].sys_id

# ── Fetch catalog item variables for this RITM ───────────────────────────────
$payload = @()
try {
  $vars = Get-Snow ("table/sc_item_option_mtom?sysparm_display_value=true&sysparm_exclude_reference_link=true&sysparm_query=request_item=" + $ritmSysId + "&sysparm_fields=sc_item_option")
  foreach ($row in $vars.result) {
    $optName = $row.sc_item_option
    if (-not $optName) { continue }
    # sc_item_option is a reference; with display_value=true it returns a label like "question_text: value"
    # Pull the actual option row for clarity
    $optResp = Get-Snow ("table/sc_item_option?sysparm_display_value=true&sysparm_exclude_reference_link=true&sysparm_query=sys_id=" + $row.sc_item_option_sys_id + "&sysparm_limit=1")
  }
} catch {
  Write-Warning "Could not fetch catalog variables: $($_.Exception.Message)"
}

# Simpler & more reliable: get options via the dedicated endpoint
try {
  $opt2 = Get-Snow ("table/sc_item_option_mtom?sysparm_display_value=all&sysparm_query=request_item=" + $ritmSysId)
  foreach ($row in $opt2.result) {
    $optRef = $row.sc_item_option
    if ($optRef -is [string]) { $optSysId = $optRef } else { $optSysId = $optRef.value }
    if (-not $optSysId) { continue }
    $opt = (Get-Snow ("table/sc_item_option?sysparm_display_value=all&sysparm_query=sys_id=" + $optSysId + "&sysparm_limit=1")).result[0]
    $qRef = $opt.item_option_new
    if ($qRef -is [string]) { $qSysId = $qRef } else { $qSysId = $qRef.value }
    $qLabel = ""
    if ($qSysId) {
      $q = (Get-Snow ("table/item_option_new?sysparm_display_value=all&sysparm_query=sys_id=" + $qSysId + "&sysparm_limit=1")).result[0]
      if ($q.question_text) { $qLabel = $q.question_text.display_value } elseif ($q.text) { $qLabel = $q.text.display_value }
    }
    $val = if ($opt.value) { $opt.value.display_value } else { "" }
    if ($qLabel) {
      $payload += [pscustomobject]@{ RequestFieldName = $qLabel; PayloadTokenValue = "$val" }
    }
  }
} catch {
  Write-Warning "Variable lookup failed: $($_.Exception.Message)"
}

# Always include short_description as a fallback payload entry
if (-not ($payload | Where-Object { $_.RequestFieldName -match 'description' })) {
  $payload += [pscustomobject]@{
    RequestFieldName  = "Enter a detailed description of the request"
    PayloadTokenValue = "$($r.short_description)"
  }
}

# ── Build SnowIaC ticket envelope ────────────────────────────────────────────
$ticket = [ordered]@{
  Request          = "$($r.request)"
  RITM             = "$($r.number)"
  RequestedFor     = "$($r.requested_for)"
  EmailAddress     = ""
  UserID           = ""
  Manager          = ""
  Location         = ""
  Department       = ""
  State            = "$($r.state)"
  Stage            = "$($r.stage)"
  Catalog          = $(if ($Catalog) { $Catalog } else { "$($r.cat_item)" })
  ShortDescription = "$($r.short_description)"
  CreatedDate      = "$($r.sys_created_on)"
  CreatedBy        = "$($r.sys_created_by)"
  ClosedDate       = "$($r.closed_at)"
  ManagerID        = ""
  Payload          = @($payload)
}
$envelope = @{ result = @($ticket) }
$json = $envelope | ConvertTo-Json -Depth 10
Write-Host "── Sending payload ──"
Write-Host $json
Write-Host ""

# ── POST to /tickets/intake ──────────────────────────────────────────────────
Write-Host "POST $AppUrl/tickets/intake ..."
$resp = Invoke-RestMethod -Uri "$AppUrl/tickets/intake" -Method POST `
  -ContentType "application/json" -Body $json -TimeoutSec 180
Write-Host "── Response ──"
$resp | ConvertTo-Json -Depth 8
