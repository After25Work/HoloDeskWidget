@echo off
setlocal EnableExtensions DisableDelayedExpansion

rem Always resolve files relative to this launcher, not the caller's directory.
set "ROOT=%~dp0"
set "SCRIPT=%ROOT%start_widget_native.py"
set "LOG=%ROOT%start_widget.log"
set "PYTHON_EXE="
set "PYTHONW_EXE="

if not exist "%SCRIPT%" (
    echo [ERROR] Missing launcher script: "%SCRIPT%"
    pause
    exit /b 1
)

rem Prefer the per-user installation, then inspect PATH candidates. Each
rem candidate is checked for both a usable interpreter and pythonw.exe.
call :select_python "%LocalAppData%\Programs\Python\Python310\python.exe"
if defined PYTHON_EXE goto PYTHON_FOUND
call :select_python "%ProgramFiles%\Python310\python.exe"
if defined PYTHON_EXE goto PYTHON_FOUND
for /f "delims=" %%P in ('where python.exe 2^>nul') do call :select_python "%%P"
if defined PYTHON_EXE goto PYTHON_FOUND

if not defined PYTHON_EXE (
    echo [ERROR] Python 3.10 or a usable Python installation was not found.
    echo Install Python 3.10+ and enable the Python launcher, then try again.
    pause
    exit /b 1
)

:PYTHON_FOUND
for %%P in ("%PYTHON_EXE%") do set "PYTHONW_EXE=%%~dpPpythonw.exe"
if not exist "%PYTHONW_EXE%" (
    echo [ERROR] pythonw.exe was not found next to "%PYTHON_EXE%".
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

:select_python
if defined PYTHON_EXE exit /b 0
if not exist "%~1" exit /b 0
for %%P in ("%~1") do if not exist "%%~dpPpythonw.exe" exit /b 0
set "PYTHON_EXE=%~1"
exit /b 0
