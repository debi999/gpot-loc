"""M4 功能回补测试 —— FR-53~61（旧 GUI 缺失功能对账后全部补齐，2026-10-10）。

覆盖：FR-53 提示词（prompt_default 下发）· FR-54 获取模型列表（base 校验/双通道
结构）· FR-56 TXT 导入三形态 · FR-57 删除条目/列排序/查看全文（纯前端不测）·
FR-58 并发间隔参数解析 · FR-59 游戏内实时翻译同步（server_config.ini 模板/行级
更新/已一致短路）· FR-60 外部改动检测 · FR-61 勾选行翻译目标选择。
不碰网络、不碰真实 config.ini（monkeypatch CONFIG_PATH）、不碰本地 LLM。
"""
from __future__ import annotations

import os
import time

import pytest

from gpot.core import injected, kernel, providers, store, translate


def _fake_store():
    s = store.Store()
    s.tstore.entries = [
        {"original": "Hello world", "translation": "你好世界", "status": "ok"},
        {"original": "Save game?", "translation": "", "status": "untranslated"},
        {"original": "Load game?", "translation": "读取", "status": "english"},
        {"original": "Exit game?", "translation": "", "status": "untranslated"},
    ]
    return s


# ---------------------------------------------------------------------------
# FR-53: 提示词默认值随 /api/state 下发（恢复默认 = kernel.LLM_SYSTEM）
# ---------------------------------------------------------------------------
def test_prompt_default_exposed():
    import gpot.api.server as server
    assert server.kernel.LLM_SYSTEM           # 内置默认提示词非空
    assert len(server.kernel.LLM_SYSTEM) > 50


# ---------------------------------------------------------------------------
# FR-54: 获取模型列表（无地址 → 明确报错；不碰网络）
# ---------------------------------------------------------------------------
def test_fetch_models_bad_base():
    # 未知提供方 + 空地址 → to_kernel_cfg 无预设可回退 → base 空 → 明确报错
    r = providers.fetch_models({"provider": "NoSuchProvider", "address": ""})
    assert r["ok"] is False
    assert "服务地址" in r["message"]


def test_fetch_models_network_failure(tmp_path, monkeypatch):
    """网络不通（mock 掉双通道请求）→ ok=False 而非抛异常。"""
    import gpot.core.providers as prov

    def _boom(*a, **kw):
        raise OSError("refused")
    monkeypatch.setattr(prov, "_get_json", _boom)
    r = prov.fetch_models({"provider": "NoSuchProvider",
                           "address": "http://127.0.0.1:9"})
    assert r["ok"] is False and r["models"] == []


def test_fetch_models_shape():
    """返回形状契约：ok/models/message 三键齐（HTTP 层直接透传）。"""
    r = providers.fetch_models({"provider": "ollama", "address": "http://127.0.0.1:1"})
    assert set(r) == {"ok", "models", "message"}


# ---------------------------------------------------------------------------
# FR-56: TXT 导入三形态（忠实移植旧 _import_txt 语义）
# ---------------------------------------------------------------------------
def _tstore():
    return kernel.TranslationStore()


