#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
独游翻译器 · 引擎自动识别器 (Engine Detector)
================================================
通过特征文件 / 目录 / 数据结构识别 15 类常见独立游戏引擎，
输出引擎家族、具体变体与置信度，供翻译管线选择注入方案。

用法:
    python engine_detector.py <游戏目录>
    python engine_detector.py <游戏目录> --json

零第三方依赖，仅标准库。识别逻辑:
  - 硬特征(决定性): 特征文件存在即命中, 如 UnityPlayer.dll / Game.exe+www/ 。
  - 软特征(加权):   目录/文件名模式累计加分, 最终按归一化置信度排序。
"""

import argparse
import json
import os
import re
import sys
# --- UTF-8 输出引导 ---------------------------------------------------------
# Windows 上 Python 的 stdout 默认跟随系统代码页（CI runner 是 cp1252，
# 简体中文机器常是 cp936）。脚本里中文 print 一旦遇到无法映射的编码就会抛
# UnicodeEncodeError 直接崩。这里在入口处强制 stdout/stderr 走 UTF-8。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# ----------------------------------------------------------------------------
# 特征定义
# 每类引擎: (硬特征列表, 软特征列表[(路径模式, 权重)])
# 路径模式用 fnmatch 风格通配, 匹配相对路径(小写, / 分隔)或目录名。
# ----------------------------------------------------------------------------

ENGINE_FEATURES = {
    'Unity': {
        # Mono 版: 有 UnityPlayer.dll 且存在 *Data/Managed/ 托管程序集,
        # 无 GameAssembly.dll (IL2CPP 标志) —— BepInEx 5 可用
        'hard': ['unityplayer.dll', 'unitycrashhandler64.exe'],
        'soft': [('*_data/level0', 3), ('*_data/*.assets', 2), ('*_data/*.resource', 2),
                 ('*_data/boot.config', 2), ('*_data/*.bundle', 1),
                 ('*_data/managed', 3), ('winhttp.dll', 1)],
        'desc': 'Unity (Mono) — 注入方案: BepInEx 5 + XUnity.AutoTranslator (本项目已实现)',
    },
    'UnityIL2CPP': {
        # IL2CPP 版: 有 GameAssembly.dll + global-metadata.dat, 无托管程序集
        # —— BepInEx 5 (Mono) 无效, 需 BepInEx 6 + Il2CppInterop
        'hard': ['gameassembly.dll', '*/il2cpp_data/metadata/global-metadata.dat'],
        'soft': [('*_data/level0', 3), ('*_data/*.assets', 2), ('*_data/*.resource', 2),
                 ('*_data/boot.config', 2), ('*_data/*.bundle', 1),
                 ('*/il2cpp_data', 3), ('*.metadata.dat', 2)],
        'desc': 'Unity (IL2CPP) — 注入方案: BepInEx 6 + Il2CppInterop + XUnity (IL2CPP 版)',
    },
    'Unreal': {
        'hard': [],
        'soft': [('*.exe', 0), ('engine/content', 3), ('*/engine/binaries', 2),
                 ('*.pak', 2), ('*/content/paks', 3), ('ue4prereqsetup*.exe', 2)],
        'desc': 'Unreal Engine — 方案: UE 注入/文本表解包, 复杂度高, 详见 plan',
    },
    'Godot': {
        'hard': ['*.pck'],
        'soft': [('.godot', 3), ('*.godot', 2), ('data_godot', 3)],
        'desc': 'Godot — 方案: 解包 .pck (gdsdecomp), 提取 csv/po/scn 文本',
    },
    'GameMaker': {
        'hard': ['data.win', 'game.unx', 'audiogroup*.dat'],
        'soft': [('options.ini', 1)],
        'desc': 'GameMaker Studio — 方案: UndertaleModTool 解包 data.win, 提取字符串',
    },
    'RPGMakerMV': {
        'hard': ['www/data/map001.json', 'www/js/rpg_core.js'],
        'soft': [('www/img', 2), ('www/audio', 2), ('www/data/*.json', 3),
                 ('www/index.html', 2), ('newgame.html', 1), ('nw.exe', 1)],
        'desc': 'RPG Maker MV — 方案: www/data/*.json 直接解析提取/回写 (管线已实现)',
    },
    'RPGMakerMZ': {
        'hard': ['www/data/map001.json', 'js/rpg_core.js'],
        'soft': [('data/*.json', 3), ('img', 1), ('audio', 1), ('index.html', 1),
                 ('nw.exe', 1), ('package.json', 1)],
        'desc': 'RPG Maker MZ — 方案: data/*.json 直接解析提取/回写 (管线已实现)',
    },
    'RPGMakerLegacy': {
        'hard': ['game.exe', 'rvdata2', 'rvdata', 'rgss*.dll'],
        'soft': [('graphics', 2), ('data/*.rvdata2', 3), ('data/*.rvdata', 3),
                 ('game.rgss3a', 2), ('game.rgss2a', 2), ('game.rgssad', 2)],
        'desc': "RPG Maker XP/VX/VX Ace — 方案: RPG Maker Trans 或解包 rgss 归档",
    },
    'RenPy': {
        'hard': ['renpy', 'lib/renpy'],
        'soft': [('game/*.rpa', 3), ('*.rpa', 2), ('renpy.exe', 3), ('*.exe', 0),
                 ('lib/*/renpy', 2), ('game/', 1)],
        'desc': "Ren'Py — 方案: unrpa 解包 → 提取 .rpy 对话 → UnRen/翻译钩子",
    },
    'WolfRPG': {
        'hard': ['data/basicdata/common.dat', 'data/basicdata'],
        'soft': [('data/*.wolf', 3), ('*.wolf', 2), ('data/', 1)],
        'desc': 'Wolf RPG Editor — 方案: WolfDec 解包 .wolf, Data/ 文本提取回写',
    },
    'SRPGStudio': {
        'hard': ['srpg_studio.exe', 'dlc'],
        'soft': [('srpg studio.exe', 3), ('dlc', 1), ('bepinex', 1)],
        'desc': 'SRPG Studio — 方案: 官方多语言 dlc 目录 / 文本包替换',
    },
    'Kirikiri': {
        'hard': ['data.xp3', 'krkr.exe'],
        'soft': [('*.xp3', 3), ('krkrz.exe', 2), ('data/', 1)],
        'desc': 'Kirikiri(吉里吉里) — 方案: krkrz 工具解包 .xp3 → 提取 ks/scn 文本',
    },
    'TyranoScript': {
        'hard': ['tyrano', 'data/other'],
        'soft': [('tyrano.js', 3), ('index.html', 1), ('data/scenario', 3)],
        'desc': 'TyranoScript — 方案: data/scenario/*.ks 直接解析提取/回写',
    },
    'NScripter': {
        'hard': ['nscript.dat', 'nscripter.exe'],
        'soft': [('*.sa', 2), ('onscripter.exe', 3), ('arc.nsa', 3)],
        'desc': 'NScripter/ONScripter — 方案: 解包 nscript.dat 脚本逐行翻译',
    },
    'Flash': {
        'hard': [],
        'soft': [('*.swf', 3), ('flashplayer*.exe', 2), ('*.swf', 1)],
        'desc': 'Flash(SWF) — 方案: JPEXS 反编译 swf → 提取文本/字体替换',
    },
}

# 二次甄别: RPGMakerLegacy 的 hard 命中 'game.exe' 太宽泛, 需确认 rgss 归档存在
_RPG_LEGACY_RE = re.compile(r'rgss|rvdata|game\.rgss', re.I)
# IL2CPP 决定性特征: GameAssembly.dll 或 global-metadata.dat
_IL2CPP_RE = re.compile(r'gameassembly\.dll|global-metadata\.dat|/il2cpp_data/', re.I)
# Mono 决定性特征: 托管程序集目录
_MONO_RE = re.compile(r'_data/managed', re.I)


def unity_flavor(paths):
    """判定 Unity 是 Mono 还是 IL2CPP。返回 'il2cpp' / 'mono' / None。

    优先 IL2CPP: 同时装了 Mono 兼容层的 IL2CPP 游戏仍应由 IL2CPP 模板处理。
    """
    has_il2cpp = any(_IL2CPP_RE.search(p) for p in paths)
    has_mono = any(_MONO_RE.search(p) for p in paths)
    if has_il2cpp:
        return 'il2cpp'
    if has_mono:
        return 'mono'
    return None


def list_entries(root):
    """返回游戏目录下的 (相对路径小写, 是否目录) 列表 (只扫两层 + 关键深扫)。"""
    entries = []
    for dirpath, dirnames, filenames in os.walk(root):
        depth = os.path.relpath(dirpath, root).count(os.sep)
        if depth > 2:  # 控制扫描深度
            dirnames[:] = []
            continue
        rel_dir = os.path.relpath(dirpath, root).replace(os.sep, '/').lower()
        if rel_dir == '.':
            rel_dir = ''
        for d in dirnames:
            entries.append(((rel_dir + '/' + d.lower()).lstrip('/'), True))
        for f in filenames:
            entries.append(((rel_dir + '/' + f.lower()).lstrip('/'), False))
        if len(entries) > 20000:  # 防御超大目录
            break
    return entries


def _match(pattern, rel):
    """fnmatch 风格匹配: 支持纯目录名与路径模式。"""
    import fnmatch
    if pattern == rel:
        return True
    return fnmatch.fnmatch(rel, pattern) or rel.endswith('/' + pattern) \
        or fnmatch.fnmatch(rel.split('/')[-1], pattern)


def detect_engine(game_dir):
    """识别引擎。返回 (排序结果列表, 扫描摘要)。
    结果项: dict(engine, score, confidence, hard_hits, soft_hits, desc)"""
    if not os.path.isdir(game_dir):
        raise NotADirectoryError(game_dir)
    entries = list_entries(game_dir)
    paths = [p for p, _ in entries]
    results = []
    for engine, spec in ENGINE_FEATURES.items():
        hard_hits = [h for h in spec['hard'] if any(_match(h, p) for p in paths)]
        soft_hits = []
        score = 0.0
        for pat, w in spec['soft']:
            if pat == '*.exe':
                continue  # *.exe 只是存在性背景, 单独处理
            if any(_match(pat, p) for p in paths):
                soft_hits.append(pat)
                score += w
        if spec['soft'] and any(p.endswith('.exe') for p in paths) \
                and any(pat == '*.exe' for pat, _ in spec['soft']):
            score += 0.5  # 有 exe 是几乎所有引擎的底分
        if engine == 'RPGMakerLegacy' and hard_hits:
            # game.exe 命中但无 rgss 佐证时降权
            if not any(_RPG_LEGACY_RE.search(h) for h in hard_hits) \
                    and not any(_RPG_LEGACY_RE.search(p) for p in paths):
                hard_hits = [h for h in hard_hits if h != 'game.exe']
        if engine in ('Unity', 'UnityIL2CPP'):
            # Mono / IL2CPP 互斥: 把对立阵营的特征剔除, 避免两个候选同时高分
            flavor = unity_flavor(paths)
            if engine == 'Unity' and flavor == 'il2cpp':
                hard_hits = [h for h in hard_hits if 'gameassembly' not in h]
                soft_hits = [h for h in soft_hits if h != '*_data/managed']
                score = sum(w for pat, w in spec['soft']
                            if pat in soft_hits) + (0.5 if any(
                                p.endswith('.exe') for p in paths) and
                            any(pat == '*.exe' for pat, _ in spec['soft']) else 0)
                score += len(hard_hits) * 5
            elif engine == 'UnityIL2CPP' and flavor == 'mono':
                hard_hits = []
                soft_hits = []
                score = 0.0
        score += len(hard_hits) * 5
        max_score = 5.0 + sum(w for _, w in spec['soft']) + len(spec['hard']) * 5
        conf = min(1.0, score / max_score) if max_score else 0.0
        if score > 0:
            results.append({
                'engine': engine,
                'score': score,
                'confidence': round(conf, 3),
                'hard_hits': hard_hits,
                'soft_hits': soft_hits,
                'desc': spec['desc'],
            })
    results.sort(key=lambda r: (-r['score'], r['engine']))
    return results, {'entries_scanned': len(paths)}


def detect_best(game_dir):
    """返回 (最佳匹配引擎名, 置信度)；无任何候选时返回 (None, 0.0)。

    ⚠️ 旧版这里写过 `if results[0]['score'] >= 5` 分支，但两个出口返回**完全相同
    的元组**，是无效判断（2026-10-07 代码审阅指出），已删。语义不变 ——
    `detect_engine` 只在 score > 0 时才收候选，故 results 非空即代表「有匹配」。
    """
    results, _ = detect_engine(game_dir)
    if not results:
        return None, 0.0
    return results[0]['engine'], results[0]['confidence']


def main(argv=None):
    ap = argparse.ArgumentParser(description='独游翻译器 · 引擎自动识别器')
    ap.add_argument('game_dir', help='游戏根目录')
    ap.add_argument('--json', action='store_true', help='以 JSON 输出')
    ap.add_argument('--all', action='store_true', help='列出全部候选(默认只显示前3)')
    args = ap.parse_args(argv)

    results, summary = detect_engine(args.game_dir)
    if args.json:
        print(json.dumps({'game_dir': os.path.abspath(args.game_dir),
                          'summary': summary, 'candidates': results},
                         ensure_ascii=False, indent=2))
        return 0
    print('=' * 56)
    print(' 独游翻译器 · 引擎识别: %s' % os.path.abspath(args.game_dir))
    print('=' * 56)
    if not results:
        print(' 未识别出已知引擎特征。')
        return 1
    shown = results if args.all else results[:3]
    for i, r in enumerate(shown, 1):
        mark = '←' if i == 1 else ' '
        print('%s [%d] %-16s 置信度 %.0f%%  硬特征=%s' % (
            mark, i, r['engine'], r['confidence'] * 100, r['hard_hits'] or '-'))
        print('      %s' % r['desc'])
    print('-' * 56)
    print(' 扫描条目: %d' % summary['entries_scanned'])
    return 0


if __name__ == '__main__':
    sys.exit(main())
