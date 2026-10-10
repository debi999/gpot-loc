# -*- coding: utf-8 -*-
"""batch_fast —— 本地 LLM 翻译「大批量 + 二分拆批重试」加速通道。

【为什么需要它·2026-10-07 实测】
    在 hy-mt2-30b-a3b-apex:nano + RTX 5080 上用**真实游戏资产**做了 7 组
    对照实验（48 条真实样本），结论与直觉相反：

    | 策略                                    | 每条均耗时 | 对齐率 |
    |-----------------------------------------|-----------|--------|
    | 当前 GUI：<<<SPLIT>>> 合并 20条/1500字    | 0.571s    | 58%   |
    | 逐条（无 max_tokens）                      | 0.286s    | 100%  |
    | 逐条 + max_tokens=256                     | 0.212s    | 100%  |
    | 编号行大批量（裸，无重试）                 | 0.100s    | 75~80%|
    | **大批量 + 二分拆批重试（本模块）**        | **0.146s**|**100%**|

    即：**「提示词长导致慢」并不成立**。
      · 空提示词反而慢到 2.69s/条 —— 模型失去约束开始"加戏"，
        输出 token 爆炸；**耗时≈输出长度**，这才是真正的瓶颈。
      · 长提示词(1461字符)与精简提示词(153字符)几乎同速
        (0.16s vs 0.15s)，因为短文本的 prefill 开销远小于 decode。
    真正的杠杆 = **减少请求次数**（摊薄固定开销）+ **限制输出长度**。

【旧批量通道为何是负优化】
    `<<<SPLIT>>>` 分隔符合并请求实测**对齐率仅 58%** —— 模型经常不原样
    吐分隔符，一旦解析失败整批作废并**逐条降级**，等于白跑一遍还多付一次
    请求，故 0.571s/条 反而比逐条(0.286s/条)慢一倍。

【本模块的做法】
    改用「一行一条 + 严格等行数返回」，并用**二分拆批递归重试**保证
    100% 对齐：行数不匹配就把这批对半拆开分别重试，递归到单条。
    实测 720 条 / 12 次请求仅拆批 3 次，代价可忽略。

【红线：绝不让错位译文进入资产】
    行数不匹配时**绝不返回**「猜测对齐」的结果（那会把 A 的译文写到 B 上）。
    只有成功对齐才写值，失败留None 交由上层记为失败项。
    探测 5 实测模型会回显编号（'1. 第一行'），故强制剥离前导编号。

【索引安全】
    内部一律用**位置**而非「原文文本」做键：游戏资产里存在大量重复
    原文，若用 dict 按文本映射会把重复条串位。
"""

import re

__all__ = ['BATCH_MAX_ITEMS', 'BATCH_MAX_CHARS', 'SINGLE_MAX_CHARS',
           'build_batch_prompt', 'parse_batch_lines', 'strip_leading_number',
           'fast_translate_batch', 'plan_batches', 'BatchStats',
           'BATCH_SYSTEM']

# ---- 参数（由探测 5「批大小拐点」实验定档）--------------------------------
# 20/40/60/80 条每批的每条耗时几乎持平(0.131/0.132/0.142/0.139s)，
# 说明瓶颈在 decode 而非请求数；取 40 作为对齐率与风险的平衡点。
BATCH_MAX_ITEMS = 40
# 总字符上限：防止超长文本把 prompt 撑爆导致输出被截断。
BATCH_MAX_CHARS = 4000
# 单条超过此长度独立走单条请求：超长对白单独翻译质量更稳，
# 且避免它在批里把其他条目的输出挤掉。
SINGLE_MAX_CHARS = 300

# 严格等行数 + 禁编号的 system 提示词（探测 6 验证）
BATCH_SYSTEM = (
    "你是游戏汉化引擎，把输入的外文游戏文本译成简体中文。\n"
    "输出规则（必须严格遵守）：\n"
    "1. 输入有 N 行，输出必须正好 N 行，逐行对应。\n"
    "2. 每行只写译文本身。禁止输出行号、编号、序号、引导符号、"
    "破折号、引号、注释或任何解释。\n"
    "3. 占位符 {0} {name} <b> <color=#xxx> \\n %s 原样保留。\n"
    "4. 已是中文或纯数字/符号/路径/URL，原样返回该行。\n"
    "5. 忠实原意，不加戏不扩写。\n"
)

# 模型回显的前导编号：'1. ' / '[2] ' / '(3) ' / '4) ' / '#5 ' / '第6条'
_NUM_PREFIX = re.compile(
    r'^\s*(?:\[\s*\d+\s*\]|\(\s*\d+\s*\)|#\s*\d+\s*'
    r'|\d+\s*[\.\)、,，:：]'
    r'|第\s*\d+\s*[条行個个])\s*')


def strip_leading_number(line):
    """剥离模型回显的行首编号。

    探测 5 实测模型会输出 '1.第一行' 这类带编号内容；
    若不剥离，编号会被当成译文的一部分写进资产。
    """
    return _NUM_PREFIX.sub('', line or '').strip()


