"""流水线编排 —— 七步状态机。

唯一持有「完成第 X 步解锁第 Y 步」规则的地方，因此 api 层与 ui 层都不必
硬编码步骤顺序。它们只需说「第 4 步做完了」，由本模块决定下一步解锁什么。
"""
from __future__ import annotations

# 每步完成后解锁的下一步；末步自锁
# 注：第 3 步（提取）直接解锁到第 5 步（保存并应用），使第 4 步（翻译）成为
# 可选项 —— 用户提取后无需强制翻译即可进入保存，翻译只是「每轮迭代」里的增值步骤。
_NEXT = {0: 1, 1: 2, 2: 3, 3: 5, 4: 5, 5: 6, 6: 6}


def complete_step(store, step: int) -> dict:
    """标记某步完成，并解锁可抵达的下一步。"""
    nxt = _NEXT.get(step)
    if nxt is not None:
        store.unlock_to(nxt)
    return store.to_dict()
