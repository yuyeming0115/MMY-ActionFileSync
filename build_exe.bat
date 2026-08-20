@echo off
setlocal

set "ROOT=%~dp0"
cd /d "%ROOT%"

echo ========================================
echo   MMY-ActionFileSync - build onefile exe
echo ========================================
echo.

set "PYTHON=%ROOT%.venv\Scripts\python.exe"

if not exist "%PYTHON%" (
    echo [1/4] Creating local virtual environment...
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
    echo [1/4] Using local virtual environment.
)
echo.

echo [2/4] Installing project dependencies...
"%PYTHON%" -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Failed to install project dependencies.
    pause
    exit /b 1
)
echo.

echo [3/4] Checking PyInstaller...
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

echo [4/4] Building executable...
"%PYTHON%" -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --onefile ^
    --windowed ^
    --name "MMY-ActionFileSync" ^
    --add-data "assets;assets" ^
    --icon "assets\icon.ico" ^
    main.py

if errorlevel 1 (
    echo.
    echo [ERROR] Build failed.
    pause
    exit /b 1
)

echo.
echo ========================================
echo   Build completed.
echo   Output: dist\MMY-ActionFileSync.exe
echo ========================================
pause
