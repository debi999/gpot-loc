@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0src"
echo [G-POT] 正在检查依赖...
python -m pip install -r requirements.txt -q 2>nul
echo [G-POT] 启动本地服务并打开系统浏览器...
python main.py --open-browser
echo.
echo 关闭浏览器后，回到此处按 Ctrl+C 停止服务。
pause
