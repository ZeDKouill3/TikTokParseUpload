<#
.SYNOPSIS
    Installe Clipper pour un utilisateur sans outil de developpement : Python,
    ffmpeg, claude, modeles, lanceur (SPEC-38f7761891f6 R2, R3 ; ADR-e1dac9ba2284).

.DESCRIPTION
    Compatible Windows PowerShell 5.1 (pas de &&, ni ??, ni operateur
    ternaire), sans elevation. Appele par Installer.bat, qui transmet les
    options telles quelles. Options (style GNU, pas les parametres nommes
    PowerShell) : --app <dossier>, --data <dossier>, --cpu, --cuda,
    --sans-console, --sans-raccourci (aucun raccourci Clipper.lnk sur le
    Bureau), --dry-run.

    --dry-run traverse exactement le meme code de decision que l'installation
    reelle (une fonction par etape, qui recoit -DryRun) : il affiche le plan
    (chemins resolus, decisions CPU/CUDA, premiere installation ou mise a
    jour...) sans rien ecrire ni telecharger. C'est le mode utilise par les
    tests (tests/test_installer.py).
#>

param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$RawArgs = @()
)

$ErrorActionPreference = "Stop"

# --------------------------------------------------------------------------
# Constantes et petites fonctions
# --------------------------------------------------------------------------

$TOTAL_STEPS = 11

# ffmpeg Windows 64 bits (GyanD/codexffmpeg, tag de version figee "9.0.2" :
# jamais "latest" ni "master", qui bougent et perimeraient le sha256 ci-
# dessous en silence). Pour renouveler : ouvrir
# https://github.com/GyanD/codexffmpeg/releases, choisir un tag de version
# (pas "latest"), telecharger son asset "*-essentials_build.zip", calculer
# son sha256 avec `Get-FileHash -Algorithm SHA256 <fichier>`, puis remplacer
# les deux constantes par la nouvelle URL (avec le tag dans le chemin) et le
# nouveau sha256.
$FFMPEG_URL = "https://github.com/GyanD/codexffmpeg/releases/download/9.0.2/ffmpeg-9.0.2-essentials_build.zip"
$FFMPEG_SHA256 = "60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba"

function Write-Step {
    param([int]$Number, [string]$Message)
    Write-Host "[$Number/$TOTAL_STEPS] $Message"
}

function Write-Detail {
    param([string]$Message)
    Write-Host "  - $Message"
}

function Fail {
    param([string]$Message, [string]$Remedy)
    Write-Host "[installer] ERREUR : $Message" -ForegroundColor Red
    if ($Remedy) {
        Write-Host "  remede : $Remedy" -ForegroundColor Red
    }
    exit 1
}

function Write-Log {
    param([string]$App, [string]$Message)
    if (-not $App) {
        return
    }
    $logPath = Join-Path $App "installer.log"
    $line = "$(Get-Date -Format 'yyyy-MM-ddTHH:mm:ss') $Message"
    Add-Content -Path $logPath -Value $line
}

function Compare-ClipperVersion {
    param([string]$A, [string]$B)
    try {
        return ([version]$A).CompareTo([version]$B)
    } catch {
        return [string]::Compare($A, $B)
    }
}

function Get-GpuDecision {
    param([switch]$Cpu, [switch]$Cuda)
    if ($Cpu) {
        return "cpu"
    }
    if ($Cuda) {
        return "cuda"
    }
    $cmd = Get-Command "nvidia-smi" -ErrorAction SilentlyContinue
    if (-not $cmd) {
        return "cpu"
    }
    try {
        $output = & nvidia-smi 2>$null
    } catch {
        return "cpu"
    }
    $text = ($output | Out-String).Trim()
    if ($text.Length -gt 0) {
        return "cuda"
    }
    return "cpu"
}

function Resolve-Wheel {
    param([string]$Root)
    $wheel = Get-ChildItem -Path $Root -Filter "clipper-*-py3-none-any.whl" -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($wheel) {
        return $wheel.FullName
    }
    return $null
}

