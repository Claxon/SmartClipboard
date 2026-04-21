@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv" (
    py -3 -m venv .venv || goto :fail
)
call ".venv\Scripts\activate.bat"
pip install -r requirements.txt || goto :fail
echo.
echo Done. Run "run.bat" to start SmartClipboard.
echo Right-click the tray icon to toggle "Run at startup".
pause
exit /b 0
:fail
echo Install failed.
pause
exit /b 1
