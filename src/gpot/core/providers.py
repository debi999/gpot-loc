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


def _model_ids(data, key: str) -> list:
    """FR-67: 从接口响应里取模型名列表（**去重且保序**）——唯一真源。

    两个坑在这里一并解决：
    ① `fetch_models` 与 `test_connection` 各写了一份 `m.get("id")` 取法（codegraph 铁律④：
       同一实现必须单源）——双份必然漂移，现共用本函数。
    ② **去重**：部分网关（OpenRouter /oneapi / vLLM 的兼容层）会把同一模型拆成
       `model-a`、`model-a:latest`、甚至带 provider 前缀的别名重复返回，不去重的话
       下拉里会出现肉眼相同的项，而「可用模型 N 个」的 N 还会虚高 —— 又是一处
       「说 2 个实际只看到…」的看不懂（FR-67 与 FR-66 同一类病：数字必须等于用户能选到的数）。

    `strip_prefix`：Gemini 返回的是 `models/gemini-2.0-flash`，接口要的是裸名
    （`[MODEL]` 头不接受带前缀的写法），所以那一条通道要剥前缀；OpenAI 兼容通道
    **绝不能剥**（模型名里本来就有 `hf.co/tencent/…` 这种带斜杠的，剥了就是错模型）。
    """
    raw = []
    for m in (data.get(key) or []):
        # ⚠️ 只认 dict：裸字符串条目一律丢弃。Ollama/OpenAI 返回的都是对象数组，
        # 而真收到裸字符串时那多半是网关返回了非预期结构（错误页/另一种 schema），
        # 把它当模型名塞进下拉 = 用户选到一个根本不存在的模型。
        # （这条是被单测 test_model_ids_dedups_and_keeps_order 逼出来的：
        #   实现原本 `m.get(...) if isinstance(m, dict) else m`，裸串被原样收下。）
        if not isinstance(m, dict):
            continue
        name = m.get("id") or m.get("name")
        if isinstance(name, str) and name.strip():
            raw.append(name.strip())
    out, seen = [], set()
    for n in raw:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def _strip_prefix(models: list, prefix: str = "models/") -> list:
    """剥掉 Gemini 那种 `models/xxx` 前缀（只用于 Gemini 通道）。"""
    return [m[len(prefix):] if m.startswith(prefix) else m for m in models]


def fetch_models(cfg: dict) -> dict:  # FR-54: 获取模型列表（独立端点，不必先连通测试）
    """拉取模型列表填下拉框（忠实移植旧 GUI _fetch_models 的双通道）。

    ① OpenAI 兼容 {base}/models（带 Bearer，有 key 才带）；
    ② 失败时兜底 Ollama 原生 /api/tags（base 以 /v1 结尾则剥掉）。
    返回 {"ok", "models", "message"}；base 为空直接 bad_base。

    ⚠️ FR-67：计数按**去重后**的条数报，与下拉里真正能选到的项数一致；
    消息里带上「可直接下拉选 N 个」，让用户能自己核对是不是被前缀过滤坑过。
    """
    kn = _KEY2NAME.get(cfg.get("provider", ""), cfg.get("provider", "免费Google"))
    kcfg = to_kernel_cfg(cfg)
    base = (kcfg["base"] or "").rstrip("/")
    key = kcfg["key"]
    if not base:
        return {"ok": False, "models": [], "message": "请先填写服务地址"}
    try:                                    # ① OpenAI 兼容通道
        data = _get_json(base + "/models",
                         {"Authorization": "Bearer %s" % key} if key else None,
                         timeout=10)
        models = _model_ids(data, "data")
        if models:
            return {"ok": True, "models": models,
                    "message": "获取到 %d 个模型 · 可直接下拉选 %d 个"
                               % (len(models), len(models))}
    except Exception:
        pass
    try:                                    # ② Ollama 原生 /api/tags 兜底
        host = base[:-3] if base.endswith("/v1") else base
        data = _get_json(host + "/api/tags", timeout=10)
        models = _model_ids(data, "models")
        if models:
            return {"ok": True, "models": models,
                    "message": "获取到 %d 个模型（Ollama 原生接口）· 可直接下拉选 %d 个"
                               % (len(models), len(models))}
    except Exception:
        pass
    return {"ok": False, "models": [], "message": "未获取到模型列表，可能接口不兼容"}


def test_connection(cfg: dict) -> dict:  # FR-38: 连通性测试（真实廉价探测）
    kn = _KEY2NAME.get(cfg.get("provider", ""), cfg.get("provider", "免费Google"))
    kcfg = to_kernel_cfg(cfg)
    base = (kcfg["base"] or "").rstrip("/")
    key = kcfg["key"]
    try:
        if kn in kernel.OPENAI_FAMILY:  # OpenAI兼容 / DeepSeek / 本地Ollama/Qwen
            data = _get_json(base + "/models",
                             {"Authorization": "Bearer %s" % key} if key else None)
            models = _model_ids(data, "data")     # FR-67: 与 fetch_models 共用同一解析（去重保序）
            msg = ("端点可达 · 可用模型 %d 个 · 下拉可选 %d 个"
                   % (len(models), len(models))) if models else "端点可达"
            return {"connected": True, "models": models, "message": msg}
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
            data = _get_json("https://generativelanguage.googleapis.com/v1beta/models?key="
                             + urllib.parse.quote(key or ""))
            models = _strip_prefix(_model_ids(data, "models"))   # FR-67: Gemini 剥 models/ 前缀
            return {"connected": True, "models": models,
                    "message": "Key 有效（模型列表校验通过 · %d 个）" % len(models)}
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
