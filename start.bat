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
set "DEPS_MARKER=.venv\.careerops_requirements_installed"
set "NEEDS_INSTALL="

"%PYTHON_EXE%" -c "import streamlit" >nul 2>nul
if errorlevel 1 set "NEEDS_INSTALL=1"
if not exist "%DEPS_MARKER%" set "NEEDS_INSTALL=1"

if defined NEEDS_INSTALL (
    echo Installing dependencies from requirements.txt...
    "%PYTHON_EXE%" -m pip install --upgrade pip
    if errorlevel 1 goto error
    "%PYTHON_EXE%" -m pip install -r requirements.txt
    if errorlevel 1 goto error
    type nul > "%DEPS_MARKER%"
)

echo Starting CareerOps Tracker...
echo Open http://localhost:8501 if the browser does not open automatically.
"%PYTHON_EXE%" -m streamlit run app.py
if errorlevel 1 goto error

goto end

:error
echo.
echo CareerOps Tracker could not start.
echo Please check the error message above.
pause
exit /b 1

:end
endlocal
