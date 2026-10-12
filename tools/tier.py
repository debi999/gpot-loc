"""改动分级（T1/T2/T3）+ 改动文件清单 —— 单一真源。

供 `tools/verify.py` 与 `tools/rule_check.py` 共用（铁律 5：同一判定只许一份）。
两份脚本各自拼 git 命令 = 判定口径会分叉（已因此踩过「R5 只看暂存区、
工作区未暂存的 UI 改动不触发」的漏洞）。

为什么分级（2026-10-13 老板亲定「按修改后每轮迭代最小时间成本改」）：
改一行文档和改 core 分层跑同一套验证 = 每轮白烧 50 秒；更糟的是会诱导
「合规表演」——认真填表却跳过真正省时间的动作。分级让成本与风险匹配。

档位（由改动路径自动判定，人/AI 不必自己选，选错 = 白跑或漏跑）：

| 档 | 触发 | 跑什么 | 耗时 |
|----|------|--------|------|
| T1 | 文档 / 注释 / 基线 / 规则文件 | 只跑规则检查 | ≈3s |
| T2 | UI 资源 / 测试 / 冒烟脚本 | 规则 + 单测 + 真浏览器冒烟 | ≈50s |
| T3 | core / api / 入口 / 端到端脚本 | 全套（再 + 端到端） | ≈55s |
"""
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 判档顺序：先 T3 后 T2，其余落 T1
TIER3_PREFIXES = (
    "src/gpot/core/",
    "src/gpot/api/",
    "src/main.py",
    "hooks/",
    "tools/verify.py",
    "tools/e2e_check.py",
)
TIER2_PREFIXES = (
    "src/gpot/ui/",
    "src/tests/",
    "tools/smoke_ui.js",
)

# UI 资源前缀（R5 验收形态签核用）
UI_PREFIXES = ("src/gpot/ui/",)


def changed_files(root: Path | None = None) -> list[str]:
    """本次全部改动文件（暂存 + 工作区 + 未跟踪），相对根、正斜杠。

    ⚠️ 两条踩过的坑：
      - 必须 `-c core.quotepath=false`，否则中文路径被转义成八进制 →
        前缀判定失败 → 规则静默不生效（2026-10-04 实测）。
      - 只看 `--cached` 会漏掉工作区未暂存的改动（R5 因此有漏洞）。
    """
    root = root or ROOT
    files: list[str] = []
    try:
        out = subprocess.check_output(
            ["git", "-c", "core.quotepath=false", "status", "--porcelain"],
            cwd=str(root), stderr=subprocess.DEVNULL,
        )
    except Exception:
        return files
    for line in out.decode("utf-8", "replace").splitlines():
        if len(line) < 4:
            continue
        p = line[3:].strip()
        if " -> " in p:                      # 重命名：取新路径
            p = p.split(" -> ")[-1]
        p = p.strip('"').replace("\\", "/")
        if p:
            files.append(p)
    return files


def classify(files: list[str]) -> tuple[int, list[str]]:
    """返回 (档位, 触发该档的文件列表)。"""
    hits = [f for f in files if f.startswith(TIER3_PREFIXES)]
    if hits:
        return 3, hits
    hits = [f for f in files if f.startswith(TIER2_PREFIXES)]
    if hits:
        return 2, hits
    return 1, list(files)


def ui_hits(files: list[str]) -> list[str]:
    return [f for f in files if f.startswith(UI_PREFIXES)]


def describe(tier: int) -> str:
    return {
        1: "T1 文档/规则 → 只跑规则检查（秒级，不跑测试）",
        2: "T2 UI/测试 → 规则 + 单测 + 真浏览器冒烟",
        3: "T3 core/api/入口 → 全套（含端到端）",
    }[tier]
