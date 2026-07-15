@echo off
setlocal

cd /d "%~dp0"
set "PYTHON_EXE=%CD%\.venv\Scripts\python.exe"

if not exist "%PYTHON_EXE%" (
    echo ERROR: Project virtual environment was not found.
    echo Run setup.bat first.
    goto error
)

echo Synchronizing private CareerOps data...
"%PYTHON_EXE%" scripts\private_data_sync.py sync %*
if errorlevel 1 goto error

echo.
echo Private data synchronization finished.
pause
exit /b 0

:error
echo.
echo Synchronization stopped safely. Review the message above and retry when ready.
pause
exit /b 1
