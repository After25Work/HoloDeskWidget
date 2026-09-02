@echo off
setlocal EnableExtensions DisableDelayedExpansion

rem Always resolve files relative to this launcher, not the caller's directory.
set "ROOT=%~dp0"
set "SPEC=%ROOT%build\HoloDesk Widget.spec"
set "PYTHON_EXE="

if not exist "%SPEC%" (
    echo [ERROR] Missing PyInstaller spec: "%SPEC%"
    pause
    exit /b 1
)

rem Prefer the per-user installation, then inspect PATH candidates.
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
rem Fail before invoking PyInstaller if it is not installed.
"%PYTHON_EXE%" -c "import PyInstaller" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] PyInstaller is not installed for:
    echo         "%PYTHON_EXE%"
    echo Install it with: "%PYTHON_EXE%" -m pip install pyinstaller
    pause
    exit /b 1
)

rem PyInstaller resolves the spec's relative script path against its own
rem directory, so run from build\ and redirect dist/work output back to root.
pushd "%ROOT%build" >nul
"%PYTHON_EXE%" -m PyInstaller "HoloDesk Widget.spec" --noconfirm --distpath "%ROOT%dist" --workpath "%ROOT%build"
set "BUILD_ERROR=%ERRORLEVEL%"
popd

if "%BUILD_ERROR%"=="0" goto BUILD_OK
echo [ERROR] PyInstaller build failed (code %BUILD_ERROR%).
pause
exit /b %BUILD_ERROR%

:BUILD_OK
echo Build complete: "%ROOT%dist\HoloDesk Widget.exe"
exit /b 0

:select_python
if defined PYTHON_EXE exit /b 0
if not exist "%~1" exit /b 0
set "PYTHON_EXE=%~1"
exit /b 0
