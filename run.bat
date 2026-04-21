@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo Creating virtualenv...
    py -3 -m venv .venv || goto :fail
    call ".venv\Scripts\activate.bat"
    pip install -r requirements.txt || goto :fail
) else (
    call ".venv\Scripts\activate.bat"
)
start "" ".venv\Scripts\pythonw.exe" "%~dp0main.py"
exit /b 0
:fail
echo Setup failed.
pause
exit /b 1
