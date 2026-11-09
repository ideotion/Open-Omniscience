@echo off
rem FROZEN: never edit this file. scripts\launch.cmd chains here to wait for a key after the app stopped, and cmd.exe reads a batch file by
rem byte offset, so a window waiting in it while an update rewrote it would run whatever text then sits at that offset. OO_WATCHED: started
rem again by the in-app updater, which watches this window end with the server instead of waiting for a key.
if defined OO_WATCHED exit /b 0
pause >nul
exit /b 0
