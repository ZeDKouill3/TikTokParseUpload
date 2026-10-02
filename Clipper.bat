@echo off
setlocal
rem Lance la console Clipper (clipper serve, port 8000) si elle ne tourne pas
rem deja, puis l'ouvre dans le navigateur. Double-clic, ou le raccourci
rem Clipper.lnk (avec le logo) cree par tools\creer-raccourci.ps1.
set REPO=%~dp0
set URL=http://127.0.0.1:8000

netstat -ano | findstr /R /C:"127.0.0.1:8000 .*LISTENING" >nul
if errorlevel 1 (
  if not exist "%REPO%.venv\Scripts\clipper.exe" (
    echo Clipper n'est pas installe : lance tools\setup.ps1 d'abord.
    pause
    exit /b 1
  )
  echo Demarrage de la console Clipper sur %URL%...
  start "Clipper serve" /min /d "%REPO%" "%REPO%.venv\Scripts\clipper.exe" serve
  rem Attend que le serveur ecoute (20 s max).
  for /l %%i in (1,1,20) do (
    netstat -ano | findstr /R /C:"127.0.0.1:8000 .*LISTENING" >nul && goto :open
    timeout /t 1 /nobreak >nul
  )
)
:open
start "" "%URL%"
