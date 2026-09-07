@echo off
setlocal EnableExtensions DisableDelayedExpansion

rem Always resolve files relative to this launcher, not the caller's directory.
set "ROOT=%~dp0"
set "VARIANT=%~1"

if "%VARIANT%"=="holo" (
    set "APP_NAME=HoloDeskWidget"
    set "EXE_NAME=HoloDesk Widget.exe"
) else if "%VARIANT%"=="vt" (
    set "APP_NAME=VTDeskWidget"
    set "EXE_NAME=VTDeskWidget.exe"
) else (
    echo [ERROR] Usage: release_widget.bat holo^|vt
    pause
    exit /b 1
)
set "VARIANT_DIR=%ROOT%variants\%VARIANT%"
set "VERSION_FILE=%VARIANT_DIR%\version.py"
set "USAGE_HTML=%VARIANT_DIR%\docs\Readme.html"
set "USAGE_HTML_EN=%VARIANT_DIR%\docs\Readme.en.html"
set "PRODUCTIONS_DIR=%VARIANT_DIR%\productions"

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

if not exist "%PRODUCTIONS_DIR%" (
    echo [ERROR] Missing productions directory: "%PRODUCTIONS_DIR%"
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

rem Guard against a __version__ line format change (quote style, extra
rem tokens, a pre-release suffix) silently producing a garbled VERSION that
rem would otherwise only surface later as a malformed staging folder/zip name.
echo %VERSION%| findstr /R "^[0-9][0-9]*\.[0-9][0-9]*\.[0-9][0-9]*$" >nul
if errorlevel 1 (
    echo [ERROR] Parsed version "%VERSION%" from "%VERSION_FILE%" doesn't look like x.y.z.
    pause
    exit /b 1
)

echo Building "%EXE_NAME%" (version %VERSION%)...
call "%ROOT%build_widget.bat" %VARIANT%
if errorlevel 1 (
    echo [ERROR] Build failed; aborting release.
    pause
    exit /b 1
)

set "EXE=%ROOT%dist\%EXE_NAME%"
if not exist "%EXE%" (
    echo [ERROR] Expected build output not found: "%EXE%"
    pause
    exit /b 1
)

set "STAGE=%ROOT%release\%APP_NAME%-v%VERSION%"
set "ZIP=%ROOT%release\%APP_NAME%-v%VERSION%.zip"

if exist "%STAGE%" rmdir /s /q "%STAGE%"
if exist "%STAGE%" (
    echo [ERROR] Could not remove stale staging folder: "%STAGE%"
    echo Close any program that has a file open inside it and try again.
    pause
    exit /b 1
)
mkdir "%STAGE%"
if errorlevel 1 (
    echo [ERROR] Failed to create staging folder: "%STAGE%"
    pause
    exit /b 1
)
if exist "%ZIP%" del /q "%ZIP%"

rem Ship only what a user needs at runtime: the exe (which anchors config
rem next to itself, see deskwidget_core/paths.py), this variant's productions
rem manifest/talent lists, and end-user usage guides in Japanese and English
rem (variants/%VARIANT%/docs/Readme*.html, not the dev-facing README.md).
rem settings.json/logs are per-machine runtime state, not release content.
copy /y "%EXE%" "%STAGE%\" >nul
mkdir "%STAGE%\productions"
xcopy /y /i /e /q "%PRODUCTIONS_DIR%" "%STAGE%\productions" >nul
rem Ship this variant's clock_zones.json whenever it has one -- feature-detected
rem rather than hardcoded per variant, so a variant that adds/removes the file
rem doesn't also need a matching edit here (see deskwidget_core/strings.py's
rem _DEFAULT_CLOCK_ZONES for the in-code fallback used when it's absent).
if exist "%VARIANT_DIR%\clock_zones.json" (
    copy /y "%VARIANT_DIR%\clock_zones.json" "%STAGE%\" >nul
)
copy /y "%USAGE_HTML%" "%STAGE%\Readme.html" >nul
copy /y "%USAGE_HTML_EN%" "%STAGE%\Readme.en.html" >nul

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
