"""引擎识别 —— STUB 接缝。

真实实现会扫描游戏目录（Assembly-CSharp.dll / UnityPlayer.dll /
MonoBleedingEdge，或 *.rpgproject，或 www/data/*.json 等），对应旧库
`gui/engine_detector.py` 的 15 条规则。原型阶段固定返回 Unity Mono，
以便把后续流程端到端跑通。M2 迁移时替换本函数体即可，契约不变。
"""
from __future__ import annotations

import time


def detect_engine(game_path: str) -> dict:
    # TODO(M2): 接入真实文件系统启发式（来自 engine_detector.py）
    time.sleep(0.4)  # 模拟扫描耗时
    return {
        "key": "unity",
        "name": "Unity (Mono)",
        "confidence": 0.79,
        "verdict": "确定性高",
        "evidence": ["Assembly-CSharp.dll", "UnityPlayer.dll",
                     "MonoBleedingEdge/", "*_Data/Managed/"],
        "sink_type": "runtime",        # runtime | rewrite | none
        "sink_desc": "XUnity 在运行时读词典替换，游戏本体不改",
    }
