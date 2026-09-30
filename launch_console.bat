@echo off
setlocal EnableExtensions
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  call "%~dp0setup.bat"
  if errorlevel 1 exit /b 1
)
".venv\Scripts\python.exe" "%~dp0app.py"
set "RC=%errorlevel%"
if not "%RC%"=="0" pause
exit /b %RC%
