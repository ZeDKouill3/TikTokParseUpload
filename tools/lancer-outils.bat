@echo off
setlocal
rem Lance le proxy px (3128) et le visualiseur ank (8765) s'ils ne tournent pas deja.
rem Usage : double-clic, ou tools\lancer-outils.bat depuis n'importe ou.
rem Reglages propres au poste, a definir une fois (setx) : PX_UPSTREAM (proxy amont),
rem PX_USER (identifiant proxy), et optionnellement OUTILS_PYTHON (python qui a px, defaut python).
if not defined OUTILS_PYTHON set OUTILS_PYTHON=python
for %%I in ("%~dp0..") do set REPO=%%~fI
set VIZBRANCH=task/TASK-7aca-ank-viz
set VIZWT=%REPO%\..\clipper-wt\ank-viz

rem --- proxy px ---
netstat -ano | findstr /R /C:":3128 .*LISTENING" >nul
if errorlevel 1 (
  if not defined PX_UPSTREAM (
    echo [proxy] PX_UPSTREAM non defini : px non lance ^(setx PX_UPSTREAM http://proxy:port^).
  ) else (
    echo [proxy] ferme, demarrage de px sur 3128...
    start "px proxy" /min "%OUTILS_PYTHON%" -m px -p 3128 -u %PX_USER% -n ONE -w -a %PX_UPSTREAM%
  )
) else (
  echo [proxy] deja lance.
)

rem --- visualiseur ank ---
netstat -ano | findstr /R /C:":8765 .*LISTENING" >nul
if not errorlevel 1 (
  echo [ank-viz] deja lance, ouverture du navigateur.
  start "" http://127.0.0.1:8765
  goto :fin
)
rem Viewer du depot s'il est merge, sinon celui de sa branche dans un worktree dedie.
set VIZ=%REPO%\tools\ank-viz\server.py
if exist "%VIZ%" goto :viz
set VIZ=%VIZWT%\tools\ank-viz\server.py
if not exist "%VIZ%" (
  echo [ank-viz] creation du worktree du viewer...
  git -C "%REPO%" worktree add --detach "%VIZWT%" %VIZBRANCH%
) else (
  git -C "%VIZWT%" checkout -q --detach %VIZBRANCH%
)
:viz
echo [ank-viz] demarrage sur http://127.0.0.1:8765 ...
start "ank-viz" /min "%OUTILS_PYTHON%" "%VIZ%" --repo "%REPO%"
:fin
endlocal
