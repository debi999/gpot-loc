#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
独游翻译器 · 注入工具包清单 (Kit Catalog)
================================================================
把 `engine_detector.py` 能识别的**全部 15 类引擎**映射到各自的「翻译注入方案」：

  ① 要下载什么工具包（injector / unpacker）
  ② 下载来的东西往游戏目录的哪里放（部署规则）
  ③ 译文最终落在哪个文件、用什么格式（sink）

设计要点
--------
* **零第三方依赖**，纯标准库 —— 与 GUI 其它共享模块一致的约束。
* **清单是数据，不是逻辑**：所有 URL / 哈希 / 路径模板都是常量表，便于测试
  与人工核对（老板可以直接看这里改版本号）。
* **`verified` 字段说实话**：True = 本机真的下载过、确认过包结构与 sha256；
  False = 只查过 GitHub API 存在性与体积，**没实际验证过**。不要装成都用过了。
* **没有可靠包的引擎不编 URL**：`tools=[]` + `reason=...` 说明为什么，
  宁可留白也不要塞一个假链接。

数据来源（2026-10-08 逐项联网核实）
----------------------------------
| 工具 | 仓库 | 验证情况 |
|---|---|---|
| BepInEx 5.4.23.5 win_x64 | BepInEx/BepInEx | ✅ 已下载并算 sha256，确认包结构 |
| XUnity.AutoTranslator 5.6.2 (BepInEx) | bbepis/XUnity.AutoTranslator | ✅ 同上 |
| XUnity.ResourceRedirector 2.1.0 | bbepis/XUnity.AutoTranslator | ✅ 同上 |
| BepInEx 6 IL2CPP win_x64 6.0.0-pre.2 | BepInEx/BepInEx | ⚠️ 仅查 API（34MB，未实拉） |
| XUnity IL2CPP 5.6.2 | bbepis/XUnity.AutoTranslator | ⚠️ 仅查 API（结构与 Mono 版同构） |
| KirikiriTools 1.7 (version.dll) | arcusmaximus/KirikiriTools | ⚠️ 仅查 API；单文件，非 zip |
| WolfDec 0.3.3 | Sinflower/WolfDec | ⚠️ 仅查 API；单文件 exe |
| GDRE_tools 2.7.0 windows | GDRETools/gdsdecomp | ⚠️ 仅查 API（42MB） |
| UndertaleModTool 0.9.2.0 | UnderminersTeam/UndertaleModTool | ⚠️ 仅查 API（93MB） |
| FFDec nightly3577 | jindrapetrik/jpexs-decompiler | ⚠️ 仅查 API（20MB，nightly 无稳定 tag） |

用法:
    python kit_catalog.py                      # 列出全部引擎的方案
    python kit_catalog.py Unity                # 看某一引擎
    python kit_catalog.py --json               # 结构化输出
