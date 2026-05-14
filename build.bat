@echo off
chcp 65001 >nul
echo ========================================
echo   图片识别自动点击器 - 打包脚本
echo ========================================
echo.

:: 检查 PyInstaller
pip show pyinstaller >nul 2>&1
if %errorlevel% neq 0 (
    echo 正在安装 PyInstaller...
    pip install pyinstaller
)

:: 清理旧的打包文件
if exist "dist" rmdir /s /q dist
if exist "build" rmdir /s /q build
if exist "PictureRecognition.spec" del /q PictureRecognition.spec

echo.
echo 开始打包...
echo.

python -m PyInstaller --noconfirm ^
    --name "PictureRecognition" ^
    --windowed ^
    --add-data "templates;templates" ^
    --add-data "scripts;scripts" ^
    --add-data "resources;resources" ^
    main.py

echo.
if exist "dist\PictureRecognition\PictureRecognition.exe" (
    echo ========================================
    echo   打包成功！
    echo   输出目录: dist\PictureRecognition\
    echo   可执行文件: PictureRecognition.exe
    echo ========================================
) else (
    echo ========================================
    echo   打包失败，请检查错误信息
    echo ========================================
)

:: 清理中间文件
if exist "build" rmdir /s /q build
if exist "PictureRecognition.spec" del /q PictureRecognition.spec

pause
