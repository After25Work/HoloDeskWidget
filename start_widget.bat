@echo off
setlocal EnableExtensions DisableDelayedExpansion

rem Always resolve files relative to this launcher, not the caller's directory.
set "ROOT=%~dp0"
set "SCRIPT=%ROOT%start_widget_native.py"
set "LOG=%ROOT%start_widget.log"

if not exist "%SCRIPT%" (
    echo [ERROR] Missing launcher script: "%SCRIPT%"
    pause
    exit /b 1
)

call "%ROOT%find_python.bat" pythonw
if not defined PYTHON_EXE (
    pause
    exit /b 1
)

rem Fail before spawning a hidden process if the required Pillow package is missing.
"%PYTHON_EXE%" -c "import PIL" >nul 2>"%LOG%.dependency"
if errorlevel 1 (
    echo [ERROR] Pillow is not installed for:
    echo         "%PYTHON_EXE%"
    echo Install it with: "%PYTHON_EXE%" -m pip install Pillow
    echo Details were written to "%LOG%.dependency"
    pause
    exit /b 1
)

pushd "%ROOT%" >nul
start "HoloDeskWidget" /b "%PYTHONW_EXE%" "%SCRIPT%"
set "START_ERROR=%ERRORLEVEL%"
popd

if "%START_ERROR%"=="0" goto LAUNCH_OK
echo [ERROR] Failed to start the widget (code %START_ERROR%).
echo See "%LOG%" for application errors.
pause
exit /b %START_ERROR%

:LAUNCH_OK
exit /b 0
