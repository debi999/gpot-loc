"""M3 功能收口测试 —— FR-35/37/41/42/43。

core 层（flow 持久化 / 动态副标题 / 目标选择 / 护栏开关）+ api 层纯函数
（查找替换 / 清理重复 / 最近列表）。不碰网络、不碰真实 config.ini
（monkeypatch CONFIG_PATH），不碰本地 LLM。
"""
from __future__ import annotations

import json
import os

import pytest

from gpot.core import kernel, store, translate


# ---------------------------------------------------------------------------
# FR-37: 步骤状态持久化（config.ini flow.* 键）
# ---------------------------------------------------------------------------
def test_flow_config_roundtrip(tmp_path, monkeypatch):
    cfg_path = str(tmp_path / "config.ini")
    monkeypatch.setattr(kernel, "CONFIG_PATH", cfg_path)
    assert not os.path.isfile(cfg_path)

    cfg = kernel.load_config()
    cfg["flow.current_step"] = "4"
    cfg["flow.max_step"] = "5"
    kernel.save_config(cfg)

    cfg2 = kernel.load_config()
    assert cfg2["flow.current_step"] == "4"    # TC-FR37-01：config.ini 出现 flow.* 键
    assert cfg2["flow.max_step"] == "5"


def test_restore_flow_bounds(tmp_path, monkeypatch):
    """恢复越界值要被夹回 [0, 6]，空串 = 首次启动保持第 0 步（TC-FR37-02）。"""
    import gpot.api.server as server
    monkeypatch.setattr(kernel, "CONFIG_PATH", str(tmp_path / "config.ini"))

    server._CFG["flow.current_step"] = ""
    server._CFG["flow.max_step"] = ""
    server._restore_flow()
    assert server._STATE.current_step == 0

    server._CFG["flow.current_step"] = "4"
    server._CFG["flow.max_step"] = "4"
    server._restore_flow()
    assert server._STATE.current_step == 4 and server._STATE.max_step == 4

    server._CFG["flow.current_step"] = "99"
    server._CFG["flow.max_step"] = "99"
    server._restore_flow()
    assert server._STATE.max_step == 6 and server._STATE.current_step == 6


# ---------------------------------------------------------------------------
# FR-35: 动态副标题（真实结果，没跑过写「待执行」）
# ---------------------------------------------------------------------------
def test_dynamic_subs():
    s = store.Store()
    d = s.to_dict()
    subs = {st["n"]: st["sub"] for st in d["steps"]}
    assert subs[0] == "未连接"
    assert subs[1] == "未选择"
    assert subs[2] == "未识别"
    assert subs[4] == "未翻译"

    s.game = {"path": "X", "name": "MyGame", "existing": 0}
    s.engine = {"key": "rm", "name": "RPG Maker MV"}
    s.kit = {"deployed": True, "tools": []}
    s.translate.update({"total": 14679, "done": 14204})
    d = s.to_dict()
    subs = {st["n"]: st["sub"] for st in d["steps"]}
    assert subs[1] == "MyGame"
    assert subs[2] == "RPG Maker MV · 工具就位"
    assert subs[4] == "已译 14,204 / 14,679"


# ---------------------------------------------------------------------------
# FR-43: 翻译目标选择（下拉四项 = select_targets 纯函数）
# ---------------------------------------------------------------------------
def _fake_store():
    s = store.Store()
    s.tstore.entries = [
        {"original": "Hello world", "translation": "你好世界", "status": "ok"},
        {"original": "Save game?", "translation": "", "status": "untranslated"},
        {"original": "Load game?", "translation": "读取", "status": "english"},
        {"original": "Exit game?", "translation": "", "status": "untranslated"},
    ]
    return s


def test_select_targets_scopes():
    s = _fake_store()
    assert len(translate.select_targets(s, "todo")) == 2
    assert len(translate.select_targets(s, "retry")) == 3      # 未翻译 + 英文残留
    assert len(translate.select_targets(s, "all")) == 4        # 连已译也重翻
    flt = {"q": "game", "status": "all"}
    assert len(translate.select_targets(s, "filtered", flt)) == 3   # Hello world 不含 game
    flt = {"q": "", "status": "english"}
    assert [e["original"] for e in translate.select_targets(s, "filtered", flt)] == ["Load game?"]
    flt = {"q": "不存在的词", "status": "all"}
    assert translate.select_targets(s, "filtered", flt) == []


