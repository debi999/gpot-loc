"""内核层解耦验证 —— 只 import gpot.core，绝不碰 api / ui。

这些测试证明：业务内核可以在没有浏览器、没有 HTTP 服务的情况下独立运行，
这正是「内核与界面解耦」可被机器检验的证据。
"""
from __future__ import annotations

import time

from gpot.core import store, detection, providers, extract, translate, sink, pipeline


def test_store_nav_lock():
    s = store.Store()
    assert s.nav(1) is False          # 第 1 步尚未解锁
    assert s.nav(0) is True
    s.unlock_to(2)
    assert s.nav(2) is True
    assert s.nav(5) is False          # 第 5 步仍锁
    print("  ✓ 导航锁规则")


def test_detection_stub():
    eng = detection.detect_engine("F:/game")
    assert eng["key"] == "unity"
    assert eng["sink_type"] == "runtime"
    print("  ✓ 引擎识别（stub）")


def test_providers():
    assert len(providers.list_providers()) == 6
    r = providers.test_connection({"provider": "ollama"})
    assert r["connected"] is True
    print("  ✓ 提供方目录 + 连通测试")


def test_extract_unlocks_translate():
    s = store.Store()
    s.unlock_to(3)
    extract.extract(s, {})
    assert s.extract["total"] == 14679
    assert s.max_step >= 4             # 提取完成解锁翻译
    print("  ✓ 提取 + 解锁链")


def test_translate_job_runs_to_completion():
    s = store.Store()
    s.translate["done"] = 0
    jid = translate.start_translate(s, retry=False)
    # 等待后台线程跑到 100%（14679/137≈107 步 × 0.15s ≈ 16s）
    for _ in range(600):
        j = translate.get_job(s, jid)
        if j and j["progress"] >= 100:
            break
        time.sleep(0.05)
    j = translate.get_job(s, jid)
    assert j["progress"] == 100.0
    assert s.translate["done"] == s.translate["total"]
    assert s.max_step >= 5             # 翻译完成解锁应用
    print("  ✓ 翻译任务跑到 100% + 解锁链")


def test_translate_cancel():
    s = store.Store()
    s.translate["done"] = 0
    jid = translate.start_translate(s, retry=False)
    time.sleep(0.1)
    assert translate.cancel_job(s, jid) is True
    time.sleep(0.2)
    j = translate.get_job(s, jid)
    assert j["running"] is False
    print("  ✓ 翻译任务可取消")


def test_sink_three_variants_and_apply():
    # 三引擎视图齐全
    for ek in ("unity", "rm", "manual"):
        v = sink.sink_view(ek)
        assert v["kind"] in ("runtime", "rewrite", "none")
    # apply 按引擎落盘并解锁验证
    s = store.Store()
    s.engine = detection.detect_engine("F:/game")
    sink.apply(s, "unity")
    assert s.sink["applied"] is True
    assert s.max_step >= 6
    # RPG Maker 应产生备份还原点
    s2 = store.Store()
    sink.apply(s2, "rm")
    assert s2.sink["backup"] is not None
    print("  ✓ 落盘三形态 + apply 解锁链")


def test_pipeline_complete_step():
    s = store.Store()
    pipeline.complete_step(s, 0)
    assert s.max_step >= 1
    print("  ✓ 流水线 complete_step")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"\n全部 {len(tests)} 项内核测试通过 ✓")
