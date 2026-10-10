"""翻译后端提供方目录 —— 接入旧库 8 后端真实预设（M2，替换原 STUB）。

预设唯一真源 = kernel.PROVIDER_PRESETS（旧库 v3.29 搬入）。
本模块负责：UI key ↔ 旧库中文提供方名 的映射，以及**真实连通性测试**
（只做廉价探测：模型列表 / 用量接口 / 极小请求；绝不加载本地大模型，
遵守「回归与测试不碰本地 LLM」的铁律）。
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request

from . import kernel

# UI key → 旧库提供方名（kernel.PROVIDERS 里的中文名是唯一真源）
UI_PROVIDERS = [
    ("ollama", "本地Ollama/Qwen"),
    ("openai", "OpenAI兼容"),
    ("google", "免费Google"),
    ("deepseek", "DeepSeek"),
    ("claude", "Claude"),
    ("gemini", "Gemini"),
    ("deepl", "DeepL"),
    ("baidu", "百度翻译"),
]
_KEY2NAME = dict(UI_PROVIDERS)
_NAME2KEY = {v: k for k, v in UI_PROVIDERS}


def list_providers() -> list:  # FR-38: 翻译后端目录（第 0 步配置翻译服务使用）
    out = []
    for key, kn in UI_PROVIDERS:
        preset = kernel.PROVIDER_PRESETS.get(kn, {})
        out.append({
            "key": key,
            "name": kn,
            "desc": preset.get("hint", ""),
            "needs_key": bool(preset.get("need_key")),
            "needs_appid": bool(preset.get("need_appid")),
            "model": preset.get("model", ""),
            "address": preset.get("base", ""),
        })
    return out


def to_kernel_cfg(cfg: dict) -> dict:
    """把 UI 配置（provider key / model / address / key…）转成 kernel.Translator 配置。"""
    kn = _KEY2NAME.get(cfg.get("provider", ""), cfg.get("provider", "免费Google"))
    preset = kernel.PROVIDER_PRESETS.get(kn, {})
    return {
        "provider": kn,
        "base": cfg.get("address") or preset.get("base", ""),
        "model": cfg.get("model") or preset.get("model", ""),
        "key": cfg.get("key", ""),
        "appid": cfg.get("appid", ""),
        "secret": cfg.get("secret", ""),
        "src": cfg.get("src", "auto"),
        "dst": cfg.get("dst", "zh-CN"),
        "prompt": cfg.get("prompt", ""),
    }


def _get_json(url: str, headers: dict | None = None, timeout: int = 6):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": kernel.UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def test_connection(cfg: dict) -> dict:  # FR-38: 连通性测试（真实廉价探测）
    kn = _KEY2NAME.get(cfg.get("provider", ""), cfg.get("provider", "免费Google"))
    kcfg = to_kernel_cfg(cfg)
    base = (kcfg["base"] or "").rstrip("/")
    key = kcfg["key"]
    try:
        if kn in kernel.OPENAI_FAMILY:  # OpenAI兼容 / DeepSeek / 本地Ollama/Qwen
            data = _get_json(base + "/models",
                             {"Authorization": "Bearer %s" % key} if key else None)
            n = len(data.get("data") or [])
            return {"connected": True,
                    "message": ("端点可达 · 可用模型 %d 个" % n) if n else "端点可达"}
        if kn == "免费Google":
            tr = kernel.Translator(dict(kcfg))
            out = tr._google_free("hello")
            return {"connected": bool(out),
                    "message": "免费接口可达 · 试译 «%s»" % (out or "")[:20]}
        if kn == "Claude":
            _get_json(base + "/models",
                      {"x-api-key": key, "anthropic-version": "2023-06-01"})
            return {"connected": True, "message": "Key 有效（/models 校验通过）"}
        if kn == "Gemini":
            _get_json("https://generativelanguage.googleapis.com/v1beta/models?key="
                      + urllib.parse.quote(key or ""))
            return {"connected": True, "message": "Key 有效（模型列表校验通过）"}
        if kn == "DeepL":
            _get_json(base + "/usage", {"Authorization": "DeepL-Auth-Key " + key})
            return {"connected": True, "message": "Key 有效（用量接口校验通过）"}
        if kn == "百度翻译":
            tr = kernel.Translator(dict(kcfg))
            tr._baidu("hi")   # 免费额度内 1 次极小请求，仅为验证签名
            return {"connected": True, "message": "AppId/Secret 签名校验通过"}
    except Exception as e:
        msg = str(e)
        if "HTTP Error" in msg:
            code = msg.split("HTTP Error")[1].strip().split(" ")[0]
            if code in ("401", "403"):
                return {"connected": False, "message": "认证失败（Key 无效或无权限）"}
            if code == "404":
                return {"connected": False, "message": "地址不对（端点 404，检查服务地址）"}
        return {"connected": False, "message": "连不上：%s" % msg[:120]}
    return {"connected": False, "message": "未知提供方"}