def test_start_translate_no_targets_completes():
    s = _fake_store()
    for e in s.tstore.entries:
        e["status"] = "ok"
    s.max_step = 3
    assert translate.start_translate(s) == "done"   # 无目标 → 直接完成（FR-49 语义）
    assert s.max_step >= 4


# ---------------------------------------------------------------------------
# FR-42: 护栏开关（关掉后判据放行、计数为 0）
# ---------------------------------------------------------------------------
def _rm_game(tmp: str) -> str:
    gdir = os.path.join(tmp, "MyRPGGame")
    os.makedirs(os.path.join(gdir, "www", "data"))
    os.makedirs(os.path.join(gdir, "www", "js"))
    os.makedirs(os.path.join(gdir, "www", "img"))
    with open(os.path.join(gdir, "www", "js", "rpg_core.js"), "wb"):
        pass
    map1 = {"events": [{"pages": [{"list": [
        {"code": 401, "parameters": ["Do you really want to quit?"]},
        {"code": 401, "parameters": ["This cannot be undone."]},
    ]}]}]}
    with open(os.path.join(gdir, "www", "data", "Actors.json"), "w", encoding="utf-8") as f:
        json.dump([{"id": 1, "name": "Harold", "nickname": "Hal",
                    "profile": "A brave hero."}], f, ensure_ascii=False)
    with open(os.path.join(gdir, "www", "data", "MapInfos.json"), "w", encoding="utf-8") as f:
        json.dump([], f)
    with open(os.path.join(gdir, "www", "data", "Map001.json"), "w", encoding="utf-8") as f:
        json.dump(map1, f, ensure_ascii=False)
    return gdir


@pytest.fixture()
def rm_store(tmp_path):
    s = store.Store()
    s.game = {"path": _rm_game(str(tmp_path)), "name": "MyRPGGame", "existing": 0}
    return s


def test_extract_guard_toggle(rm_store):
    from gpot.core import extract
    r1 = extract.extract(rm_store, {"mode": "replace"})
    r2 = extract.extract(rm_store, {"mode": "replace",
                                    "guard_frag": False, "guard_poll": False})
    assert r2["guarded"] == 0                  # 关护栏 → 拦截计数归零
    assert r2["total"] >= r1["total"]          # 被拦的可能进入现表


# ---------------------------------------------------------------------------
# FR-43: 查找替换 / 清理重复（api 层纯函数）
# ---------------------------------------------------------------------------
@pytest.fixture()
def api_store(tmp_path, monkeypatch):
    import gpot.api.server as server
    s = server._STATE
    s.tstore.entries = [
        {"original": "Hello world", "translation": "你好世界", "status": "ok"},
        {"original": "Hello world", "translation": "", "status": "untranslated"},
        {"original": "Save game?", "translation": "保存？", "status": "ok"},
        {"original": "Exit game?", "translation": "Hello world", "status": "ok"},
    ]
    s.tstore.path = str(tmp_path / "dict.txt")
    s.tstore.bom = True
    yield s
    s.tstore.entries = []
    s.tstore.path = None


def test_replace_rows(api_store):
    import gpot.api.server as server
    n = server._replace_rows("Hello world", "你好", "original")
    assert n == 2                              # 原文含该词的两条都改了
    assert api_store.tstore.entries[0]["original"] == "你好"
    assert os.path.isfile(api_store.tstore.path)   # 立即落盘
    assert server._replace_rows("", "x", "translation") == 0
    n2 = server._replace_rows("Hello world", "再见", "translation")
    assert n2 == 1                             # 只剩第 4 条的译文里还有这个词


def test_dedup_rows(api_store):
    import gpot.api.server as server
    removed = server._dedup_rows()
    assert removed == 1
    kept = [e for e in api_store.tstore.entries if e["original"] == "Hello world"]
    assert len(kept) == 1
    assert kept[0]["translation"] == "你好世界"    # 保留有译文的那条


# ---------------------------------------------------------------------------
# FR-39: 最近使用列表（api 层）
# ---------------------------------------------------------------------------
def test_recent_list(tmp_path, monkeypatch):
    import gpot.api.server as server
    gdir = _rm_game(str(tmp_path))
    monkeypatch.setattr(server, "_CFG", {"recent_dirs": [gdir, str(tmp_path / "ghost")]})
    out = server._recent_list()
    assert len(out) == 1                       # 不存在的目录被剔除
    assert out[0]["path"] == gdir
    assert out[0]["name"] == "MyRPGGame"
    assert out[0]["configured"] is False       # 没有词典文件 → 未配置