function Format-ClipperBat {
    <#
    .SYNOPSIS
        Remplit installer/Clipper.bat.template avec les chemins absolus de
        app et data. Utilisee a l'identique pour ecrire le vrai lanceur
        (installation reelle) et pour afficher le resultat (--dry-run,
        criterion 4) : une seule fonction, jamais deux copies divergentes.
    #>
    param([string]$TemplatePath, [string]$App, [string]$Data)
    $content = Get-Content -Path $TemplatePath -Raw
    return $content.Replace("__APP__", $App).Replace("__DATA__", $Data)
}

# --------------------------------------------------------------------------
# Etapes (R3) : une fonction par etape, qui recoit -DryRun. En --dry-run,
# aucune ne cree de dossier, n'ecrit de fichier ni ne lance de telechargement :
# seule la ligne de decision est affichee.
# --------------------------------------------------------------------------

function Invoke-Step1-Prepare {
    param([string]$App, [string]$Data, [string]$NewVersion, [switch]$DryRun)
    $versionFile = Join-Path $App "version.txt"
    $isUpdate = $false
    if (Test-Path $versionFile) {
        $oldVersion = (Get-Content $versionFile -Raw).Trim()
        $cmp = Compare-ClipperVersion $NewVersion $oldVersion
        if ($cmp -lt 0) {
            Fail `
                "version $NewVersion plus ancienne que la version installee ($oldVersion) : pas de retrogradation" `
                "telecharge la derniere version depuis la page des releases GitHub"
        }
        $isUpdate = $true
        Write-Step 1 "Preparation : app=$App (mise a jour $oldVersion -> $NewVersion) ; data=$Data"
        Write-Detail ".venv sera supprime puis recree (python/ et ffmpeg/ conserves)"
    } else {
        Write-Step 1 "Preparation : app=$App (premiere installation, version $NewVersion) ; data=$Data"
    }
    if (-not $DryRun) {
        New-Item -ItemType Directory -Force -Path $App | Out-Null
        New-Item -ItemType Directory -Force -Path $Data | Out-Null
        if ($isUpdate) {
            $venvDir = Join-Path $App ".venv"
            if (Test-Path $venvDir) {
                Remove-Item -Recurse -Force -Path $venvDir
            }
        }
        Write-Log $App "etape 1/$TOTAL_STEPS : preparation ($App, $Data)"
    }
    return $isUpdate
}

function Invoke-Step2-Python {
    param([string]$App, [switch]$DryRun)
    $pythonDir = Join-Path $App "python"
    Write-Step 2 "Python 3.11 sous $pythonDir (uv python install 3.11)"
    if ($DryRun) {
        return
    }
    $env:UV_PYTHON_INSTALL_DIR = $pythonDir
    & uv python install 3.11
    if ($LASTEXITCODE -ne 0) {
        Fail "'uv python install 3.11' a echoue" "verifie la connexion reseau puis relance Installer.bat"
    }
    Write-Log $App "etape 2/$TOTAL_STEPS : python installe sous $pythonDir"
}

