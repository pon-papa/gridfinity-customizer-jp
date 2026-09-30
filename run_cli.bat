@echo off
setlocal EnableExtensions
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  call "%~dp0setup.bat"
  if errorlevel 1 exit /b 1
)
if "%~1"=="" (
  echo Usage: run_cli.bat presets\sample_units_plus_mm.json
  pause
  exit /b 1
)
set "PYTHONPATH=%CD%\src"
".venv\Scripts\python.exe" -m gridfinity_customizer.cli "%~1"
set "RC=%errorlevel%"
pause
exit /b %RC%
