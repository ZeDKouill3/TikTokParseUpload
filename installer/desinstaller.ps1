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
    # Bureau ou chercher Clipper.lnk : meme statut que $Port, seulement un
    # point d'injection pour les tests (un test ne doit jamais toucher le vrai
    # Bureau). Vide = dossier Bureau de l'utilisateur.
    [string]$Bureau = "",
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

function Get-CheminNormalise {
    param([string]$Chemin)
    return [IO.Path]::GetFullPath($Chemin).TrimEnd('\')
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

# I6 : refuse si $App ne ressemble pas a une installation Clipper (aucun
# install.json ni version.txt), sinon un --app absent ou une faute de frappe
# affichait "Desinstallation terminee." en vert (succes silencieux, ADR-ad2e)
# sans rien supprimer, ou a l'inverse supprimait n'importe quel dossier passe
# en --app sans aucune verification.
$hasInstallMarker = (Test-Path (Join-Path $App "install.json")) -or (Test-Path (Join-Path $App "version.txt"))
if (-not $hasInstallMarker) {
    Fail "aucune installation Clipper sous $App (install.json absent)" "passe --app <dossier app> ou verifie l'installation"
}

if ($Bureau) {
    $desktop = $Bureau
} else {
    $desktop = [Environment]::GetFolderPath("Desktop")
}
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

# Pointeur %LOCALAPPDATA%\Clipper\install.json (pose par install.ps1 Step11,
# toujours a cet emplacement fixe, meme avec --app personnalise). Il n'est
# retire que s'il designe CE $App ; un pointeur d'une autre installation ou
# illisible est laisse, et le dit (ADR-ad2e : aucun repli silencieux).
$pointerDir = Join-Path $env:LOCALAPPDATA "Clipper"
$pointerPath = Join-Path $pointerDir "install.json"
$pointerSupprime = $false
$pointerRaison = ""
if (Test-Path $pointerPath) {
    $pointerApp = $null
    try {
        $pointerInfo = Get-Content -Path $pointerPath -Raw | ConvertFrom-Json
        $pointerApp = [string]$pointerInfo.app
    } catch {
        $pointerApp = $null
    }
    if (-not $pointerApp) {
        $pointerRaison = "illisible ou sans champ app"
    } else {
        # Normalisation hors du try precedent : un chemin aux caracteres
        # interdits leve ArgumentException ; le pointeur est alors laisse.
        $memeApp = $false
        try {
            $memeApp = (Get-CheminNormalise $pointerApp) -ieq (Get-CheminNormalise $App)
        } catch {
            $pointerRaison = "champ app illisible ($pointerApp)"
        }
        if (-not $pointerRaison) {
            if ($memeApp) {
                $pointerSupprime = $true
            } else {
                $pointerRaison = "autre installation : $pointerApp"
            }
        }
    }
    if ($pointerSupprime) {
        Write-Host "Desinstallation : $pointerPath sera supprime"
    } else {
        Write-Host "Desinstallation : $pointerPath laisse ($pointerRaison)" -ForegroundColor Yellow
        if ($pointerRaison -like "*illisible*") {
            Write-Host "  remede : verifie ou supprime ce fichier a la main, il n'est pas lu par cette desinstallation" -ForegroundColor Yellow
        }
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

if ($pointerSupprime -and (Test-Path $pointerPath)) {
    Remove-Item -Force -Path $pointerPath
    # Le dossier %LOCALAPPDATA%\Clipper ne part que vide : il peut contenir
    # autre chose (autre installation, fichiers de l'utilisateur).
    if ((Test-Path $pointerDir) -and -not (Get-ChildItem -Force -Path $pointerDir)) {
        Remove-Item -Force -Path $pointerDir
    }
}

Write-Host "Desinstallation terminee." -ForegroundColor Green
exit 0
