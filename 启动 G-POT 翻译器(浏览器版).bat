@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul 2>&1
cd /d "%~dp0src"

set "LOG=%TEMP%\gpot-launch.log"
echo [%date% %time%] === G-POT 启动日志(浏览器版) === > "%LOG%"

REM ---------------------------------------------------------------------------
REM 1) 选取 Python 解释器（浏览器版不需要 webview，故不要求自带；排除沙箱/store 桩）
REM ---------------------------------------------------------------------------
set "CANDIDATES=%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\python.exe"
set "CANDIDATES=%CANDIDATES%;%LOCALAPPDATA%\Python\python.exe"
set "CANDIDATES=%CANDIDATES%;%LOCALAPPDATA%\Python\bin\python.exe"
set "CANDIDATES=%CANDIDATES%;py"
set "CANDIDATES=%CANDIDATES%;python"

for /f "usebackq delims=" %%i in (`where python 2^>nul`) do (
  set "p=%%i"
  if not "!p:workbuddy=!"=="!p!" (
    echo [skip] 跳过 WorkBuddy 沙箱 python: %%i >> "%LOG%"
  ) else if not "!p:WindowsApps=!"=="!p!" (
    echo [skip] 跳过 WindowsApps store 桩: %%i >> "%LOG%"
  ) else (
    set "CANDIDATES=!CANDIDATES!;%%i"
  )
)

set "PY="
for %%P in (%CANDIDATES%) do (
  if not defined PY (
    "%%~P" -c "import sys; sys.exit(0)" >nul 2>&1
    if !errorlevel! == 0 (
      set "PY=%%~P"
      echo [G-POT] 选用解释器: %%~P >> "%LOG%"
    )
  )
)

if not defined PY (
  echo [G-POT] 未找到可用的 Python。请先安装 Python 3.11+ 并勾选 "Add to PATH"。
  echo 详细日志: %LOG%
  pause
  exit /b 1
)

REM ---------------------------------------------------------------------------
REM 2) 启动（--open-browser：仅本地服务 + 系统浏览器，不依赖 WebView2 / pywebview）
REM ---------------------------------------------------------------------------
echo [G-POT] 启动 G-POT 翻译器（系统浏览器模式）...
echo [G-POT] 将自动打开默认浏览器；此黑窗口请勿关闭。
"%PY%" main.py --open-browser
echo [G-POT] 程序已退出，退出码 %errorlevel%。详细日志: %LOG%
type "%LOG%"
pause
endlocal
