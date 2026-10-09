@echo off
setlocal
chcp 65001 >nul 2>&1
cd /d "%~dp0src"

set "LOG=%TEMP%\gpot-launch.log"
echo [%date% %time%] === G-POT 启动日志 === > "%LOG%"

REM 1) 定位 python / py
set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY ( where py >nul 2>nul && set "PY=py" )
if not defined PY (
  echo [G-POT] 未找到 python 或 py 命令。
  echo [G-POT] 请先安装 Python 并勾选 "Add to PATH"，或改用「启动 G-POT 翻译器(浏览器版).bat」。
  echo 日志已写入：%LOG%
  pause
  exit /b 1
)
echo [G-POT] 使用解释器：%PY% >> "%LOG%"

REM 2) 安装 / 校验依赖（输出进日志，不再吞掉报错）
echo [G-POT] 正在安装或校验依赖（首次运行稍慢）...
%PY% -m pip install -r requirements.txt >> "%LOG%" 2>&1
if errorlevel 1 (
  echo [G-POT] 依赖安装失败，详情见日志：%LOG%
  echo [G-POT] 常见原因：未联网 / pip 源不可达。可改用「浏览器版」bat（不依赖 pywebview）。
  type "%LOG%"
  pause
  exit /b 1
)

REM 3) 启动（WebView2 窗口；若系统缺 WebView2 运行时，主程序会自动改用浏览器）
echo [G-POT] 启动 G-POT 翻译器（WebView2 窗口）...
%PY% main.py >> "%LOG%" 2>&1
echo [G-POT] 程序已退出，退出码 %errorlevel%。日志：%LOG%
type "%LOG%"
pause
endlocal
