# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置 —— G-POT 翻译器 v0.6.0（M4）。

产物落 F 盘（``F:\\erogame\\G-POT\\dist\\``），**不入库 git**（AGENTS 纪律：
产物放产物盘，git 只提交 I 盘源码）。

打包要点（每条都是踩过的坑，别删）：
- ``console=False``：无边框 GUI，不能有控制台窗口。
- ``--noconsole`` 等价，但 main.py 自己还会做一次无窗重启（见 main.py 顶部），
  打包后 sys.stdout 为 None，那段会写 %TEMP%\\gpot-run.log —— 保留这个行为。
- ``upx=False``：UPX 打包 pywebview/WebView2 相关 .pyd 容易崩，一律关掉。
- ``icon=assets/icon.ico``：单真源由 tools/gen_logo.py 生成。
- webview 走运行时后端（edgechromium），但 winforms / cef / gtk 后端也要带上，
  否则 fallback 分支 import 就崩。
"""
import os
import sys

# spec 文件所在目录就是仓库根（PyInstaller 执行 spec 时 SPECPATH 指向它）
SPEC_DIR = globals().get('SPECPATH') or os.path.dirname(os.path.abspath(__file__)) or os.getcwd()
ROOT = SPEC_DIR
SRC = os.path.join(ROOT, 'src')
ASSETS = os.path.join(SRC, 'gpot', 'ui', 'assets')
ICON = os.path.join(ASSETS, 'icon.ico')

# PyInstaller 的 Analysis 不吃 collect 参数，但可以通过 datas 显式把整个包目录塞进去。
# webview 各后端是**动态导入**（按 gui= 名字挑），静态分析抓不到 —— 历史上
# 打包出的 exe 一运行就 ModuleNotFoundError: webview。这里直接把整个包目录
# 当数据文件打进去，最省事也最稳（多几 MB，换来不会炸）。
datas = []

_webview_dir = None
for _cand in (SRC, sys.prefix):
    _p = os.path.join(_cand, 'webview')
    if os.path.isdir(_p):
        _webview_dir = _p
        break
if _webview_dir is None:
    for _base in sys.path:
        _p = os.path.join(_base, 'webview')
        if os.path.isdir(_p):
            _webview_dir = _p
            break
if _webview_dir:
    datas.append((_webview_dir, 'webview'))
    print('[spec] 已收集 webview：%s' % _webview_dir)
else:
    raise SystemExit('[spec] 找不到 webview 包目录 —— 打包必然产出跑不起来的 exe，'
                     '请先在当前解释器里 pip install pywebview')

# clr_loader / pythonnet：winforms 与 edgechromium 后端要用
for _extra in ('clr_loader', 'pythonnet'):
    for _base in sys.path:
        _p = os.path.join(_base, _extra)
        if os.path.isdir(_p):
            datas.append((_p, _extra))
            break

# 静态前端资源必须原样带进包里（index.html/app.js/styles.css/icon.ico）
# FR-83：含 fonts/ 子目录（ZCOOL KuaiLe woff2）——这里是整目录递归拷贝，
# 子目录自动带上；但若日后改成逐文件列举，**务必别漏 fonts/**，
# 漏了字体在打包版里会静默失效（中文掉回雅黑，且界面不报错）。
datas.append((ASSETS, 'gpot/ui/assets'))
# main.py 里 `from ..core import ...` 是相对导入，必须声明 package 以保留层级
hiddenimports = [
    'webview',
    'webview.platforms.winforms',
    'webview.platforms.edgechromium',
    'gpot.core.winframe',
]

block_cipher = None

a = Analysis(
    [os.path.join(SRC, 'main.py')],
    pathex=[SRC],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 明确排除重家伙伴：打包慢、体积大、运行用不到
        'tkinter', 'matplotlib', 'numpy', 'pandas', 'PIL',
        'playwright', 'pytest', 'IPython',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='G-POT翻译器',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # 坑：UPX 压 pywebview 的 .pyd 会崩
    console=False,      # GUI 程序，不能有控制台
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON if os.path.isfile(ICON) else None,
    version=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='G-POT翻译器',
)