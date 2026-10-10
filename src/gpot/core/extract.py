"""文本提取 —— 接入旧库真实提取 + 护栏（M2，替换原 STUB）。

编排逻辑复刻旧库 GUI `_extract_worker` + `_apply_extract_result`（v3.27 起按引擎分流）：
  RPG Maker  → kernel.extract_rows_rpgmaker()（结构化，失败回退通用扫描）
  其余/Unity → kernel.find_asset_files() + kernel.scan_and_collect()
             （字节流正则 + CJK 通道 + 三条护栏，护栏计数经模块函数包装统计）
"""
from __future__ import annotations

from gpot.core import detection, pipeline

from . import kernel, rpgmaker_engine


def _collect(game_dir: str, deep: bool = False, with_labels: bool = False,
             guard_frag: bool = True, guard_poll: bool = True):
    """按引擎分流扫描。返回 (kept, labels, guarded_counts)。

    guard_frag / guard_poll（FR-42）：护栏开关，关掉后对应判据直接放行
    （计数也为 0）——用户明确选择「不过滤」时生效，默认全开。
    """
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
        if not guard_frag:
            return False
        r = orig_frag(s)
        if r:
            counts["frag"].add(s)
        return r

    def poll(s):  # noqa: ANN001
        if not guard_poll:
            return False
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


def extract(store, options: dict) -> dict:  # FR-42: 文本提取与护栏（真实提取+护栏；选项：mode/deep/guard_*）
    mode = options.get("mode", "merge")   # merge=仅补缺失（默认）| replace=全量替换
    deep = bool(options.get("deep", False))
    guard_frag = options.get("guard_frag", True) is not False
    guard_poll = options.get("guard_poll", True) is not False
    gdir = store.game.get("path", "")
    tstore = store.tstore

    # FR-63: 没有游戏目录就别装模作样扫一遍报「新增 0 条」——
    # 那是 v0.5.0「提取后表格空白」的根因（目录没选却显示提取成功）。
    if not gdir or not kernel.os.path.isdir(gdir):
        return {"ok": False, "error": "no_game",
                "message": "还没选游戏目录 —— 先回第 1 步选对目录再提取"}

    if not tstore.path:
        tstore.path = kernel.translation_file_path(gdir)
    if not tstore.entries and tstore.path and kernel.os.path.isfile(tstore.path):
        tstore.load(tstore.path)   # 已有译文先入表（merge 时保留已翻译内容）

    kept, guarded = _collect(gdir, deep=deep,
                             guard_frag=guard_frag, guard_poll=guard_poll)

    # FR-63: 提取过程自己就识别出了引擎（_collect 内部跑过 rpgmaker_engine.detect /
    # 走的是哪条扫描分支），必须回写 store.engine —— 否则事实闸会认为「引擎未识别」
    # 把用户挡在第 4 步外，而第 5 步也不知道该用 rewrite 还是 unity 管线。
    # 幂等：store.engine 已有值就不覆盖（用户可能在第 2 步手动选过）。
    if store.engine is None:
        try:
            store.engine = detection.detect_engine(gdir)
        except Exception:
            pass

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
