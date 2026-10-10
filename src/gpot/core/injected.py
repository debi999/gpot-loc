"""游戏内实时翻译服务同步 —— 忠实移植旧 GUI _sync_injected_model（v3.x，FR-59）。

把当前选中的「提供方/Base URL/模型」同步到游戏内注入式翻译服务：
  目标文件: <游戏目录>/BepInEx/plugins/server_config.ini
  （即 HyMT2LocalServer.exe 同目录的配置文件, 游戏内实时翻译读取它）
仅当提供方为本地 Ollama 族、且已定位游戏目录时生效；
文件不存在则按内置模板自动创建。[ollama] 段行级更新，保留注释与其他段。
改动需要重启翻译服务/游戏才生效。返回 True 表示已同步(或本就一致)。
"""
from __future__ import annotations

import os
import re

SERVER_CONFIG_TEMPLATE = """; ============================================================
; 本地翻译服务配置 —— 由「G-POT 翻译器」自动生成/同步
; 修改后保存, 再重启翻译服务/游戏即生效 —— 无需改代码、无需重新打包
; 编码必须为 UTF-8 (本文件自带 BOM 亦可, 会被自动跳过)
; ============================================================

[server]
; 监听端口 (XUnity 插件请求的地址写死为 http://127.0.0.1:18765/translate,
; 一般不需要改; 只有同时改插件 Config 时才动这里)
port = 18765

[ollama]
; Ollama / llama.cpp / Xinference 的 OpenAI 兼容接口地址
base = {base}
; 使用的模型名 —— 必须与 `ollama list` 输出的名字完全一致
model = {model}

[request]
; 单次请求超时(秒)。本地大模型首次加载权重可能很慢, 默认 5 分钟
timeout = 300
; 单条文本最大长度(与 XUnity MaxCharactersPerTranslation=2500 保持一致)
max_text = 2500
"""


def sync_injected(provider_name: str, base: str, model: str,
                  game_dir: str, local_providers: tuple) -> bool:
    """同步模型到游戏内 server_config.ini（纯 core，无 UI 依赖）。

    provider_name 必须是旧库中文名（kernel.PROVIDER_PRESETS 的键）；
    local_providers 传 kernel.LOCAL_PROVIDERS。
    返回 True=已写入（或本就一致）；False=条件不满足或失败。
    """
    try:
        if provider_name not in local_providers:
            return False
        if not game_dir or not os.path.isdir(os.path.join(game_dir, 'BepInEx')):
            return False
        ini = os.path.join(game_dir, 'BepInEx', 'plugins', 'server_config.ini')
        base = (base or '').strip() or 'http://127.0.0.1:11434/v1'
        model = (model or '').strip()
        if not model:
            return False

        if os.path.isfile(ini):
            with open(ini, encoding='utf-8-sig', errors='ignore') as f:
                txt = f.read()
            m_b = re.search(r'(?im)^\s*base\s*=\s*(.+?)\s*$', txt)
            m_m = re.search(r'(?im)^\s*model\s*=\s*(.+?)\s*$', txt)
            if (m_b and m_m and m_b.group(1).strip() == base
                    and m_m.group(1).strip() == model):
                return True                      # 已一致, 无需写盘

            # 行级更新 [ollama] 段内的 base=/model= (保留注释与其他段)。
            # 注：不判「当前段是否仍是 ollama」——b_ok/m_ok 只在 ollama 段内置位，
            # 老版判 `sec == 'ollama'`（最后所在段）导致 [ollama] 后还有其他段时
            # 永远走整体重建、丢掉注释与 [server]/[request] 定制（v0.5.0 修正）。
            sec = None
            b_ok = m_ok = False
            out = []
            for ln in txt.splitlines(keepends=True):
                ls = ln.strip()
                if ls.startswith('[') and ls.endswith(']'):
                    sec = ls[1:-1].strip().lower()
                if sec == 'ollama':
                    if not b_ok and re.match(r'(?i)^\s*base\s*=', ln):
                        ln = re.sub(r'(?i)^(\s*base\s*=\s*).*',
                                    lambda mm: mm.group(1) + base,
                                    ln.rstrip('\r\n')) + '\n'
                        b_ok = True
                    elif not m_ok and re.match(r'(?i)^\s*model\s*=', ln):
                        ln = re.sub(r'(?i)^(\s*model\s*=\s*).*',
                                    lambda mm: mm.group(1) + model,
                                    ln.rstrip('\r\n')) + '\n'
                        m_ok = True
                out.append(ln)
            if b_ok and m_ok:
                with open(ini, 'w', encoding='utf-8', newline='') as f:
                    f.writelines(out)
            else:
                # [ollama] 段缺失或缺键: 整体按模板重建
                with open(ini, 'w', encoding='utf-8', newline='') as f:
                    f.write(SERVER_CONFIG_TEMPLATE.format(base=base, model=model))
        else:
            os.makedirs(os.path.dirname(ini), exist_ok=True)
            with open(ini, 'w', encoding='utf-8', newline='') as f:
                f.write(SERVER_CONFIG_TEMPLATE.format(base=base, model=model))
        return True
    except Exception:
        return False
