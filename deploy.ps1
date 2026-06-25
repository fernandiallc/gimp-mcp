#requires -Version 5.1
<#
.SYNOPSIS
    Install or update the GIMP MCP plugin into the per-user GIMP 3.x plug-ins folder.
.DESCRIPTION
    Copies gimp-mcp-plugin.py from this repo into
    %APPDATA%\GIMP\<ver>\plug-ins\gimp-mcp-plugin\gimp-mcp-plugin.py
    (GIMP requires the .py to sit in a same-named subfolder).
    Prefers GIMP 3.2; falls back to the newest installed 3.x version folder.
.PARAMETER Check
    Compare installed vs repo file by SHA-256 and report status WITHOUT copying.
    Exit codes: 0 in-sync, 10 drift, 20 not-installed.
.EXAMPLE
    .\deploy.ps1            # install / update
.EXAMPLE
    .\deploy.ps1 -Check     # drift check only (safe; never writes)
#>
[CmdletBinding()]
param(
    [switch]$Check
)

$ErrorActionPreference = 'Stop'

$PluginFileName = 'gimp-mcp-plugin.py'
$PluginSubdir   = 'gimp-mcp-plugin'

function Get-RepoPluginPath {
    $src = Join-Path $PSScriptRoot $PluginFileName
    if (-not (Test-Path -LiteralPath $src -PathType Leaf)) {
        throw "Repo plugin not found at '$src'. Run deploy.ps1 from the gimp-mcp repo root."
    }
    return $src
}

function Get-GimpVersionDir {
    if ([string]::IsNullOrWhiteSpace($env:APPDATA)) {
        throw "APPDATA is not set; cannot locate the GIMP config folder."
    }
    $base = Join-Path $env:APPDATA 'GIMP'
    if (-not (Test-Path -LiteralPath $base -PathType Container)) {
        throw "GIMP config folder not found at '$base'. Launch GIMP once, then re-run."
    }

    # Only major.minor dirs (3.0, 3.2, 3.4, ...). Restrict to major 3 so a future
    # GIMP 4.x doesn't get a 3.x plugin silently dropped into it.
    $dirs = Get-ChildItem -LiteralPath $base -Directory |
        Where-Object { $_.Name -match '^3\.\d+$' }
    if (-not $dirs) {
        throw "No GIMP 3.x version folder under '$base'. Launch GIMP 3 once, then re-run."
    }

    $preferred = $dirs | Where-Object { $_.Name -eq '3.2' } | Select-Object -First 1
    if ($preferred) { return $preferred }

    $newest = $dirs | Sort-Object { [version]$_.Name } | Select-Object -Last 1
    Write-Host "GIMP 3.2 folder absent; falling back to newest 3.x: $($newest.Name)" -ForegroundColor Yellow
    return $newest
}

# --- resolve paths -----------------------------------------------------------
$source     = Get-RepoPluginPath
$versionDir = Get-GimpVersionDir
$targetDir  = Join-Path (Join-Path $versionDir.FullName 'plug-ins') $PluginSubdir
$targetFile = Join-Path $targetDir $PluginFileName

$srcHash = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash

# --- -Check mode (read-only) -------------------------------------------------
if ($Check) {
    Write-Host "Repo     : $source"
    Write-Host "Installed: $targetFile"
    if (-not (Test-Path -LiteralPath $targetFile -PathType Leaf)) {
        Write-Host "STATUS: NOT INSTALLED" -ForegroundColor Red
        exit 20
    }
    $tgtHash = (Get-FileHash -LiteralPath $targetFile -Algorithm SHA256).Hash
    if ($srcHash -eq $tgtHash) {
        Write-Host "STATUS: IN SYNC (SHA-256 $srcHash)" -ForegroundColor Green
        exit 0
    }
    Write-Host "STATUS: DRIFT" -ForegroundColor Yellow
    Write-Host "  repo      $srcHash"
    Write-Host "  installed $tgtHash"
    Write-Host "Run deploy.ps1 (no args) to update."
    exit 10
}

# --- install / update --------------------------------------------------------
New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
Copy-Item -LiteralPath $source -Destination $targetFile -Force

$tgtHash = (Get-FileHash -LiteralPath $targetFile -Algorithm SHA256).Hash
if ($tgtHash -ne $srcHash) {
    throw "Copy verification failed: installed hash $tgtHash != repo hash $srcHash"
}

Write-Host ""
Write-Host "Installed: $targetFile" -ForegroundColor Green
Write-Host "SHA-256  : $tgtHash"
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1. Restart GIMP (fully quit and reopen)."
Write-Host "  2. In GIMP: Tools > MCP > Start MCP Server."
Write-Host "  3. In Claude Code: run  /mcp  to reconnect."
exit 0
