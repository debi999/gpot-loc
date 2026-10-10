#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
独游翻译器 · UI 短词快路径表（唯一真源）
============================================
历史上这张表有两份物理副本：
  - GUI  : StarmakerTranslator.py  LOCAL_UI_TERMS  (+ _LOCAL_UI_RE)
  - 服务端: BepInEx/plugins/HyMT2LocalServer.py  SHORT_TERMS (+ SHORT_TERM_RE)
两份内容逐条相同（42 条），但改一处忘另一处会导致两条链路行为不一致拆。
本模块把它们合并为唯一真源，GUI 与服务端均改为 import 本模块。

其他项目复用：本文件零第三方依赖，可直接复制到任何 Python 工程。
⚠️ 工具链库（I:/AIcoding/translator）持一份副本；改动必须同步两处。

用法:
    from ui_terms import lookup
    lookup('Save')     -> '存档'
    lookup('Save 5')   -> '存档 5'
    lookup('Hello')    -> None      # 未命中，交由后续翻译链路
"""

import re
import sys

# --- UTF-8 输出引导 ---------------------------------------------------------
# Windows 上 Python 的 stdout 默认跟随系统代码页（CI runner 是 cp1252，
# 简体中文机器常是 cp936）。中文 print 一旦遇到无法映射的编码就会抛
# UnicodeEncodeError 直接崩。这里强制 stdout/stderr 走 UTF-8。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# ---------------------------------------------------------------------------
# 高频 UI 词直译表（键一律小写）
# ---------------------------------------------------------------------------
UI_TERMS = {
    'save': '存档', 'load': '读取', 'settings': '设置', 'options': '选项',
    'skip': '跳过', 'back': '返回', 'return': '返回', 'confirm': '确认', 'cancel': '取消',
    'quit': '退出', 'exit': '退出', 'menu': '菜单', 'play': '开始',
    'resume': '继续', 'next': '下一个', 'previous': '上一个', 'prev': '上一个',
    'start': '开始', 'stop': '停止', 'continue': '继续', 'restart': '重新开始',
    'auto save': '自动存档', 'autosave': '自动存档', 'quit game': '退出游戏',
    'save game': '存档', 'load game': '读取游戏', 'new game': '新游戏',
    'start game': '开始游戏', 'main menu': '主菜单', 'pause': '暂停',
    'controls': '控制', 'audio': '音频', 'video': '画面',
    'language': '语言', 'credits': '制作人员', 'gallery': '画廊', 'extras': '额外',
    'yes': '是', 'no': '否', 'ok': '确定', 'apply': '应用', 'reset': '重置',
}

# "Save 5" / "Load 10" 这种带编号的 UI 按钮
NUM_SUFFIX_RE = re.compile(r'^\s*([A-Za-z][A-Za-z\s]*?)\s+(\d+)\s*$')

# 极短输入的判定阈值（<6 字符的术语才走快路径直译）
SHORT_LEN = 6


def lookup(text):
    """短词快路径查询。命中返回中文译文，未命中返回 None。

    规则（与历史行为完全一致，不改语义）：
      1. 整串（去首尾空白 + 小写）精确命中 UI_TERMS → 直接返回；
      2. 形如 "术语 + 数字"（Save 5）→ 返回 "译文 + 空格 + 数字"（存档 5）；
      3. 其余 → None，交由模型/API 处理。
    """
    if not text:
        return None
    s = text.strip()
    if not s:
        return None
    low = s.lower()
    hit = UI_TERMS.get(low)
    if hit is not None:
        return hit
    m = NUM_SUFFIX_RE.match(s)
    if m:
        term = m.group(1).strip().lower()
        num = m.group(2)
        hit = UI_TERMS.get(term)
        if hit is not None:
            return '%s %s' % (hit, num)
    return None


def is_short_term(text):
    """是否属于"极短术语"（用于统计快路径覆盖率）。"""
    s = (text or '').strip()
    return bool(s) and len(s) < SHORT_LEN and s.lower() in UI_TERMS


def term_count():
    return len(UI_TERMS)


if __name__ == '__main__':
    # 自检
    cases = [('Save', '存档'), ('save', '存档'), (' SAVE ', '存档'),
             ('Save 5', '存档 5'), ('load 10', '读取 10'),
             ('Auto Save', '自动存档'), ('Hello world', None),
             ('', None), (None, None), ('Save5', None)]
    bad = 0
    for inp, want in cases:
        got = lookup(inp)
        mark = 'OK ' if got == want else 'NG '
        if got != want:
            bad += 1
        print('%s lookup(%r) = %r  (want %r)' % (mark, inp, got, want))
    print('术语 %d 条 | %s' % (term_count(), 'ALL_PASS' if not bad else 'FAILED'))
