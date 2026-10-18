@echo off
setlocal DisableDelayedExpansion
py -3 -m venv "%~dp0.venv"
if errorlevel 1 goto failed
"%~dp0.venv\Scripts\python.exe" -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 goto failed
echo Setup complete. For DWG input install ODA File Converter separately.
pause
exit /b 0
:failed
echo Setup failed. Install Python 3.10 or later first.
pause
exit /b 1
