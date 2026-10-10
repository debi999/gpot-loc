"""M3 功能收口测试 —— FR-35/37/39/41/42/43/45。

core 层（flow 持久化 / 动态副标题 / 目标选择 / 护栏开关 / 表格操作 / exe 查找）。
2026-10-10 codegraph 评估后：业务逻辑下沉 core（store.replace_rows/dedup_rows/
edit_row/recent_games、detection.find_game_exe），api 只做 HTTP 映射——
测试随之只打 core，不再打 server 内部函数。
不碰网络、不碰真实 config.ini（monkeypatch CONFIG_PATH），不碰本地 LLM。
"""
from __future__ import annotations

import json
import os

import pytest

from gpot.core import kernel, pipeline, store, translate


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
    """恢复越界值要被夹回 [0, 6]，空串 = 首次启动保持第 0 步（TC-FR37-02）。

    FR-63 分工：越界**只管夹取**（99 → 6，与事实无关）；
    「能不能真停在第 N 步」归 prereq_ok 事实闸管（另见 test_nav_facts_gate_m3）。
    """
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
    # 夹取上限仍是 6（不是 99），事实闸只会往下压不会往上抬
    assert server._STATE.max_step <= 6 and server._STATE.current_step == server._STATE.max_step


# ---------------------------------------------------------------------------
# FR-63: 导航事实闸（core 层，不必经 HTTP）
# ---------------------------------------------------------------------------
def test_nav_facts_gate_m3():
    """数字解锁 ≠ 事实成立：没选目录/没认引擎就不许进第 3、4 步。"""
    s = store.Store()
    s.unlock_to(6)                                # 纯数字全解锁
    assert s.nav(1) is True and s.nav(2) is False  # 无目录：连「识别引擎」都不该进
    assert s.nav(3) is False                      # 更不用说提取
    assert s.nav(4) is False
    assert s.nav(0) is True

    s.game = {"path": "C:/x", "name": "x", "existing": 0}
    assert s.nav(3) is False                      # 有目录但没引擎 → 第 3 步仍拒
    s.engine = {"engine": "Unity", "key": "unity"}
    assert s.nav(3) is True and s.nav(4) is True

    # 词典空 → 第 5 步（保存并应用）不许进
    assert s.nav(5) is False
    s.tstore.entries.append({"original": "a", "translation": "b", "status": "translated"})
    assert s.nav(5) is True

    # 未应用 → 第 6 步（启动验证）不许进
    assert s.nav(6) is False
    s.sink["applied"] = True
    assert s.nav(6) is True


def test_prereq_msg_specific_m3():
    """被拦时给的是**具体**缺哪一步，不是笼统的「还没解锁」。"""
    s = store.Store()
    s.engine = {"engine": "Unity", "key": "unity"}
    s.game = {"path": "C:/x", "name": "x", "existing": 0}
    m = s.prereq_msg(5)
    assert "第 3 步" in m and "提取" in m      # 词典空 → 指向第 3 步


def test_extract_no_game_refuses_m3():
    """FR-63：没游戏目录时提取必须早退并说人话，不能扫一遍报「新增 0 条」。"""
    from gpot.core import extract as ex
    s = store.Store()
    r = ex.extract(s, {})
    assert r["ok"] is False and r["error"] == "no_game"
    assert "第 1 步" in r["message"]
    assert "status" not in r                    # 绝不写 store.extract = done
    assert s.max_step == 0 and s.current_step == 0


def test_extract_dead_dir_refuses_m3():
    """目录还在配置里但磁盘上已被删/移动 → 同样早退（不许拿空目录报成功）。"""
    from gpot.core import extract as ex
    s = store.Store()
    s.game = {"path": "Z:/绝对不存在的路径/xx", "name": "x", "existing": 0}
    r = ex.extract(s, {})
    assert r["ok"] is False and r["error"] == "no_game"


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
# FR-43: 表格操作（core/store 唯一实现；落盘由 HTTP 层负责）
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
    n = store.replace_rows(api_store.tstore, "Hello world", "你好", "original")
    assert n == 2                              # 原文含该词的两条都改了
    assert api_store.tstore.entries[0]["original"] == "你好"
    assert api_store.tstore.dirty              # 改了要置脏（落盘是 HTTP 层职责）
    assert store.replace_rows(api_store.tstore, "", "x", "translation") == 0
    n2 = store.replace_rows(api_store.tstore, "Hello world", "再见", "translation")
    assert n2 == 1                             # 只剩第 4 条的译文里还有这个词


def test_replace_case_insensitive(api_store):
    n = store.replace_rows(api_store.tstore, "HELLO WORLD", "X", "original",
                           case_sensitive=False)
    assert n == 2                              # 忽略大小写也能命中
    n2 = store.replace_rows(api_store.tstore, "HELLO WORLD", "X", "original")
    assert n2 == 0                             # 默认大小写敏感（保持 v0.4.4 行为）


