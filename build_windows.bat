@echo off
REM ============================================================
REM  MC Java Seed Scanner - Windows one-click build & package
REM  Requirements: Python 3.9+ in PATH (internet needed once to
REM  download a portable MinGW-w64 toolchain into .\tools)
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

REM ---------- 1. locate gcc ----------
REM priority: system PATH gcc  ->  .\tools\mingw64\bin\gcc.exe (downloaded before)
set "TOOLS_DIR=%~dp0tools"
set "MINGW_BIN="
where gcc >nul 2>nul && set "MINGW_BIN=gcc"
if not defined MINGW_BIN if exist "%TOOLS_DIR%\mingw64\bin\gcc.exe" set "MINGW_BIN=%TOOLS_DIR%\mingw64\bin\gcc.exe"

if not defined MINGW_BIN (
    echo [INFO] gcc not found. Downloading portable MinGW-w64 ^(WinLibs 16.2.0, POSIX threads, ~300MB^)...
    echo        URL: https://github.com/brechtsanders/winlibs_mingw/releases
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
    if not exist "%TOOLS_DIR%\mingw64\bin\gcc.exe" goto :dlfail

    set "MINGW_BIN=%TOOLS_DIR%\mingw64\bin\gcc.exe"
    echo [OK] MinGW-w64 ready: !MINGW_BIN!
)

REM add its folder to this session PATH if not a plain PATH entry
if not "%MINGW_BIN%"=="gcc" (
    for %%i in ("%MINGW_BIN%") do set "MINGW_BIN_DIR=%%~dpi"
    set "PATH=!MINGW_BIN_DIR!%PATH%"
)
where gcc >nul 2>nul
if errorlevel 1 (
    echo [ERROR] gcc still not callable. Check .\tools folder and PATH.
    pause
    exit /b 1
)

echo [3/5] Building C core (cubiomes + scanner_core.dll) ...
cd csrc
if not exist cubiomes\libcubiomes.a (
    echo    -- building cubiomes static library ...
    cd cubiomes
    gcc -c -O3 -fPIC -D_WIN32 -o noise.o noise.c || goto :err
    gcc -c -O3 -fPIC -D_WIN32 -o biomes.o biomes.c || goto :err
    gcc -c -O3 -fPIC -D_WIN32 -o layers.o layers.c || goto :err
    gcc -c -O3 -fPIC -D_WIN32 -o biomenoise.o biomenoise.c || goto :err
    gcc -c -O3 -fPIC -D_WIN32 -o generator.o generator.c || goto :err
    gcc -c -O3 -fPIC -D_WIN32 -o finders.o finders.c || goto :err
    gcc -c -O3 -fPIC -D_WIN32 -o util.o util.c || goto :err
    gcc -c -O3 -fPIC -D_WIN32 -o quadbase.o quadbase.c || goto :err
    ar cr libcubiomes.a *.o
    cd ..
)
echo    -- building scanner_core.dll ...
gcc -O3 -fPIC -shared -o scanner_core.dll scanner_core.c cubiomes\libcubiomes.a -lm -lpthread || goto :err
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
echo [DOWNLOAD FAILED] Could not download MinGW-w64.
echo   - Check your internet connection (GitHub may need a proxy).
echo   - Or download the zip manually, extract so that you have:
echo       .\tools\mingw64\bin\gcc.exe
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