function Invoke-Step3-Venv {
    param([string]$App, [string]$Root, [string]$Device, [switch]$DryRun)
    $venvDir = Join-Path $App ".venv"
    if ($Device -eq "cuda") {
        Write-Step 3 "Environnement sous $venvDir ; GPU : [cuda] detecte, extra clipper[cuda] installe"
    } else {
        Write-Step 3 "Environnement sous $venvDir ; GPU : CPU (transcription plus lente)"
    }
    if ($DryRun) {
        return
    }
    $wheel = Resolve-Wheel -Root $Root
    if (-not $wheel) {
        Fail "wheel clipper introuvable a cote d'Installer.bat" "retelecharge le zip complet depuis la page des releases"
    }
    $env:UV_CACHE_DIR = Join-Path $App "cache"
    & uv venv $venvDir --python 3.11
    if ($LASTEXITCODE -ne 0) {
        Fail "'uv venv' a echoue" "relance Installer.bat"
    }
    $target = $wheel
    if ($Device -eq "cuda") {
        $target = "$wheel[cuda]"
    }
    # --python explicite : sans lui, "uv pip install" cherche un .venv en
    # remontant depuis le dossier courant (ou VIRTUAL_ENV) et peut installer
    # dans un venv totalement different de celui qu'on vient de creer sous
    # $App (observe reellement quand Installer.bat est lance depuis un
    # dossier dont un ancetre contient un .venv de developpement).
    $venvPython = Join-Path $venvDir "Scripts\python.exe"
    & uv pip install --python $venvPython $target
    if ($LASTEXITCODE -ne 0) {
        Fail "'uv pip install' a echoue" "verifie la connexion reseau puis relance Installer.bat"
    }
    Write-Log $App "etape 3/$TOTAL_STEPS : environnement installe ($Device)"
}

function Invoke-Step4-Ffmpeg {
    param([string]$App, [switch]$DryRun)
    $binDir = Join-Path $App "ffmpeg\bin"
    $ffmpegExe = Join-Path $binDir "ffmpeg.exe"
    if (Test-Path $ffmpegExe) {
        Write-Step 4 "ffmpeg deja present sous $binDir (conserve)"
        return
    }
    Write-Step 4 "ffmpeg sera telecharge sous $binDir ($FFMPEG_URL)"
    if ($DryRun) {
        return
    }
    $archive = Join-Path $env:TEMP "clipper-ffmpeg.zip"
    Invoke-WebRequest -Uri $FFMPEG_URL -OutFile $archive
    $actualHash = (Get-FileHash -Path $archive -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne $FFMPEG_SHA256) {
        Remove-Item -Force -Path $archive -ErrorAction SilentlyContinue
        Fail "sha256 de l'archive ffmpeg invalide ($actualHash)" "relance Installer.bat ; si l'echec persiste, l'URL ffmpeg epinglee a change"
    }
    $extractDir = Join-Path $env:TEMP "clipper-ffmpeg-extract"
    if (Test-Path $extractDir) {
        Remove-Item -Recurse -Force -Path $extractDir
    }
    Expand-Archive -Path $archive -DestinationPath $extractDir
    New-Item -ItemType Directory -Force -Path $binDir | Out-Null
    $sourceBin = Get-ChildItem -Path $extractDir -Recurse -Filter "ffmpeg.exe" | Select-Object -First 1
    if (-not $sourceBin) {
        Fail "ffmpeg.exe introuvable dans l'archive telechargee" "relance Installer.bat"
    }
    Copy-Item -Path (Join-Path $sourceBin.DirectoryName "ffmpeg.exe") -Destination $binDir -Force
    Copy-Item -Path (Join-Path $sourceBin.DirectoryName "ffprobe.exe") -Destination $binDir -Force
    Remove-Item -Force -Path $archive -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force -Path $extractDir -ErrorAction SilentlyContinue
    Write-Log $App "etape 4/$TOTAL_STEPS : ffmpeg installe sous $binDir"
}

