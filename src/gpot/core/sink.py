"""落盘（应用）层 —— 接入真实落盘链路（M2，替换原 STUB 数据视图）。

「译文怎么才生效」的唯一真源 = kit_catalog.sink_apply()（旧库 v3.28 定规）。
三形态的真实动作：
  runtime -> TranslationStore.save() 原子写词典文件（.bak 三代轮转），游戏本体不动
  rewrite -> rpgmaker_engine.apply() 字段白名单回写 www/data/*.json（先全量备份原文）
  none    -> kernel.export_csv() 导出草稿（无自动注入的引擎）
"""
from __future__ import annotations

import os

from gpot.core import pipeline

from . import kernel, kit_catalog, rpgmaker_engine

# UI 家族 key → kit_catalog 默认引擎名（预览其它管线时用；应用时以识别结果为准）
_FAMILY2ENGINE = {
    "unity": "Unity", "rm": "RPGMakerMV", "renpy": "RenPy",
    "kirikiri": "Kirikiri", "wolf": "WolfRPG", "godot": "Godot",
    "gamemaker": "GameMaker", "flash": "Flash", "tyrano": "TyranoScript",
    "nscripter": "NScripter", "srpg": "SRPGStudio", "unreal": "Unreal",
}

_RPG_BLACKLIST = ("characterName / faceName / battlerName（图集名）· "
                  "switches / variables（插件按名查找）· 事件命令码 355/655 "
                  "的 JS 脚本 · 注释 108 · note")
_RPG_WHITELIST = ["name", "description", "message(s) 对话", "nickname",
                  "profile", "terms 用语"]


def _resolve_engine(engine_key: str, store=None) -> str | None:
    """优先用当前游戏识别出的精确引擎名；预览其它家族时退到家族默认。"""
    if store is not None and store.engine:
        detected_family = store.engine.get("key")
        if engine_key in (None, "", detected_family):
            return store.engine.get("engine") or _FAMILY2ENGINE.get(engine_key)
    return _FAMILY2ENGINE.get(engine_key)


def _kind_of(engine_name: str | None) -> str:
    if not engine_name:
        return "none"
    sa = kit_catalog.sink_apply(engine_name)
    if sa.get("kind") == "rpgmaker":
        return "rewrite"
    return "runtime" if not sa.get("need") else "none"


def _translated(store):
    return [e for e in store.tstore.entries if e["translation"].strip()]


def sink_view(engine_key: str, store=None) -> dict:  # FR-44: 落盘三形态视图
    eng = _resolve_engine(engine_key, store)
    kind = _kind_of(eng)
    gdir = (store.game.get("path") if store else "") or ""

    if kind == "rewrite":
        data_dir = None
        try:
            ok, data_dir, _e = rpgmaker_engine.detect(gdir)
        except Exception:
            ok = False
        n_files = 0
        if ok and data_dir and os.path.isdir(data_dir):
            n_files = sum(1 for n in os.listdir(data_dir) if n.lower().endswith(".json"))
        backup_root = (rpgmaker_engine.game_root(data_dir)
                       if ok and data_dir else gdir)
        backup_root = os.path.join(backup_root, "_原文备份")
        n_tr = len(_translated(store)) if store else 0
        return {
            "kind": "rewrite",
            "title": "备份原文并回写游戏",
            "warn": "这一步会改真实游戏文件。执行前自动备份原文，随时可一键还原。",
            "metrics": [
                {"l": "待回写条目", "v": f"{n_tr:,}", "n": "已翻译的条目"},
                {"l": "数据文件", "v": f"{n_files} 个", "n": "data 目录 json"},
                {"l": "备份", "v": "执行时创建", "n": "_原文备份/data-…/"},
            ],
            "files": [
                {"path": (os.path.relpath(data_dir, gdir) if data_dir and gdir
                          else (data_dir or "www/data")),
                 "note": f"共 {n_files} 个数据文件", "action": "将被修改", "badge": "warn"},
                {"path": os.path.relpath(backup_root, gdir) if gdir else backup_root,
                 "note": "按时间戳的一次性还原点", "action": "还原用", "badge": "info"},
            ],
            "whitelist": list(_RPG_WHITELIST),
            "blacklist": _RPG_BLACKLIST,
            "can_restore": True,
        }

    if kind == "runtime":
        dest = None
        if gdir:
            dest = kit_catalog.sink_path(eng, gdir) if eng \
                else kernel.translation_file_path(gdir)
        n_tr = len(_translated(store)) if store else 0
        return {
            "kind": "runtime",
            "title": "保存并写入词典",
            "warn": "游戏本体一个字节都不动。写坏了删掉词典文件就能回到原样。",
            "metrics": [
                {"l": "待写入条目", "v": f"{n_tr:,}", "n": "已翻译的条目"},
                {"l": "写入体积", "v": "—", "n": "执行后回填"},
                {"l": "改动", "v": "增量", "n": ".bak 自动轮转三代"},
            ],
            "files": [
                {"path": dest or "(先选择游戏目录)",
                 "note": "由注入插件在运行时读取替换", "action": "存在" if dest and os.path.isfile(dest) else "将创建",
                 "badge": "ok" if dest and os.path.isfile(dest) else "info"},
            ],
            "whitelist": [],
            "blacklist": "",
            "can_restore": False,
        }

    # none —— 无自动注入
    return {
        "kind": "none",
        "title": "导出 CSV（无自动注入）",
        "warn": "这个引擎没有可靠的自动注入方案。译文不会丢，但需人工或改用通用钩子。",
        "reasons": [
            {"t": "找不到稳定的 Windows 发布包",
             "s": "社区工具多为停更单文件、非标准打包，无法可靠校验与自动部署",
             "badge": "danger"},
            {"t": "文本与代码混排，缺乏结构化落点",
             "s": "无法确定译文该写到哪个文件的哪个位置", "badge": "danger"},
        ],
        "alternatives": [
            {"t": "导出 CSV 人工回填",
             "s": "已备译文格式标准，导入 XUnity / 同类工具即可", "badge": ""},
            {"t": "改用通用文本钩子",
             "s": "Textractor / LunaTranslator：截取显示层文本实时翻译，不动任何游戏文件",
             "badge": "info"},
        ],
        "can_restore": False,
    }


