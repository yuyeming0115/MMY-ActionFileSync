@echo off
chcp 65001 >nul
echo ========================================
echo   MMY-ActionFileSync - 打包为单文件 exe
echo ========================================
echo.

:: 检查 pip
pip --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 pip，请先安装 Python 和 pip
    pause
    exit /b 1
)

:: 安装/检查 pyinstaller
echo [1/3] 检查 PyInstaller...
pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo PyInstaller 未安装，正在安装...
    pip install pyinstaller
    if errorlevel 1 (
        echo [错误] PyInstaller 安装失败
        pause
        exit /b 1
    )
) else (
    echo PyInstaller 已安装
)
echo.

:: 安装项目依赖
echo [2/3] 安装项目依赖...
pip install -r requirements.txt
if errorlevel 1 (
    echo [错误] 依赖安装失败
    pause
    exit /b 1
)
echo.

:: 执行打包
echo [3/3] 开始打包...
pyinstaller ^
    --onefile ^
    --windowed ^
    --name "MMY-ActionFileSync" ^
    --add-data "assets;assets" ^
    --icon="assets\icon.ico" ^
    main.py

if errorlevel 1 (
    echo.
    echo [错误] 打包失败
    pause
    exit /b 1
)

echo.
echo ========================================
echo   打包完成！
echo   输出文件: dist\MMY-ActionFileSync.exe
echo ========================================
pause
