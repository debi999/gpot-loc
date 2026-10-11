"""M4 打包脚本 —— 一条命令出 exe（产物落 F 盘，不入库 git）。

用法：
    python tools/build_exe.py            # 打包到 F:\\erogame\\G-POT\\dist
    python tools/build_exe.py --keep     # 打包后保留中间目录（排查用）

纪律（AGENTS.md）：
- 源码只在 I 盘；**产物放 F 盘**；git 只提交 I 盘，产物不入库。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUT = r'F:\erogame\G-POT\dist'
SPEC = os.path.join(ROOT, 'build.spec')


def find_pyinstaller() -> str:
    """找一个**同时**装了 PyInstaller 和 pywebview 的解释器。

    顺序不能反：本机两个环境的组合是分开的 ——
    WorkBuddy 托管 venv 有 PyInstaller 但**没有** pywebview；
    hermes venv 有 pywebview 但（当前）没有 PyInstaller。
    只查 PyInstaller 会挑中前者，打出跑不起来的 exe（webview 动态导入，
    静态分析抓不到）。所以两个都得验。
    """
    cands = [sys.executable,
             r'C:\Users\Administrator\.workbuddy\binaries\python\envs\default\Scripts\python.exe',
             r'C:\Users\Administrator\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe',
             r'C:\Users\Administrator\AppData\Local\Python\python.exe']
    probe = 'import PyInstaller, webview; print(PyInstaller.__version__)'
    for c in cands:
        if not c or not os.path.isfile(c):
            continue
        r = subprocess.run([c, '-c', probe], capture_output=True, text=True)
        if r.returncode == 0:
            print('[build] 用解释器：%s（PyInstaller %s + pywebview ✓）'
                  % (c, r.stdout.strip()))
            return c
        why = '缺 PyInstaller' if 'PyInstaller' in r.stderr else '缺 pywebview'
        print('[build] 跳过 %s（%s）' % (c, why))
    raise SystemExit('[build] 没有同时装了 PyInstaller 与 pywebview 的解释器。\n'
                     '        在某个解释器里执行：pip install pywebview pyinstaller')


def main() -> int:
    args = [a for a in sys.argv[1:]]
    keep = '--keep' in args
    args = [a for a in args if a != '--keep']
    out = args[0] if args else DEFAULT_OUT

    py = find_pyinstaller()
    if os.path.isdir(out):
        stamp = time.strftime('%H%M%S')
        backup = out + '_old_' + stamp
        print('[build] 已存在产物目录，改名备份：%s' % backup)
        shutil.move(out, backup)
    os.makedirs(out, exist_ok=True)

    cmd = [py, '-m', 'PyInstaller', '--noconfirm',
           '--distpath', out,
           '--workpath', os.path.join(out, '_work')]
    cmd.append(SPEC)
    if not keep:
        cmd.append('--clean')
    print('[build] 执行：%s' % ' '.join(cmd))
    r = subprocess.run(cmd, cwd=ROOT)
    if r.returncode != 0:
        print('[build] 打包失败（退出码 %d）' % r.returncode)
        return r.returncode

    exe = os.path.join(out, 'G-POT翻译器', 'G-POT翻译器.exe')
    if os.path.isfile(exe):
        size_mb = os.path.getsize(exe) / 1024.0 / 1024.0
        print('[build] ✅ 产物：%s（%.1f MB）' % (exe, size_mb))
        print('[build]    把整个 “G-POT翻译器” 文件夹拷走即可脱机运行；')
        print('[build]    工具缓存会自动落在该文件夹的 toolcache\\ 里。')
        return 0
    print('[build] ⚠️ 打包结束但没找到 exe：%s' % exe)
    return 1


if __name__ == '__main__':
    sys.exit(main())