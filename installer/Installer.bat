@echo off
rem Installe Clipper (SPEC-38f7761891f6). Double-clic, ou depuis un terminal
rem avec des options : Installer.bat --app <dossier> --data <dossier> [--cpu
rem | --cuda] [--sans-console] [--dry-run]. Toutes les options sont
rem transmises telles quelles a installer\install.ps1.
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
exit /b %errorlevel%
