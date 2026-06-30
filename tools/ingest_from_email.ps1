<#
.SYNOPSIS
  Turn an inbound email into a SnowIaC ticket payload and POST it to /tickets/intake.

  This is the email-channel equivalent of ingest_from_snow.ps1. The app core
  (agents, workflow, Terraform, GitHub PR/deploy) is unchanged — only the SOURCE
  adapter differs. The LLM parameter extractor reads the email body out of the
  "Enter a detailed description of the request" payload field, so no rigid parsing
  of the message is required here.

.EXAMPLE
  ./tools/ingest_from_email.ps1 -EmlPath .\request.eml

.EXAMPLE
  ./tools/ingest_from_email.ps1 `
    -From "Amy Smith <amy.smith@contoso.com>" `
    -Subject "Bump sql1-data to 350 MB/s" `
    -Body "Please increase the sql1-data managed disk to 5000 IOPS / 350 MB/s in resource group MultiAgentSnow."
#>
param(
  [string]$EmlPath = "",
  [string]$From = "",
  [string]$Subject = "",
  [string]$Body = "",
  [string]$Ritm = "",
  [string]$AppUrl = "https://snowiac-app.wittyflower-d82ff27c.eastus.azurecontainerapps.io",
  [string]$Catalog = "Azure Cloud Infrastructure Change"
)

$ErrorActionPreference = "Stop"

# ── Parse a raw .eml file into From / Subject / Body ─────────────────────────
function Parse-Eml([string]$path) {
  if (-not (Test-Path $path)) { throw "EML file not found: $path" }
  $raw = Get-Content -Path $path -Raw

  # Headers end at the first blank line; the rest is the body.
  $headerText = $raw
  $bodyText = ""
  $m = [regex]::Match($raw, "(?s)^(.*?)(\r?\n\r?\n)(.*)$")
  if ($m.Success) {
    $headerText = $m.Groups[1].Value
    $bodyText   = $m.Groups[3].Value
  }

  # Unfold RFC 5322 folded headers (continuation lines start with whitespace).
  $headerText = $headerText -replace "\r?\n[ \t]+", " "
  $from = ([regex]::Match($headerText, "(?im)^From:\s*(.+)$")).Groups[1].Value.Trim()
  $subj = ([regex]::Match($headerText, "(?im)^Subject:\s*(.+)$")).Groups[1].Value.Trim()

  return [pscustomobject]@{ From = $from; Subject = $subj; Body = $bodyText.Trim() }
}

if ($EmlPath) {
  $parsed = Parse-Eml $EmlPath
  if (-not $From)    { $From = $parsed.From }
  if (-not $Subject) { $Subject = $parsed.Subject }
  if (-not $Body)    { $Body = $parsed.Body }
}

if (-not $From -and -not $Subject -and -not $Body) {
  throw "Provide -EmlPath, or at least -Subject/-Body (and ideally -From)."
}

# ── Split "Display Name <addr@host>" into name + address ─────────────────────
$fromName = $From
$fromAddr = ""
$mAddr = [regex]::Match($From, "<([^>]+)>")
if ($mAddr.Success) {
  $fromAddr = $mAddr.Groups[1].Value.Trim()
  $fromName = ($From -replace "<[^>]+>", "").Trim().Trim('"')
} elseif ($From -match "^\S+@\S+$") {
  $fromAddr = $From.Trim()
  $fromName = $From.Trim()
}

if (-not $Ritm) { $Ritm = "EML-" + (Get-Date -Format "yyyyMMddHHmmss") }

# The extractor reads this exact field name, or falls back to ShortDescription.
$description = if ($Body) { $Body } else { $Subject }

# ── Build the SnowIaC ticket envelope (same shape /tickets/intake expects) ───
$ticket = [ordered]@{
  Request          = $Ritm
  RITM             = $Ritm
  RequestedFor     = $(if ($fromName) { $fromName } else { $fromAddr })
  EmailAddress     = $fromAddr
  UserID           = ""
  Manager          = ""
  Location         = ""
  Department       = ""
  State            = "New"
  Stage            = "Request"
  Catalog          = $Catalog
  ShortDescription = $Subject
  CreatedDate      = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
  CreatedBy        = $fromAddr
  ClosedDate       = ""
  ManagerID        = ""
  Payload          = @(
    [pscustomobject]@{
      RequestFieldName  = "Enter a detailed description of the request"
      PayloadTokenValue = "$description"
    }
  )
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