def apply(store, engine_key: str) -> dict:  # FR-44: 应用落盘（真实动作）
    eng = _resolve_engine(engine_key, store)
    kind = _kind_of(eng)
    gdir = store.game.get("path", "") or ""
    tstore = store.tstore

    if kind == "runtime":
        dest = (kit_catalog.sink_path(eng, gdir) if eng and gdir else None) \
            or kernel.translation_file_path(gdir)
        tstore.path = dest
        tstore.save()
        files = [dest]
        backup = None
        note = "已写入词典（.bak 三代轮转）"

    elif kind == "rewrite":
        translations = {e["original"]: e["translation"] for e in _translated(store)}
        if not translations:
            raise RuntimeError("没有已翻译的条目可回写")
        res = rpgmaker_engine.apply(gdir, translations)
        if not res.get("ok"):
            raise RuntimeError(res.get("reason", "回写失败"))
        files = [res.get("data_dir") or os.path.join(gdir, "www", "data")]
        backup = res.get("backup")
        st = res.get("stats") or {}
        note = ("已回写 %d 条（改 %d 个文件，未命中 %d）"
                % (st.get("applied", 0), st.get("changed_files", 0),
                   len(res.get("miss") or ())))

    else:
        out = os.path.join(gdir or os.getcwd(), "_G-POT_译文导出.csv")
        kernel.export_csv(tstore, out)
        files = [out]
        backup = None
        note = "已导出 CSV 草稿"

    store.sink = {
        "applied": True,
        "engine": engine_key,
        "files": files,
        "backup": backup,
        "note": note,
    }
    pipeline.complete_step(store, 5)  # 应用完成 → 解锁验证（第 6 步）
    return store.sink


def verify(store) -> dict:  # FR-45: 启动验证（应用结果闭环，真实校验）
    ek = (store.sink.get("engine")
          or (store.engine or {}).get("key")
          or "unity")
    eng = _resolve_engine(ek, store)
    kind = _kind_of(eng)
    hints = {
        "runtime": "注入插件需要重启游戏才会加载新词典。如果游戏已在运行，先退干净再启动。",
        "rewrite": "数据已回写。如发现立绘丢失或文本异常，用「还原原文」回滚到备份。",
        "none": "这个引擎没有注入方案，译文存为本地草稿，导出后人工处理。",
    }
    checks: list[dict] = []
    if kind == "runtime":
        path = (store.sink.get("files") or [None])[0]
        exists = bool(path and os.path.isfile(path))
        checks.append({"t": "词典文件存在", "s": path or "(未写入)", "ok": exists})
        if exists:
            probe = kernel.TranslationStore()
            try:
                probe.load(path)
                checks.append({"t": "条目数匹配",
                               "s": "文件 %d 条 · 在表 %d 条"
                                    % (len(probe.entries), len(store.tstore.entries)),
                               "ok": len(probe.entries) == len(store.tstore.entries)})
                bad = sum(1 for e in probe.entries
                          if "=" in e["original"] or "\n" in e["original"])
                checks.append({"t": "格式合法",
                               "s": "原文=译文 逐行，无孤立等号、无换行残留" if not bad
                                    else "%d 条原文含等号/换行（异常）" % bad,
                               "ok": bad == 0})
            except Exception as e:
                checks.append({"t": "文件可读", "s": str(e)[:80], "ok": False})
    elif kind == "rewrite":
        bk = store.sink.get("backup")
        checks.append({"t": "原文备份存在", "s": bk or "(未备份)", "ok": bool(bk and os.path.isdir(bk))})
        checks.append({"t": "回写统计", "s": store.sink.get("note", ""), "ok": bool(store.sink.get("applied"))})
    else:
        out = (store.sink.get("files") or [None])[0]
        checks.append({"t": "CSV 草稿已导出", "s": out or "(未导出)", "ok": bool(out and os.path.isfile(out))})
    return {"engine": ek, "hint": hints.get(kind, hints["runtime"]), "checks": checks}
