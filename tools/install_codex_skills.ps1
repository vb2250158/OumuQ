param(
  [string]$CodexHome = "",
  [switch]$Force
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$sourceRoot = Join-Path $repoRoot "skills"

if (-not $CodexHome) {
  if ($env:CODEX_HOME) {
    $CodexHome = $env:CODEX_HOME
  } else {
    $CodexHome = Join-Path $HOME ".codex"
  }
}

$targetRoot = Join-Path $CodexHome "skills"
New-Item -ItemType Directory -Force -Path $targetRoot | Out-Null

$installed = @()
$skipped = @()

Get-ChildItem -Path $sourceRoot -Directory | ForEach-Object {
  $skillFile = Join-Path $_.FullName "SKILL.md"
  if (-not (Test-Path $skillFile)) {
    return
  }

  $target = Join-Path $targetRoot $_.Name
  if ((Test-Path $target) -and -not $Force) {
    $skipped += $_.Name
    return
  }

  Copy-Item -Path $_.FullName -Destination $targetRoot -Recurse -Force
  $installed += $_.Name
}

Write-Host "Codex skills directory: $targetRoot"

if ($installed.Count -gt 0) {
  Write-Host "Installed or updated:"
  $installed | ForEach-Object { Write-Host "  - $_" }
}

if ($skipped.Count -gt 0) {
  Write-Host "Skipped existing skills. Re-run with -Force to update:"
  $skipped | ForEach-Object { Write-Host "  - $_" }
}

Write-Host ""
Write-Host "Restart Codex or open a new Codex session so the skills are reloaded."
