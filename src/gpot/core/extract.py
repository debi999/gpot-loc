"""文本提取 —— 接入旧库真实提取 + 护栏（M2，替换原 STUB）。

编排逻辑复刻旧库 GUI `_extract_worker` + `_apply_extract_result`（v3.27 起按引擎分流）：
  RPG Maker  → kernel.extract_rows_rpgmaker()（结构化，失败回退通用扫描）
  其余/Unity → kernel.find_asset_files() + kernel.scan_and_collect()
             （字节流正则 + CJK 通道 + 三条护栏，护栏计数经模块函数包装统计）
"""
from __future__ import annotations

from gpot.core import pipeline

from . import kernel, rpgmaker_engine


def _collect(game_dir: str, deep: bool = False, with_labels: bool = False):
    """按引擎分流扫描。返回 (kept, labels, guarded_counts)。"""
    kept: dict = {}
    labels: dict = {} if with_labels else None

    # 护栏计数：包装 kernel 的两个护栏函数（scan_and_collect 内部按名引用模块级函数，
    # 包装模块属性即可统计，不改旧逻辑本体；提取为单线程调用，计数安全）。
    # 按 normalize 后的字符串去重 —— 计数口径 = 被拦的独立文本数（同一碎片多通道
    # 重复判定时只计一次）。
    counts = {"frag": set(), "poll": set()}
    orig_frag = kernel.is_truncated_fragment
    orig_poll = kernel.is_polluted_cjk_key

    def frag(s):  # noqa: ANN001 —— 包装器签名与原函数一致
        r = orig_frag(s)
        if r:
            counts["frag"].add(s)
        return r

    def poll(s):  # noqa: ANN001
        r = orig_poll(s)
        if r:
            counts["poll"].add(s)
        return r

    try:
        kernel.is_truncated_fragment = frag
        kernel.is_polluted_cjk_key = poll

        ok, _data_dir, _eng = False, None, None
        try:
            ok, _data_dir, _eng = rpgmaker_engine.detect(game_dir)
        except Exception:
            ok = False
        if ok:
            rows = kernel.extract_rows_rpgmaker(game_dir)
            for src, _key in rows:
                kept.setdefault(kernel.normalize(src), src)
        else:
            files = kernel.find_asset_files(game_dir, deep=deep)
            for p in files:
                kernel.scan_and_collect(p, kept, labels=labels, deep_scan=deep)
            if labels:
                for norm, orig in labels.items():
                    kept.setdefault(norm, orig)
    finally:
        kernel.is_truncated_fragment = orig_frag
        kernel.is_polluted_cjk_key = orig_poll
    return kept, counts


def extract(store, options: dict) -> dict:  # FR-42: 文本提取与护栏（真实提取+护栏）
    mode = options.get("mode", "merge")   # merge=仅补缺失（默认）| replace=全量替换
    deep = bool(options.get("deep", False))
    gdir = store.game.get("path", "")
    tstore = store.tstore

    if not tstore.path:
        tstore.path = kernel.translation_file_path(gdir)
    if not tstore.entries and tstore.path and kernel.os.path.isfile(tstore.path):
        tstore.load(tstore.path)   # 已有译文先入表（merge 时保留已翻译内容）

    kept, guarded = _collect(gdir, deep=deep)

    if mode == "replace":
        # 全量替换：清空所有现有条目（含已翻译），重建为未翻译原文（旧库 v39-2 语义）
        tstore.entries = [{"original": orig, "translation": "", "status": "untranslated"}
                          for orig in kept.values()]
        tstore.dirty = True
        added = len(tstore.entries)
        existing = 0
    else:
        # 仅补充缺失：保留现有（含已翻译），只新增扫描到的新原文
        existing_norms = {kernel.normalize(e["original"]) for e in tstore.entries}
        added = 0
        existing = 0
        for norm, orig in kept.items():
            if norm in existing_norms:
                existing += 1
                continue
            tstore.entries.append({"original": orig, "translation": "",
                                   "status": "untranslated"})
            existing_norms.add(norm)
            added += 1
        if added:
            tstore.dirty = True

    guarded_n = len(guarded["frag"] | guarded["poll"])
    stats = tstore.stats()
    store.extract = {
        "added": added,
        "existing": existing,
        "guarded": guarded_n,
        "scanned": len(kept),
        "total": stats["total"],
        "translated": stats["translated"],
        "status": "done",
    }
    store.translate["total"] = stats["total"]
    store.translate["done"] = stats["translated"]
    # FR-49: 提取完成 → 解锁由 pipeline._NEXT 统一定义（直达第 5 步，翻译可选）。
    pipeline.complete_step(store, 3)
    return store.extract
