@echo off
setlocal EnableExtensions

set "ROOT=%~dp0"
cd /d "%ROOT%"

echo ========================================
echo   MMY-ActionFileSync - versioned build
echo ========================================
echo.

set "PYTHON=%ROOT%.venv\Scripts\python.exe"

if not exist "%PYTHON%" (
    echo [1/5] Creating local virtual environment...
    py -3 -m venv "%ROOT%.venv"
    if errorlevel 1 (
        python -m venv "%ROOT%.venv"
    )
    if not exist "%PYTHON%" (
        echo [ERROR] Failed to create .venv. Please install Python 3 and try again.
        pause
        exit /b 1
    )
) else (
    echo [1/5] Using local virtual environment.
)
echo.

echo [2/5] Installing project dependencies...
"%PYTHON%" -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Failed to install project dependencies.
    pause
    exit /b 1
)
echo.

echo [3/5] Checking PyInstaller...
"%PYTHON%" -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo PyInstaller is not installed. Installing...
    "%PYTHON%" -m pip install pyinstaller
    if errorlevel 1 (
        echo [ERROR] Failed to install PyInstaller.
        pause
        exit /b 1
    )
) else (
    echo PyInstaller is already installed.
)
echo.

echo [4/5] Resolving version and build timestamp...
rem 版本号取自 utils/app_info.py 的 APP_VERSION，时间戳精确到秒，
rem 每次构建输出到独立目录 releases\v{版本}_{时间戳}\，旧版本全部保留。
rem 通过临时文件中转，避开 bat 内嵌 python -c 的引号转义问题。
"%PYTHON%" -m utils.build_stamp > "%TEMP%\mmy_build_stamp.txt"
set "STAMP="
set /p STAMP=<"%TEMP%\mmy_build_stamp.txt"
del "%TEMP%\mmy_build_stamp.txt" >nul 2>&1
if not defined STAMP (
    echo [ERROR] Failed to read APP_VERSION from utils\app_info.py.
    pause
    exit /b 1
)
for /f "tokens=1,2" %%A in ("%STAMP%") do (
    set "VER=%%A"
    set "TS=%%B"
)
if not defined VER (
    echo [ERROR] Failed to read APP_VERSION from utils\app_info.py.
    pause
    exit /b 1
)
if not defined TS (
    echo [ERROR] Failed to generate build timestamp.
    pause
    exit /b 1
)

set "RELEASE_NAME=v%VER%_%TS%"
set "RELEASE_DIR=%ROOT%releases\%RELEASE_NAME%"
echo     Version : v%VER%
echo     Release : releases\%RELEASE_NAME%
echo.

echo [5/5] Building executable...
rem 注意：不要给 PyInstaller 传 --specpath "%ROOT%" 之类的尾部反斜杠带引号参数，
rem "path\" 会被 C 运行时解析成转义引号，破坏后续所有参数的引号配对。
"%PYTHON%" -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --onefile ^
    --windowed ^
    --name "MMY-ActionFileSync" ^
    --distpath "%RELEASE_DIR%" ^
    --workpath "%ROOT%build\pyinstaller" ^
    --add-data "assets;assets" ^
    --icon "assets\icon.ico" ^
    main.py

if errorlevel 1 (
    echo.
    echo [ERROR] Build failed.
    pause
    exit /b 1
)

rem 记录构建信息，便于日后辨认每个发布目录对应哪个版本/哪次提交。
set "GIT_HASH=unknown"
for /f "delims=" %%H in ('git rev-parse --short HEAD 2^>nul') do set "GIT_HASH=%%H"

(
    echo app=MMY-ActionFileSync
    echo version=v%VER%
    echo build_time=%TS%
    echo git_commit=%GIT_HASH%
) > "%RELEASE_DIR%\build_info.txt"

echo.
echo ========================================
echo   Build completed.
echo   Output: releases\%RELEASE_NAME%\MMY-ActionFileSync.exe
echo   Old releases are kept in releases\ for rollback.
echo ========================================
pause
