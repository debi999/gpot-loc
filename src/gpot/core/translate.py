"""翻译任务 —— STUB 接缝，但保留真实流式形状。

真实的任务（batch_fast + 8 后端）会流式推进并支持取消。这里模拟同一形状，
让前端的进度条、轮询、取消按钮都对着一个真正的异步契约工作。
api 层只负责把 job 进度转成 JSON 推给前端，不在此处理并发。
"""
from __future__ import annotations

import threading
import time
import uuid

from gpot.core import pipeline


def start_translate(store, retry: bool) -> str:
    with store.lock:
        job_id = uuid.uuid4().hex[:8]
        total = store.translate["total"]
        start_done = store.translate["failed"] if retry else store.translate["done"]
        job = {
            "id": job_id, "progress": 0.0, "done": start_done,
            "failed": store.translate["failed"], "running": True,
            "cancel": False, "result": None,
        }
        store.jobs[job_id] = job
        store.translate["running"] = True

    def worker() -> None:
        while True:
            with store.lock:
                if not job["running"] or job["cancel"]:
                    break
                job["done"] += 137
                if job["done"] >= total:
                    job["done"] = total
                    job["running"] = False
                    job["progress"] = 100.0
                    store.translate["done"] = total
                    store.translate["failed"] = 34
                    store.translate["running"] = False
                    pipeline.complete_step(store, 4)  # 翻译完成 → 解锁应用（第 5 步）
                    break
                job["progress"] = round(job["done"] / total * 100, 1)
                store.translate["done"] = job["done"]
            time.sleep(0.15)

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
