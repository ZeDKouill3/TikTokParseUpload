# Cree Clipper.lnk a la racine du depot : lance Clipper.bat, avec le logo
# (tools\clipper.ico). A relancer si le depot change de dossier.
$repo = Split-Path -Parent $PSScriptRoot
$shell = New-Object -ComObject WScript.Shell
$lnk = $shell.CreateShortcut((Join-Path $repo "Clipper.lnk"))
$lnk.TargetPath = Join-Path $repo "Clipper.bat"
$lnk.WorkingDirectory = $repo
$lnk.IconLocation = (Join-Path $PSScriptRoot "clipper.ico") + ",0"
$lnk.WindowStyle = 7
$lnk.Description = "Console Clipper"
$lnk.Save()
Write-Output "Raccourci cree : $(Join-Path $repo 'Clipper.lnk')"