function Invoke-Step5-Claude {
    param([string]$App, [switch]$DryRun)
    $found = Get-Command "claude" -ErrorAction SilentlyContinue
    if ($found) {
        Write-Step 5 "claude trouve ($($found.Source)) : connexion verifiee (claude auth status)"
    } else {
        Write-Step 5 "claude introuvable : sera installe (irm https://claude.ai/install.ps1 | iex) puis connexion demandee"
    }
    if ($DryRun) {
        return
    }
    if (-not $found) {
        Invoke-Expression (Invoke-WebRequest -Uri "https://claude.ai/install.ps1" -UseBasicParsing).Content
        $found = Get-Command "claude" -ErrorAction SilentlyContinue
        if (-not $found) {
            Fail "l'installation de claude a echoue" "installe-le manuellement (https://claude.ai/install.ps1) puis relance Installer.bat"
        }
    }
    & claude auth status
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[installer] claude n'est pas connecte : ouverture de 'claude auth login'..." -ForegroundColor Yellow
        Start-Process -FilePath "claude" -ArgumentList "auth", "login"
        Write-Host "[installer] connecte-toi dans la fenetre ouverte, puis appuie sur une touche ici..."
        [void][System.Console]::ReadKey($true)
        & claude auth status
        if ($LASTEXITCODE -ne 0) {
            Fail "claude n'est toujours pas connecte" "lance 'claude auth login' puis relance Installer.bat (ADR-b1c1, ADR-ad2e : pas de LLM, pas d'installation)"
        }
    }
    Write-Log $App "etape 5/$TOTAL_STEPS : claude pret"
}

function Invoke-Step6-Chrome {
    param([string]$App, [switch]$DryRun)
    $candidates = @(
        (Join-Path $env:ProgramFiles "Google\Chrome\Application\chrome.exe"),
        (Join-Path ${env:ProgramFiles(x86)} "Google\Chrome\Application\chrome.exe"),
        (Join-Path $env:LOCALAPPDATA "Google\Chrome\Application\chrome.exe")
    )
    $chrome = $candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
    if ($chrome) {
        Write-Step 6 "Google Chrome trouve : $chrome"
    } else {
        Write-Host "[6/$TOTAL_STEPS] ATTENTION : Google Chrome introuvable (necessaire seulement pour publier) : https://www.google.com/chrome" -ForegroundColor Yellow
    }
    if (-not $DryRun) {
        Write-Log $App "etape 6/$TOTAL_STEPS : chrome $(if ($chrome) { $chrome } else { 'absent' })"
    }
}

function Invoke-Step7-Data {
    param([string]$App, [string]$Data, [string]$PremierClipSource, [switch]$DryRun)
    $configPath = Join-Path $Data "config.toml"
    $initNeeded = -not (Test-Path $configPath)
    if ($initNeeded) {
        Write-Step 7 "Donnees : clipper init sera execute dans $Data (config.toml absent)"
    } else {
        Write-Step 7 "Donnees : $Data existe deja (config.toml present), clipper init non appele"
    }
    Write-Detail "$Data\PREMIER-CLIP.txt sera ecrit"
    if ($DryRun) {
        return
    }
    if ($initNeeded) {
        Push-Location $Data
        try {
            & clipper init
            if ($LASTEXITCODE -ne 0) {
                Fail "'clipper init' a echoue dans $Data" "verifie les droits d'ecriture de $Data"
            }
        } finally {
            Pop-Location
        }
    }
    Copy-Item -Path $PremierClipSource -Destination (Join-Path $Data "PREMIER-CLIP.txt") -Force
    Write-Log $App "etape 7/$TOTAL_STEPS : donnees pretes dans $Data (init $(if ($initNeeded) { 'execute' } else { 'ignore' }))"
}

function Invoke-Step8-Models {
    param([string]$App, [string]$Data, [switch]$DryRun)
    Write-Step 8 "Modeles : clipper models prefetch sera execute dans $Data (whisper, mediapipe)"
    if ($DryRun) {
        return
    }
    Push-Location $Data
    try {
        & clipper models prefetch
        if ($LASTEXITCODE -ne 0) {
            Fail "'clipper models prefetch' a echoue" "verifie la connexion reseau puis relance Installer.bat (une relance reprend la ou il s'est arrete)"
        }
    } finally {
        Pop-Location
    }
    Write-Log $App "etape 8/$TOTAL_STEPS : modeles prets"
}

