@echo off
setlocal

cd /d "%~dp0"
set "PYTHON_EXE=%CD%\.venv\Scripts\python.exe"

if not exist "%PYTHON_EXE%" (
    echo ERROR: Project virtual environment was not found.
    echo Run setup.bat first.
    goto error
)

echo Validating the private CareerOps data export without committing or pushing...
"%PYTHON_EXE%" scripts\private_data_sync.py dry-run %*
if errorlevel 1 goto error

echo.
echo Dry-run finished. No commit or push was performed.
pause
exit /b 0

:error
echo.
echo Dry-run stopped safely. No commit or push was performed.
pause
exit /b 1
