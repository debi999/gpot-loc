"""文本提取 —— STUB 接缝。

真实提取（字节流正则 + 启发式 + 护栏）在旧库 `gui/` 提取路径。
原型阶段复用 UI 设计所围绕的真实数字，让步骤 3 可演练。
"""
from __future__ import annotations

import time

from gpot.core import pipeline


def extract(store, options: dict) -> dict:
    # TODO(M2): 接入真实提取 + 护栏（过滤 ~35.4% 碎片、80/95 污染）
    time.sleep(0.5)
    store.extract = {
        "added": 3421, "existing": 11258, "guarded": 8045,
        "total": 14679, "status": "done",
    }
    # 提取完成 → 解锁下一步。解锁目标由 pipeline._NEXT 统一定义
    # （当前为第 5 步「保存并应用」，使翻译成为可选项）。
    pipeline.complete_step(store, 3)
    return store.extract
