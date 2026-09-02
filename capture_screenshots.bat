@echo off
setlocal EnableExtensions DisableDelayedExpansion

rem Always resolve files relative to this launcher, not the caller's directory.
set "ROOT=%~dp0"
set "SCRIPT=%ROOT%tools\capture_screenshots.py"

if not exist "%SCRIPT%" (
    echo [ERROR] Missing script: "%SCRIPT%"
    pause
    exit /b 1
)

call "%ROOT%find_python.bat"
if not defined PYTHON_EXE (
    pause
    exit /b 1
)

pushd "%ROOT%" >nul
"%PYTHON_EXE%" "%SCRIPT%"
set "RUN_ERROR=%ERRORLEVEL%"
popd

echo.
if "%RUN_ERROR%"=="0" (
    echo Done.
) else (
    echo [ERROR] capture_screenshots.py exited with code %RUN_ERROR%.
)
pause
exit /b %RUN_ERROR%
