@echo off
setlocal

cd /d "%~dp0"

if not exist "app.py" (
    echo ERROR: app.py was not found in %CD%.
    goto error
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 goto error
)

set "PYTHON_EXE=%CD%\.venv\Scripts\python.exe"

echo Upgrading pip...
"%PYTHON_EXE%" -m pip install --upgrade pip
if errorlevel 1 goto error

echo Installing dependencies from requirements.txt...
"%PYTHON_EXE%" -m pip install -r requirements.txt
if errorlevel 1 goto error
type nul > ".venv\.careerops_requirements_installed"

echo.
echo Setup complete. You can now double-click start.bat or run:
echo "%PYTHON_EXE%" -m streamlit run app.py
echo.
pause
goto end

:error
echo.
echo Setup failed. Please check the error message above.
pause
exit /b 1

:end
endlocal
