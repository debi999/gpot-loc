"""前端源码静态门禁（v0.5.5 新增）。

为什么需要：前端是**纯静态文件**，没有编译步骤，改坏了不会立刻报错 ——
只在浏览器加载时才抛。v0.5.5 修「最近使用路径反斜杠被吃」时，为了转义
U+2028/U+2029 在源码里写了**裸不可见字符**，结果整个 app.js 抛
`Invalid regular expression: missing /`，**整个前端挂掉、所有功能全废**，
而单测/端到端（只碰后端）一个都没红。

所以这一层门禁的意义是：**在提交前把「前端整个挂掉」这类事故挡在浏览器之前**。
"""
from __future__ import annotations

import os
import re

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      os.pardir, "gpot", "ui", "assets")
JS_FILES = ("app.js",)


def _read(name: str) -> str:
    with open(os.path.join(ASSETS, name), encoding="utf-8") as f:
        return f.read()


def test_no_bare_line_separators_in_js():
    """⚠️ 源码里绝不许出现裸 U+2028/U+2029 行/段分隔符。

    它们在 JS 字符串字面量里会**截断源码**，在正则字面量里会直接破坏正则
    （`Invalid regular expression`）。而不可见字符在编辑/传输/工具链里极易被破坏，
    症状是「整个 app.js 加载失败」而非某个功能不对 —— 破坏面极大。
    要处理它们必须写 `new RegExp('\\u2028', 'g')` 这种显式转义。
    """
    for name in JS_FILES:
        s = _read(name)
        assert "\u2028" not in s, "%s 含裸 U+2028（行分隔符）—— 会截断 JS 源码" % name
        assert "\u2029" not in s, "%s 含裸 U+2029（段分隔符）—— 会截断 JS 源码" % name


def test_js_has_no_nul_and_no_truncated_tail():
    """app.js 以 `})();` 收尾（IIFE）—— 文件被截断/写坏时这个尾巴会丢。

    不用括号配平做判据：正则字面量 `/…/`、模板字符串里的反引号与花括号会让
    「正则清洗 + 计数」这套近似法误报（实测 {} 219 vs 218 —— 全是误判）。
    真解析交给浏览器（冒烟脚本一加载就会炸），这里只守最朴素的两条硬信号。
    """
    for name in JS_FILES:
        s = _read(name)
        assert "\x00" not in s, "%s 含 NUL 字节 —— 文件写入被截断" % name
        tail = s.rstrip()[-8:]
        assert tail.endswith("})();"), (
            "%s 结尾不是 `})();`（实际 %r）—— 文件疑似被截断或写坏，"
            "整个前端会加载失败" % (name, tail))


def test_jsstr_helper_exists_and_escapes_backslash():
    """FR-68: 动态字符串进 onclick 必须走 `_jsStr` —— 它得存在且会转义反斜杠。

    反斜杠不转义的话 `F://a//b` 里的 `\\a`/`\\b` 被 JS 当转义序列吃掉，
    点一下路径就变成 `F:ab`（老板 2026-10-11 实测：最近使用点一下斜杠全没）。
    """
    s = _read("app.js")
    assert "function _jsStr(" in s, "_jsStr 不存在——动态字符串没有安全的内联传参方式"
    m = re.search(r"function _jsStr\(s\)\s*\{(.*?)\n\}", s, flags=re.S)
    assert m, "_jsStr 函数体解析不到"
    body = m.group(1)
    assert "\\\\\\\\" in body or "\\\\" in body, "_jsStr 必须转义反斜杠"
    # 调用点：最近使用必须走 _jsStr，不能用 esc
    assert "selectRecent('${_jsStr(x.path)}')" in s, \
        "最近使用必须用 _jsStr 传路径（用 esc 会丢反斜杠）"
