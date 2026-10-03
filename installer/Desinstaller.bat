@echo off
rem Desinstalle Clipper (SPEC-38f7761891f6 R8). Double-clic, ou depuis un
rem terminal avec des options : Desinstaller.bat [--donnees] [--dry-run].
rem Toutes les options sont transmises telles quelles a
rem installer\desinstaller.ps1.
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0desinstaller.ps1" %*
exit /b %errorlevel%
