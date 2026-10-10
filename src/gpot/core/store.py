"""流水线运行时状态 —— 唯一真源（single source of truth）。

本模块持有全部运行态数据，并且是**唯一**知道「导航锁规则」的地方
（nav / unlock_to）。它不依赖任何 UI 或 HTTP 概念，只存可 JSON 序列化的数据。
api 层读写它，ui 层永远不直接碰它。
"""
from __future__ import annotations

import threading

from . import kernel, detection
import os
import re

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
                         "backup": None, "note": "", "verified": False}

    def _steps_dynamic(self) -> list:  # FR-35: 副标题 = 该步真实结果，没跑过写「待执行」，不许编造
        c = self.config
        e = self.engine or {}
        ext = self.extract
        t = self.translate
        subs = [
            (f"{c.get('provider', '')} · 已连接" if c.get("connected")
             else "未连接"),
            (self.game.get("name") or "未选择"),
            ((e.get("name") or "未识别") + (" · 工具就位" if self.kit.get("deployed") else "")),
            (f"在表 {ext.get('total', 0):,} 条" if ext.get("status") == "done"
             else "未提取"),
            (f"已译 {t.get('done', 0):,} / {t.get('total', 0):,}" if t.get("total")
             else "未翻译"),
            ("已应用" if self.sink.get("applied") else "待执行"),
            ("自检通过" if self.sink.get("verified") else "待执行"),
        ]
        return [dict(s, sub=subs[s["n"]]) for s in STEPS]

    def to_dict(self) -> dict:
        with self.lock:
            return {
                "steps": self._steps_dynamic(),
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


# ---------------------------------------------------------------------------
# 第 4 步表格操作（FR-43）—— core 层唯一实现，api/server.py 只做 HTTP 映射。
# codegraph 纪律：api 层禁止新增业务逻辑（2026-10-10 评估后下沉至此）。
# ---------------------------------------------------------------------------
def name_from_path(p: str) -> str:
    p = (p or "").rstrip("/\\")
    return p.split("/")[-1].split("\\")[-1] or "未命名游戏"


def replace_rows(tstore, find: str, repl: str, field: str = "translation",
                 case_sensitive: bool = True) -> int:
    """查找替换（子串语义，与 UI 模态一致）。field = translation|original|both。

    返回改动条数；**不落盘**——落盘由调用方负责（HTTP 层据此映射 500）。
    case_sensitive=False 时按字面忽略大小写（re.escape，非正则语义）。
    """
    if not find:
        return 0
    fields = {"translation", "original"} if field == "both" else {field}
    pat = None if case_sensitive else re.compile(re.escape(find), re.IGNORECASE)
    n = 0
    for e in tstore.entries:
        hit = False
        for f in fields:
            cur = e.get(f) or ""
            new = cur.replace(find, repl) if pat is None \
                else pat.sub(lambda _m: repl, cur)
            if new != cur:
                e[f] = new
                hit = True
        if hit:
            tstore.update_status(e)
            tstore.dirty = True
            n += 1
    return n


def dedup_rows(tstore) -> int:
    """清理重复：**归一化后**同原文只留一条（有译文的优先保留）。返回删除条数，不落盘。

    键 = kernel.normalize(原文)（v3 语义：空白折叠 + 去首尾 + 小写，
    「Hello  world」与「hello world」视为同一条）。
    """
    keep: dict = {}
    drop: set = set()
    for i, e in enumerate(tstore.entries):
        k = kernel.normalize(e["original"])
        if k not in keep:
            keep[k] = i
            continue
        ki = keep[k]
        if e["translation"].strip() and not tstore.entries[ki]["translation"].strip():
            drop.add(ki)
            keep[k] = i
        else:
            drop.add(i)
    if not drop:
        return 0
    tstore.entries = [e for i, e in enumerate(tstore.entries) if i not in drop]
    tstore.dirty = True
    return len(drop)


def edit_row(tstore, i: int, translation: str) -> dict | None:
    """双击行内编辑（i = 条目序号；原文不可改）。换行转义 \\n 落词典。
    返回该条目；越界/无效返回 None（HTTP 层映射 400）。"""
    if i < 0 or i >= len(tstore.entries) or tstore.entries[i] is None:
        return None
    e = tstore.entries[i]
    e["translation"] = str(translation).replace("\r", "").replace("\n", "\\n")
    tstore.update_status(e)
    tstore.dirty = True
    return e


def recent_games(recent_dirs, limit: int = 5) -> list:
    """FR-39: 最近使用列表（游戏名+路径+已积累条数+已配置徽章；失效目录剔除）。"""
    out = []
    for d in (recent_dirs or [])[:limit]:
        if not d or not os.path.isdir(d):
            continue
        root, _rel = detection.resolve_game_root(d)
        tp = kernel.translation_file_path(root) if root else ""
        n = 0
        if tp and os.path.isfile(tp):
            probe = kernel.TranslationStore()
            try:
                probe.load(tp)
                n = len(probe.entries)
            except Exception:
                n = 0
        out.append({"path": d, "name": name_from_path(root or d),
                    "entries": n, "configured": n > 0})
    return out
