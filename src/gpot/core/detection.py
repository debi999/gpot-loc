"""引擎识别 —— 接入旧库真实启发式（M2 已完成，替换原 STUB）。

真实规则来自 `engine_detector.py`（15 条引擎特征，随 M2 迁入）；
「译文怎么才生效」的判定来自 `kit_catalog.sink_apply()`（唯一真源）。
本模块只做两件事：把识别结果归一化为 UI 家族 key，并把 sink 三形态映射出来。
"""
from __future__ import annotations

import os

from . import engine_detector, kit_catalog

# 识别器引擎名 → UI 家族 key（前端 FR-48 选择器 / engineName 用）
_FAMILY = {
    "Unity": "unity", "UnityIL2CPP": "unity",
    "RPGMakerMV": "rm", "RPGMakerMZ": "rm",
    "RenPy": "renpy", "Kirikiri": "kirikiri", "WolfRPG": "wolf",
    "Godot": "godot", "GameMaker": "gamemaker", "Flash": "flash",
    "TyranoScript": "tyrano", "NScripter": "nscripter",
    "SRPGStudio": "srpg", "Unreal": "unreal",
    "RPGMakerLegacy": "manual",
}

# 展示名（旧库 GUI 同款措辞）
_NAME = {
    "Unity": "Unity (Mono)", "UnityIL2CPP": "Unity (IL2CPP)",
    "RPGMakerMV": "RPG Maker MV", "RPGMakerMZ": "RPG Maker MZ",
    "RPGMakerLegacy": "RPG Maker Legacy", "RenPy": "Ren'Py",
    "Kirikiri": "KiriKiri", "WolfRPG": "WolfRPG", "Godot": "Godot",
    "GameMaker": "GameMaker", "Flash": "Flash",
    "TyranoScript": "TyranoScript", "NScripter": "NScripter",
    "SRPGStudio": "SRPG Studio", "Unreal": "Unreal",
}


def sink_kind_for(engine_name: str) -> str:
    """按 kit_catalog 判定三形态：runtime / rewrite / none。

    kind='rpgmaker' → rewrite（需回写）；need=False（kv/rpy 词典）→ runtime；
    其余（无自动方案）→ none。
    """
    if not engine_name:
        return "none"
    sa = kit_catalog.sink_apply(engine_name)
    if sa.get("kind") == "rpgmaker":
        return "rewrite"
    if not sa.get("need"):
        return "runtime"
    return "none"


def detect_engine(game_path: str) -> dict:  # FR-40: 引擎识别（真实启发式）
    if not game_path or not os.path.isdir(game_path):
        return {
            "key": "manual", "name": "未识别", "confidence": 0.0,
            "verdict": "目录不可读", "evidence": [],
            "sink_type": "none", "sink_desc": "请先在第 1 步选择游戏目录",
            "engine": "manual",
        }
    results, summary = engine_detector.detect_engine(game_path)
    if not results:
        return {
            "key": "manual", "name": "未识别（按手动管线）", "confidence": 0.0,
            "verdict": "没有引擎特征",
            "evidence": ["扫描 %d 个文件，无已知引擎硬证据"
                         % summary.get("entries_scanned", 0)],
            "sink_type": "none", "sink_desc": "未发现已知引擎，仅支持导出 CSV",
            "engine": "manual",
        }
    best = results[0]
    eng = best["engine"]
    key = _FAMILY.get(eng, "manual")
    kind = sink_kind_for(eng)
    conf = float(best["confidence"])
    verdict = ("确定性高" if conf >= 0.6 else
               "基本确定" if conf >= 0.3 else "特征偏少，仅参考")
    evidence = list(best.get("hard_hits") or []) or list(best.get("soft_hits") or [])
    return {
        "key": key,
        "name": _NAME.get(eng, eng),
        "confidence": conf,
        "verdict": verdict,
        "evidence": evidence[:6],
        "sink_type": kind,          # runtime | rewrite | none（与原型契约一致）
        "sink_desc": kit_catalog.sink_apply(eng).get("hint", ""),
        "engine": eng,              # kit_catalog 精确引擎名（部署/落盘用）
        "candidates": [{"engine": r["engine"], "confidence": r["confidence"]}
                       for r in results[1:4]],
    }