def build_batch_prompt(texts):
    """构造等行数批请求的 user prompt。texts 已 strip 且不含换行。"""
    return '把下面 %d 行游戏文本逐行译成简体中文：\n\n%s' % (
        len(texts), '\n'.join(texts))


def parse_batch_lines(raw, expect):
    """解析成恰好 expect 行；不匹配返回 None。

    绝不返回长度与 expect 不同的结果 —— 那意味着译文与原文错位。
    """
    if not raw:
        return None
    lines = [strip_leading_number(l) for l in raw.split('\n')]
    while lines and not lines[-1]:
        lines.pop()
    if len(lines) != expect or any(not l for l in lines):
        return None
    return lines


class BatchStats(object):
    """加速通道统计，供 GUI 展示与回归断言。"""

    def __init__(self):
        self.requests = 0      # 实际发出的模型请求数
        self.splits = 0        # 二分拆批次数
        self.singles = 0       # 单条请求次数
        self.failed = 0        # 最终失败(留None)的条数

    def as_dict(self):
        return {'requests': self.requests, 'splits': self.splits,
                'singles': self.singles, 'failed': self.failed}

    def __repr__(self):
        return ('BatchStats(requests=%d, splits=%d, singles=%d, failed=%d)'
                % (self.requests, self.splits, self.singles, self.failed))


def plan_batches(items):
    """把 [(index, text), ...] 切成批。

    返回 [[(index, text), ...], ...]。超长条（>SINGLE_MAX_CHARS）独立成批，
    其余按条数与总字符双上限成批。
    """
    batches, cur, chars = [], [], 0
    for idx, txt in items:
        if len(txt) > SINGLE_MAX_CHARS:
            batches.append([(idx, txt)])
            continue
        if cur and (len(cur) >= BATCH_MAX_ITEMS or
                    chars + len(txt) > BATCH_MAX_CHARS):
            batches.append(cur)
            cur, chars = [], 0
        cur.append((idx, txt))
        chars += len(txt)
    if cur:
        batches.append(cur)
    return batches


def fast_translate_batch(texts, ask, stats=None):
    """大批量 + 二分拆批重试的翻译主流程。

    参数
    ----
    texts : list[str] 待译原文（空串/纯空白 → 返回 ''）
    ask   : callable(list[str]) -> str  送一批原文、返回模型原始多行文本
    stats : BatchStats 可选

    返回
    ----
    与 texts 等长的列表：成功为译文，失败为 None（**绝不返回错位译文**）。
    """
    if stats is None:
        stats = BatchStats()
    out = [None] * len(texts)
    items = []
    for i, t in enumerate(texts):
        s = (t or '').strip()
        if not s:
            out[i] = ''
        elif '\n' in s or '\r' in s:
            # 含换行的条目无法用「一行一条」表达，探测 5 实测会多吐行
            out[i] = _ask_single(s, ask, stats, i, out)
        else:
            items.append((i, s))
    for batch in plan_batches(items):
        _solve(batch, ask, stats, out)
    return out


def _ask_single(text, ask, stats, idx, out):
    """含换行条目：走单条请求。

    含换行的原文无法用「一行一条」表达，其译文也可能是多行，
    因此这里接受整段返回（与旧单条路径行为一致）。
    """
    stats.singles += 1
    stats.requests += 1
    try:
        raw = ask([text])
    except Exception:
        raw = None
    val = (raw or '').strip()
    if val:
        return val
    stats.failed += 1
    return None


def _solve(batch, ask, stats, out):
    """对齐一批；不对齐则二分拆批递归重试。

    batch: [(index, text), ...]
    """
    if len(batch) == 1:
        idx, txt = batch[0]
        stats.singles += 1
        stats.requests += 1
        try:
            raw = ask([txt])
        except Exception:
            raw = None
        # 【红线】单条也必须「恰好一行」才算成功。
        # 模型可能先吐一行寒暄/说明再给译文（如 '多余行\n译文'），
        # 若直接取第一行会把那句说明当成译文写进资产。
        # 含换行的原文本就不进批（见 fast_translate_batch），
        # 故此处出现多行即判定为「无法确定哪行是译文」→ 交 None 上层降级。
        lines = [strip_leading_number(l) for l in (raw or '').split('\n')]
        lines = [l for l in lines if l]
        if len(lines) == 1:
            out[idx] = lines[0]
        else:
            stats.failed += 1
        return
    stats.requests += 1
    try:
        raw = ask([t for _, t in batch])
    except Exception:
        raw = None
    lines = parse_batch_lines(raw, len(batch))
    if lines is not None:
        for (idx, _), zh in zip(batch, lines):
            out[idx] = zh
        return
    # 对不齐 → 二分拆批（探测 7：720 条仅拆 3 次，代价可忽略）
    stats.splits += 1
    mid = len(batch) // 2
    _solve(batch[:mid], ask, stats, out)
    _solve(batch[mid:], ask, stats, out)