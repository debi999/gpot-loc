@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0src"
echo [G-POT] 正在检查依赖（首次运行会安装 pywebview，稍慢）...
python -m pip install -r requirements.txt -q 2>nul
if errorlevel 1 (
  echo [G-POT] 依赖安装失败：请确认 python 已加入 PATH，或改用「启动 G-POT 翻译器(浏览器版).bat」。
  pause
  exit /b 1
)
echo [G-POT] 启动 G-POT 翻译器（WebView2 原生窗口）...
python main.py
echo.
echo 若窗口空白或报错，多半是系统缺少 WebView2 运行时，请改用「浏览器版」bat。
pause
