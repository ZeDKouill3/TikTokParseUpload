@echo off
rem Installe Clipper (SPEC-38f7761891f6). Double-clic, ou depuis un terminal
rem avec des options : Installer.bat --app <dossier> --data <dossier> [--cpu
rem | --cuda] [--sans-console] [--sans-raccourci] [--dry-run]. Toutes les
rem options sont transmises telles quelles a installer\install.ps1.
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\install.ps1" %*
exit /b %errorlevel%
