@echo off
setlocal

cd /d "%~dp0"
set "PYTHON_EXE=%CD%\.venv\Scripts\python.exe"

if not exist "%PYTHON_EXE%" (
    echo ERROR: Project virtual environment was not found.
    echo Run setup.bat first.
    goto error
)

echo Initializing the private CareerOps data repository...
"%PYTHON_EXE%" scripts\private_data_sync.py initialize %*
if errorlevel 1 goto error

echo.
echo Initialization complete. Run verify_private_data_sync.bat before the first sync.
pause
exit /b 0

:error
echo.
echo Private repository initialization stopped safely. No Tracker data was changed.
pause
exit /b 1
