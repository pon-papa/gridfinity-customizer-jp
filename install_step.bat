@echo off
setlocal EnableExtensions
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  call "%~dp0setup.bat"
  if errorlevel 1 exit /b 1
)
".venv\Scripts\python.exe" -m pip --disable-pip-version-check install --prefer-binary -r "requirements-step.txt"
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -c "import cadquery; print('CadQuery', cadquery.__version__)"
if errorlevel 1 goto failed
echo.
echo STEP support installed successfully. Restart the application.
pause
exit /b 0
:failed
echo.
echo ERROR: STEP support installation failed.
echo Python 3.12 64-bit is the recommended environment.
pause
exit /b 1
