"""流水线编排 —— 七步状态机。

唯一持有「完成第 X 步解锁第 Y 步」规则的地方，因此 api 层与 ui 层都不必
硬编码步骤顺序。它们只需说「第 4 步做完了」，由本模块决定下一步解锁什么。
"""
from __future__ import annotations

# FR-35（七步导航轨·唯一权威）& FR-36（柔性导航：只解锁不跳前）& FR-49（翻译可选）：
# 每步完成后解锁的下一步；末步自锁。第 3 步（提取）直接跳到第 5 步（保存并应用），
# 使第 4 步（翻译）成为可选项 —— 提取后无需强制翻译即可保存。
_NEXT = {0: 1, 1: 2, 2: 3, 3: 5, 4: 5, 5: 6, 6: 6}


def complete_step(store, step: int) -> dict:
    # FR-36: 步骤只解锁不跳前；解锁目标一律由上方 _NEXT 决定，调用方不得越权指定
    """标记某步完成，并解锁可抵达的下一步。"""
    nxt = _NEXT.get(step)
    if nxt is not None:
        store.unlock_to(nxt)
    return store.to_dict()