function Invoke-Step9-Launcher {
    param([string]$App, [string]$Data, [string]$TemplatePath, [switch]$SansRaccourci, [switch]$DryRun)
    $launcherPath = Join-Path $App "Clipper.bat"
    $filled = Format-ClipperBat -TemplatePath $TemplatePath -App $App -Data $Data
    if ($SansRaccourci) {
        Write-Step 9 "Lanceur : $launcherPath (PATH = ffmpeg\bin puis .venv\Scripts, data courant, ouvre http://127.0.0.1:8000) ; aucun raccourci (--sans-raccourci)"
    } else {
        Write-Step 9 "Lanceur : $launcherPath (PATH = ffmpeg\bin puis .venv\Scripts, data courant, ouvre http://127.0.0.1:8000) et raccourci Clipper.lnk sur le Bureau"
    }
    if ($DryRun) {
        Write-Host "--- $launcherPath (apercu) ---"
        Write-Host $filled
        Write-Host "--- fin de l'apercu ---"
        return
    }
    Set-Content -Path $launcherPath -Value $filled -NoNewline
    if ($SansRaccourci) {
        Write-Log $App "etape 9/$TOTAL_STEPS : lanceur $launcherPath, pas de raccourci (--sans-raccourci)"
        return
    }
    $desktop = [Environment]::GetFolderPath("Desktop")
    $shortcutPath = Join-Path $desktop "Clipper.lnk"
    $shell = New-Object -ComObject WScript.Shell
    $lnk = $shell.CreateShortcut($shortcutPath)
    $lnk.TargetPath = $launcherPath
    $lnk.WorkingDirectory = $Data
    $iconPath = Join-Path $PSScriptRoot "clipper.ico"
    if (Test-Path $iconPath) {
        $lnk.IconLocation = "$iconPath,0"
    }
    $lnk.Description = "Console Clipper"
    $lnk.Save()
    Write-Log $App "etape 9/$TOTAL_STEPS : lanceur $launcherPath, raccourci $shortcutPath"
}

function Invoke-Step10-Doctor {
    param([string]$App, [string]$Data, [switch]$DryRun)
    $binDir = Join-Path $App "ffmpeg\bin"
    $scriptsDir = Join-Path $App ".venv\Scripts"
    Write-Step 10 "Controle : clipper doctor dans $Data (PATH = $binDir;$scriptsDir)"
    if ($DryRun) {
        return
    }
    $previousPath = $env:Path
    $previousLocation = Get-Location
    try {
        $env:Path = "$binDir;$scriptsDir;" + $env:Path
        Set-Location $Data
        $report = & clipper doctor
        $exitCode = $LASTEXITCODE
        $report | ForEach-Object { Write-Host $_ }
        if ($exitCode -ne 0) {
            Fail "clipper doctor rapporte un probleme (voir le rapport ci-dessus)" "corrige le point signale puis relance Installer.bat"
        }
    } finally {
        $env:Path = $previousPath
        Set-Location $previousLocation
    }
    Write-Log $App "etape 10/$TOTAL_STEPS : clipper doctor ok"
}

function Invoke-Step11-Finish {
    param([string]$App, [string]$Data, [string]$Version, [string]$Device, [switch]$SansConsole, [switch]$DryRun)
    $installJson = Join-Path $App "install.json"
    $cacheDir = Join-Path $App "cache"
    Write-Step 11 "Fin : $installJson ecrit, $cacheDir supprime$(if (-not $SansConsole) { ', console ouverte' })"
    if ($DryRun) {
        return
    }
    $payload = @{
        app     = $App
        data    = $Data
        version = $Version
        cuda    = ($Device -eq "cuda")
        date    = (Get-Date -Format "o")
    }
    $payload | ConvertTo-Json | Set-Content -Path $installJson
    # Step1-Prepare lit ce fichier pour decider premiere installation / mise
    # a jour : sans lui, une relance se croit toujours a sa premiere
    # installation, ne supprime jamais l'ancien .venv et 'uv venv' echoue
    # (deja observe reellement, R2).
    Set-Content -Path (Join-Path $App "version.txt") -Value $Version -NoNewline
    if (Test-Path $cacheDir) {
        Remove-Item -Recurse -Force -Path $cacheDir
    }
    Write-Log $App "etape 11/$TOTAL_STEPS : installation terminee ($Version, $Device)"
    Write-Host ""
    Write-Host "Installation terminee : programme sous $App, donnees sous $Data" -ForegroundColor Green
    if (-not $SansConsole) {
        & (Join-Path $App "Clipper.bat")
    }
}