def test_dedup_rows(api_store):
    removed = store.dedup_rows(api_store.tstore)
    assert removed == 1
    kept = [e for e in api_store.tstore.entries if e["original"] == "Hello world"]
    assert len(kept) == 1
    assert kept[0]["translation"] == "你好世界"    # 保留有译文的那条


def test_dedup_normalized_key(api_store):
    """去重键 = kernel.normalize(原文)（v3 语义：空白折叠+小写，视为同一条）。"""
    api_store.tstore.entries = [
        {"original": "Hello  World", "translation": "A", "status": "ok"},
        {"original": "hello world", "translation": "", "status": "untranslated"},
    ]
    removed = store.dedup_rows(api_store.tstore)
    assert removed == 1                        # 空白折叠+小写后视为重复
    assert api_store.tstore.entries[0]["translation"] == "A"


def test_edit_row(api_store):
    e = store.edit_row(api_store.tstore, 1, "第一行\n第二行")
    assert e is not None and e["translation"] == "第一行\\n第二行"   # 换行转义
    assert e["status"] == "translated"         # classify 原始键（显示层 SMAP 映射 ok）
    assert store.edit_row(api_store.tstore, 99, "x") is None    # 越界
    assert store.edit_row(api_store.tstore, -1, "x") is None


def test_filter_entries_smap_parity():
    """筛选唯一实现：请求键 untranslated 必须命中行状态 untranslated（回归防复发）。"""
    s = _fake_store()
    got = translate.filter_entries(s.tstore, {"q": "", "status": "untranslated"})
    assert [e["original"] for _i, e in got] == ["Save game?", "Exit game?"]
    assert [i for i, _e in translate.filter_entries(
        s.tstore, {"q": "game", "status": "all"})] == [1, 2, 3]


# ---------------------------------------------------------------------------
# FR-45: 游戏本体 exe 查找（core/detection.find_game_exe）
# ---------------------------------------------------------------------------
def test_find_game_exe(tmp_path):
    from gpot.core import detection
    gdir = tmp_path / "Game"
    gdir.mkdir()
    (gdir / "UnityCrashHandler64.exe").write_bytes(b"x" * 100)      # 排除
    (gdir / "Unity.exe").write_bytes(b"x" * 200)                    # 排除
    (gdir / "My Cool Game.exe").write_bytes(b"x" * 5000)            # 本体最大
    (gdir / "launcher.exe").write_bytes(b"x" * 300)                 # 排除
    assert detection.find_game_exe(str(gdir)).endswith("My Cool Game.exe")
    assert detection.find_game_exe(str(tmp_path / "nope")) is None  # 目录不存在
    empty = tmp_path / "Empty"; empty.mkdir()
    assert detection.find_game_exe(str(empty)) is None              # 无 exe


# ---------------------------------------------------------------------------
# FR-35/45: 第 6 步副标题真实化（verify 回写 verified）
# ---------------------------------------------------------------------------
def test_verify_sets_verified(tmp_path):
    from gpot.core import sink
    s = store.Store()
    s.sink = {"applied": True, "engine": "unity", "files": [],
              "backup": None, "note": "", "verified": False}
    sink.verify(s)                                 # 词典不存在 → 自检失败
    assert s.sink["verified"] is False
    assert {st["n"]: st["sub"] for st in s.to_dict()["steps"]}[6] == "待执行"

    s.tstore.entries = [{"original": "Hi", "translation": "你好", "status": "ok"}]
    p = str(tmp_path / "Translation.txt")
    s.tstore.save(p)
    s.sink["files"] = [p]
    sink.verify(s)                                 # 词典存在 + 条目匹配 + 格式合法
    assert s.sink["verified"] is True
    assert {st["n"]: st["sub"] for st in s.to_dict()["steps"]}[6] == "自检通过"


# ---------------------------------------------------------------------------
# 词典污染计数（load 的 U+FFFD 统计暴露，不再无声混入）
# ---------------------------------------------------------------------------
def test_load_corrupt_chars(tmp_path):
    p = tmp_path / "bad.txt"
    p.write_bytes("Hello=你好\n".encode("utf-8") + b"\xff\xfe broken" + "\nEnd=末\n".encode("utf-8"))
    t = kernel.TranslationStore()
    t.load(str(p))
    assert t.corrupt_chars >= 1                # 损坏字节被计数而非静默
    assert len(t.entries) == 3


# ---------------------------------------------------------------------------
# FR-39: 最近使用列表（core/store.recent_games）
# ---------------------------------------------------------------------------
def test_recent_list(tmp_path):
    gdir = _rm_game(str(tmp_path))
    out = store.recent_games([gdir, str(tmp_path / "ghost")])
    assert len(out) == 1                       # 不存在的目录被剔除
    assert out[0]["path"] == gdir
    assert out[0]["name"] == "MyRPGGame"
    assert out[0]["configured"] is False       # 没有词典文件 → 未配置
