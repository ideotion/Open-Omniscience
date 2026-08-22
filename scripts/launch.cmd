@echo off
rem ---------------------------------------------------------------------------
rem  Open Omniscience -- Windows launcher (the counterpart of scripts/launch.sh).
rem
rem  Starts the local app and opens your browser once it actually answers, rather
rem  than after a guessed delay. Binds to 127.0.0.1 only; nothing listens off
rem  loopback. Close this window to stop the app.
rem ---------------------------------------------------------------------------
setlocal
title Open Omniscience

cd /d "%~dp0.."

set "PORT=%OO_PORT%"
if "%PORT%"=="" set "PORT=8000"
set "URL=http://127.0.0.1:%PORT%"
set "APP=.venv\Scripts\open-omniscience.exe"

if not exist "%APP%" (
  echo.
  echo   Open Omniscience is not installed in this folder yet.
  echo.
  echo   Run this once, then try again:
  echo     powershell -ExecutionPolicy Bypass -File "%~dp0..\install.ps1"
  echo.
  echo   Press any key to close.
  pause >nul
  exit /b 1
)

rem If a server is already answering, just open the browser -- never start a second
rem one (it would fail to bind the port and look like a crash).
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $null = Invoke-WebRequest -Uri '%URL%' -UseBasicParsing -TimeoutSec 2; exit 0 } catch { exit 1 }"
if not errorlevel 1 (
  echo   Open Omniscience is already running -- opening %URL%
  start "" "%URL%"
  exit /b 0
)

echo.
echo   Starting Open Omniscience...
echo   Your browser will open at %URL% once the app is ready.
echo   First launch takes longer: it prepares the database and seeds sources.
echo.
echo   Close this window (or use the app's power button) to stop the app.
echo.

rem Wait for the server to answer, then open the browser. Up to ~2 minutes, which a
rem first-run database preparation can genuinely need.
start "" /min powershell -NoProfile -ExecutionPolicy Bypass -Command "$u='%URL%'; for ($i=0; $i -lt 240; $i++) { try { $null = Invoke-WebRequest -Uri $u -UseBasicParsing -TimeoutSec 2; Start-Process $u; break } catch { Start-Sleep -Milliseconds 500 } }"

"%APP%"

echo.
echo   Open Omniscience has stopped. Press any key to close.
pause >nul
endlocal
