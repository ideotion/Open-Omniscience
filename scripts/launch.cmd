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

rem The in-app updater's watch flag (scripts\apply_update.py) is for THIS window only: copied to OO_WATCHED, then cleared, so nothing the
rem server starts carries it on (the server sees OO_WATCHED, which every start of this file sets afresh).
set "OO_WATCHED=%OO_UPDATE_WATCH%"
set "OO_UPDATE_WATCH="

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
  rem The browser never inherits a passphrase: the two names the server holds,
  rem secret_scrub.HELD_ENV_VARS, are cleared first. This is inside setlocal,
  rem so the window that ran this launcher keeps them. No brackets in these
  rem lines: they sit inside a bracketed block.
  set "OO_DB_PASSPHRASE="
  set "OO_KEY_PASSPHRASE="
  start "" "%URL%"
  exit /b 0
)

echo.
echo   Starting Open Omniscience...
echo   Your browser will open at %URL% once the app is ready.
echo   First launch takes longer: it prepares the database and seeds sources.
echo.
echo   Close this window (or use the app's power button) to stop the app.
echo   You can close the browser at any time: the app keeps running in this window.
echo.

rem Wait for the server to answer, then open the browser. Up to ~2 minutes, which a
rem first-run database preparation can genuinely need.
rem The waiting PowerShell and the browser it starts never inherit a passphrase: the
rem two names the server holds (src\monitoring\secret_scrub.py HELD_ENV_VARS, which
rem tests\test_launcher_browser_env.py holds this list to) are cleared in a nested
rem setlocal for that one start, and endlocal gives them back for the server below,
rem which needs them.
setlocal
set "OO_DB_PASSPHRASE="
set "OO_KEY_PASSPHRASE="
start "" /min powershell -NoProfile -ExecutionPolicy Bypass -Command "$u='%URL%'; for ($i=0; $i -lt 240; $i++) { try { $null = Invoke-WebRequest -Uri $u -UseBasicParsing -TimeoutSec 2; Start-Process $u; break } catch { Start-Sleep -Milliseconds 500 } }"
endlocal

rem THE TERMINAL PANEL (R600, anticipated for Windows; not run on Windows yet). src\tui\panel.py shows the app's status and jobs with
rem Open UI / Pause collection / Stop app. Python's curses exists on Windows only with the windows-curses package (a pyproject dependency
rem on Intel/AMD Windows since R602; no ARM64 build exists), so the panel starts only
rem when "import curses" works there, and never with OO_PANEL=0. It opens in a window of its own, because this one holds the server's
rem output: closing the panel window does NOT stop the app (the panel says so); closing THIS window still does.
rem The panel never needs the passphrases, so neither it nor the curses check gets them: both names are cleared in a nested setlocal
rem that endlocal undoes before the server starts below. The clears come BEFORE the check, because clearing a name that is not set
rem sets ERRORLEVEL, and the check's own exit code is what "if not errorlevel 1" reads.
if not "%OO_PANEL%"=="0" if exist ".venv\Scripts\python.exe" (
  setlocal
  set "OO_DB_PASSPHRASE="
  set "OO_KEY_PASSPHRASE="
  ".venv\Scripts\python.exe" -c "import curses" >nul 2>&1
  if not errorlevel 1 start "Open Omniscience panel" ".venv\Scripts\python.exe" -m src.tui.panel --port %PORT% --url "%URL%/"
  endlocal
)
rem Run the server through scripts\launch_server.ps1 when it is there: the window still shows every line the server prints, and the wrapper
rem records the server's fatal-error headers and how it ended for the app's next boot to read. It leaves a marker file once it has STARTED
rem the server; no marker means the wrapper itself could not run (PowerShell missing or blocked), and the server is then started plainly,
rem exactly as before.
set "MARK=%TEMP%\oo-launch-%RANDOM%-%RANDOM%.started"
if not exist "%~dp0launch_server.ps1" goto plain
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0launch_server.ps1" -App "%APP%" -Marker "%MARK%"
if exist "%MARK%" (
  del "%MARK%" >nul 2>&1
  goto stopped
)

:plain
"%APP%"

:stopped
echo.
echo   Open Omniscience has stopped. Press any key to close.
rem CHAINED, never called: control passes to launch_stopped.cmd and never comes back here. cmd.exe re-reads a batch file by byte offset
rem after every command, so a window waiting for a key while the in-app updater rewrites THIS file would carry on at the old offset in the new
rem text. launch_stopped.cmd holds the wait and is frozen (tests/test_self_update.py pins its content).
"%~dp0launch_stopped.cmd"
