@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Gridfinity Customizer JP Setup

echo [Gridfinity Customizer JP 1.2.1]
echo Installing the standard 3MF and STL components only.
echo STEP support is NOT installed by this setup.
echo SciPy, NetworkX, and CadQuery are NOT required for standard operation.
echo Packages: numpy, shapely, trimesh
echo.
set "PY_CMD="

py -3.12 -c "import sys; raise SystemExit(0 if (3,10) <= sys.version_info[:2] < (3,14) else 1)" >nul 2>&1
if not errorlevel 1 set "PY_CMD=py -3.12"
if defined PY_CMD goto python_found

py -3.13 -c "import sys; raise SystemExit(0 if (3,10) <= sys.version_info[:2] < (3,14) else 1)" >nul 2>&1
if not errorlevel 1 set "PY_CMD=py -3.13"
if defined PY_CMD goto python_found

py -3.11 -c "import sys; raise SystemExit(0 if (3,10) <= sys.version_info[:2] < (3,14) else 1)" >nul 2>&1
if not errorlevel 1 set "PY_CMD=py -3.11"
if defined PY_CMD goto python_found

py -3.10 -c "import sys; raise SystemExit(0 if (3,10) <= sys.version_info[:2] < (3,14) else 1)" >nul 2>&1
if not errorlevel 1 set "PY_CMD=py -3.10"
if defined PY_CMD goto python_found

python -c "import sys; raise SystemExit(0 if (3,10) <= sys.version_info[:2] < (3,14) else 1)" >nul 2>&1
if not errorlevel 1 set "PY_CMD=python"
if defined PY_CMD goto python_found

echo ERROR: Compatible Python was not found.
echo Install 64-bit Python 3.12 from python.org, then run this file again.
echo During installation, enable the Python launcher or Add Python to PATH.
pause
exit /b 1

:python_found
echo Using: %PY_CMD%
if not exist ".venv\Scripts\python.exe" (
  echo Creating the private environment .venv ...
  %PY_CMD% -m venv ".venv"
  if errorlevel 1 goto setup_failed
)

echo Installing the three standard packages. This can take several minutes.
".venv\Scripts\python.exe" -m pip --disable-pip-version-check install --prefer-binary -r "requirements.txt"
if errorlevel 1 goto setup_failed

".venv\Scripts\python.exe" -c "import tkinter, numpy, shapely, trimesh"
if errorlevel 1 goto setup_failed

echo Running an actual 3MF generation test ...
".venv\Scripts\python.exe" "%~dp0selftest.py"
if errorlevel 1 goto setup_failed

echo.
echo Setup completed successfully.
echo Start the application with launch.bat.
echo STEP remains optional and is installed only by install_step.bat.
pause
exit /b 0

:setup_failed
echo.
echo ERROR: Setup or the 3MF self-test failed.
echo Check the Internet connection and use 64-bit Python 3.10 through 3.13.
pause
exit /b 1
