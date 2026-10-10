"""翻译任务 —— 接入旧库真实后端（M2，替换原 STUB，流式契约不变）。

真实链路：kernel.Translator（8 后端）+ translate_batch_fast（一行一条 +
二分拆批重试，100% 对齐）。任务线程分块推进，进度/取消契约与原型一致：
  job = {id, progress, done, failed, running, cancel, result}
api 层只负责把 job 进度转成 JSON 推给前端，不在此处理并发。
"""
from __future__ import annotations

import threading
import time
import uuid

from gpot.core import pipeline

from . import kernel, providers as _providers

CHUNK = 10   # 每次送 batch_fast 的条数（批内自动再拆批/对齐）

# FR-43: 主按钮下拉四项的目标选择（纯函数，便于单测）
#   todo     仅未翻译（默认）    filtered 当前筛选（q/status 与第 4 步表格同规则）
#   all      全部（连已译也重翻） retry    仅重试失败（未翻译 + 英文残留）
SMAP = {"translated": "ok", "english": "warn", "untranslated": "todo"}
"""状态键映射（请求/筛选键 ↔ 行状态）的唯一真源——server._rows 与 select_targets 共用。"""


def filter_entries(tstore, flt: dict | None) -> list:
    """第 4 步表格筛选的唯一实现（server._rows 与 select_targets 共用）。

    flt: {"q": 搜索词, "status": all|translated|english|untranslated}
    请求里的状态键与行状态都过同一张 SMAP（untranslated→todo…），
    否则会复发「筛选永远 0 命中」。返回 [(i, entry), ...]，i = 条目序号。
    """
    flt = flt or {}
    status = flt.get("status", "all")
    kw = (flt.get("q", "") or "").strip().lower()
    want = SMAP.get(status, status)
    out = []
    for i, e in enumerate(tstore.entries):
        s = SMAP.get(e["status"], e["status"])
        if want != "all" and s != want:
            continue
        if kw and kw not in e["original"].lower() \
                and kw not in e["translation"].lower():
            continue
        out.append((i, e))
    return out


def select_targets(store, scope: str = "todo", flt: dict | None = None) -> list:
    tstore = store.tstore
    if scope == "all":
        return list(tstore.entries)
    if scope == "filtered":
        return [e for _i, e in filter_entries(tstore, flt)]
    if scope == "selected":   # FR-61: 任意勾选行（flt["indices"] = 条目序号列表）
        idx = (flt or {}).get("indices") or []
        out = []
        for i in idx:
            if isinstance(i, int) and 0 <= i < len(tstore.entries):
                out.append(tstore.entries[i])
        return out
    targets = [e for e in tstore.entries if e["status"] == "untranslated"]
    if scope == "retry":
        targets += [e for e in tstore.entries if e["status"] == "english"]
    return targets


def sort_matched(matched: list, col: str, rev: bool) -> list:  # FR-57: 列排序
    """第 4 步表头排序（纯函数）。col = original|translation|status，其余原样返回。

    matched 是 _rows 已筛选的行字典列表（{i,o,t,s}）；空值排最后（不分方向）。
    """
    if col not in ("original", "translation", "status"):
        return matched
    keyf = (lambda r: (r["t"] == "", r["t"].lower())) if col == "translation" \
        else (lambda r: (r["o"] == "", r["o"].lower())) if col == "original" \
        else (lambda r: (r["s"] == "", r["s"]))
    out = sorted(matched, key=keyf, reverse=bool(rev))
    # 空值永远沉底：反向时把空值段再挪回末尾
    if rev:
        nonempty = [r for r in out if not keyf(r)[0]]
        empties = [r for r in out if keyf(r)[0]]
        out = nonempty + empties
    return out


def start_translate(store, retry: bool = False, scope: str = "todo",
                    flt: dict | None = None) -> str | None:  # FR-43: 翻译任务（真实后端）
    with store.lock:
        if store.translate.get("running"):
            return None
        tstore = store.tstore
        # 常规：翻所有未翻译；retry：把「英文残留」的也重翻一遍（scope 见 select_targets）
        targets = select_targets(store, "retry" if retry else scope, flt)
        if not targets:
            pipeline.complete_step(store, 4)
            return "done"
        job_id = uuid.uuid4().hex[:8]
        job = {
            "id": job_id, "progress": 0.0, "done": 0, "failed": 0,
            "total": len(targets), "running": True, "cancel": False, "result": None,
        }
        store.jobs[job_id] = job
        store.translate["running"] = True

    def worker() -> None:
        tr = kernel.Translator(_providers.to_kernel_cfg(dict(store.config)))
        # FR-58: 并发/延迟（第 0 步可配；conc=1 时等价旧的顺序分块）
        try:
            conc = max(1, min(8, int(str(store.config.get("concurrency", "") or 3), 10)))
        except (TypeError, ValueError):
            conc = 3
        try:
            delay = max(0.0, min(10.0, float(str(store.config.get("delay", "") or 0))))
        except (TypeError, ValueError):
            delay = 0.0
        chunks = [targets[i:i + CHUNK] for i in range(0, len(targets), CHUNK)]
        ok = True

        def run_chunk(chunk):
            try:
                return chunk, tr.translate_batch_fast(
                    [e["original"] for e in chunk])
            except Exception:
                return chunk, [None] * len(chunk)

        def apply(chunk, outs):
            with store.lock:
                for e, o in zip(chunk, outs):
                    if o:
                        e["translation"] = o
                        tstore.update_status(e)
                        tstore.dirty = True
                        job["done"] += 1
                    else:
                        job["failed"] += 1
                processed = job["done"] + job["failed"]
                job["progress"] = round(processed / max(1, job["total"]) * 100, 1)

        if conc <= 1:
            for chunk in chunks:
                with store.lock:
                    if job["cancel"] or not job["running"]:
                        ok = False
                        break
                chunk, outs = run_chunk(chunk)
                apply(chunk, outs)
                if delay:
                    time.sleep(delay)
                if job["done"] + job["failed"] >= job["total"]:
                    break
        else:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=conc) as ex:
                pending = []
                for chunk in chunks:           # 主线程派发（可响应取消）
                    with store.lock:
                        if job["cancel"] or not job["running"]:
                            ok = False
                            break
                    pending.append(ex.submit(run_chunk, chunk))
                    if delay:
                        time.sleep(delay)
                for fut in pending:            # 结果按派发序回填
                    if job["cancel"] or not job["running"]:
                        ok = False
                        break
                    chunk, outs = fut.result()
                    apply(chunk, outs)

        with store.lock:
            job["running"] = False
            if not job["cancel"]:
                job["progress"] = 100.0
            job["result"] = "cancelled" if job["cancel"] else "finished"
            stats = tstore.stats()
            store.translate["done"] = stats["translated"]
            store.translate["failed"] = stats["untranslated"]
            store.translate["running"] = False
            if not job["cancel"]:
                pipeline.complete_step(store, 4)  # 翻译完成 → 解锁应用（第 5 步）

    threading.Thread(target=worker, daemon=True).start()
    return job_id


def get_job(store, job_id: str):
    with store.lock:
        return store.jobs.get(job_id)


def cancel_job(store, job_id: str) -> bool:
    with store.lock:
        j = store.jobs.get(job_id)
        if j:
            j["cancel"] = True
            j["running"] = False
            store.translate["running"] = False
            return True
    return False
