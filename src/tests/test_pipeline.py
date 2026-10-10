"""内核解耦测试 —— M2 真实内核版。

只 import core（三层解耦铁律①），用临时目录夹具走真实链路：
识别（engine_detector）→ 提取（rpgmaker_engine / scan_and_collect）→
翻译（注入假后端，不碰网络/本地 LLM）→ 落盘（词典原子写 / rpgmaker 回写）→ 验证。
"""
from __future__ import annotations

import json
import os
import time

import pytest

from gpot.core import detection, providers, extract, translate, sink, store
from gpot.core import pipeline


# ---------------------------------------------------------------------------
# 夹具：RPG Maker MV 临时游戏目录
# ---------------------------------------------------------------------------
def _rm_game(tmp: str) -> str:
    gdir = os.path.join(tmp, "MyRPGGame")
    os.makedirs(os.path.join(gdir, "www", "data"))
    os.makedirs(os.path.join(gdir, "www", "js"))
    os.makedirs(os.path.join(gdir, "www", "img"))
    with open(os.path.join(gdir, "www", "js", "rpg_core.js"), "wb"):
        pass
    actors = [{"id": 1, "name": "Harold", "nickname": "Hal",
               "profile": "A brave hero of the north."}]
    map1 = {"events": [{
        "pages": [{"list": [
            {"code": 401, "parameters": ["Do you really want to quit?"]},
            {"code": 401, "parameters": ["This cannot be undone."]},
        ]}],
    }]}
    with open(os.path.join(gdir, "www", "data", "Actors.json"), "w", encoding="utf-8") as f:
        json.dump(actors, f, ensure_ascii=False)
    with open(os.path.join(gdir, "www", "data", "MapInfos.json"), "w", encoding="utf-8") as f:
        json.dump([], f, ensure_ascii=False)
    with open(os.path.join(gdir, "www", "data", "Map001.json"), "w", encoding="utf-8") as f:
        json.dump(map1, f, ensure_ascii=False)
    return gdir


@pytest.fixture()
def rm_store(tmp_path):
    gdir = _rm_game(str(tmp_path))
    s = store.Store()
    s.game = {"path": gdir, "name": "MyRPGGame", "existing": 0}
    return s


# ---------------------------------------------------------------------------
# 导航锁（FR-35/36/49）
# ---------------------------------------------------------------------------
def test_store_nav_lock():
    s = store.Store()
    assert s.nav(1) is False          # 第 1 步尚未解锁
    assert s.nav(0) is True
    pipeline.complete_step(s, 1)
    assert s.nav(2) is True
    assert s.nav(5) is False          # 第 5 步仍锁


# ---------------------------------------------------------------------------
# 识别（FR-40，真实启发式）
# ---------------------------------------------------------------------------
def test_detect_rpgmaker_real(rm_store):
    eng = detection.detect_engine(rm_store.game["path"])
    assert eng["key"] == "rm"
    assert eng["engine"].startswith("RPGMakerM")
    assert eng["sink_type"] == "rewrite"          # RPG Maker = 回写管线
    assert eng["confidence"] > 0


def test_detect_empty_dir(tmp_path):
    eng = detection.detect_engine(str(tmp_path))
    assert eng["key"] == "manual" and eng["sink_type"] == "none"


# ---------------------------------------------------------------------------
# 提取（FR-42，真实提取 + 护栏）
# ---------------------------------------------------------------------------
def test_extract_rpgmaker_real(rm_store):
    r = extract.extract(rm_store, {})
    assert r["added"] >= 3                          # Actors 字段 + Map 对白（去重后 ≥3）
    assert rm_store.tstore.entries
    assert rm_store.extract["status"] == "done"
    assert rm_store.max_step >= 5                   # FR-49: 提取直达第 5 步
    assert rm_store.nav(4) is True                  # 翻译仍可达但非必经


def test_extract_merge_keeps_translations(rm_store):
    extract.extract(rm_store, {})
    rm_store.tstore.entries[0]["translation"] = "已译"
    rm_store.tstore.entries[0]["status"] = "translated"
    before = len(rm_store.tstore.entries)
    r = extract.extract(rm_store, {"mode": "merge"})
    assert r["added"] == 0                          # 重复提取不再新增
    assert len(rm_store.tstore.entries) == before
    assert rm_store.tstore.entries[0]["translation"] == "已译"   # 已译保留