def test_import_txt_eq_form(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("Hello=你好\n# 注释\n\n1. Save=保存\n", encoding="utf-8")
    t = _tstore()
    n = kernel.import_txt(t, str(p))
    assert n == 2                                 # 注释/空行不计
    assert t.entries[0]["original"] == "Hello"
    assert t.entries[0]["status"] == "translated"
    assert t.entries[1]["original"] == "Save"     # 行首编号剥掉
    assert t.entries[1]["translation"] == "保存"


def test_import_txt_tab_and_pure(tmp_path):
    p = tmp_path / "b.txt"
    p.write_text("Load\t读取\nBrand new line\n", encoding="utf-8")
    t = _tstore()
    n = kernel.import_txt(t, str(p))
    assert n == 2
    assert t.entries[0]["translation"] == "读取"   # Tab 分隔
    assert t.entries[1]["translation"] == ""       # 纯原文 → 未翻译
    assert t.entries[1]["status"] == "untranslated"


def test_import_txt_merge_updates_differing(tmp_path):
    """合并语义（忠实旧版）：译文不同 → 更新；空译文 → 回填；
    原文先精确匹配、再 normalize 匹配（「HELLO 」命中「Hello」）。"""
    t = _tstore()
    t.entries = [{"original": "Hello", "translation": "旧译文", "status": "translated"}]
    p = tmp_path / "c.txt"
    p.write_text("HELLO =新译文\n", encoding="utf-8")
    n = kernel.import_txt(t, str(p))
    assert n == 1                                  # normalize 后同原文，译文不同 → 更新
    assert t.entries[0]["translation"] == "新译文"


def test_import_txt_append_new(tmp_path):
    t = _tstore()
    t.entries = [{"original": "Old", "translation": "旧", "status": "translated"}]
    p = tmp_path / "d.txt"
    p.write_text("Fresh line\n", encoding="utf-8")
    n = kernel.import_txt(t, str(p))
    assert n == 1 and len(t.entries) == 2
    assert t.entries[1]["original"] == "Fresh line"


# ---------------------------------------------------------------------------
# FR-57: 删除条目 + 列排序（core 唯一实现）
# ---------------------------------------------------------------------------
def test_delete_rows():
    s = _fake_store()
    n = store.delete_rows(s.tstore, [0, 2, 2, 99, -1])   # 去重 + 越界忽略
    assert n == 2
    assert [e["original"] for e in s.tstore.entries] == ["Save game?", "Exit game?"]
    assert s.tstore.dirty
    assert store.delete_rows(s.tstore, []) == 0
    assert store.delete_rows(s.tstore, [50]) == 0


def test_sort_matched():
    rows = [{"i": 0, "o": "b", "t": "二", "s": "ok"},
            {"i": 1, "o": "a", "t": "", "s": "todo"},
            {"i": 2, "o": "c", "t": "三", "s": "warn"}]
    assert [r["o"] for r in translate.sort_matched(rows, "original", False)] == ["a", "b", "c"]
    out = translate.sort_matched(rows, "original", True)
    assert [r["o"] for r in out] == ["c", "b", "a"]
    out = translate.sort_matched(rows, "translation", False)
    # 码位序：三(U+4E09) < 二(U+4E8C)，空译文沉底
    assert [r["o"] for r in out] == ["c", "b", "a"]
    out = translate.sort_matched(rows, "translation", True)
    assert [r["o"] for r in out] == ["b", "c", "a"]       # 反向时空值仍沉底
    assert translate.sort_matched(rows, "bogus", False) is rows  # 非法列原样返回


# ---------------------------------------------------------------------------
# FR-61: 勾选行翻译目标（indices 越界忽略）
# ---------------------------------------------------------------------------
def test_select_targets_selected():
    s = _fake_store()
    got = translate.select_targets(s, "selected", {"indices": [0, 2, 99]})
    assert [e["original"] for e in got] == ["Hello world", "Load game?"]
    assert translate.select_targets(s, "selected", {"indices": []}) == []
    assert translate.select_targets(s, "selected", None) == []


# ---------------------------------------------------------------------------
# FR-58: 并发/间隔参数解析（worker 内 clamp；此处验 config 键能进 kernel cfg）
# ---------------------------------------------------------------------------
def test_concurrency_delay_config_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(kernel, "CONFIG_PATH", str(tmp_path / "config.ini"))
    cfg = kernel.load_config()
    assert "concurrency" in cfg and "delay" in cfg      # kernel 默认值仍在
    cfg["concurrency"] = "5"
    cfg["delay"] = "0.2"
    kernel.save_config(cfg)
    cfg2 = kernel.load_config()
    assert cfg2["concurrency"] == "5" and cfg2["delay"] == "0.2"


# ---------------------------------------------------------------------------
# FR-59: 游戏内实时翻译同步（server_config.ini）
# ---------------------------------------------------------------------------
LOCAL = kernel.LOCAL_PROVIDERS


def _game(tmp, with_ini=None):
    gdir = os.path.join(str(tmp), "Game")
    os.makedirs(os.path.join(gdir, "BepInEx", "plugins"), exist_ok=True)
    ini = os.path.join(gdir, "BepInEx", "plugins", "server_config.ini")
    if with_ini is not None:
        with open(ini, "w", encoding="utf-8") as f:
            f.write(with_ini)
    return gdir, ini


def test_sync_injected_creates_template(tmp_path):
    gdir, ini = _game(tmp_path)
    assert injected.sync_injected("本地Ollama/Qwen", "http://127.0.0.1:11434/v1",
                                  "qwen:test", gdir, LOCAL) is True
    txt = open(ini, encoding="utf-8").read()
    assert "[ollama]" in txt and "base = http://127.0.0.1:11434/v1" in txt
    assert "model = qwen:test" in txt and "[server]" in txt


def test_sync_injected_line_level_update(tmp_path):
    """已有配置：行级更新 [ollama] base=/model=，保留注释与 [request] 段。"""
    old = ("; header\n[server]\nport = 18765\n[ollama]\n; c\nbase = http://old/v1\n"
           "model = old-model\n[request]\ntimeout = 300\n")
    gdir, ini = _game(tmp_path, with_ini=old)
    assert injected.sync_injected("本地Ollama/Qwen", "http://new:11434/v1",
                                  "new-model", gdir, LOCAL) is True
    txt = open(ini, encoding="utf-8").read()
    assert "base = http://new:11434/v1" in txt and "model = new-model" in txt
    assert "; header" in txt and "port = 18765" in txt        # 其他内容保留
    assert "timeout = 300" in txt and "[request]" in txt
    assert "http://old" not in txt


def test_sync_injected_already_consistent(tmp_path):
    cfg = ("[ollama]\nbase = http://a/v1\nmodel = m\n")
    gdir, ini = _game(tmp_path, with_ini=cfg)
    before = os.path.getmtime(ini)
    time.sleep(0.02)
    assert injected.sync_injected("本地Ollama/Qwen", "http://a/v1", "m", gdir, LOCAL) is True
    assert os.path.getmtime(ini) == before                    # 已一致 → 不写盘


def test_sync_injected_conditions(tmp_path):
    gdir, _ini = _game(tmp_path)
    assert injected.sync_injected("Claude", "http://x", "m", gdir, LOCAL) is False  # 非本地
    assert injected.sync_injected("本地Ollama/Qwen", "", "", gdir, LOCAL) is False  # 无模型
    plain = os.path.join(str(tmp_path), "NoBep")
    os.makedirs(plain, exist_ok=True)
    assert injected.sync_injected("本地Ollama/Qwen", "http://x", "m",
                                  plain, LOCAL) is False      # 无 BepInEx
    assert injected.sync_injected("本地Ollama/Qwen", "http://x", "m",
                                  "", LOCAL) is False          # 无游戏目录


# ---------------------------------------------------------------------------
# FR-60: 外部改动检测（mtime 基线）
# ---------------------------------------------------------------------------
def test_external_changed(tmp_path):
    p = tmp_path / "dict.txt"
    p.write_text("Hello=你好\n", encoding="utf-8")
    t = kernel.TranslationStore()
    t.load(str(p))
    assert t.external_changed() is False
    time.sleep(0.03)
    with open(p, "a", encoding="utf-8") as f:
        f.write("New=新\n")
    assert t.external_changed() is True
    t.load(str(p))                       # 重载后基线刷新
    assert t.external_changed() is False
    t.path = None
    assert t.external_changed() is False  # 无路径 → 恒 False
