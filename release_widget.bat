@echo off
setlocal EnableExtensions DisableDelayedExpansion

rem Always resolve files relative to this launcher, not the caller's directory.
set "ROOT=%~dp0"
set "VERSION_FILE=%ROOT%holowidget\version.py"
set "USAGE_HTML=%ROOT%docs\Readme.html"
set "USAGE_HTML_EN=%ROOT%docs\Readme.en.html"

if not exist "%VERSION_FILE%" (
    echo [ERROR] Missing version file: "%VERSION_FILE%"
    pause
    exit /b 1
)

if not exist "%USAGE_HTML%" (
    echo [ERROR] Missing usage guide: "%USAGE_HTML%"
    pause
    exit /b 1
)

if not exist "%USAGE_HTML_EN%" (
    echo [ERROR] Missing usage guide: "%USAGE_HTML_EN%"
    pause
    exit /b 1
)

rem Extract the quoted value out of __version__ = "x.y.z"
set "VERSION="
for /f "tokens=2 delims==" %%V in ('findstr /R "^__version__" "%VERSION_FILE%"') do set "VERSION_RAW=%%V"
if not defined VERSION_RAW (
    echo [ERROR] Could not find __version__ in "%VERSION_FILE%"
    pause
    exit /b 1
)
set "VERSION_RAW=%VERSION_RAW: =%"
set "VERSION=%VERSION_RAW:"=%"

echo Building "HoloDesk Widget.exe" (version %VERSION%)...
call "%ROOT%build_widget.bat"
if errorlevel 1 (
    echo [ERROR] Build failed; aborting release.
    exit /b 1
)

set "EXE=%ROOT%dist\HoloDesk Widget.exe"
if not exist "%EXE%" (
    echo [ERROR] Expected build output not found: "%EXE%"
    pause
    exit /b 1
)

set "STAGE=%ROOT%release\HoloDeskWidget-v%VERSION%"
set "ZIP=%ROOT%release\HoloDeskWidget-v%VERSION%.zip"

if exist "%STAGE%" rmdir /s /q "%STAGE%"
mkdir "%STAGE%" 2>nul
if exist "%ZIP%" del /q "%ZIP%"

rem Ship only what a user needs at runtime: the exe (which anchors config
rem next to itself, see holowidget/paths.py), the default talent list, and
rem end-user usage guides in Japanese and English (docs/Readme*.html, not
rem the dev-facing README.md). settings.json/logs are per-machine runtime
rem state, not release content.
copy /y "%EXE%" "%STAGE%\" >nul
copy /y "%ROOT%talents.json" "%STAGE%\" >nul
copy /y "%ROOT%docs\Readme.html" "%STAGE%\Readme.html" >nul
copy /y "%ROOT%docs\Readme.en.html" "%STAGE%\Readme.en.html" >nul

powershell -NoProfile -Command ^
    "Compress-Archive -Path '%STAGE%\*' -DestinationPath '%ZIP%' -Force"
if errorlevel 1 (
    echo [ERROR] Failed to create archive: "%ZIP%"
    pause
    exit /b 1
)

rmdir /s /q "%STAGE%"

echo.
echo Release artifact created: "%ZIP%"
exit /b 0
