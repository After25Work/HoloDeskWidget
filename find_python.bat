@echo off
rem Shared Python interpreter discovery for start_widget.bat and build_widget.bat.
rem Searches, in order: the per-user 3.10 install, the machine-wide 3.10
rem install, then PATH. Sets PYTHON_EXE on success. Call with "pythonw" as
rem the first argument to additionally require pythonw.exe next to the
rem interpreter (only candidates that have it are accepted) and set
rem PYTHONW_EXE to it.
rem
rem On failure PYTHON_EXE is left undefined, an error is printed, and this
rem script exits /b 1 -- callers should pause/exit themselves so the
rem message stays visible when double-clicked from Explorer.
rem
rem Usage: call find_python.bat [pythonw]

set "PYTHON_EXE="
set "PYTHONW_EXE="
set "_FIND_PYTHON_REQUIRE_PYTHONW=%~1"

call :select_python "%LocalAppData%\Programs\Python\Python310\python.exe"
if defined PYTHON_EXE goto :eof
call :select_python "%ProgramFiles%\Python310\python.exe"
if defined PYTHON_EXE goto :eof
for /f "delims=" %%P in ('where python.exe 2^>nul') do call :select_python "%%P"
if defined PYTHON_EXE goto :eof

echo [ERROR] Python 3.10 or a usable Python installation was not found.
echo Install Python 3.10+ and enable the Python launcher, then try again.
exit /b 1

:select_python
if defined PYTHON_EXE exit /b 0
if not exist "%~1" exit /b 0
if /i "%_FIND_PYTHON_REQUIRE_PYTHONW%"=="pythonw" (
    for %%P in ("%~1") do if not exist "%%~dpPpythonw.exe" exit /b 0
    for %%P in ("%~1") do set "PYTHONW_EXE=%%~dpPpythonw.exe"
)
set "PYTHON_EXE=%~1"
exit /b 0
