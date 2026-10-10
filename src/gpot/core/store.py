"""流水线运行时状态 —— 唯一真源（single source of truth）。

本模块持有全部运行态数据，并且是**唯一**知道「导航锁规则」的地方
（nav / unlock_to）。它不依赖任何 UI 或 HTTP 概念，只存可 JSON 序列化的数据。
api 层读写它，ui 层永远不直接碰它。
"""
from __future__ import annotations

import threading

from . import kernel

# FR-35: 七步领域定义（步骤元数据属于内核，不属于界面）
STEPS = [
    {"n": 0, "key": "config",   "title": "配置翻译服务",        "sub": "本地 Ollama · 未连接"},
    {"n": 1, "key": "game",     "title": "选择游戏目录",        "sub": "未选择"},
    {"n": 2, "key": "engine",   "title": "识别引擎与部署工具",  "sub": "未识别"},
    {"n": 3, "key": "extract",  "title": "提取待翻译文本",      "sub": "未提取"},
    {"n": 4, "key": "translate","title": "翻译与人工校对",      "sub": "未翻译"},
    {"n": 5, "key": "sink",     "title": "保存并应用到游戏",    "sub": "待执行"},
    {"n": 6, "key": "verify",   "title": "启动验证",            "sub": "待执行"},
]

class Store:
    """线程安全的运行时状态容器。"""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.jobs: dict = {}
        # M2: 真实译文资产（唯一真源 = kernel.TranslationStore，原子写 + .bak 三代轮转）。
        # reset() 只清流水线状态，不清资产本体。
        self.tstore = kernel.TranslationStore()
        self.reset()

    # ---- 导航锁：唯一权威（FR-36）----
    def nav(self, step: int) -> bool:
        """跳转到 step。只能落在已解锁区间 [0, max_step]。"""
        with self.lock:
            if step < 0 or step > len(STEPS) - 1:
                return False
            if step > self.max_step:
                return False
            self.current_step = step
            return True

    def unlock_to(self, step: int) -> None:  # FR-36: 解锁只增不减
        with self.lock:
            if step > self.max_step:
                self.max_step = step

    def reset(self) -> None:
        with self.lock:
            self.current_step = 0
            self.max_step = 0
            self.config = {
                "provider": "ollama",
                "model": "hy-mt2-30b-a3b-apex:nano",
                "address": "http://127.0.0.1:11434",
                "key": "",
                "appid": "",
                "secret": "",
                "src": "auto",
                "dst": "zh-CN",
                "prompt": "",
                "connected": False,
            }
            self.game = {"path": "", "name": "", "existing": 0}
            self.engine = None
            self.kit = {"deployed": False, "tools": []}
            self.extract = {"added": 0, "existing": 0, "guarded": 0,
                            "scanned": 0, "total": 0, "translated": 0,
                            "status": "idle"}
            self.translate = {
                "total": 0,
                "done": 0,
                "failed": 0,
                "running": False,
            }
            self.sink = {"applied": False, "engine": None, "files": [],
                         "backup": None, "note": ""}

    def to_dict(self) -> dict:
        with self.lock:
            return {
                "steps": STEPS,
                "current_step": self.current_step,
                "max_step": self.max_step,
                "config": self.config,
                "game": self.game,
                "engine": self.engine,
                "kit": self.kit,
                "extract": self.extract,
                "translate": self.translate,
                "sink": self.sink,
            }