# --------------------------------------------------------------------------
# Lecture des options (style GNU : --app, --data, --cpu, --cuda,
# --sans-console, --dry-run), puis execution des 11 etapes dans l'ordre.
# --------------------------------------------------------------------------

$App = Join-Path $env:LOCALAPPDATA "Clipper\app"
$Data = Join-Path ([Environment]::GetFolderPath("MyDocuments")) "Clipper"
$Cpu = $false
$Cuda = $false
$SansConsole = $false
$SansRaccourci = $false
$DryRun = $false

$i = 0
while ($i -lt $RawArgs.Count) {
    $token = $RawArgs[$i]
    if ($token -eq "--app") {
        $i++
        $App = $RawArgs[$i]
    } elseif ($token -eq "--data") {
        $i++
        $Data = $RawArgs[$i]
    } elseif ($token -eq "--cpu") {
        $Cpu = $true
    } elseif ($token -eq "--cuda") {
        $Cuda = $true
    } elseif ($token -eq "--sans-console") {
        $SansConsole = $true
    } elseif ($token -eq "--sans-raccourci") {
        $SansRaccourci = $true
    } elseif ($token -eq "--dry-run") {
        $DryRun = $true
    } else {
        Fail "option inconnue : $token" "options valides : --app, --data, --cpu, --cuda, --sans-console, --sans-raccourci, --dry-run"
    }
    $i++
}

if ($Cpu -and $Cuda) {
    Fail "options --cpu et --cuda incompatibles (choisis l'une des deux, ou aucune pour la detection automatique)" "relance avec --cpu ou --cuda, jamais les deux"
}

$versionFile = Join-Path (Split-Path -Parent $PSScriptRoot) "version.txt"
if (-not (Test-Path $versionFile)) {
    Fail "fichier version.txt introuvable ($versionFile)" "reconstruis le zip (tools/build_portable.py)"
}
$newVersion = (Get-Content $versionFile -Raw).Trim()
$root = Split-Path -Parent $versionFile
$templatePath = Join-Path $PSScriptRoot "Clipper.bat.template"
$premierClipSource = Join-Path $PSScriptRoot "PREMIER-CLIP.txt"

$isUpdate = Invoke-Step1-Prepare -App $App -Data $Data -NewVersion $newVersion -DryRun:$DryRun
Invoke-Step2-Python -App $App -DryRun:$DryRun
$device = Get-GpuDecision -Cpu:$Cpu -Cuda:$Cuda
Invoke-Step3-Venv -App $App -Root $root -Device $device -DryRun:$DryRun
Invoke-Step4-Ffmpeg -App $App -DryRun:$DryRun
Invoke-Step5-Claude -App $App -DryRun:$DryRun
Invoke-Step6-Chrome -App $App -DryRun:$DryRun
Invoke-Step7-Data -App $App -Data $Data -PremierClipSource $premierClipSource -DryRun:$DryRun
Invoke-Step8-Models -App $App -Data $Data -DryRun:$DryRun
Invoke-Step9-Launcher -App $App -Data $Data -TemplatePath $templatePath -SansRaccourci:$SansRaccourci -DryRun:$DryRun
Invoke-Step10-Doctor -App $App -Data $Data -DryRun:$DryRun
Invoke-Step11-Finish -App $App -Data $Data -Version $newVersion -Device $device -SansConsole:$SansConsole -DryRun:$DryRun

exit 0
