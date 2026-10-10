#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
语言自动检测（启发式，零第三方依赖）
====================================
**重点支持 5 种源语言：日语(ja) / 英语(en) / 韩语(ko) / 俄语(ru) / 西班牙语(es)**，
另保留中文(zh) 作为「原文已是目标语言」的判定（源语言下拉的 auto 依赖它跳过中文）。

针对游戏文本场景的轻量检测：
- 按 Unicode 书写范围判类：假名→ja、谚文→ko
- 汉字-only 时用假名排除法（无假名→zh）；但若含**日本新字体/国字**则判 ja
  （2026-10-07 修正：此前纯汉字日文会被误判为 zh，进而在 auto 模式下被跳过）
- 拉丁字母用**英语/西班牙语**高频词与特征字符区分 en/es
- 西里尔→ru
- 其余语言（法/德/意/葡/阿/泰等）**统一归为 other**，不再细分

设计取舍（2026-10-03）：
    需求为「只需识别出源语言是 日/英/韩/俄/西」。因此不再区分法德意葡等，
    认不出的拉丁文本一律按 en（游戏文本最常见），避免误判串到未维护的语言。
    检测不是百分百精确，是给翻译链路选提示词/路由用的"足够好"的判断。
"""
import re

# Unicode 区块（用字符区间判断，兼容窄 UCS-2）
RANGE_KANA = ((0x3040, 0x309F), (0x30A0, 0x30FF), (0x31F0, 0x31FF))   # 平假名/片假名
RANGE_HANGUL = ((0xAC00, 0xD7AF), (0x1100, 0x11FF), (0x3130, 0x318F))
RANGE_HAN = ((0x4E00, 0x9FFF), (0x3400, 0x4DBF), (0xF900, 0xFAFF))
RANGE_CYRILLIC = ((0x0400, 0x04FF),)
RANGE_LATIN = ((0x0041, 0x005A), (0x0061, 0x007A), (0x00C0, 0x024F))

# 高频词（按空格/标点切词后小写匹配）—— 只保留 en / es 两族
_WORD_HINTS = {
    'en': {'the', 'you', 'and', 'is', 'are', 'was', 'to', 'of', 'it', 'that',
           'what', 'with', 'for', 'not', 'this', 'have', 'will', 'your', 'my',
           'hello', 'welcome', 'thanks', 'thank', 'please', 'sorry', 'yes',
           'no', 'good', 'morning', 'come', 'here', 'can', 'do', 'go'},
    'es': {'el', 'los', 'las', 'una', 'que', 'por', 'para', 'con', 'pero',
           'muy', 'está', 'usted', 'gracias', 'hola', 'cómo', 'buenos',
           'días', 'señor', 'señora', 'bueno', 'estás', 'como', 'bien',
           'también', 'nada', 'todo', 'sí', 'no', 'más'},
}

# 特征字母：西班牙语专属变音符（en 无此类字符）
# 注意：不再收 fr/de/it/pt 的变音符，它们一律归 other / en
_ACCENT_HINTS = {
    'es': set('áéíóúñ¿¡'),
}

# 日本「新字体(shinjitai) / 国字(kokuji)」专有汉字集（2026-10-07 新增）。
# 用途：`detect_lang` 的「汉字-only」分支。
#   日语存在大量**不含假名**的文本（UI 词条 / 名词短语 / 标题，如 攻撃力・図鑑），
#   单靠「无假名 → zh」会把它误判为中文，进而在 auto 模式下被当成
#   「已是目标语言」跳过、根本不送翻译。
# 这些字是日本新字体或和制汉字的写法，**既非简体也非繁体中文的用字**：
#   圧(压/壓) 対(对/對) 実(实/實) 気(气/氣) … 込・畑・峠・辻（和制汉字）
# ⚠️ 不变式：**本集合内所有字符都无法用 GB2312 编码**（即都不是简体常用字），
#    由 test_lang_detector.py 的断言守住，防止日后误把常用字加进来导致误判。
# 已知局限：与繁体中文共用的汉字（設・電・無・確 等）不在此列 —— 繁中与日语
#    字形相同，无法可靠区分，故这类纯汉字文本仍归 zh（宁可漏判，不可误判）。
_JP_ONLY_KANJI = frozenset(
    '圧対実気単変図団売読戦発経続総転覚験検権産価帰訳営挙薬険剣拡拠縁齢掲渉稲'
    '増徳恵歩収児沢択駅摂拝頬顕畳剰塁塩壌壊寛専浄遅鉄録錬剤帯済亜悪囲壱隠栄桜応'
    '仮絵楽渇巻陥歓観犠暁駆勲薫渓蛍軽継撃県倹圏厳戸呉娯効広鉱黒砕斎雑桟賛歯舎釈'
    '従渋獣縦粛処奨乗縄嬢譲醸酔粋穂髄瀬斉説'
    '込畑峠辻働凪雫榊匂凧〆')


def _has_jp_only_kanji(text):
    """文本中是否出现日本专有汉字（新字体 / 国字）。"""
    return any(ch in _JP_ONLY_KANJI for ch in text)

LANG_NAMES = {
    'ja': '日语', 'en': '英语', 'ko': '韩语', 'ru': '俄语', 'es': '西班牙语',
    'zh': '中文', 'other': '未知',
}

# 对外声明「重点支持的源语言」——GUI 下拉/提示可据此列出
SUPPORTED = ('ja', 'en', 'ko', 'ru', 'es')


def _in_ranges(ch, ranges):
    o = ord(ch)
    return any(lo <= o <= hi for lo, hi in ranges)


def _count_class(text, ranges):
    return sum(1 for ch in text if _in_ranges(ch, ranges))


def detect_lang(text):
    """检测单条文本语言，返回语言码（'other' 表示无法判断/非重点语言）。

    返回值只可能是：'ja' / 'en' / 'ko' / 'ru' / 'es' / 'zh' / 'other'。
    """
    text = (text or '').strip()
    if not text:
        return 'other'
    letters = [ch for ch in text if ch.isalpha()]   # 数字/符号不计入
    if not letters:
        return 'other'
    n = len(letters)

    kana = _count_class(text, RANGE_KANA)
    if kana >= max(1, n * 0.05):          # 有假名几乎必是日语
        return 'ja'
    hangul = _count_class(text, RANGE_HANGUL)
    if hangul >= n * 0.3:
        return 'ko'
    cyr = _count_class(text, RANGE_CYRILLIC)
    if cyr >= n * 0.3:
        return 'ru'

    han = _count_class(text, RANGE_HAN)
    latin = _count_class(text, RANGE_LATIN)
    if han >= n * 0.3:                     # 有汉字但无假名
        # 默认判中文（目标语言）。但先排除「纯汉字日文」——
        # 出现日本新字体/国字即判日语（见 _JP_ONLY_KANJI，对简中/繁中零误伤）。
        if _has_jp_only_kanji(text):
            return 'ja'
        return 'zh'
    if latin >= n * 0.3:
        return _detect_latin(text, n)
    # 阿拉伯 / 泰文等不再细分 → other
    return 'other'


def _detect_latin(text, n):
    """拉丁文本只在 en / es 之间判别；认不出按 en（游戏文本最常见）。"""
    low = text.lower()
    # 1) 西班牙语特征变音符（¿¡ñ 及重音）——英语无此类字符
    best_cnt = sum(1 for ch in low if ch in _ACCENT_HINTS['es'])
    if best_cnt >= max(1, n * 0.02):
        return 'es'
    # 2) 高频词打分（en / es）
    words = re.findall(r"[a-zà-ÿ']+", low)
    if not words:
        return 'en'
    split_words = []                       # 撇号分词（如 es: d'… 极少，稳妥处理）
    for w in words:
        split_words.extend(p for p in w.split("'") if p)
    scores = {lang: sum(1 for w in split_words if w in hints)
              for lang, hints in _WORD_HINTS.items()}
    # 先看西班牙语分是否明显领先；否则默认 en
    es_score = scores.get('es', 0)
    en_score = scores.get('en', 0)
    if es_score > en_score:
        return 'es'
    return 'en'


def detect_dominant(texts, min_samples=5):
    """批量检测主导语言。返回 (lang, ratio, counts) —— ratio 为主导语言占比。"""
    counter = {}
    total = 0
    for t in texts:
        if not t or not (t or '').strip():
            continue
        lang = detect_lang(t)
        if lang != 'other':
            counter[lang] = counter.get(lang, 0) + 1
            total += 1
    if not counter:
        return 'other', 0.0, {}
    lang = max(counter, key=lambda k: counter[k])
    cnt = counter[lang]
    return lang, (cnt / total if total else 0.0), dict(counter)


if __name__ == '__main__':
    demo = [
        ('Hello, traveler! Welcome to our town.', 'en'),
        ('こんにちは、旅の方！ようこそ。', 'ja'),
        ('안녕하세요, 여러분.', 'ko'),
        ('Привет, путник!', 'ru'),
        ('Hola, ¿cómo estás? Gracias.', 'es'),
        ('欢迎来到我们的小镇。', 'zh'),
        # 以下语言已裁剪：预期归 other 或 en
        ('Bonjour, comment allez-vous?', 'other/en'),
        ('Guten Morgen, wie geht es dir?', 'other/en'),
        ('สวัสดีครับ', 'other'),
    ]
    for s, expect in demo:
        got = detect_lang(s)
        print('%-8s expect=%-9s got=%-3s  %r' % ('[demo]', expect, got, s[:36]))
    print('SUPPORTED =', SUPPORTED)
