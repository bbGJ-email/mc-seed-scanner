@echo off
REM ============================================================
REM  MC Java Seed Scanner - Windows one-click build & package
REM  Requirements: Python 3.9+ in PATH (MinGW-w64 is auto-detected
REM  from PATH or from .\tools\mingw64, otherwise auto-downloaded)
REM  Usage: double-click or run build_windows.bat in project root
REM ============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

REM ---------- 0. python ----------
where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] python not found in PATH.
    echo         Install Python 3.9+ from https://www.python.org/downloads/
    echo         and tick "Add python.exe to PATH" during setup.
    pause
    exit /b 1
)

REM ---------- 1. locate gcc (by absolute path, no PATH dependency) ----------
set "TOOLS_DIR=%~dp0tools"
set "GCC_BIN="
where gcc >nul 2>nul && set "GCC_BIN=gcc"
if not defined GCC_BIN if exist "%TOOLS_DIR%\mingw64\bin\gcc.exe" set "GCC_BIN=%TOOLS_DIR%\mingw64\bin\gcc.exe"
if not defined GCC_BIN if exist "%TOOLS_DIR%\gcc.exe" set "GCC_BIN=%TOOLS_DIR%\gcc.exe"

if not defined GCC_BIN (
    echo [INFO] gcc not found. Downloading portable MinGW-w64 ^(WinLibs 16.2.0, POSIX threads, ~300MB^)...
    if not exist "%TOOLS_DIR%" mkdir "%TOOLS_DIR%"
    set "WL_URL=https://github.com/brechtsanders/winlibs_mingw/releases/download/16.2.0posix-14.0.0-ucrt-r1/winlibs-x86_64-posix-seh-gcc-16.2.0-mingw-w64ucrt-14.0.0-r1.zip"
    set "WL_ZIP=%TOOLS_DIR%\winlibs.zip"
    echo [1/5] Downloading toolchain ...
    curl.exe -L --retry 3 --connect-timeout 30 -o "!WL_ZIP!" "!WL_URL!"
    if errorlevel 1 (
        echo [WARN] curl failed, trying PowerShell fallback ...
        powershell -NoProfile -Command "Invoke-WebRequest -Uri '!WL_URL!' -OutFile '!WL_ZIP!' -UseBasicParsing"
        if errorlevel 1 goto :dlfail
    )
    if not exist "!WL_ZIP!" goto :dlfail
    echo [2/5] Extracting toolchain ...
    powershell -NoProfile -Command "Expand-Archive -Path '!WL_ZIP!' -DestinationPath '!TOOLS_DIR!' -Force"
    if errorlevel 1 goto :dlfail
    if exist "%TOOLS_DIR%\mingw64\bin\gcc.exe" set "GCC_BIN=%TOOLS_DIR%\mingw64\bin\gcc.exe"
)
if not defined GCC_BIN goto :dlfail

REM ---- gcc / ar full paths ----
if "%GCC_BIN%"=="gcc" (
    echo [OK] Using gcc from system PATH.
    set "GCC=gcc"
    set "AR=ar"
) else (
    echo [OK] Using gcc: %GCC_BIN%
    for %%i in ("%GCC_BIN%") do set "GCC_DIR=%%~dpi"
    set "GCC=%GCC_BIN%"
    if exist "%GCC_DIR%ar.exe" ( set "AR=%GCC_DIR%ar.exe" ) else ( set "AR=ar" )
    REM also expose the folder to this session PATH as a bonus
    set "PATH=!GCC_DIR!%PATH%"
)
if not exist "%GCC%" (
    echo [ERROR] gcc not callable: %GCC%
    pause
    exit /b 1
)

echo [3/5] Building C core (cubiomes + scanner_core.dll) ...
cd csrc
if not exist cubiomes\libcubiomes.a (
    echo    -- building cubiomes static library ...
    cd cubiomes
    "%GCC%" -c -O3 -fPIC -D_WIN32 -o noise.o noise.c || goto :err
    "%GCC%" -c -O3 -fPIC -D_WIN32 -o biomes.o biomes.c || goto :err
    "%GCC%" -c -O3 -fPIC -D_WIN32 -o layers.o layers.c || goto :err
    "%GCC%" -c -O3 -fPIC -D_WIN32 -o biomenoise.o biomenoise.c || goto :err
    "%GCC%" -c -O3 -fPIC -D_WIN32 -o generator.o generator.c || goto :err
    "%GCC%" -c -O3 -fPIC -D_WIN32 -o finders.o finders.c || goto :err
    "%GCC%" -c -O3 -fPIC -D_WIN32 -o util.o util.c || goto :err
    "%GCC%" -c -O3 -fPIC -D_WIN32 -o quadbase.o quadbase.c || goto :err
    "%AR%" cr libcubiomes.a *.o
    cd ..
)
echo    -- building scanner_core.dll ...
"%GCC%" -O3 -fPIC -shared -o scanner_core.dll scanner_core.c cubiomes\libcubiomes.a -lm -lpthread || goto :err
cd ..

echo [4/5] Installing Python dependencies ...
python -m pip install -r requirements.txt || goto :err

echo [5/5] Running core self-check ...
python -c "from mcss import core_binding; print('core_binding OK:', core_binding._lib._name)" || goto :err

echo Packaging single-file EXE with PyInstaller ...
python -m PyInstaller --noconfirm --clean --onefile --windowed ^
    --name "MCSeedScanner" ^
    --add-binary "csrc\scanner_core.dll;csrc" ^
    --add-data "csrc\cubiomes;csrc\cubiomes" ^
    main.py || goto :err

echo.
echo ============================================================
echo  Build finished: dist\MCSeedScanner.exe
echo  (data folder is auto-created next to the exe on first run)
echo ============================================================
pause
exit /b 0

:dlfail
echo.
echo [DOWNLOAD FAILED] Could not find or download MinGW-w64 gcc.
echo   - If you already downloaded it manually, make sure the path is:
echo       .\tools\mingw64\bin\gcc.exe
echo   - Or download the zip, extract it so that the above path exists,
echo     then re-run this script.
echo   - Direct link:
echo     https://github.com/brechtsanders/winlibs_mingw/releases/download/16.2.0posix-14.0.0-ucrt-r1/winlibs-x86_64-posix-seh-gcc-16.2.0-mingw-w64ucrt-14.0.0-r1.zip
pause
exit /b 1

:err
echo.
echo [BUILD FAILED] See error above. Common causes:
echo   - antivirus blocking pip / PyInstaller / gcc
echo   - Python not in PATH (use py -m instead of python)
echo   - missing runtime DLLs for the toolchain
pause
exit /b 1
