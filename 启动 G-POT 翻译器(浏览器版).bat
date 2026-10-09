@echo off
setlocal
chcp 65001 >nul 2>&1
cd /d "%~dp0src"

set "LOG=%TEMP%\gpot-launch.log"
echo [%date% %time%] === G-POT 启动日志 === > "%LOG%"

set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY ( where py >nul 2>nul && set "PY=py" )
if not defined PY (
  echo [G-POT] 未找到 python 或 py 命令，请安装 Python 并勾选 "Add to PATH"。
  echo 日志已写入：%LOG%
  pause
  exit /b 1
)
echo [G-POT] 使用解释器：%PY% >> "%LOG%"

echo [G-POT] 正在安装或校验依赖（首次运行稍慢）...
%PY% -m pip install -r requirements.txt >> "%LOG%" 2>&1
if errorlevel 1 (
  echo [G-POT] 依赖安装失败，详情见日志：%LOG%
  type "%LOG%"
  pause
  exit /b 1
)

echo [G-POT] 启动本地服务并用系统浏览器打开界面...
%PY% main.py --open-browser >> "%LOG%" 2>&1
echo [G-POT] 程序已退出，退出码 %errorlevel%。日志：%LOG%
type "%LOG%"
pause
endlocal
