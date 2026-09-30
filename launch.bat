@echo off
setlocal EnableExtensions
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  call "%~dp0setup.bat"
  if errorlevel 1 exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" "%~dp0app.py"
exit /b 0