def test_providers_real_catalog():
    ps = providers.list_providers()
    assert len(ps) == 8                              # 旧库 8 后端全量
    keys = {p["key"] for p in ps}
    assert {"ollama", "openai", "google", "deepl", "baidu"} <= keys
    ollama = next(p for p in ps if p["key"] == "ollama")
    assert ollama["needs_key"] is False and ollama["address"]


# ---------------------------------------------------------------------------
# 翻译（FR-43，任务契约 + 假后端，不碰网络/本地 LLM）
# ---------------------------------------------------------------------------
class _FakeTranslator:
    """替身：按原文查表返回译文，验证任务线程的真实推进/落表逻辑。"""

    TABLE = {"Harold": "哈罗德", "Hal": "小哈",
             "A brave hero of the north.": "北方来的勇敢英雄。",
             "Do you really want to quit?": "真的要退出吗？",
             "This cannot be undone.": "这一步无法撤销。"}


def test_translate_job_runs_real_pipeline(rm_store, monkeypatch):
    extract.extract(rm_store, {})

    def fake_batch_fast(texts):
        return [_FakeTranslator.TABLE.get(t) for t in texts]

    class FakeTr:
        def __init__(self, cfg):
            self.cfg = cfg
        translate_batch_fast = staticmethod(fake_batch_fast)

    import gpot.core.translate as tr_mod
    monkeypatch.setattr(tr_mod.kernel, "Translator", FakeTr)
    jid = tr_mod.start_translate(rm_store, False)
    assert jid and jid != "done"
    for _ in range(100):
        j = tr_mod.get_job(rm_store, jid)
        if j and not j["running"]:
            break
        time.sleep(0.05)
    assert j["progress"] == 100.0
    assert j["done"] == j["total"] and j["failed"] == 0
    st = rm_store.tstore.stats()
    assert st["translated"] == st["total"]           # 全部落表
    assert rm_store.max_step >= 5


def test_translate_noop_when_all_done(rm_store):
    extract.extract(rm_store, {})
    rm_store.translate["running"] = False
    # 全部标成已译 → start_translate 直接走 done 分支
    for e in rm_store.tstore.entries:
        e["translation"] = "x"
        rm_store.tstore.update_status(e)
    jid = translate.start_translate(rm_store, False)
    assert jid == "done"


# ---------------------------------------------------------------------------
# 落盘（FR-44，真实回写 + 备份）与验证（FR-45）
# ---------------------------------------------------------------------------
def test_sink_rewrite_apply_and_backup(rm_store):
    extract.extract(rm_store, {})
    for e in rm_store.tstore.entries:
        e["translation"] = "译-" + e["original"]
        rm_store.tstore.update_status(e)
    res = sink.apply(rm_store, "rm")
    assert res["applied"] and res["backup"] and os.path.isdir(res["backup"])
    # 真实回写校验：Actors.json 的 name 字段已被替换
    with open(os.path.join(rm_store.game["path"], "www", "data", "Actors.json"),
              encoding="utf-8") as f:
        actors = json.load(f)
    assert actors[0]["name"].startswith("译-")
    assert rm_store.max_step >= 6


def test_sink_view_three_kinds(rm_store):
    extract.extract(rm_store, {})
    v = sink.sink_view("rm", rm_store)
    assert v["kind"] == "rewrite" and v["can_restore"] is True
    v2 = sink.sink_view("manual", rm_store)
    assert v2["kind"] == "none" and v2["alternatives"]


def test_verify_after_apply(rm_store):
    extract.extract(rm_store, {})
    for e in rm_store.tstore.entries:
        e["translation"] = "译-" + e["original"]
    sink.apply(rm_store, "rm")
    v = sink.verify(rm_store)
    assert v["engine"] == "rm"
    assert v["checks"] and v["checks"][0]["ok"]      # 备份存在 = 第一项校验通过


# ---------------------------------------------------------------------------
# 状态容器契约
# ---------------------------------------------------------------------------
def test_state_to_dict_shape():
    s = store.Store()
    d = s.to_dict()
    for k in ("steps", "current_step", "max_step", "config", "game",
              "engine", "kit", "extract", "translate", "sink"):
        assert k in d
    assert len(d["steps"]) == 7
