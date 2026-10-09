@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul 2>&1
cd /d "%~dp0src"

set "LOG=%TEMP%\gpot-launch.log"
echo [%date% %time%] === G-POT 启动日志 === > "%LOG%"

REM ---------------------------------------------------------------------------
REM 1) 选取 Python 解释器
REM    候选顺序：已知已装 webview 的开发环境 -> py 启动器 -> where python(排除沙箱/store 桩)
REM    优先选用「已经 import webview 成功」的解释器，避免现场装包；都没有再装。
REM ---------------------------------------------------------------------------
set "CANDIDATES=%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\python.exe"
set "CANDIDATES=%CANDIDATES%;%LOCALAPPDATA%\Python\python.exe"
set "CANDIDATES=%CANDIDATES%;%LOCALAPPDATA%\Python\bin\python.exe"
set "CANDIDATES=%CANDIDATES%;py"
set "CANDIDATES=%CANDIDATES%;python"

REM 把 where python 的结果收进来，但跳过 WorkBuddy 托管沙箱与 WindowsApps store 桩
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
set "PYREADY="
for %%P in (%CANDIDATES%) do (
  if not defined PY (
    "%%~P" -c "import webview" >nul 2>&1
    if !errorlevel! == 0 (
      set "PY=%%~P"
      set "PYREADY=1"
      echo [G-POT] 选用解释器(已含 webview): %%~P >> "%LOG%"
    )
  )
)

REM 没有任何解释器自带 webview -> 退而求其次，挑一个有 pip 的来现场装
if not defined PY (
  for %%P in (%CANDIDATES%) do (
    if not defined PY (
      "%%~P" -m pip --version >nul 2>&1
      if !errorlevel! == 0 (
        set "PY=%%~P"
        echo [G-POT] 选用解释器(需安装 webview): %%~P >> "%LOG%"
      )
    )
  )
)

if not defined PY (
  echo [G-POT] 未找到可用的 Python。请先安装 Python 3.11+ 并勾选 "Add to PATH"。
  echo 详细日志: %LOG%
  pause
  exit /b 1
)

if not defined PYREADY (
  echo [G-POT] 正在安装运行依赖 pywebview（首次稍慢，请联网）...
  "%PY%" -m pip install -r requirements.txt >> "%LOG%" 2>&1
  if errorlevel 1 (
    echo [G-POT] 依赖安装失败，常见原因：未联网 / pip 源不可达。
    echo 详细日志: %LOG%
    type "%LOG%"
    pause
    exit /b 1
  )
)

REM ---------------------------------------------------------------------------
REM 2) 启动（直接在窗口显示输出，便于排错；WebView2 缺失时主程序会自动改用浏览器）
REM ---------------------------------------------------------------------------
echo [G-POT] 启动 G-POT 翻译器（WebView2 窗口）...
echo [G-POT] 若约 10 秒内未出现窗口，将自动改用系统浏览器；此黑窗口请勿关闭。
"%PY%" main.py
echo [G-POT] 程序已退出，退出码 %errorlevel%。详细日志: %LOG%
type "%LOG%"
pause
endlocal
