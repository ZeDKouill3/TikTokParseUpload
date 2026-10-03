<#
.SYNOPSIS
    Desinstalle Clipper (SPEC-38f7761891f6 R8). Appele par Desinstaller.bat.

.DESCRIPTION
    Compatible Windows PowerShell 5.1. Options (style GNU) : --app <dossier>
    (par defaut %LOCALAPPDATA%\Clipper\app), --donnees (supprime aussi le
    dossier de donnees sans demander), --dry-run (affiche le plan sans agir,
    jamais interactif). Refuse si la console Clipper (port 8000) ecoute.
    Ne touche jamais claude, Chrome ni les caches de modeles (~/.cache/clipper,
    cache Hugging Face).
#>

param(
    # Port de la console Clipper a verifier : jamais une option publique
    # (Desinstaller.bat ne la transmet pas), seulement un point d'injection
    # pour les tests (tests/test_installer.py), la vraie console ecoutant
    # toujours sur 8000.
    [int]$Port = 8000,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$RawArgs = @()
)

$ErrorActionPreference = "Stop"

function Fail {
    param([string]$Message, [string]$Remedy)
    Write-Host "[desinstaller] ERREUR : $Message" -ForegroundColor Red
    if ($Remedy) {
        Write-Host "  remede : $Remedy" -ForegroundColor Red
    }
    exit 1
}

function Test-ConsolePortListening {
    param([int]$Port)
    $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    return ($null -ne $conn)
}

$App = Join-Path $env:LOCALAPPDATA "Clipper\app"
$Donnees = $false
$DryRun = $false

$i = 0
while ($i -lt $RawArgs.Count) {
    $token = $RawArgs[$i]
    if ($token -eq "--app") {
        $i++
        $App = $RawArgs[$i]
    } elseif ($token -eq "--donnees") {
        $Donnees = $true
    } elseif ($token -eq "--dry-run") {
        $DryRun = $true
    } else {
        Fail "option inconnue : $token" "options valides : --app, --donnees, --dry-run"
    }
    $i++
}

if (Test-ConsolePortListening -Port $Port) {
    Fail "la console Clipper tourne (le port $Port ecoute)" "ferme la console (fenetre 'Clipper serve') puis relance Desinstaller.bat"
}

$desktop = [Environment]::GetFolderPath("Desktop")
$shortcut = Join-Path $desktop "Clipper.lnk"

Write-Host "Desinstallation : $App sera supprime"
Write-Host "Desinstallation : $shortcut sera supprime"

$data = $null
$installJsonPath = Join-Path $App "install.json"
if (Test-Path $installJsonPath) {
    $info = Get-Content -Path $installJsonPath -Raw | ConvertFrom-Json
    if ($info.data) {
        $data = [string]$info.data
    }
}

if ($DryRun) {
    if ($Donnees -and $data) {
        Write-Host "Desinstallation : $data sera aussi supprime (--donnees)"
    }
    exit 0
}

$removeData = $Donnees
if (-not $removeData -and $data) {
    $answer = Read-Host "Supprimer aussi les donnees ($data) ? (o/N)"
    $removeData = ($answer -match "^(o|oui)$")
}

if ($removeData -and $data) {
    Write-Host "Desinstallation : $data sera aussi supprime"
}

if (Test-Path $App) {
    Remove-Item -Recurse -Force -Path $App
}
if (Test-Path $shortcut) {
    Remove-Item -Force -Path $shortcut
}
if ($removeData -and $data -and (Test-Path $data)) {
    Remove-Item -Recurse -Force -Path $data
}

Write-Host "Desinstallation terminee." -ForegroundColor Green
exit 0