"""

import os
import sys

# --- UTF-8 输出引导 ---------------------------------------------------------
# 详见 engine_detector.py 同款注释：CI 默认 cp1252，中文 print 会崩。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# ----------------------------------------------------------------------------
# 工具包种类
# ----------------------------------------------------------------------------
KIND_INJECTOR = 'injector'   # 运行时注入插件 → 部署到游戏目录，启动游戏即生效
KIND_UNPACKER = 'unpacker'   # 解包/资源工具 → 放本地工具目录，供提取文本用
KIND_NATIVE = 'native'       # 引擎原生多语言机制 → 无需任何外部工具

KIND_LABEL = {
    KIND_INJECTOR: '注入插件',
    KIND_UNPACKER: '解包工具',
    KIND_NATIVE: '原生机制',
}

# ----------------------------------------------------------------------------
# 打包 / 部署规则
# ----------------------------------------------------------------------------
# dest:
#   'game_root'   解压/复制到游戏根目录（绝大多数情况：包内就是 BepInEx/）
#   'tool_dir'    放本地工具目录，不进游戏目录（解包类工具）
#   'game_file'   单文件，按 target 指定的相对路径放进游戏目录
#
# strip_root:
#   0 / None    包内路径直接相对目标根（已验证的三个 BepInEx 系包都是这种）
#   1           包内有一层版本目录，需要剥掉
#
# on_conflict:
#   'skip'      目标已存在就跳过（**默认**，保护老板现有的已调好配置）
#   'overwrite' 覆盖
# ----------------------------------------------------------------------------

PACKS = {
    # ---------------- Unity Mono ----------------
    'bepinex5-win-x64': {
        'id': 'bepinex5-win-x64',
        'title': 'BepInEx 5.4.23.5 (Windows x64)',
        'kind': KIND_INJECTOR,
        'url': ('https://github.com/BepInEx/BepInEx/releases/download/'
                'v5.4.23.5/BepInEx_win_x64_5.4.23.5.zip'),
        'filename': 'BepInEx_win_x64_5.4.23.5.zip',
        'size': 639118,
        'sha256': '82f9878551030f54657792c0740d9d51a09500eeae1fba21106b0c441e6732c4',
        'dest': 'game_root',
        'strip_root': 0,
        'on_conflict': 'skip',
        'home': 'https://github.com/BepInEx/BepInEx',
        'verified': True,
        'marker': 'BepInEx/core/BepInEx.Preloader.dll',
        'desc': 'Unity Mono 插件加载器。解压到游戏根目录即可，游戏启动时自动挂插件。',
    },
    'xunity-autotranslator-bepinex': {
        'id': 'xunity-autotranslator-bepinex',
        'title': 'XUnity.AutoTranslator 5.6.2 (BepInEx/Mono)',
        'kind': KIND_INJECTOR,
        'url': ('https://github.com/bbepis/XUnity.AutoTranslator/releases/download/'
                'v5.6.2/XUnity.AutoTranslator-BepInEx-5.6.2.zip'),
        'filename': 'XUnity.AutoTranslator-BepInEx-5.6.2.zip',
        'size': 758678,
        'sha256': '836a4066b9369b0d23dc1b0ef6336ad7fe7ae16880931259ec4d157aff7a81c0',
        'dest': 'game_root',
        'strip_root': 0,
        'on_conflict': 'skip',
        'home': 'https://github.com/bbepis/XUnity.AutoTranslator',
        'verified': True,
        'marker': 'BepInEx/plugins/XUnity.AutoTranslator/XUnity.AutoTranslator.Plugin.BepInEx.dll',
        'desc': '游戏内文本实时翻译注入器（本项目主用方案）。',
    },
    'xunity-redirector-bepinex': {
        'id': 'xunity-redirector-bepinex',
        'title': 'XUnity.ResourceRedirector 2.1.0 (BepInEx/Mono)',
        'kind': KIND_INJECTOR,
        'url': ('https://github.com/bbepis/XUnity.AutoTranslator/releases/download/'
                'v5.6.2/XUnity.ResourceRedirector-BepInEx-2.1.0.zip'),
        'filename': 'XUnity.ResourceRedirector-BepInEx-2.1.0.zip',
        'size': 98672,
        'sha256': '93c86ffc1d6d849b9964732a2c44594689990515d02cb2a78bd6aaa4cec0bf0e',
        'dest': 'game_root',
        'strip_root': 0,
        'on_conflict': 'skip',
        'home': 'https://github.com/bbepis/XUnity.AutoTranslator',
        'verified': True,
        'marker': 'BepInEx/plugins/XUnity.ResourceRedirector/XUnity.ResourceRedirector.dll',
        'optional': True,
        'desc': '资源重定向（换字体 / 换贴图）。Starmaker 用它挂中文字体，别的游戏按需。',
    },

    # ---------------- Unity IL2CPP ----------------
    'bepinex6-il2cpp-win-x64': {
        'id': 'bepinex6-il2cpp-win-x64',
        'title': 'BepInEx 6.0.0-pre.2 (Unity IL2CPP, Windows x64)',
        'kind': KIND_INJECTOR,
        'url': ('https://github.com/BepInEx/BepInEx/releases/download/'
                'v6.0.0-pre.2/BepInEx-Unity.IL2CPP-win-x64-6.0.0-pre.2.zip'),
        'filename': 'BepInEx-Unity.IL2CPP-win-x64-6.0.0-pre.2.zip',
        'size': 34146254,
        'sha256': None,          # 未实拉，暂不能校验内容；仅比对体积
        'dest': 'game_root',
        'strip_root': 0,
        'on_conflict': 'skip',
        'home': 'https://github.com/BepInEx/BepInEx',
        'verified': False,
        'marker': 'BepInEx/core/BepInEx.dll',
        'desc': 'IL2CPP 专用 BepInEx（pre-release）。34MB，首次安装要等一会儿。',
    },
    'xunity-autotranslator-il2cpp': {
        'id': 'xunity-autotranslator-il2cpp',
        'title': 'XUnity.AutoTranslator 5.6.2 (BepInEx/IL2CPP)',
        'kind': KIND_INJECTOR,
        'url': ('https://github.com/bbepis/XUnity.AutoTranslator/releases/download/'
                'v5.6.2/XUnity.AutoTranslator-BepInEx-IL2CPP-5.6.2.zip'),
        'filename': 'XUnity.AutoTranslator-BepInEx-IL2CPP-5.6.2.zip',
        'size': 761721,
        'sha256': None,
        'dest': 'game_root',
        'strip_root': 0,
        'on_conflict': 'skip',
        'home': 'https://github.com/bbepis/XUnity.AutoTranslator',
        'verified': False,
        'marker': 'BepInEx/plugins/XUnity.AutoTranslator/XUnity.AutoTranslator.Plugin.BepInEx.dll',
        'desc': 'IL2CPP 版 XUnity。包结构与 Mono 版同构（未本机实拉验证）。',
    },

    # ---------------- Kirikiri（吉里吉里）----------------
    'kirikiri-hook': {
        'id': 'kirikiri-hook',
        'title': 'KirikiriTools version.dll (1.7)',
        'kind': KIND_INJECTOR,
        'url': ('https://github.com/arcusmaximus/KirikiriTools/releases/download/'
                '1.7/version.dll'),
        'filename': 'version.dll',
        'size': 94208,
        'sha256': None,
        'dest': 'game_file',
        'target': 'version.dll',
        'on_conflict': 'skip',
        'home': 'https://github.com/arcusmaximus/KirikiriTools',
        'verified': False,
        'desc': '通用 Kirikiri hook。丢进游戏根目录，游戏启动即加载本地 patch。',
    },
    'kirikiri-descrambler': {
        'id': 'kirikiri-descrambler',
        'title': 'KirikiriDescrambler 1.7',
        'kind': KIND_UNPACKER,
        'url': ('https://github.com/arcusmaximus/KirikiriTools/releases/download/'
                '1.7/KirikiriDescrambler.exe'),
        'filename': 'KirikiriDescrambler.exe',
        'size': 9728,
        'sha256': None,
        'dest': 'tool_dir',
        'on_conflict': 'skip',
        'home': 'https://github.com/arcusmaximus/KirikiriTools',
        'verified': False,
        'optional': True,
        'desc': '解开加扰的 .xp3 / 脚本文件，取文本用。',
    },
    'kirikiri-xp3pack': {
        'id': 'kirikiri-xp3pack',
        'title': 'Xp3Pack 1.7',
        'kind': KIND_UNPACKER,
        'url': ('https://github.com/arcusmaximus/KirikiriTools/releases/download/'
                '1.7/Xp3Pack.exe'),
        'filename': 'Xp3Pack.exe',
        'size': 9216,
        'sha256': None,
        'dest': 'tool_dir',
        'on_conflict': 'skip',
        'home': 'https://github.com/arcusmaximus/KirikiriTools',
        'verified': False,
        'optional': True,
        'desc': '把改好的文本重新打包成 .xp3。',
    },

    # ---------------- Wolf RPG ----------------
    'wolfdec': {
        'id': 'wolfdec',
        'title': 'WolfDec 0.3.3',
        'kind': KIND_UNPACKER,
        'url': 'https://github.com/Sinflower/WolfDec/releases/download/v0.3.3/WolfDec.exe',
        'filename': 'WolfDec.exe',
        'size': 263680,
        'sha256': None,
        'dest': 'tool_dir',
        'on_conflict': 'skip',
        'home': 'https://github.com/Sinflower/WolfDec',
        'verified': False,
        'desc': '解 .wolf / .data 的游戏数据，提取可翻译字符串。',
    },

    # ---------------- Godot ----------------
    'gdre-tools': {
        'id': 'gdre-tools',
        'title': 'GDRE_tools 2.7.0 (Windows)',
        'kind': KIND_UNPACKER,
        'url': ('https://github.com/GDRETools/gdsdecomp/releases/download/'
                'v2.7.0/GDRE_tools-v2.7.0-windows.zip'),
        'filename': 'GDRE_tools-v2.7.0-windows.zip',
        'size': 42619156,
        'sha256': None,
        'dest': 'tool_dir',
        'strip_root': 1,        # 发布包惯例：顶层 GDRE_tools-*/ 一层壳
        'on_conflict': 'skip',
        'home': 'https://github.com/GDRETools/gdsdecomp',
        'verified': False,
        'desc': '解 .pck，还原工程结构与 csv/po 文本。42MB。',
    },

    # ---------------- GameMaker ----------------
    'undertalemodtool': {
        'id': 'undertalemodtool',
        'title': 'UndertaleModTool 0.9.2.0 (Windows SingleFile)',
        'kind': KIND_UNPACKER,
        'url': ('https://github.com/UnderminersTeam/UndertaleModTool/releases/download/'
                '0.9.2.0/UndertaleModTool_v0.9.2.0-Windows-SingleFile.zip'),
        'filename': 'UndertaleModTool_v0.9.2.0-Windows-SingleFile.zip',
        'size': 93182580,
        'sha256': None,
        'dest': 'tool_dir',
        'strip_root': 1,
        'on_conflict': 'skip',
        'home': 'https://github.com/UnderminersTeam/UndertaleModTool',
        'verified': False,
        'desc': '解包 data.win 提取字符串并回写。93MB，重。',
    },

    # ---------------- Flash ----------------
    'ffdec': {
        'id': 'ffdec',
        'title': 'FFDec (JPEXS Free Flash Decompiler)',
        'kind': KIND_UNPACKER,
        'url': ('https://github.com/jindrapetrik/jpexs-decompiler/releases/download/'
                'nightly3577/ffdec_26.3.0_nightly3577.zip'),
        'filename': 'ffdec_26.3.0_nightly3577.zip',
        'size': 20163719,
        'sha256': None,
        'dest': 'tool_dir',
        'strip_root': 1,
        'on_conflict': 'skip',
        'home': 'https://github.com/jindrapetrik/jpexs-decompiler',
        'verified': False,
        'desc': '反编译 swf 取文本/换字体。⚠️ 上游只发 nightly，没有稳定 release tag。',
    },
}

# ----------------------------------------------------------------------------
# 译文落点（sink）——「翻译完往哪儿存」的答案
# ----------------------------------------------------------------------------
# fmt:
#   'kv'      原文=译文，一行一条（XUnity.AutoTranslator）
#   'rpy'     Ren'Py translate 块
#   'builtin' 不写单边文件，委托项目已有引擎模块回写原始数据
#   'manual'  格式/流程依赖具体游戏，本工具只给出目标目录，不自动写（诚实标注）
#
# file_tpl / dir_tpl 里的 {lang} 用 set_language 传入的值替换。
# ----------------------------------------------------------------------------

SINKS = {
    'xunity_auto': {
        'fmt': 'kv',
        'file_tpl': 'BepInEx{sep}Translation{sep}{lang}{sep}Text{sep}_AutoGeneratedTranslations.txt',
        'desc': 'XUnity.AutoTranslator 自动翻译词典，游戏运行时直接读它。',
    },
    'renpy_tl': {
        'fmt': 'rpy',
        'dir_tpl': 'game{sep}tl{sep}{lang}',
        'desc': "Ren'Py 原生多语言：每个脚本一个同名的 .rpy，引擎自己会加载。",
    },
    'rpgmaker_builtin': {
        'fmt': 'builtin',
        'file_tpl': '_AutoGeneratedTranslations.txt',
        # v3.29：apply 已实现（rpgmaker_engine.apply），会先全量备份再回写。
        'apply': 'rpgmaker',
        'desc': 'RPG Maker MV/MZ：此 txt 只是翻译器的**工作副本**（放游戏根目录）。'
                '游戏不读它 —— 必须再点「应用到游戏」把译文回写进 www/data/*.json。',
    },
    'game_root_txt': {
        'fmt': 'kv',
        'file_tpl': '_AutoGeneratedTranslations.txt',
        'desc': '游戏根目录下独立词典文件（该引擎没有标准注入词典路径，'
                '需配合对应 hook 使用）。',
    },
    'kirikiri_patch': {
        'fmt': 'manual',
        'file_tpl': 'patch{sep}ScenarioPatch.txt',
        'desc': 'Kirikiri 的 patch 规则由各 hook 版本自行约定，'
                '工具不替你猜格式 —— 先把译文放这儿，再按 hook 文档处理。',
    },
    'tool_unpack_then_manual': {
        'fmt': 'manual',
        'file_tpl': '_Extracted{sep}strings.txt',
        'desc': '此引擎没有运行时注入方案：先用下载的解包工具取出文本，'
                '译文整理后回填资源。',
    },
    # TyranoScript / NScripter / Unreal / SRPGStudio 走这一条：
    # 各引擎的落点规则互不相同且不通用，不编造统一路径，只给根目录工作副本。
    'manual': {
        'fmt': 'manual',
        'file_tpl': '_AutoGeneratedTranslations.txt',
        'apply': None,          # v3.29：没有自动回写方案，需人工按引擎流程回填
        'desc': '该引擎没有统一的注入词典路径，译文先落到游戏根目录的工作副本，'
                '再按引擎各自的流程回填（本工具不会自动改游戏数据）。',
    },
}

_MANUAL_SINK = SINKS['manual']   # 未知 sink id 的兜底（防御性，正常路径不会走到）

# ----------------------------------------------------------------------------
# 引擎 → 方案
# ----------------------------------------------------------------------------
# 与 engine_detector.ENGINE_FEATURES 的键**逐一对应**（测试会校验这条一致性）。
# tools: 需要安装的工具包 id 列表；optional=True 的包由 include_optional 控制。
# ----------------------------------------------------------------------------

ENGINE_KITS = {
    'Unity': {
        'engine': 'Unity',
        'display': 'Unity (Mono)',
        'tools': ['bepinex5-win-x64', 'xunity-autotranslator-bepinex',
                  'xunity-redirector-bepinex'],
        'sink': 'xunity_auto',
        'notes': '本项目主用方案，Starmaker Story 即是这条链路。',
    },
    'UnityIL2CPP': {
        'engine': 'UnityIL2CPP',
        'display': 'Unity (IL2CPP)',
        'tools': ['bepinex6-il2cpp-win-x64', 'xunity-autotranslator-il2cpp'],
        'sink': 'xunity_auto',
        'notes': 'BepInEx 6 仍带 pre 前缀；IL2CPP 包第一次装要下载 34MB。',
    },
    'RenPy': {
        'engine': 'RenPy',
        'display': "Ren'Py",
        'tools': [],
        'sink': 'renpy_tl',
        'reason': "Ren'Py 引擎原生支持多语言：只要把译文按 translate 块写进 "
                  "game/tl/<语言>/ 即可，不需要注入插件。",
        'notes': '提取用项目自带的 renpy_unpacker.py（解 .rpa）。',
    },
    'RPGMakerMV': {
        'engine': 'RPGMakerMV',
        'display': 'RPG Maker MV',
        'tools': [],
        'sink': 'rpgmaker_builtin',
        'reason': 'MV 的文本就是 www/data/*.json 明文，直接改数据文件最干净，'
                  '不需要运行时注入。',
        'notes': 'v3.29：提取 + 回写都已可用。回写会先全量备份 www/data，'
                 '可随时用「还原原文」退回英文。注意 note 字段默认不翻'
                 '（插件会解析它），开关在应用对话框里。',
    },
    'RPGMakerMZ': {
        'engine': 'RPGMakerMZ',
        'display': 'RPG Maker MZ',
        'tools': [],
        'sink': 'rpgmaker_builtin',
        'reason': '同 MV，MZ 的文本就在 data/*.json。',
        'notes': 'v3.29：同 MV，提取 + 回写都已可用（数据在 data/*.json）。',
    },
    'RPGMakerLegacy': {
        'engine': 'RPGMakerLegacy',
        'display': 'RPG Maker XP/VX/VX Ace',
        'tools': [],
        'sink': 'tool_unpack_then_manual',
        'reason': 'XP/VX/VX Ace 没有稳定的通用注入插件 —— 网络上流传的 '
                  'RPGMakerTrans 原仓库已 404，不编 URL。',
        'notes': 'rgss 归档里的 rvdata2 需自行解包；本工具只负责把译文备好。',
    },
    'Kirikiri': {
        'engine': 'Kirikiri',
        'display': 'Kirikiri (吉里吉里)',
        'tools': ['kirikiri-hook', 'kirikiri-descrambler', 'kirikiri-xp3pack'],
        'sink': 'kirikiri_patch',
        'notes': 'hook 是 version.dll，直接放游戏根；解包/打包工具放本地工具目录。',
    },
    'WolfRPG': {
        'engine': 'WolfRPG',
        'display': 'Wolf RPG Editor',
        'tools': ['wolfdec'],
        'sink': 'tool_unpack_then_manual',
        'reason': 'Wolf 生态有翻译工具但未发布 Windows 二进制 release '
                  '（elizagamedev/wolftrans 无 release），只有解包器可用。',
        'notes': 'wolfdec 解出的 Game.dat 文本需人工/脚本回写。',
    },
    'Godot': {
        'engine': 'Godot',
        'display': 'Godot',
        'tools': ['gdre-tools'],
        'sink': 'tool_unpack_then_manual',
        'reason': 'Godot 没有运行时文本注入标准件，标准做法是解 .pck → 改 '
                  'csv/po → 重新打包。',
        'notes': '42MB，按需下载。',
    },
    'GameMaker': {
        'engine': 'GameMaker',
        'display': 'GameMaker Studio',
        'tools': ['undertalemodtool'],
        'sink': 'tool_unpack_then_manual',
        'reason': '无运行时注入；业内标准做法是 UTMT 解包 data.win 改字符串回写。',
        'notes': '单文件版 93MB，首次下载慢。',
    },
    'Flash': {
        'engine': 'Flash',
        'display': 'Flash (SWF)',
        'tools': ['ffdec'],
        'sink': 'tool_unpack_then_manual',
        'reason': 'SWF 早已停更，无注入方案；只能反编译改文本再重打。',
        'notes': '⚠️ 上游只发 nightly 版，链接可能随时间失效。',
    },
    'TyranoScript': {
        'engine': 'TyranoScript',
        'display': 'TyranoScript',
        'tools': [],
        'sink': 'manual',
        'reason': 'data/scenario/*.ks 是明文，直接改最省事，不需要注入器；'
                  '社区工具没有可靠 Windows release，不编 URL。',
        'notes': 'P2-2 待办里 TyranoScript 排第一，届时实现 builtin 回写。',
    },
    'NScripter': {
        'engine': 'NScripter',
        'display': 'NScripter/ONScripter',
        'tools': [],
        'sink': 'manual',
        'reason': '脚本为定制二进制格式且各版本加密不同，无公开通用注入工具。',
        'notes': 'nscript.dat 解包需按具体游戏定方案。',
    },
    'Unreal': {
        'engine': 'Unreal',
        'display': 'Unreal Engine',
        'tools': [],
        'sink': 'manual',
        'reason': 'UE 文本在 .pak 的 locres 表里，通用注入方案不存在；'
                  '且连 u4pak / UnrealPakViewer 的 release 接口都已 404。',
        'notes': '复杂度高，建议单独立项。',
    },
    'SRPGStudio': {
        'engine': 'SRPGStudio',
        'display': 'SRPG Studio',
        'tools': [],
        'sink': 'manual',
        'reason': '官方走 Data/DLC 多语言目录替换，没有第三方注入器。',
        'notes': '按官方 dlc 目录约定放译文即可。',
    },
}

# 语言占位符默认值
DEFAULT_LANG = 'zh'


# ----------------------------------------------------------------------------
# 对外 API
# ----------------------------------------------------------------------------

def all_engine_names():
    """清单里登记的全部引擎名（应与 engine_detector 的键一致）。"""
    return sorted(ENGINE_KITS.keys())


def get_kit(engine):
    """取某引擎的方案 dict；未登记返回 None。"""
    if not engine:
        return None
    return ENGINE_KITS.get(engine)


def get_pack(pack_id):
    """取工具包定义 dict；未登记返回 None。"""
    return PACKS.get(pack_id)


def sink_apply(engine):
    """该引擎译文「怎么才能真的生效」。返回 dict，GUI 用它决定提示与按钮。

      need  : True = 保存到工作副本后**还必须**再执行一次回写才生效
      kind  : 'rpgmaker' = 走 rpgmaker_engine.apply；None = 无自动方案
      hint  : 给玩家看的一句话说明
    """
    sink = get_sink(engine)
    kind = sink.get('apply')
    fmt = sink.get('fmt')
    if kind == 'rpgmaker':
        return {'need': True, 'kind': kind,
                'hint': 'RPG Maker 的文本在游戏数据文件里。保存只是存到翻译器的'
                        '工作副本，还需点「应用到游戏」把译文回写进数据 json。'}
    if fmt == 'kv':
        return {'need': False, 'kind': None,
                'hint': '该引擎的注入插件在运行时读取词典文件，保存后重启游戏即生效。'}
    if fmt == 'rpy':
        return {'need': False, 'kind': None,
                'hint': "Ren'Py 原生多语言：译文已写进 game/tl 目录，重启游戏即生效。"}
    return {'need': True, 'kind': None,
            'hint': '该引擎暂无自动回写方案，译文已存为工作副本，'
                    '需按引擎各自的流程手动回填。'}


def get_sink(engine):
    """取某引擎的译文落点定义 dict（含 fmt / file_tpl / desc / apply）。"""
    kit = get_kit(engine)
    if not kit:
        return dict(_MANUAL_SINK)
    sid = kit.get('sink')
    if sid and sid in SINKS:
        return SINKS[sid]
    return dict(_MANUAL_SINK)


def _tpl_to_path(tpl, lang, native=True):
    """把 file_tpl / dir_tpl 里的 {lang} {sep} 替换成实际值。

    native=True 时用系统分隔符；测试里常用 False 固定传 sep 以稳定比对。
    """
    sep = os.sep if native else '/'
    return tpl.format(lang=lang, sep=sep)


def sink_path(engine, game_dir, lang=None, native=True):
    """译文落地文件的**绝对路径**。返回 None 表示该引擎不产出单文件落点。

    对 fmt='builtin' / fmt='manual' 的引擎，路径依然返回一个「工作副本」位置，
    便于 GUI 当作资产文件继续编辑，真正生效靠各自链路。
    """
    lang = lang or DEFAULT_LANG
    sink = get_sink(engine)
    tpl = sink.get('file_tpl')
    if not tpl:
        return None
    return os.path.join(game_dir, _tpl_to_path(tpl, lang, native))


def sink_dir(engine, game_dir, lang=None, native=True):
    """译文落地**目录**的绝对路径（dir_tpl 型 sink 才有）。"""
    lang = lang or DEFAULT_LANG
    sink = get_sink(engine)
    tpl = sink.get('dir_tpl')
    if not tpl:
        return None
    return os.path.join(game_dir, _tpl_to_path(tpl, lang, native))


def required_tools(engine, include_optional=False):
    """该引擎要装的工具包列表（返回 pack dict，顺序即安装顺序）。

    include_optional=False（默认）时跳过 optional 包 —— 比如 ResourceRedirector
    只在要换字体时才需要。
    """
    kit = get_kit(engine)
    if not kit:
        return []
    out = []
    for pid in kit.get('tools', []):
        p = PACKS.get(pid)
        if not p:
            continue
        if p.get('optional') and not include_optional:
            continue
        out.append(p)
    return out


def build_urls(pack, prefer='mirror'):
    """构造下载候选 URL，按顺序尝试。

    ⚠️ 默认 **mirror 优先**：本机实测 GitHub 直连只有 ~25KB/s，ghfast 约
    1.5MB/s —— 34MB 的 BepInEx IL2CPP 包走直连要 20 分钟以上。镜像失效时
    installer 自动回退到下一条（直连）。

    prefer='official' 可以反转顺序（想拿官方源时用）。
    """
    url = pack.get('url', '')
    gh = 'https://github.com/'
    if not url.startswith(gh):
        return [url]
    mirror = 'https://ghfast.top/' + url
    return [mirror, url] if prefer != 'official' else [url, mirror]


def language_from_ini(game_dir):
    """读游戏里已有的 AutoTranslatorConfig.ini 的 Language，给 sink 路径用。

    找不到就返回默认 'zh'。这一步沿用 GUI 里 read_config_lang 的思路，
    但这里**自己实现一遍**，避免 kit_* 模块反向依赖 GUI 主程序（GUI 依赖 kit，
    依赖关系必须单向）。
    """
    import configparser
    cfg = os.path.join(game_dir, 'BepInEx', 'config', 'AutoTranslatorConfig.ini')
    if os.path.isfile(cfg):
        try:
            cp = configparser.RawConfigParser()
            cp.read(cfg, encoding='utf-8-sig', errors='replace')
            for sec in ('General', 'Behaviour', 'general', 'behaviour'):
                if cp.has_section(sec):
                    for opt in ('Language', 'language', 'FromLanguage'):
                        if cp.has_option(sec, opt):
                            v = (cp.get(sec, opt) or '').strip()
                            if v:
                                return v
        except Exception:
            pass
    return DEFAULT_LANG


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------

def _fmt_size(n):
    if n is None:
        return '?'
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024 or unit == 'GB':
            return '%.0f%s' % (n, unit) if unit == 'B' else '%.1f%s' % (n, unit)
        n /= 1024.0


def main(argv=None):
    ap = __import__('argparse').ArgumentParser(description='独游翻译器 · 注入工具包清单')
    ap.add_argument('engine', nargs='?', help='引擎名（留空列出全部）')
    ap.add_argument('--json', action='store_true', help='结构化输出')
    ap.add_argument('--optional', action='store_true', help='包含可选包')
    args = ap.parse_args(argv)

    if args.json:
        if args.engine:
            kit = get_kit(args.engine)
            print(__import__('json').dumps(
                {'engine': args.engine, 'kit': kit,
                 'sink': get_sink(args.engine),
                 'tools': [p['id'] for p in required_tools(
                     args.engine, args.optional)]},
                ensure_ascii=False, indent=2))
        else:
            print(__import__('json').dumps(
                {e: {'kit': get_kit(e), 'sink': get_sink(e),
                     'tools': [p['id'] for p in required_tools(e, args.optional)]}
                 for e in all_engine_names()},
                ensure_ascii=False, indent=2))
        return 0

    names = [args.engine] if args.engine else all_engine_names()
    for name in names:
        kit = get_kit(name)
        if not kit:
            print('未登记的引擎: %s' % name)
            return 1
        sink = get_sink(name)
        print('=' * 62)
        print(' %s' % kit.get('display', name))
        print('=' * 62)
        tools = required_tools(name, args.optional)
        if tools:
            print(' 需要安装:')
            for p in tools:
                flag = '✓' if p.get('verified') else '⚠'
                opt = ' (可选)' if p.get('optional') else ''
                print('   [%s] %s%s  %s' % (flag, p['title'], opt,
                                            _fmt_size(p.get('size'))))
                print('        %s' % p['desc'])
        else:
            print(' 需要安装: 无 —— %s' % kit.get('reason', '引擎原生机制即可'))
        sp = sink_path(name, '<游戏目录>')
        print(' 译文落点: %s' % (sp or '—'))
        print('     格式: %s  %s' % (sink['fmt'], sink['desc']))
        if kit.get('notes'):
            print(' 备注: %s' % kit['notes'])
        print()
    return 0


if __name__ == '__main__':
    sys.exit(main())
