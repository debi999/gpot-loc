"""翻译后端提供方目录 —— STUB 接缝。

真实的 8 个后端在旧库 `gui/Translator.py` + `batch_fast.py`，M2 迁入。
这里只登记目录 + 一个假连通性测试，让配置步骤可演练。
"""
from __future__ import annotations

# FR-38: 翻译后端目录（第 0 步配置翻译服务使用）
PROVIDERS = [
    {"key": "ollama", "name": "本地 Ollama", "desc": "免费 · 离线 · 本机已装", "needs_key": False},
    {"key": "openai", "name": "OpenAI 兼容", "desc": "任意兼容端点", "needs_key": True},
    {"key": "google", "name": "Google 免费", "desc": "免 Key · 但不稳定", "needs_key": False},
    {"key": "claude", "name": "Claude", "desc": "质量最好 · 费用最高", "needs_key": True},
    {"key": "gemini", "name": "Gemini", "desc": "有免费额度", "needs_key": True},
    {"key": "deepl", "name": "DeepL · 百度", "desc": "术语最准 · 建议兜底", "needs_key": True},
]


def list_providers() -> list:
    return PROVIDERS


def test_connection(cfg: dict) -> dict:  # FR-38: 连通性测试
    # TODO(M2): 真实 ping 已配置的端点
    ok = cfg.get("provider") == "ollama"  # 原型：本地模型默认通，其余需 Key
    return {
        "connected": ok,
        "message": ("已注入模型 hy-mt2-30b-a3b-apex:nano"
                    if ok else "需要 API Key 才能连接"),
    }
