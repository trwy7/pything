@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "UV=%SCRIPT_DIR%.venv\Scripts\uv.exe"
set "OUTPUT=%SCRIPT_DIR%dist\pything-windows.exe"
set "BUILD_DIR=%TEMP%\pything-build-%RANDOM%-%RANDOM%"
set "STAGE=%BUILD_DIR%\payload"
set "BUILDER=%BUILD_DIR%\launcher.exe"

if not exist "%UV%" (
    echo Could not find uv at "%UV%" 1>&2
    exit /b 1
)
where gcc >nul 2>nul
if errorlevel 1 (
    echo A GCC C compiler is required to build PYThing. 1>&2
    exit /b 1
)

mkdir "%STAGE%\bin"
if errorlevel 1 goto :failure
if not exist "%SCRIPT_DIR%dist" mkdir "%SCRIPT_DIR%dist"
gcc -O2 -std=c11 "%SCRIPT_DIR%launch.c" -o "%BUILDER%"
if errorlevel 1 goto :failure
copy /y "%UV%" "%STAGE%\bin\uv.exe" >nul
if errorlevel 1 goto :failure
xcopy "%SCRIPT_DIR%src" "%STAGE%\src\" /E /I /Y >nul
if errorlevel 1 goto :failure
for /d /r "%STAGE%\src" %%D in (__pycache__) do if exist "%%D" rmdir /s /q "%%D"
for /d /r "%STAGE%\src" %%D in (cache) do if exist "%%D" rmdir /s /q "%%D"
for /r "%STAGE%\src" %%F in (*.pyc) do if exist "%%F" del /q "%%F"
::copy /y "%SCRIPT_DIR%pyproject.toml" "%STAGE%\pyproject.toml" >nul
::copy /y "%SCRIPT_DIR%uv.lock" "%STAGE%\uv.lock" >nul
::copy /y "%SCRIPT_DIR%README.md" "%STAGE%\README.md" >nul
if exist "%OUTPUT%" del /q "%OUTPUT%"
"%BUILDER%" --pack "%STAGE%" "%OUTPUT%"
if errorlevel 1 goto :failure
rmdir /s /q "%BUILD_DIR%"
echo Built self-extracting Windows binary: %OUTPUT%
endlocal
exit /b 0

:failure
if exist "%BUILD_DIR%" rmdir /s /q "%BUILD_DIR%"
exit /b 1
