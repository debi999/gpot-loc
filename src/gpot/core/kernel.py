"""业务内核 —— 从旧库 gui/StarmakerTranslator.py (v3.29) 拆出的唯一真源。

M2 迁移（2026-10-10）：**只搬家不改逻辑**。本文件 = 旧库主程序的第 232~2144 行
（常量 / 工具函数 / 提取与护栏 / TranslationStore / Translator 8 后端 / CSV / 配置）
原样搬入，仅做两处适配：
  1. 去掉 tkinter 导入（业务段本就零 tkinter 引用，已 grep 验证）；
  2. 同目录兄弟模块改为包内相对导入（engine_detector / lang_detector /
     ui_terms / rpgmaker_engine / batch_fast / kit_catalog / kit_installer）。
旧版 App 类（tkinter 界面）与 _TipBalloon / launch_gui **不迁**——UI 由
src/gpot/ui/ 的 WebView2 前端接手。版本历史详见旧库文件头。
"""
from __future__ import annotations

import os
import re
import sys
import csv
import json
import time
import mmap
import struct
import threading
import urllib.parse
import urllib.request
import urllib.error
import configparser

# M2 迁移适配：原 try/except ImportError 的可选导入改为包内相对导入
# （模块已随包迁入，必然存在；业务代码里的 `if batch_fast:` 真值判断不受影响）
from . import engine_detector
from . import lang_detector
from . import ui_terms
from . import rpgmaker_engine
from . import batch_fast
from . import kit_catalog
from . import kit_installer

# ----------------------------------------------------------------------------
# 常量 / 基础工具
# ----------------------------------------------------------------------------
APP_NAME = "独游翻译器 · 翻译管理器"
APP_VERSION = "3.29"

APP_DIR = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) \
    else os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(APP_DIR, 'config.ini')

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

CJK_RE = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf]')
ASCII_LETTER_RE = re.compile(r'[A-Za-z]')

LANG_MAP = {
    'zh': 'zh-CN', 'chinese': 'zh-CN', 'zh-cn': 'zh-CN', 'zh_cn': 'zh-CN',
    'zh-tw': 'zh-TW', 'zh-hant': 'zh-TW', 'zh_tw': 'zh-TW',
    'en': 'en', 'english': 'en', 'ja': 'ja', 'japanese': 'ja', 'jp': 'ja',
    'ko': 'ko', 'korean': 'ko', 'fr': 'fr', 'de': 'de', 'es': 'es', 'ru': 'ru',
}
DEEPL_MAP = {'zh-cn': 'ZH', 'zh-tw': 'ZH', 'zh': 'ZH', 'en': 'EN', 'ja': 'JA',
             'ko': 'KO', 'fr': 'FR', 'de': 'DE', 'es': 'ES', 'ru': 'RU'}
BAIDU_MAP = {'zh-cn': 'zh', 'zh': 'zh', 'en': 'en', 'ja': 'jp', 'ko': 'kor',
             'fr': 'fra', 'de': 'de', 'es': 'spa', 'ru': 'ru'}

# 翻译提供方预设
PROVIDERS = ['免费Google', 'OpenAI兼容', '本地Ollama/Qwen',
             'DeepSeek', 'Claude', 'Gemini', 'DeepL', '百度翻译']
PROVIDER_PRESETS = {
    '免费Google': {'base': '', 'model': '', 'need_key': False,
                   'hint': '无需密钥，走 Google 免费接口'},
    'OpenAI兼容': {'base': 'https://api.openai.com/v1', 'model': 'gpt-4o-mini',
                   'need_key': True, 'hint': '兼容 OpenAI 的接口(含本地 Ollama/混元等)'},
    '本地Ollama/Qwen': {'base': 'http://127.0.0.1:11434/v1',
                        'model': 'qwen3.8:27b-q4_K_M',
                        'need_key': False,
                        'hint': 'Ollama 本地任意模型(Qwen/HY-MT2等)：自动检测模型下拉自选，选择会同步到游戏内实时翻译'},
    'DeepSeek':  {'base': 'https://api.deepseek.com/v1', 'model': 'deepseek-chat',
                  'need_key': True, 'hint': 'DeepSeek 官方接口'},
    'Claude':    {'base': 'https://api.anthropic.com/v1', 'model': 'claude-3-5-sonnet-latest',
                  'need_key': True, 'hint': 'Anthropic Claude'},
    'Gemini':    {'base': 'https://generativelanguage.googleapis.com/v1beta',
                  'model': 'gemini-1.5-flash', 'need_key': True, 'hint': 'Google Gemini'},
    'DeepL':     {'base': 'https://api-free.deepl.com/v2', 'model': '',
                  'need_key': True, 'hint': 'DeepL (免费/Pro 域名为自动识别)'},
    '百度翻译':  {'base': 'https://fanyi-api.baidu.com/api/trans/vip', 'model': '',
                  'need_key': True, 'need_appid': True, 'hint': '百度翻译开放平台'},
}

# 本地 Ollama 族提供方：切换/启动时自动探测模型列表，并把选择同步到游戏内注入式翻译服务
# (v3.14: 原「本地HY-MT2」与「本地Ollama/Qwen」功能重复，已合并为后者)
LOCAL_PROVIDERS = ('本地Ollama/Qwen',)

# 走 OpenAI /chat/completions 协议族的提供方(测试连接等按其协议处理)
OPENAI_FAMILY = ('OpenAI兼容', 'DeepSeek', '本地Ollama/Qwen')

# 保存备份轮转代数: .bak(上一版) / .bak1 / .bak2, 最多保留三代
BACKUP_MAX_GENS = 3

# 游戏内注入式翻译服务配置文件模板（HyMT2LocalServer.exe 同目录 server_config.ini）
SERVER_CONFIG_TEMPLATE = """; ============================================================
; 本地翻译服务配置 —— 由「独游翻译器·翻译管理器」自动生成/同步
; 修改后保存, 再重启翻译服务/游戏即生效 —— 无需改代码、无需重新打包
; 编码必须为 UTF-8 (本文件自带 BOM 亦可, 会被自动跳过)
; ============================================================

[server]
; 监听端口 (XUnity 插件请求的地址写死为 http://127.0.0.1:18765/translate,
; 一般不需要改; 只有同时改插件 Config 时才动这里)
port = 18765

[ollama]
; Ollama / llama.cpp / Xinference 的 OpenAI 兼容接口地址
base = {base}
; 使用的模型名 —— 必须与 `ollama list` 输出的名字完全一致
model = {model}

[request]
; 单次请求超时(秒)。本地大模型首次加载权重可能很慢, 默认 5 分钟
timeout = 300
; 单条文本最大长度(与 XUnity MaxCharactersPerTranslation=2500 保持一致)
max_text = 2500
"""

LLM_SYSTEM = (
    "<Role>\n"
    "你是一位拥有10年经验的资深游戏本地化专家，专注于官能游戏（成人向游戏）的现代都市题材。"
    "你的核心原则是\u201c信、达、雅\u201d基础上的\u201c游戏适配性\u201d。你必须严格克制，绝不允许擅自加戏、扩写或过度艺术加工。\n"
    "</Role>\n"
    "\n"
    "<Context>\n"
    "- 游戏类型：官能游戏 / 现代都市\n"
    "- 文本基调：原汁原味、精准还原、符合UI与配音限制\n"
    "</Context>\n"
    "\n"
    "<StrictRules>\n"
    "1. 绝对忠实原文结构：严禁擅自增加原文没有的动作、神态、心理描写或修饰词。原文是一句简短的话，译文也必须是一句简短的话。\n"
    "2. 精准替换而非扩写：遇到英文粗俗俚语（如 MILF），仅在词汇层面进行意译替换，不改变原句的语法结构。\n"
    "   - 若原文为 \"She is a MILF\"，仅翻译为 \u201c她是个尤物\u201d 或 \u201c她是个熟女\u201d，绝不扩写为 \u201c她是个散发着成熟魅力的尤物\u201d。\n"
    "3. 标点符号克制：除非原文本身带有省略号或感叹号，否则不要为了表现\u201c喘息\u201d或\u201c娇嗔\u201d而擅自添加波浪号（~）或省略号（\u2026\u2026）。保持标点与原文一致。\n"
    "4. 字数与UI限制：中文译文长度应尽量与原文长度保持视觉上的平衡，避免过长导致游戏UI爆框。\n"
    "5. 词汇选择：在保持克制的前提下，依然要使用符合官能游戏调性的词汇（如：尤物、熟女、娇妇等），避免使用低俗直白的脏话，但要保留原文的性张力。\n"
    "</StrictRules>\n"
    "\n"
    "<TerminologyRules>\n"
    "\u3010最高优先级\u3011当输入文本中包含游戏系统术语、UI按钮或功能提示时，必须使用绝对直译，禁止任何艺术加工或意译。\n"
    "- 常见术语对照（包括但不限于）：\n"
    "  - Start Game / New Game -> 开始游戏 / 新游戏\n"
    "  - Load / Save -> 读取 / 存档\n"
    "  - Settings / Options -> 设置 / 选项\n"
    "  - Skip -> 跳过\n"
    "  - Back / Return -> 返回\n"
    "  - Confirm / Cancel -> 确认 / 取消\n"
    "- 若遇到上述或类似的系统级词汇，直接输出对应的标准中文，不得添加任何修饰语。\n"
    "</TerminologyRules>\n"
    "\n"
    "【输出要求】\n"
    "输出 ONLY 翻译后的中文文本，不要有任何解释、注释或引号。\n"
    "保留所有占位符（如 {0}, {name}, <b>, \\n, %s）不变。"
)


def norm_lang(code):
    if not code:
        return code
    return LANG_MAP.get(code.lower(), code)


def deepl_lang(code):
    if not code:
        return code
    c = code.lower()
    return DEEPL_MAP.get(c, c.upper()[:2])


def baidu_lang(code):
    if not code:
        return code
    c = code.lower()
    return BAIDU_MAP.get(c, c)


def normalize(s):
    return re.sub(r'\s+', ' ', (s or '')).strip().lower()


def has_cjk(s):
    return bool(CJK_RE.search(s or ''))


def is_english_left(original, translation):
    t = (translation or '').strip()
    if not t:
        return True
    if t == (original or '').strip():
        return True
    if not has_cjk(t) and ASCII_LETTER_RE.search(t):
        return True
    return False


def classify(original, translation):
    if is_english_left(original, translation):
        if not (translation or '').strip():
            return 'untranslated'
        return 'english'
    return 'translated'


def build_kw_pattern(kw, case_sensitive=False, whole_word=False):
    """按关键字构建字面匹配 pattern(非正则)。
    全词匹配: 纯英文用 \\b 词边界; 含中文时用 CJK 边界断言
    (排除关键字与相邻中文粘在一起时的误配)。"""
    flags = 0 if case_sensitive else re.IGNORECASE
    is_eng = all(c.isascii() and not c.isspace() for c in kw)
    if whole_word:
        if is_eng:
            return re.compile(r'\b' + re.escape(kw) + r'\b', flags)
        prefix = r'(?:^|(?<=[^\u4e00-\u9fff\u3400-\u4dbf]))'
        suffix = r'(?:$|(?=[^\u4e00-\u9fff\u3400-\u4dbf]))'
        return re.compile(prefix + re.escape(kw) + suffix, flags)
    return re.compile(re.escape(kw), flags)


# ----------------------------------------------------------------------------
# 游戏目录 / 资源文件定位
# ----------------------------------------------------------------------------
def find_game_dir(start=None, hint=None):
    """定位游戏根目录。

    hint: 优先尝试的目录(通常来自 config.ini 里记忆的 game_dir)。
          v3.18 起「配置记忆值」是第一优先级来源; 向上查找降级为**兜底**,
          因为程序位于游戏目录内/外都可能(见 P0-4 / P2-1)。
    返回 None 表示未找到。
    """
    # ① 配置记忆的目录优先(用户曾经选过, 以用户意图为准)
    if hint:
        h = os.path.abspath(hint)
        if os.path.isdir(h):
            return h
    if start is None:
        start = os.path.dirname(os.path.abspath(__file__))
    cur = os.path.abspath(start)
    # ② 从自身位置向上查找(适用于程序仍放在游戏目录内的情况)
    for _ in range(8):
        if os.path.isdir(os.path.join(cur, 'BepInEx', 'Translation')):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    # ③ 兜底: 向上找含 starmaker 主程序的目录
    cur = os.path.abspath(start)
    for _ in range(8):
        try:
            for f in os.listdir(cur):
                if f.lower().endswith('.exe') and 'starmaker' in f.lower():
                    return cur
        except Exception:
            pass
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return None


def translation_file_path(game_dir):
    # v3.27：**RPG Maker 走独立资产文件**。RPG Maker 没有 BepInEx，
    # 沿用 Unity 路径会退到一个不存在的默认位置 → GUI 里「打开游戏目录」
    # 永远找不到文件。放在最前面判，不影响 Unity 行为。
    if rpgmaker_engine is not None:
        try:
            ok, data_dir, _engine = rpgmaker_engine.detect(game_dir)
        except Exception:
            ok, data_dir = False, None
        if ok:
            # 放在 www/data 的同级（游戏根）下，避免污染引擎数据目录
            root = os.path.dirname(os.path.dirname(data_dir))
            return os.path.join(root, '_AutoGeneratedTranslations.txt')

    candidates = []
    cfg_lang = read_config_lang(game_dir)
    if cfg_lang:
        candidates.append(os.path.join(game_dir, 'BepInEx', 'Translation', cfg_lang,
                                       'Text', '_AutoGeneratedTranslations.txt'))
    for lang in ('zh', 'zh-CN', 'cn', 'chinese'):
        candidates.append(os.path.join(game_dir, 'BepInEx', 'Translation', lang,
                                       'Text', '_AutoGeneratedTranslations.txt'))
    base = os.path.join(game_dir, 'BepInEx', 'Translation')
    if os.path.isdir(base):
        for lang in os.listdir(base):
            p = os.path.join(base, lang, 'Text', '_AutoGeneratedTranslations.txt')
            if os.path.isfile(p):
                candidates.append(p)
    for c in candidates:
        if os.path.isfile(c):
            return c
    # 文件尚不存在时返回默认期望路径
    return os.path.join(game_dir, 'BepInEx', 'Translation', 'zh', 'Text',
                        '_AutoGeneratedTranslations.txt')


def extract_rows_rpgmaker(game_dir):
    """v3.27：RPG Maker MV/MZ 提取。返回 `[(source, key_or_None), ...]`。

    与 Unity 路径的差异：RPG Maker 的 key（如 `Actors.json#obj1-name`）**可选**——
    GUI 的资产格式是 `原文=译文`，没有 key 概念，故只取原文，key 留空。
    保留 key 的价值在于将来支持回写；本版GUI 只做提取，先不落key。

    返回的 rows 已按 `normalize()` 去重（同原文只留一条）。
    """
    if rpgmaker_engine is None:
        return []
    ok, _data_dir, engine = rpgmaker_engine.detect(game_dir)
    if not ok:
        return []
    rows, _info = rpgmaker_engine.extract(game_dir)
    if not rows:
        # 兜底：结构化提取为空时用通用扫描，至少别让用户看到「0 条」
        rows, _ = rpgmaker_engine.extract_generic(game_dir)
        if rows:
            print('[RPGMaker] 结构化提取为空，已回退通用扫描：%d 条' % len(rows))
    seen = set()
    out = []
    for key, src in rows:
        norm = normalize(src)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        out.append((src, key))
    return out


def find_asset_files(game_dir, deep=False):
    """返回所有待扫描的 Unity 资源文件 (.assets / .resource / level*)。

    v3.22：只收录**真正的 Unity 序列化文件**（头部含版本串），跳过无关的
    .resource 后缀文本与目录噪声。

    v3.23（召回率专项实测）：
      * 旧代码里的 `if low.endswith('.ress'): continue` 是**死代码** ——
        头部校验 `_unity_header` 本来就会把 resS 全拦掉。留着只会误导人。
      * 实测本游戏 resS + .resource 共 1,107.5 MB（占 _Data 目录 91.3%），
        强制全扫后独立真文本 **0 条**（resS 里只有浮点/图形噪声）→ 默认
        不扫是对的。
      * 但**别的 Unity 游戏**（尤其把文本塞进 resS 的）需要扫，故加
        `deep=True` 开关：收录 resS / .resource，并跳过 header 校验。
        代价：扫描时间从 ~40s 涨到数分钟，噪声需靠 keep_* 判据兜。
    """
    dirs = set()
    # 优先：与 .exe 同名的 *_Data 目录（Unity 标准布局）
    try:
        for name in os.listdir(game_dir):
            p = os.path.join(game_dir, name)
            if os.path.isdir(p) and name.endswith('_Data'):
                dirs.add(p)
    except Exception:
        pass
    for cand in [os.path.join(game_dir, 'Starmaker Story_Data'),
                 os.path.join(game_dir, 'Starmaker 1.8E', 'Starmaker Story_Data')]:
        if os.path.isdir(cand):
            dirs.add(cand)
    # 兜底：递归查找任意 *_Data 目录
    for root, ds, _ in os.walk(game_dir):
        if os.path.basename(root).endswith('_Data'):
            dirs.add(root)
            ds[:] = []          # 不再深入 _Data 的子目录（Plugins/Resources 无文本）
    files = []
    for d in sorted(dirs):
        try:
            names = os.listdir(d)
        except Exception:
            continue
        for name in names:
            low = name.lower()
            if low.startswith('level'):
                files.append(os.path.join(d, name))
            elif low.endswith(('.assets', '.resource', '.ress')):
                if not deep and low.endswith('.ress'):
                    continue     # deep 模式才收 resS
                files.append(os.path.join(d, name))
    if deep:
        return files           # resS/.resource 无版本串，跳过 header 校验
    # 只保留头部可识别的 Unity 序列化文件
    out = []
    for p in files:
        try:
            with open(p, 'rb') as f:
                head = f.read(64)
            if _unity_header(head):
                out.append(p)
        except Exception:
            pass
    return out



def _unity_header(head):
    """判断前 64 字节是否为 Unity 序列化文件头，返回 (data_offset, file_size, ver)。
    头布局（大端）：fileSize@28, dataOffset@36, 版本串@48。"""
    if len(head) < 64:
        return None
    try:
        fs = struct.unpack_from('>I', head, 28)[0]
        do = struct.unpack_from('>I', head, 36)[0]
        ver = head[48:64].split(b'\x00')[0].decode('ascii', 'ignore')
        if fs <= 0 or do <= 0 or do > fs:
            return None
        if not re.match(r'^\d{4}\.\d+\.\d+', ver):
            return None
        return do, fs, ver
    except Exception:
        return None


def read_config_lang(game_dir):
    ini = os.path.join(game_dir, 'BepInEx', 'config', 'AutoTranslatorConfig.ini')
    lang = None
    from_lang = None
    if os.path.isfile(ini):
        try:
            with open(ini, encoding='utf-8-sig', errors='ignore') as f:
                section = None
                for line in f:
                    line = line.strip()
                    if not line or line.startswith(';') or line.startswith('#'):
                        continue
                    if line.startswith('[') and line.endswith(']'):
                        section = line[1:-1]
                        continue
                    if '=' in line:
                        k, v = line.split('=', 1)
                        k = k.strip().lower()
                        v = v.strip()
                        if section == 'General':
                            if k == 'language':
                                lang = v
                            elif k == 'fromlanguage':
                                from_lang = v
        except Exception:
            pass
    return lang or from_lang


def read_translation_service(game_dir):
    info = {'deepl_key': '', 'baidu_id': '', 'baidu_secret': ''}
    ini = os.path.join(game_dir, 'BepInEx', 'config', 'AutoTranslatorConfig.ini')
    if not os.path.isfile(ini):
        return info
    try:
        with open(ini, encoding='utf-8-sig', errors='ignore') as f:
            section = None
            for line in f:
                line = line.strip()
                if not line or line.startswith(';') or line.startswith('#'):
                    continue
                if line.startswith('[') and line.endswith(']'):
                    section = line[1:-1]
                    continue
                if '=' in line:
                    k, v = line.split('=', 1)
                    k = k.strip().lower()
                    v = v.strip()
                    if section == 'DeepLLegitimate' and k == 'apikey':
                        info['deepl_key'] = v
                    elif section == 'Baidu':
                        if k == 'baiduappid':
                            info['baidu_id'] = v
                        elif k == 'baiduappsecret':
                            info['baidu_secret'] = v
    except Exception:
        pass
    return info


# ----------------------------------------------------------------------------
# 逆向解包：资源文件字符串提取（v3.22 重写）
# ----------------------------------------------------------------------------
# 设计要点（对照 AssetsTools.NET / UABEA / Il2CppDumper 的做法）：
#   1. 只扫描 Unity 序列化文件的 **数据段**（data_offset 之后），跳过类型树与
#      asset 元数据区——那里全是 classID/路径/哈希，是噪声的主要来源；
#   2. 原生文本（日/中/韩）走 CJK 通道：UTF-8 解码 + 相邻可读字节聚簇，
#      要求 ≥2 个 CJK 字符。这个方法对 IL2CPP 与 Mono 通用；
#   3. 英文文本走 ASCII 通道：严格词形判定（见 keep_string），
#      拒绝随机二进制碎片（如 'q NF' / 'b* GP' / 'F+ Vxlt@'）；
#   4. 资源/动画/材质标识符（含下划线、混合大小写英文）统一剔除。
# ----------------------------------------------------------------------------
ASCII_RE = re.compile(rb'[\x20-\x7e]{4,}')
UTF16_RE = re.compile(rb'(?:[\x20-\x7e]\x00){4,}')
# 相邻可读文本聚簇：连续 UTF-8（含 CJK 多字节）字节
TEXT_RUN_RE = re.compile(
    rb'(?:[\x20-\x7e]|[\xc2-\xdf][\x80-\xbf]|[\xe0-\xef][\x80-\xbf]{2}'
    rb'|[\xf0-\xf4][\x80-\xbf]{3})+')

NOISE_TOKENS = ('/', '\\', '://', '.dll', '.png', '.asset', '.unity', '.cs',
                '.shader', '.mat', '.asset', '0x', 'UnityEngine', 'UnityEditor',
                'Assets/', 'Packages/', 'Library/', 'ProjectSettings/', '.prefab',
                '.bytes', '.txt', '.json', '.wav', '.mp3', '.ogg', '.fbx',
                'Assembly-CSharp', 'System.', 'Unity.', 'TMPro', 'TextMeshPro')

# 引擎内部 pass/材质名：即使是自然英文短语也**不可翻译**，必须剔除
#
# v3.23 修正（召回率专项）：旧版用 `any(term in low)` **子串匹配**，且表里
# 混着大量 2~4 字母短词（coc/lod/uv/mask/root/queue/icon），导致：
#   - 'coc' 命中 'cocks'（真台词）→ 'Mmm... two hard cocks already?' 被毙
#   - 'lod'/'uv'/'root' 命中任意超集
# 实测 3,682 条漏条里有 569 条(15.5%)死于本判据，是第二大误杀源。
# 修法：① 拆成「单词」与「短语」两表——单词走**词边界集合匹配**，
#       短语才允许子串匹配（'depth of field' 这类必须按子串）；
#      ② 单词表只保留 ≥5 字母的术语，短词一律删除。
_ENGINE_SINGLE = frozenset((
    # 渲染 / 后处理
    'blur', 'prefilter', 'upsample', 'downsample', 'bloom', 'bokeh', 'panini',
    'tonemapping', 'distortion', 'aberration', 'vignette', 'occlusion',
    'antialiasing', 'antialias', 'shadows', 'grading', 'textures',
    'attributes', 'lighting', 'stamping', 'dithering', 'vorticity',
    # 图形资源
    'material', 'shader', 'prefab', 'sprite', 'atlas', 'mesh', 'texture',
    'camera', 'canvas', 'stencil', 'clipping', 'lighting', 'emission',
    'occludee', 'occluder', 'blending', 'renderer', 'buffer', 'buffers',
    # 动画
    'animator', 'animation', 'listener', 'clipping',
    # 组件 / 状态机（≥5 字母，安全）
    'button', 'toggle', 'slider', 'scroll', 'canvas', 'cancelas',
    'graphic', 'layout', 'canvasgroup', 'content', 'element', 'togglegroup',
    'masking', 'raycast', 'hitcast', 'physics', 'trigger', 'collider',
    'rigidbody', 'particle', 'emitter', 'trail', 'lens', 'flare', 'bloom',
    'spriteatlas', 'quality', 'default', 'master', 'stream', 'settings',
    'quality', 'tonemap', 'gamma', 'exposure', 'contrast', 'saturation',
    'vibrance', 'whitebalance', 'split', 'screen', 'overlay', 'pass',
    'asset', 'bundle', 'preload', 'mipmap', 'streaming', 'scalable',
    'optimized', 'incremental', 'background', 'foreground', 'transparency',
    'liberation', 'ascender', 'descender', 'external', 'characters',
    'leading', 'following', 'tracking', 'kerning', 'ligature', 'fallback',
    'atlas', 'static', 'dynamic', 'geometry', 'hierarchy', 'instance',
    'override', 'reference', 'template', 'variable', 'property', 'function',
    'component', 'container', 'modifier', 'propertyblock', 'coroutine',
    'delegate', 'interface', 'abstract', 'virtual', 'override', 'sealed',
    'serializ', 'deserial', 'marshal', 'unmanaged', 'pointer', 'struct',
    'generic', 'invoke', 'reflect', 'serialize', 'thread', 'async', 'await',
    # 游戏内部系统名
    'visualscripting', 'gamen', 'kaisou', 'easisave', 'easysave',
))

# 需要按「子串」匹配的**多词短语**（单词表管不到这些）
_ENGINE_PHRASE = (
    'depth of field', 'motion blur', 'color grading', 'tone mapping',
    'lens distortion', 'chromatic aberration', 'film grain',
    'ambient occlusion', 'screen space', 'post process', 'compute buffer',
    'render texture', 'frame buffer', 'layer mask', 'font asset',
    'cull mode', 'alpha clip', 'clip rect', 'write mask', 'read mask',
    'color mask', 'global light', 'vertex attributes', 'light layer',
    'render pass', 'new state', 'new animation', 'normal map',
    'base layer', 'use alpha', 'ztest', 'zwrite', 'leading characters',
    'following characters', 'external alpha',
)

# 兼容旧名（外部测试/代码可能引用 ENGINE_TERMS）
ENGINE_TERMS = _ENGINE_PHRASE


def _is_engine_term(low):
    """v3.23：单词走词边界集合匹配，短语走子串匹配。

    旧实现是纯子串，导致 'coc' 误杀 'cocks'、'lod' 误杀一切含 lod 的词。
    """
    if any(ph in low for ph in _ENGINE_PHRASE):
        return True
    # 词边界：用非字母数字切分后查集合（比正则快，且天然处理 'cocks'）
    toks = _NON_ALNUM_SPLIT.split(low)
    for t in toks:
        if t in _ENGINE_SINGLE:
            return True
    return False



# CJK 判定：汉字 + 假名 + 韩文音节 + 全角标点
CJK_TEXT_RE = re.compile(
    r'[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\uff01-\uff60]')

VOWELS = set('aeiouyAEIOUY')
_SYMBOL_OK = set(" .,!?'\"-:;()[]%@&*+=#\n\t")
# v3.23：词边界切分（_is_engine_term 用）
_NON_ALNUM_SPLIT = re.compile(r'[^a-z0-9]+')
# v3.23：这些是**合法标点**，不计入「乱码符号占比」（R12）。
# 旧版把 . , ' " ! ? ~ … 全算符号，导致 'How are you doing, Buddy?' 这类
# 正常句子超阈被毙（863 条漏条 = 23.4%，第一大误杀源）。
_PUNCT_HARMLESS = set(".,!?'\"-;:%…、。，！？：；（）【】《》“”‘’~～*")



def _vowel_ratio(w):
    al = [c for c in w if c.isalpha()]
    if not al:
        return 0.0
    return sum(c in VOWELS for c in al) / len(al)


# v3.24：判断「像一句自然语句」——用于把尖叫体对话 / 含数字台词从
# 资源名判据里救出来。判据刻意保守（两项都要满足），避免放行组件名：
#   ① 至少 4 个空格分隔的词（资源名极少有这么多词）；
#   ② 以句末标点/引号/括号收尾（'HNGAAH!!!' / '...Drowning!' 都满足，
#      而 'AbreveabreveGbreveIdotaccentIJij' 连空格都没有）。
_SENTENCE_END_RE = re.compile(r'[.!?"”\'’)\]]\s*$')


def _sentence_like(s):
    return len(s.split()) >= 4 and bool(_SENTENCE_END_RE.search(s))


def _looks_like_identifier(s):
    """代码/资源标识符：下划线、点号命名空间、连续 3+ 大写、路径分隔。

    v3.24：`_` / `A.B` / `[A-Z]{3,}` / `\\d{2,}` 四条**按内容分流**——
    真正被毙的是「游戏尖叫体对话」（'HNGAAAAGHHH!!! AAAAHHH!!!'、'FUCK!
    I'M DROWNING!'）与「含年龄/数量数字的正常台词」（'at 34, certainly
    knows'、'a 56-year-old game developer'）。这两类在 v3.23 全被误杀，
    实测占漏条 28.6% + 9.7%。
    修法：**只有当整串「不像自然语句」时才按标识符拒收**。
    「像自然语句」= ≥4 个词 且 以句末标点/引号收尾（见 `_sentence_like`）。
    这样 'AbreveabreveGbreveIdotaccent'（无空格连写）仍被拒，
    'HNGAAAAGHHH!!! AAAAHHH!!!'（有空格有句末叹号）被放行。
    """
    if '_' in s:
        return True
    if re.search(r'[A-Za-z]\.[A-Za-z]', s):
        return True
    if not _sentence_like(s):
        # 非语句形态：3+ 连续大写 / 2+ 连续数字 都是资源名的强信号
        if re.search(r'[A-Z]{3,}', s):
            return True
        if re.search(r'\d{2,}', s):
            return True
    return False


def keep_string(s):
    """过滤英文候选：只保留『像真实游戏文本(对话/UI)』的字符串。

    v3.22 收紧：旧版只要有一个『≥2 个全大写字母』的词就放行，导致
    'q NF' / 'b* GP' / 'F+ Vxlt@' 这类二进制碎片全部误收；现要求：
      - 至少 2 个词形合法的 token（长度≥3、元音比例合理）；
      - 全大写缩写不再单独作为通行证；
      - 数字串、符号占比、平均词长、整体元音比例共同判据。
    """
    s = s.strip()
    n = len(s)
    if not (5 <= n <= 300):
        return False
    if ' ' not in s:
        return False
    if any(tok in s for tok in NOISE_TOKENS):
        return False
    low = s.lower()
    if _is_engine_term(low):          # v3.23：词边界匹配，替掉旧子串匹配
        return False
    if _looks_like_identifier(s):
        return False
    if re.search(r'[(){}\[\]=;<>|]', s):
        return False
    if re.search(r'[^\x00-\x7e]', s):      # ASCII 通道：出现高位字符即非英文短语
        return False
    if re.fullmatch(r'[0-9a-fA-F]{32}', s):
        return False
    if re.search(r'\d{4}\.\d+\.\d+', s):
        return False

    letters = sum(c.isalpha() for c in s)
    if letters < 5:
        return False
    allowed = sum(c.isalnum() or c in _SYMBOL_OK for c in s)
    if allowed / n < 0.9:
        return False
    # v3.23 R12：只统计**非合法标点**的杂符号（. , ' " ! ? ~ … 不算）
    sym = sum((not c.isalnum()) and c != ' ' and c not in _PUNCT_HARMLESS
              for c in s)
    if sym / n > 0.18:
        return False

    words = [w for w in s.split() if w]
    if len(words) < 2:
        return False
    # v3.23 R14：3.0 -> 2.5（旧值误杀 'I think... a b c' 类短词句）
    avg_len = sum(len(w) for w in words) / len(words)
    if avg_len < 2.5:
        return False
    digits = sum(c.isdigit() for c in s)
    if digits and digits / n > 0.12:
        return False

    # v3.23 R16：合法词 >=2 -> >=1，但用「总字母数」兜底防碎片。
    # 单独放行 1 个合法词时要求整体字母数 >= 12，杜绝 'q NF' 这类碎片。
    wl = [_is_word_like(w) for w in words]
    if sum(wl) < 2:
        if sum(wl) < 1 or letters < 12:
            return False
    allw = ''.join(w for w in words if w.isalpha())
    if allw:
        vr = _vowel_ratio(allw)
        if not (0.18 <= vr <= 0.72):
            return False
    return True


def keep_label(s):
    """v3.23 新增：短标签通道（UI 单词标签）。

    背景：`keep_string` 结构上要求「≥2 词 + 含空格」，于是
    'Garage' / 'Whiskey' / 'Anniversary' / 'Upstairs' 这类**单词 UI 标签**
    永远进不来（实测漏 286 条 = 7.8%）。但直接放宽 `keep_string` 的
    空格要求会打穿 test_whitebox W04 的 'word' 拒断言，也会放进海量
    组件名/资源名 —— 所以单开一条门槛独立、判据更严的通道。

    与 `keep_string` 的区别（更严）：
      - 长度 **4~12**（实测真标签全落 4~11；放宽到 24 时噪声率飙到
        95.5%，因为 asset 名/连写垃圾基本都 >12 字符）；
      - 必过词形 + 元音比例 + 引擎术语三道关；
      - 额外拦「长连写垃圾」（8+ 字母但元音极少，如 'saaaaabekx'）。

    ⚠ 实测（Starmaker 本体）：真源命中 142 条 / 噪声 3011 条 = 命中率
    仅 4.5%。**收益远小于代价，故 GUI 提取流程默认不并入主表**
    （`scan_and_collect` 的 `labels` 参数留空即可关闭）。
    保留本函数是为了别的游戏（UI 标签占比高的 2D/AVG）可显式启用。
    """
    t = s.strip()
    n = len(t)
    if not (4 <= n <= 12):
        return False
    if '_' in t or any(ch.isdigit() for ch in t):
        return False
    if not re.fullmatch(r"[A-Za-z][A-Za-z'\-]*", t):
        return False
    # 排除专有名词式的引擎/资源标识（Assembly/Config/System 等前缀）
    if re.match(r'^(System|Assembly|Config|Unity|TMPro|UnityEngine)[A-Z]', t):
        return False
    core = t.strip("-'")
    if not (core.islower() or core.istitle()):
        return False
    if not _is_word_like(core):
        return False
    if _is_engine_term(t.lower()):
        return False
    vr = _vowel_ratio(core)
    if not (0.25 <= vr <= 0.70):
        return False
    if len(core) >= 8 and vr < 0.35:      # 连写垃圾特征
        return False
    return True



def _is_word_like(w):
    """词形判定（严格版）：长度≥3 且元音比例在英文合理区间。
    全大写 token 不再自动放行（那正是旧版误收 2 字母碎片的根因）。"""
    w = w.strip('.,!?\'"-:;()[]%@&*+=#\\/')
    if len(w) < 3:
        return False
    if not w.isalpha():          # 含连字符/数字/下划线 -> 非普通过词（foo-bar/OK1）
        return False
    core = w
    # 大小写形态：允许 全小写 / 首字母大写 / 全大写（由 keep_string 统一把关）。
    # 但**混排大小写**（HeLLo、kWay）是二进制碎片/代码标识符的典型特征，拒绝。
    if not (core.islower() or core.isupper() or core.istitle()):
        return False
    vr = _vowel_ratio(core)
    return 0.2 <= vr <= 0.75


def keep_cjk_string(s):
    """过滤 CJK/日文候选：只保留『像真实日文/中文文本』的字符串。

    v3.22.1 重写（乱码根因修复）：
      旧版只要求「≥2 个 CJK 字符」，而 `TEXT_RUN_RE` 的 `[\\xe0-\\xef][\\x80-\\xbf]{2}`
      分支会**把 float32 二进制字节当成合法 UTF-8** —— 例如
        e8 90 9a 3e = float32 ≈0.302  → 解码成 '萚>'
        e5 9b 90 41 = float32 ≈18.08  → 解码成 '囐A'
      于是动画关键帧/颜色/Transform 数组被整片误收。实测 Starmaker 本体
      18109 条里 31 条含 CJK，**真日文 0 条，31/31 全是 float 巧合**。

      新判据（必须同时成立）：
        ① 至少 2 个「真 CJK」（汉字/假名/韩文音节，不含全角标点；
           标点单独计入会稀释判据，故 `CJK_TEXT_RE` 拆成汉字/假名两组）；
        ② 存在**文本信号**之一：
           - 含平假名/片假名（日文实词的强信号）；或
           - 含中文常见字（的/了/是/我/你/在/有/不/这/那/他/她/们…）；
        ③ 拒绝「CJK 占比过低」的串（float 巧合串常混大量 ASCII，如
           '囐A囐A' / 'ff濣p}?p=꿮G' / 'B囘A因A'）。
    """
    s = s.strip()
    if not (2 <= len(s) <= 200):
        return False

    # ---- 真 CJK 计数（汉字 + 假名 + 韩文音节；全角标点不计）----
    han = sum(1 for c in s if '\u3400' <= c <= '\u4dbf'
              or '\u4e00' <= c <= '\u9fff' or '\uf900' <= c <= '\ufaff')
    kana = sum(1 for c in s if '\u3040' <= c <= '\u309f'
               or '\u30a0' <= c <= '\u30ff')
    hangul = sum(1 for c in s if '\uac00' <= c <= '\ud7af')
    real_cjk = han + kana + hangul
    if real_cjk < 2:
        return False

    if '_' in s:                              # girl_1_anim_立ち揉み
        return False
    if re.search(r'[A-Za-z]{3,}', s):          # 混排英文标识符
        return False
    if re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', s):
        return False
    if '\\' in s:
        return False
    # BOM / 孤立私有标记 / 替换符
    if any(c in s for c in ('\ufeff', '\ufffe', '\ufffd')):
        return False

    # ---- 判据 ③：CJK 必须占足够比重（剔除 float 巧合的 ASCII 混排）----
    if real_cjk / len(s) < 0.6:
        return False

    # ---- 判据 ②：必须有「文本真实性信号」----
    #  a) 假名（日文）——最强的真实文本信号。**优先判定**，因为日文
    #     文本里汉字可能生僻（姉/雫…），不能拿汉字常用度去卡它。
    if kana >= 1:
        return True
    #  b) 韩文音节：真韩文的终声分布自然，float 巧合的终声几乎全是
    #     罕见复合终声（ㄳㄵㄺㄻㄽㄾㄿㅀㅄ）。用「终声合法性」筛。
    if hangul >= 2:
        jong_ok = 0
        for c in s:
            if '\uac00' <= c <= '\ud7a3':
                if _hangul_jong(ord(c)) in _JONG_COMMON:
                    jong_ok += 1
        return hangul > 0 and jong_ok / hangul >= 0.6
    #  c) 纯汉字文本（中文）：要求「汉字基本是常用字」。
    #     float 巧合拼出的汉字 95% 是生僻字（萚記卹囐囈囘囸㿅囀…），
    #     而真实中文文本的字几乎都能编进 GB2312（6763 字覆盖）。
    if han >= 2:
        common_han = 0
        for c in s:
            if '\u3400' <= c <= '\u4dbf' or '\u4e00' <= c <= '\u9fff' \
                    or '\uf900' <= c <= '\ufaff':
                try:
                    c.encode('gb2312')
                    common_han += 1
                except Exception:
                    pass
        if common_han / han < 0.5:
            return False
        # 补刀：float 巧合串常把汉字与单个拉丁字母**直接相邻**（如
        # 'U邋稹' / '晒ā啊'），而中文文本不会在词内夹孤立拉丁字母。
        if re.search(r'[A-Za-z][\u4e00-\u9fff]|[\u4e00-\u9fff][A-Za-z]', s):
            return False
        return True

    # 无任何真实性信号 → 判定为二进制巧合产物
    return False


# ---------------------------------------------------------------------------
# v3.25 中文键护栏 —— 识别「提示词 / 术语表片段被误当原文键写入」
# ---------------------------------------------------------------------------
# 事故背景（2026-10-04 / 10-07 各发现一次）：
#   真源里混入 95 条**中文键**，逐条字节校验确认它们在游戏 .assets 里**根本不存在**。
#   形态分两类（实测比例）：
#     ① 术语表片段 54 条 —— 形如「读档：恢复之前的游戏进度」「确定：确认执行某动作」
#        来自翻译提示词里内置的术语对照表整段被写入；
#     ② 提示词正文 41 条 —— 形如「### **版本一：经典诱惑版**」「* **“留下来吧”**：……」，
#        甚至整段「希望这些译法能满足您的需求…」。
#   2026-10-07 重新提取时其中 1 条被引擎照搬回列表（见 is_polluted_cjk_key）。
#
# ⚠️ **设计教训**：最初判据写成「成对引号包裹的完整句子」，只因为手里有那条样本。
#    实测 95 条里只有 4 条带引号、91 条不带 → 判据方向错了。
#    真实特征不是「像译文」，而是**结构上根本不是游戏对白**。
#
# 判据（三条任一命中即判污染，刻意保守以免误伤原生中文游戏）：
#   A. Markdown 记法：`###` 标题、`**加粗**`、`*`/`-` 列表项 —— 游戏文本不会有
#   B. 「术语：解释」结构：冒号前 ≤6 字且冒号后 ≥4 字
#   C. 成对引号包裹且引号内含中文（长度 ≥4）
# 只含中文但不符合以上任一形态的（如「开始游戏」「牛图案的翻译」）→ **放行**。

_MD_HEADING_RE = re.compile(r'^\s*#{1,6}\s')
_MD_BOLD_RE = re.compile(r'\*\*')
_MD_LIST_RE = re.compile(r'^\s*[*\-•]\s+')
# 「术语：解释」—— 冒号前1~6 字，冒号（含全角）后 ≥4 字
# ⚠️ 这里的 \uff1a 必须用**单反斜杠**：本文件是 non-raw 字符串，`\\uff1a`
#    会变成字面反斜杠+u，regex 永远匹配不到（曾踩过这个坑）。
_COLON_TERM_RE = re.compile(u'^[^：:]{1,6}[：:].{4,}$')
# 成对引号包裹（兜底，覆盖引号形态的提示词片段）
_QUOTED_CJK_RE = re.compile(u'^["“「『](.{4,})["”」』]\\s*$')
# 提示词正文的长度阈值。实测漏网的条目多为 ≥60 字的整段叙述；
# 游戏原生中文对白单条极少超过 60 字。
_PROMPT_PARA_MIN = 60
# 提示词口吻标志词 —— 出现在**键**里就说明这是给翻译模型看的指令，不是游戏文本。
# ⚠️ 只收录**绝不会出现在游戏对白/UI 里**的词。实测踩坑：「适用于」被收进来后
#    误伤了 '（适用于大多数需要营造暧昧氛围的场景）' 这类可能 legit 的括号说明句，
#    已移除。「例如」「语气」「建议」等词游戏里也会出现，同样不收。
_PROMPT_TOKENS = (
    u'希望这些', u'请随时提供', u'请提供更具体', u'在进行专业翻译之前',
    u'为您提供', u'需要您提供', u'如果您有更多', u'如果您希望',
    u'在实际游戏中', u'请根据角色', u'核心原则', u'感官冲击',
    u'术语表', u'译法', u'为您打造', u'赞助支持',
)


def is_polluted_cjk_key(s):
    """v3.25：识别「翻译提示词 / 术语表片段被误当原文键写入」的污染条目。

    ⚠️ 这是**兜底护栏**，主防线在写入端。这些形态的游戏原文**不存在于 .assets
    字节里**，所以正常提取路径压根不该产出它们；它们只在真源被外部写入时才出现。

    只含中文但形态正常的键（原生中文对白 / UI 标签）一律放行。
    """
    if not s:
        return False
    if not CJK_RE.search(s):
        return False                        # 无中文 → 不归本函数管
    t = s.strip()
    # A. Markdown 记法
    if _MD_HEADING_RE.match(t) or _MD_BOLD_RE.search(t) or _MD_LIST_RE.match(t):
        return True
    # B. 「术语：解释」结构
    if _COLON_TERM_RE.match(t) and CJK_RE.search(t):
        return True
    # C. 成对引号包裹 + 内部含中文
    m = _QUOTED_CJK_RE.match(t)
    if m and CJK_RE.search(m.group(1)):
        return True
    # D. 超长段落（提示词正文 / 整段叙述）
    if len(t) >= _PROMPT_PARA_MIN:
        return True
    # E. 含提示词口吻标志词
    for tok in _PROMPT_TOKENS:
        if tok in t:
            return True
    return False


# ---------------------------------------------------------------------------
# v3.26 截断文本过滤器 —— 老板 2026-10-07 要求：
#   「提取出来被截断的文本如果直接翻译的话也会文不达意，改成不提取，
#     等游戏运行时即时注入翻译」
# ---------------------------------------------------------------------------
# 背景：真源里大量条目是**句子的残片**，翻译出来语义不完整。例如：
#     'You know what? I'          ← 后面还有内容
#     'Every time you touch me like that'
#     'll bounce back, Jack. Probably. Maybe.'   ← 开头 'you' 被吃掉
#     '... "From 40 onward" ...  "It\'s never too late to '   ← 尾部被吃
#
# ⚠️ **关键实测结论（推翻了我的初始假设）**：
#   抽查 60 条候选 → **58 条在 .assets 字节里根本找不到**（仅 2 条命中且都是掐头）。
#   → 这些残片**不是静态提取的产物**，而是 **XUnity 运行时抓的中间态**
#      （与 re-engineering-notes 记录的 25.7% 中间态同源）。
#   → 因此它们**无法通过改进提取器消除**，只能过滤 + 依赖运行时注入。
#
# 三条判据（任一命中即判为残片，不提取）：
#   A. 开头是「单词碎片 + 空格」：'t smile...' / 's family...' / 've heard...'
#   B. 符号/非字母数字开头：`!Binding Life` / `...Okay.` / `+1 Fan today`
#   C. 尾部截断：整体无句末标点收尾，且末尾是虚词/连词（'...but I' / '...Told you it'）
#
# ⚠️ 刻意保守：**只删「有明确截断特征」的**，绝不按「没有句号」粗暴过滤——
#    否则 'Milky Coins' / 'World of Roundscape' / 'Apple Tree' 这类
#    正常的无标点 UI 文本会被误杀（实测占不带标点条目的 40%+）。

# A. 掐头残片：单词被切断后残留的碎片（Febucci 逐字显示的典型产物）
_HEAD_FRAGMENT_RE = re.compile(
    r'^(t|s|ve|re|m|ll|d|n|w|y|c|b|f|h|j|k|p|v|z|g)\s+', re.I)
# B. 符号开头：正常对白/UI 极少以标点或符号起头
#    ⚠️ **必须限定 ASCII**！曾写成 `^[^A-Za-z0-9'"(\[]` → 把**所有非 ASCII 开头的
#    文本**（日文「こんにちは。」/ 中文「初次见面」/ 韩文）全部误杀，
#    被 test_extract.py F2 当场抓住。教训：字符类排除法必须显式限定码位范围。
#    现在只拦「ASCII 标点/符号开头」，CJK 文本一律走keep_cjk_string 放行。
_SYMBOL_HEAD_RE = re.compile(r'^[!-/:-@\[-`{-~]')
# C. 尾部截断：虚词/连词收尾（完整句子不会这么结束）
_FUNCTION_WORD_TAIL_RE = re.compile(
    r"\b(and|or|but|the|a|an|is|are|was|were|be|been|being|to|of|in|on|at|"
    r"for|with|my|your|his|her|its|our|their|that|this|it|he|she|they|you|"
    r"I|we|as|if|so|no|not|do|does|did|have|has|had|will|would|can|could|"
    r"should|may|might|must|than|then|when|while|because|about|into|out|up|"
    r"down|off|over|under|very|just|too|also|only|even|still|yet|like)$", re.I)
# 正常句子的收尾：句末标点 或引号/括号
_SENTENCE_END_OK_RE = re.compile(r'[.!?\'")\]]\s*$')
# C 判据的长度门槛：短于此值且以虚词收尾的，多半是**完整短语**而非截断
# （实测：`thank you` / `Is this` / `Wow, that` / `going on` 都是完整 UI 文本；
#   而 `You know what? I` / `Every time you touch me like that` 都 ≥20 字）
# 12 字是实测分界：短句候选仅 187 条，长句候选 2,218 条。
_TRUNC_MIN_LEN = 12
# D. 缩略词丢撇号 —— **截断的强信号**（实测保留区里的高频漏网项）
#   don(281) / didn(96) / isn(63) / won(48) / doesn(48) / wasn(30) / couldn(18)...
#   正常文本里 `don't` / `didn't` 的撇号**绝不可能丢**，因为那是同一个字符。
#   判据：结尾是「否定缩略词干」且后面没有撇号。
#   ⚠️ 只收「必须带撇号」的否定式（don/doesn/didn/isn/aren/wasn/weren/won/
#      wouldn/shouldn/couldn/hasn/haven/hadn）—— **不含 can/let/must/may**，
#      因为 'can' / 'may' / 'must' 本身就是完整单词（"I can." / "you may."），
#      收了会误伤（实测 'can' / 'may' 单���被拦）。
_CONTRACTION_TAIL_RE = re.compile(
    r"\b(don|doesn|didn|isn|aren|wasn|weren|won|wouldn|shouldn|couldn|"
    r"hasn|haven|hadn)\s*$", re.I)
# E. 句末紧跟单个字母 —— Febucci 逐字显示的典型残留（'Y-Yes! It's all for you!V'）
#    ⚠️ 必须排除「缩写撇号」形态：'don't' / "can't" / "won't" 的 `n't` 也会命中
#    `[.!?"')\]][A-Za-z]$`。故要求长度 ≥12 **且** 撇号前不是 n。
_TRAILING_JUNK_RE = re.compile(r'[.!?")\]]\s*[A-Za-z]\s*$')


def is_truncated_fragment(s):
    """v3.26：判断字符串是否为**截断的句子残片**（不该提取、不该翻译）。

    老板要求：「提取出来被截断的文本如果直接翻译的话也会文不达意，
    改成不提取截断的文本，等游戏运行时即时注入翻译」。

    典型样本：
        'You know what? I'                    ← 尾部截断
        'll bounce back, Jack. Probably. Maybe.' ← 头部掐断
        '!Binding Life'                        ← 符号开头
        '... "From 40 onward" ... "It\'s never too late to '  ← 尾部截断

    ⚠️ 必须放行的正常文本（实测占「无句末标点」条目的 40%+）：
        'Milky Coins' / 'World of Roundscape' / 'Apple Tree'
        / 'thank you' / 'Is this' / 'going on'
        ——它们没有句末标点，但**没有截断特征**，一律保留。

    实测规模（2026-10-07，真源 22,725 条）：
        A 掐头残片 5,299 / B 符号开头 328 / C 尾部截断 2,405（加长度门槛后）
        A∪B∪C 去重后约 **7,000 条**（占 ~31%）
    """
    if not s:
        return False
    t = s.strip()
    if not t:
        return False
    # A. 头部掐断
    if _HEAD_FRAGMENT_RE.match(t):
        return True
    # B. 符号开头（但要放过 `(` `'` `"` `[` —— 括号/引号包裹的合法文本）
    if _SYMBOL_HEAD_RE.match(t):
        return True
    # C. 尾部截断：整体无句末标点收尾 **且** 末尾是虚词 **且** 长度够长
    #    （长度门槛是为了放过'thank you' / 'Is this' 这类完整短语）
    if (len(t) >= _TRUNC_MIN_LEN
            and not _SENTENCE_END_OK_RE.search(t)
            and _FUNCTION_WORD_TAIL_RE.search(t)):
        return True
    # D. 缩略词丢撇号（don / didn / isn / won…）—— 强截断信号，不看长度
    if _CONTRACTION_TAIL_RE.search(t) and "'" not in t:
        return True
    # E. 句末标点后紧跟单个孤立字母（逐字显示残留），长度门槛 +排除 n't
    if len(t) >= _TRUNC_MIN_LEN and _TRAILING_JUNK_RE.search(t):
        m = _TRAILING_JUNK_RE.search(t)
        if not (m and m.group(0).lstrip()[-2:-1] == "n"):
            return True
    return False


# 中文最常见的虚词/代词/动词（真实中文文本几乎必然出现至少一个）。
# 用于把『汉字段被二进制巧合拼出来』的串挡掉（如 '記醒' / '圃卹' / 'U邋稹'）。
_ZH_COMMON = frozenset(
    '的了是在有我你他她它们这那不没和与就都也还很才会能要会到说去来'
    '一个上们人为个中大小多少好可以么什么怎样对从被把给让但而且还或'
    '如果因所以时间天地人心里地方东西前后左右多少时候现在应该知道'
    '看听想问说走做给拿想觉得或者但然')


def _hangul_jong(code):
    """韩文音节的终声下标（0..27）。终声=0 表示无收音。"""
    return (code - 0xAC00) % 28


# 现代韩语**常用**终声：无收音(0) + 单辅音收音 (ㄱㄴㄷㄹㅁㅂㅇ)。
# 罕见的复合终声（ㄳㄵㄶㄺㄻㄼㄽㄾㄿㅀㅄ）在真实文本里占比很低，
# 而 float 巧合恰好大量落在这些下标（1/13/19/21/23…）上。
_JONG_COMMON = frozenset({0, 1, 4, 7, 8, 16, 17, 21})



def scan_and_collect(path, kept, labels=None, deep_scan=False):
    """扫描单个 Unity 资源文件，把通过过滤的字符串以 norm->original 存入 kept。

    v3.22：
      * 只在数据段（data_offset 之后）扫描——类型树/元数据区是噪声重灾区；
      * 先走 CJK 通道（多语言游戏的原生文本），再走 ASCII / UTF-16 通道；
      * 全程 mmap 流式扫描，避免大文件（近 600MB）整读进内存。

    v3.23：
      * 新增**短标签通道**（`keep_label`）—— 单词型 UI 标签（Garage/Whiskey）
        结构上过不了 `keep_string` 的「≥2 词」关，实测漏 286 条(7.8%)。
        为避免污染主表，标签存进独立的 `labels` 字典，由调用方决定是否合并。
      * 新增 `deep` 参数：是否扫描 resS / resource（默认关）。
        Starmaker 实测这 1.1GB 里独立真文本为 0（全是浮点/图形噪声），
        故默认不扫；但别的 Unity 游戏（尤其把文本放 resS 的）需要开。
    v3.25：
      * **新增中文键护栏** `is_polluted_cjk_key()`。历史事故：某次批量操作把**译文**
        误当新原文键写进真源（"“唔……这种感觉真是让人心跳加速呢。”"），10-04 清理
        漏了 1 条，10-07 重新提取时被照搬回列表。
        判定：**键含中文 且 是「带引号的完整句子」** → 判为译文被当键，直接拒收。
        只含中文但形态正常的键仍放行，避免误伤 CJK 通道的合法原生中文。
    v3.26（2026-10-07 老板要求）：
      * **新增截断残片过滤** `is_truncated_fragment()`。老板原话：
        「提取出来被截断的文本如果直接翻译的话也会文不达意，改成不提取
          截断的文本，等游戏运行时即时注入翻译」。
        覆盖三条判据（掐头残片 / 符号开头 / 尾部虚词收尾），实测拦下 7,080 条（31.2%）。
        ⚠️ 这些残片**不是静态提取的产物**（抽查 60 条，58 条在 .assets 字节里不存在），
           而是 XUnity 运行时抓的中间态 → 只能过滤，无法靠改进提取器消除。
        被拦下的文本在游戏运行时由 XUnity 实时翻译（不受影响）。
    """
    try:
        with open(path, 'rb') as f:
            mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
            try:
                # 数据段起点：无法识别头部时从头扫（向后兼容旧资源）。
                # deep 模式忽略 header 判据（resS/.resource 本就没有版本串）。
                if deep_scan:
                    base = 0
                else:
                    hdr = _unity_header(bytes(mm[:64]))
                    base = hdr[0] if hdr else 0
                view = mm[base:] if base else mm
                try:
                    # ---- CJK 通道（日/中/韩 原生文本）----
                    for m in TEXT_RUN_RE.finditer(view):
                        raw = m.group()
                        if not CJK_TEXT_RE.search(raw.decode('utf-8', 'ignore')):
                            continue
                        s = raw.decode('utf-8', 'ignore').strip()
                        if (keep_cjk_string(s)
                                and not is_polluted_cjk_key(s)
                                and not is_truncated_fragment(s)):
                            kept.setdefault(normalize(s), s)
                    # ---- ASCII 通道（英文文本）----
                    for m in ASCII_RE.finditer(view):
                        s = m.group().decode('ascii', 'ignore').strip()
                        if is_truncated_fragment(s):
                            continue          # v3.26：截断残片不提取
                        if keep_string(s):
                            kept.setdefault(normalize(s), s)
                        elif labels is not None and keep_label(s):
                            labels.setdefault(normalize(s), s)
                    # ---- UTF-16 通道 ----
                    for m in UTF16_RE.finditer(view):
                        s = m.group().decode('utf-16-le', 'ignore').strip()
                        if is_truncated_fragment(s):
                            continue          # v3.26：截断残片不提取
                        if keep_string(s):
                            kept.setdefault(normalize(s), s)
                        elif labels is not None and keep_label(s):
                            labels.setdefault(normalize(s), s)
                finally:

                    if base:
                        del view
            finally:
                mm.close()
    except Exception:
        pass


# ----------------------------------------------------------------------------
# 数据模型
# ----------------------------------------------------------------------------
class TranslationStore:
    def __init__(self):
        self.path = None
        self.entries = []
        self.bom = True
        self.dirty = False
        self.corrupt_chars = 0   # load() 时统计的 U+FFFD 数（词典文件损坏指标）

    def load(self, path):
        self.path = path
        self.entries = []
        with open(path, 'rb') as f:
            raw = f.read()
        self.bom = raw.startswith(b'\xef\xbb\xbf')
        text = raw.decode('utf-8-sig', errors='replace')
        # 污染计数：errors='replace' 会把损坏字节静默变成 U+FFFD —— 计数暴露而非无声混入
        self.corrupt_chars = text.count('\ufffd')
        for line in text.split('\n'):
            line = line.rstrip('\r')
            if line == '':
                continue
            if '=' in line:
                original, translation = line.split('=', 1)
            else:
                original, translation = line, ''
            original = original.rstrip('\r')
            translation = translation.rstrip('\r')
            status = classify(original, translation)
            self.entries.append({'original': original, 'translation': translation,
                                  'status': status})
        self.dirty = False

    @staticmethod
    def _escape_line(s):
        """XUnity 行格式为单行 original=translation; 把字段内部换行转义为字面 \\n,
        防止一行被拆成两行后重载时把译文后半当成新条目(损坏文件)。"""
        return (s or '').replace('\r\n', '\\n').replace('\n', '\\n').replace('\r', '\\n')

    def save(self, path=None, backup=True):
        """原子写: 临时文件 + fsync + os.replace。

        避免直接覆盖写时中途崩溃(磁盘满/杀进程/断电)留下半截文件损坏资产。
        备份顺序也已修正: 先备份当前完整版本, 再原子替换 -> .bak 必定可用。
        """
        path = path or self.path
        if backup and os.path.isfile(path):
            # 备份轮转: .bak1->.bak2, .bak->.bak1, 当前文件->.bak (保留三代历史)
            try:
                import shutil
                if os.path.isfile(path + '.bak1'):
                    shutil.copy2(path + '.bak1', path + '.bak2')
                if os.path.isfile(path + '.bak'):
                    shutil.copy2(path + '.bak', path + '.bak1')
                shutil.copy2(path, path + '.bak')
            except Exception:
                pass
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        # 临时文件必须与目标同目录(同卷), 否则 os.replace 退化为拷贝+删除, 失去原子性
        tmp = path + '.tmp'
        try:
            with open(tmp, 'w', encoding='utf-8', newline='') as f:
                if self.bom:
                    f.write('\ufeff')
                for e in self.entries:
                    f.write('%s=%s\n' % (self._escape_line(e['original']),
                                         self._escape_line(e['translation'])))
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        except Exception:
            # 写失败: 清理残留 tmp, 主文件保持原样(未受影响)
            try:
                if os.path.isfile(tmp):
                    os.remove(tmp)
            except Exception:
                pass
            raise
        self.dirty = False

    def stats(self):
        s = {'total': len(self.entries), 'translated': 0, 'untranslated': 0, 'english': 0}
        for e in self.entries:
            s[e['status']] = s.get(e['status'], 0) + 1
        return s

    def update_status(self, e):
        e['status'] = classify(e['original'], e['translation'])

    def find_and_replace(self, keyword, replacement, case_sensitive=False, whole_word=False):
        """全局查找替换(作用于翻译文本)。返回 (matched, replaced)。
        匹配语义见 build_kw_pattern: 英文 \\b 词边界 / 中文 CJK 边界断言。"""
        import re
        matched = 0
        replaced = 0
        if not keyword:
            return matched, replaced
        try:
            pat = build_kw_pattern(keyword, case_sensitive, whole_word)
        except re.error:
            return matched, replaced

        for e in self.entries:
            trans = e['translation']
            if not pat.search(trans):
                continue
            matched += 1
            new_trans = pat.sub(replacement, trans)
            if new_trans != trans:
                e['translation'] = new_trans
                replaced += 1
                self.dirty = True
                self.update_status(e)
        return matched, replaced


# ----------------------------------------------------------------------------
# 翻译后端 (可选手模型 + API)
# ----------------------------------------------------------------------------
# 本地模型的 UI 高频词直译表：这些极短按钮/提示词直接查表返回，不调模型
# (避免本地大模型对短输入又慢又容易"加戏"，与游戏内代理的短词快路径一致)
#
# v3.19: 表已抽到 ui_terms.py 作为唯一真源，GUI 与服务端共用同一份。
# 保留 LOCAL_UI_TERMS / _LOCAL_UI_RE 作为「ui_terms 缺失时的兜底」，
# 以免打包漏带 ui_terms.py 时快路径整体失效。
try:
    LOCAL_UI_TERMS = dict(ui_terms.UI_TERMS) if ui_terms else {}
except Exception:
    LOCAL_UI_TERMS = {}
_LOCAL_UI_RE = re.compile(r'^\s*([A-Za-z][A-Za-z\s]*?)\s+(\d+)\s*$')


class Translator:
    def __init__(self, cfg):
        # cfg: dict with provider, base, key, model, appid, secret, src, dst, prompt
        self.cfg = cfg
        self.provider = cfg.get('provider', '免费Google')
        self.base = cfg.get('base', '')
        self.key = cfg.get('key', '')
        self.model = cfg.get('model', '')
        self.appid = cfg.get('appid', '')
        self.secret = cfg.get('secret', '')
        self.src = norm_lang(cfg.get('src', 'auto')) or 'auto'
        self.dst = norm_lang(cfg.get('dst', 'zh-CN')) or 'zh-CN'
        self.prompt = cfg.get('prompt', '')
        # P1-1: 翻译结果缓存(memo)。批次内 + 跨批次复用, 显著减少重复请求。
        self._memo = {}          # key -> 译文(进程内)
        self._memo_hits = 0
        self._memo_miss = 0
        self._memo_key_prefix = None

    # ------------------------------------------------------------------
    # P1-1 结果缓存
    # ------------------------------------------------------------------
    def _memo_key(self, text):
        """key = sha1(provider|model|src|dst|prompt_hash|text)。

        provider/model/src/dst/prompt 任一变化都会整体失效,
        避免"改了提示词却命中旧译文"的静默错误。
        """
        import hashlib
        if self._memo_key_prefix is None:
            ph = hashlib.sha1(
                (self.get_llm_system() or '').encode('utf-8')).hexdigest()[:12]
            self._memo_key_prefix = '|'.join([
                self.provider, self.model, self.src, self.dst, ph])
        return hashlib.sha1(
            (self._memo_key_prefix + '|' + text).encode('utf-8')).hexdigest()

    def memo_stats(self):
        tot = self._memo_hits + self._memo_miss
        return {'size': len(self._memo), 'hits': self._memo_hits,
                'miss': self._memo_miss,
                'ratio': (self._memo_hits / tot) if tot else 0.0}

    def preload_memo(self, pairs):
        """用已有译文预热缓存(如从当前 store 的已译条目灌入)。

        pairs: iterable of (original, translation)。只接受非空译文。
        """
        n = 0
        for orig, trans in pairs:
            if orig and trans and str(trans).strip():
                self._memo[self._memo_key(orig)] = trans
                n += 1
        return n

    def _llm_system_with_src(self, text):
        """系统提示词；src=auto 时逐条检测语言并在提示中注明，提升准确性。

        英语/中文不加注: 前者模型天然识别, 后者无需翻译。
        """
        sys_prompt = self.get_llm_system()
        if self.src == 'auto' and lang_detector:
            try:
                lang = lang_detector.detect_lang(text)
            except Exception:
                lang = 'other'
            if lang not in ('en', 'zh', 'other', None, ''):
                sys_prompt += '\n【源语言】原文是%s，请先理解原文再翻译。' \
                              % lang_detector.LANG_NAMES.get(lang, lang)
        return sys_prompt

    def get_llm_system(self):
        """获取系统提示词：优先用户自定义，留空用内置"""
        return self.prompt.strip() if self.prompt.strip() else LLM_SYSTEM

    def _local_ui_direct(self, text):
        """UI 高频词直译快路径: 命中返回译文, 否则返回 None。

        v3.19 两处变更:
          1. 表改为 ui_terms 唯一真源(缺失时回退内置字典);
          2. **不再限定本地提供方** —— 纯术语(如 Save/Load)无论走哪个后端,
             直译都优于送模型(更快、更稳、零成本), 且不会引入翻译质量差异。
             "术语+数字"(Save 5)仍仅对本地提供方启用, 保持既有行为不变。
        """
        s = (text or '').strip()
        if not s:
            return None
        # 唯一真源优先
        if ui_terms is not None:
            hit = ui_terms.lookup(s)
            if hit is not None:
                # 纯术语: 任何提供方都可直用
                if s.lower() in LOCAL_UI_TERMS or _LOCAL_UI_RE.match(s) is None:
                    return hit
                # 术语+数字: 仅本地提供方(保持既有行为, 避免云端译文被改写)
                if self.provider in LOCAL_PROVIDERS:
                    return hit
                return None
        # 兜底: ui_terms 缺失时用内置表(原逻辑)
        if self.provider not in LOCAL_PROVIDERS:
            return None
        if s.lower() in LOCAL_UI_TERMS:
            return LOCAL_UI_TERMS[s.lower()]
        m = _LOCAL_UI_RE.match(s)
        if m:
            term = m.group(1).strip().lower()
            if term in LOCAL_UI_TERMS:
                return LOCAL_UI_TERMS[term] + ' ' + m.group(2)
        return None

    def translate_one(self, text):
        text = (text or '').strip()
        if not text:
            return ''
        # 本地模型: UI 高频短词直接查表返回, 不调模型 (快且稳定)
        direct = self._local_ui_direct(text)
        if direct is not None:
            return direct
        # P1-1: 结果缓存 —— 同一 (provider,model,src,dst,prompt,text) 只翻一次
        mkey = self._memo_key(text)
        cached = self._memo.get(mkey)
        if cached is not None:
            self._memo_hits += 1
            return cached
        self._memo_miss += 1
        result = self._translate_uncached(text)
        if result:
            self._memo[mkey] = result
        return result

    def _translate_uncached(self, text):
        """真正的后端调用(不含快路径与缓存)。"""
        p = self.provider
        if p == '免费Google':
            return self._google_free(text)
        if p in ('OpenAI兼容', 'DeepSeek', '本地Ollama/Qwen'):
            return self._openai_compat(text)
        if p == 'Claude':
            return self._claude(text)
        if p == 'Gemini':
            return self._gemini(text)
        if p == 'DeepL':
            return self._deepl(text)
        if p == '百度翻译':
            return self._baidu(text)
        return self._google_free(text)

    # ------------------------------------------------------------------
    # P1-1 批量合并请求(仅 LLM 提供方)
    # ------------------------------------------------------------------
    BATCH_MAX_ITEMS = 20          # 每批最多条数
    BATCH_MAX_CHARS = 1500        # 每批最多字符
    BATCH_ITEM_MAXLEN = 32        # 超过此长度的单条不参与合并(保质量)
    BATCH_SEP = '\n<<<SPLIT>>>\n'

    def supports_batch(self):
        """是否支持合并请求(只有 chat 类 LLM 提供方有"按编号返回"的语义)。"""
        return self.provider in ('OpenAI兼容', 'DeepSeek', '本地Ollama/Qwen',
                                 'Claude', 'Gemini')

    # ------------------------------------------------------------------
    # v3.25 大批量加速通道（batch_fast）
    #
    # 为什么要换掉上面的旧合并通道？2026-10-07 用真实游戏资产实测：
    #   旧 <<<SPLIT>>> 合并请求 0.571s/条 且对齐率只有 58%
    #   逐条请求           0.286s/条 且对齐率 100%
    #   本通道(一+二分重试) 0.146s/条 且对齐率 100%   → 约 3.9 倍提速
    # 旧通道解析失败时会整批作废并逐条降级，等于白跑一遍还多付一次请求。
    #
    # 另需澄清一个误解：**「提示词长导致慢」并不成立**。
    #   实测长提示词(1461字符) 0.16s/条、精简提示词(153字符) 0.15s/条，
    #   几乎同速；而空提示词反而慢到 2.69s/条 —— 因为模型失去约束
    #   开始"加戏"，输出 token 爆炸。耗时≈输出长度，而非提示词长度。
    #   故本次优化不砍提示词（砍了反而更慢）。
    # ------------------------------------------------------------------
    FAST_BATCH_MIN_ITEMS = 2        # 少于这么多条就不值得走批通道

    def supports_fast_batch(self):
        """是否走 v3.25 大批量加速通道。"""
        return bool(batch_fast) and self.supports_batch()

    def translate_batch_fast(self, texts):
        """v3.25 加速通道：快路径/缓存短路 → 一行一条大批量 → 二分拆批重试。

        返回与 texts 等长；失败条为 None（**绝不返回错位译文**）。
        """
        n = len(texts)
        out = [None] * n
        rest = []
        # 1) 快路径 + 结果缓存：命中的不占模型请求
        for i, t in enumerate(texts):
            s = (t or '').strip()
            if not s:
                out[i] = ''
                continue
            direct = self._local_ui_direct(s)
            if direct is not None:
                out[i] = direct
                continue
            cached = self._memo.get(self._memo_key(s))
            if cached is not None:
                self._memo_hits += 1
                out[i] = cached
                continue
            rest.append(i)
        if len(rest) < self.FAST_BATCH_MIN_ITEMS:
            # 剩下的不足两条, 逐条即可(不必付批通道的 system 开销)
            for i in rest:
                out[i] = self.translate_one(texts[i])
            return out

        sub = [texts[i] for i in rest]
        stats = batch_fast.BatchStats()
        res = batch_fast.fast_translate_batch(sub, self._ask_batch_llm, stats)
        self._fast_batch_stats = stats          # 供 GUI 展示/诊断
        for k, i in enumerate(rest):
            v = res[k]
            if v:
                out[i] = v
                self._memo_miss += 1
                self._memo[self._memo_key(sub[k])] = v
            else:
                # 批通道彻底失败 → 退回旧路径再试一次, 避免无谓丢失
                out[i] = self.translate_one(texts[i])
        return out

    def _ask_batch_llm(self, texts):
        """batch_fast 的 ask 回调：发一批请求, 返回原始多行文本。

        用 BATCH_SYSTEM 而不是用户自定义 prompt：大批量需要
        「严格等行数 + 禁编号」的强约束才能保证 100% 对齐。
        实测用户那套含任务路由/纠错原则的长提示词是为**单条翻译质量**
        写的, 放进批请求反而让模型分心、破坏行对齐。
        """
        prompt = batch_fast.build_batch_prompt(texts)
        raw = self._call_llm_raw(prompt, system=batch_fast.BATCH_SYSTEM,
                                 max_tokens=max(768, len(texts) * 120))
        return raw or ''

    def _call_llm_raw(self, prompt, system=None, max_tokens=None):
        """调用 LLM 后端返回原始文本(带 system/max_tokens 控制)。"""
        if self.provider in ('OpenAI兼容', 'DeepSeek', '本地Ollama/Qwen'):
            return self._openai_compat_raw(prompt,
                                           system=system or self.get_llm_system(),
                                           max_tokens=max_tokens)
        if self.provider == 'Claude':
            return self._claude(prompt)
        if self.provider == 'Gemini':
            return self._gemini(prompt)
        return None

    def translate_batch(self, texts):
        """批量翻译。返回与 texts 等长的译文列表; 任一环节失败则整体逐条降级。

        正确性优先: 只要解析结果条数不匹配, 立即抛弃本批结果并逐条重试,
        绝不让错位的译文写入 store。
        """
        n = len(texts)
        out = [None] * n
        i = 0
        while i < n:
            # 组批: 仅收「短文本 + 尚未命中缓存/快路径」的条目
            batch, idxs = [], []
            chars = 0
            while i < n and len(batch) < self.BATCH_MAX_ITEMS:
                t = (texts[i] or '').strip()
                if not t:
                    out[i] = ''
                    i += 1
                    continue
                direct = self._local_ui_direct(t)
                if direct is not None:
                    out[i] = direct
                    i += 1
                    continue
                # P1-1: 命中结果缓存 → 直接取用, 不进批(省一次网络往返)
                mkey = self._memo_key(t)
                cached = self._memo.get(mkey)
                if cached is not None:
                    self._memo_hits += 1
                    out[i] = cached
                    i += 1
                    continue
                if len(t) > self.BATCH_ITEM_MAXLEN:
                    break
                if batch and chars + len(t) > self.BATCH_MAX_CHARS:
                    break
                if t in batch:       # 批内去重
                    i += 1
                    continue
                batch.append(t)
                idxs.append(i)
                chars += len(t)
                i += 1
            if not batch:
                # 当前条是长文本 → 走单条路径(含缓存)
                if i < n and out[i] is None:
                    out[i] = self.translate_one(texts[i])
                    i += 1
                continue
            res = self._try_batch(batch)
            if res is None:
                for j, k in enumerate(idxs):
                    out[k] = self.translate_one(texts[k])
            else:
                for j, k in enumerate(idxs):
                    out[k] = res[j]
                    if res[j]:
                        self._memo[self._memo_key(texts[k])] = res[j]
                self._memo_miss += len(idxs)
        return out

    def _try_batch(self, batch):
        """尝试一次合并请求。成功返回译文列表(与 batch 等长), 失败返回 None。"""
        try:
            joined = self.BATCH_SEP.join(batch)
            prompt = (
                '下面是 %d 条待翻译的界面文本，用 %s 分隔。\n'
                '请逐条翻译，输出时**保持完全相同的分隔符与顺序**，'
                '每条翻译不要合并、不要添加编号或解释：\n\n%s'
                % (len(batch), self.BATCH_SEP.strip(), joined))
            raw = self._call_llm(prompt)
            if not raw:
                return None
            parts = [p.strip() for p in raw.split(self.BATCH_SEP.strip())]
            if len(parts) != len(batch):
                # 模型没遵守分隔符 → 尝试按行数对齐
                lines = [l.strip() for l in raw.split('\n') if l.strip()]
                if len(lines) == len(batch):
                    parts = lines
                else:
                    return None      # 交给逐条降级, 保证正确性
            if any(not p for p in parts):
                return None
            return parts
        except Exception:
            return None

    def _call_llm(self, prompt):
        """调用当前 LLM 后端并返回纯文本(供批量请求复用)。"""
        p = self.provider
        if p in ('OpenAI兼容', 'DeepSeek', '本地Ollama/Qwen'):
            return self._openai_compat_raw(prompt, system=self.get_llm_system())
        if p == 'Claude':
            return self._claude(prompt)
        if p == 'Gemini':
            return self._gemini(prompt)
        return None

    def _openai_compat_raw(self, text, system=None, max_tokens=None):
        """与 _openai_compat 相同, 但可指定独立的 system 提示词与输出上限。

        max_tokens: v3.25 新增。实测不设上限时模型容易"加戏"输出
        超长内容(单条 3.5s vs 限长后 0.2s), 这是本地翻译慢的真正主因
        —— 耗时≈输出长度, 与提示词长短无关。
        """
        base = self.base or 'https://api.openai.com/v1'
        url = base.rstrip('/') + '/chat/completions'
        body = {
            'model': self.model or 'gpt-4o-mini',
            'temperature': 0.3,
            'messages': [
                {'role': 'system', 'content': system or self.get_llm_system()},
                {'role': 'user', 'content': text},
            ],
        }
        if max_tokens:
            body['max_tokens'] = max_tokens
        data = json.dumps(body).encode('utf-8')
        headers = {'Content-Type': 'application/json', 'User-Agent': UA}
        if self.key:
            headers['Authorization'] = 'Bearer %s' % self.key
        req = urllib.request.Request(url, data=data, headers=headers)
        timeout = 180 if self.provider in LOCAL_PROVIDERS else 60
        with urllib.request.urlopen(req, timeout=timeout) as r:
            res = json.loads(r.read().decode('utf-8'))
        return self._clean_llm(res['choices'][0]['message']['content'])

    # -- 免费 Google --
    def _google_free(self, text):
        # src=auto 时 Google 原生支持自动检测 (sl=auto)
        sl = 'auto' if self.src == 'auto' else self.src
        url = ("https://translate.googleapis.com/translate_a/single"
               "?client=gtx&sl=%s&tl=%s&dt=t&q=%s") % (
            urllib.parse.quote(sl, safe=''),
            urllib.parse.quote(self.dst, safe=''),
            urllib.parse.quote(text, safe=''))
        req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': '*/*'})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode('utf-8'))
        parts = []
        for seg in data[0]:
            if seg and seg[0]:
                parts.append(seg[0])
        return ''.join(parts)

    # -- OpenAI 兼容 / DeepSeek / 本地 HY-MT2 --
    def _openai_compat(self, text):
        base = self.base or 'https://api.openai.com/v1'
        url = base.rstrip('/') + '/chat/completions'
        body = {
            'model': self.model or 'gpt-4o-mini',
            'temperature': 0.3,
            'messages': [
                {'role': 'system', 'content': self._llm_system_with_src(text)},
                {'role': 'user', 'content': text},
            ],
        }
        # v3.25: 限制输出长度。实测不设上限时模型容易「加戏」把输出
        # 拉长数倍(单条 3.5s→0.2s)。上限按原文长度给足余量,
        # 不会截断正常译文(中文一般约为原文的 1-2 倍)。
        body['max_tokens'] = self._max_tokens_for(text)
        data = json.dumps(body).encode('utf-8')
        headers = {
            'Content-Type': 'application/json',
            'User-Agent': UA,
        }
        if self.key:
            headers['Authorization'] = 'Bearer %s' % self.key
        req = urllib.request.Request(url, data=data, headers=headers)
        # 本地大模型单条请求可能较慢: 放宽到 180s, 云端仍用 60s
        timeout = 180 if self.provider in LOCAL_PROVIDERS else 60
        with urllib.request.urlopen(req, timeout=timeout) as r:
            res = json.loads(r.read().decode('utf-8'))
        return self._clean_llm(res['choices'][0]['message']['content'])

    @staticmethod
    def _max_tokens_for(text):
        """按原文长度估算输出上限。

        经验系数：中日文约 2.5 token/字, 拉丁文约 1.5 token/字符,
        再留 3 倍余量兜住正常扩写, 最低 256、最高 4096。
        """
        t = text or ''
        cjk = sum(1 for c in t if '\u4e00' <= c <= '\u9fff')
        other = len(t) - cjk
        est = cjk * 2.5 + other * 1.5
        return max(256, min(4096, int(est * 3) + 64))

    # -- Anthropic Claude --
    def _claude(self, text):
        if not self.key:
            raise RuntimeError('未填写 API Key')
        base = self.base or 'https://api.anthropic.com/v1'
        url = base.rstrip('/') + '/messages'
        body = {
            'model': self.model or 'claude-3-5-sonnet-latest',
            'max_tokens': 4096,
            'system': self.get_llm_system(),
            'messages': [{'role': 'user', 'content': text}],
        }
        data = json.dumps(body).encode('utf-8')
        req = urllib.request.Request(url, data=data, headers={
            'Content-Type': 'application/json',
            'x-api-key': self.key,
            'anthropic-version': '2023-06-01',
            'User-Agent': UA,
        })
        with urllib.request.urlopen(req, timeout=30) as r:
            res = json.loads(r.read().decode('utf-8'))
        return self._clean_llm(res['content'][0]['text'])

    # -- Google Gemini --
    def _gemini(self, text):
        if not self.key:
            raise RuntimeError('未填写 API Key (Gemini)')
        model = self.model or 'gemini-1.5-flash'
        url = ("https://generativelanguage.googleapis.com/v1beta/models/%s"
               ":generateContent?key=%s") % (urllib.parse.quote(model),
                                             urllib.parse.quote(self.key))
        body = {
            'contents': [{'role': 'user', 'parts': [
                {'text': self._llm_system_with_src(text) + '\n\n' + text}]}],
        }
        data = json.dumps(body).encode('utf-8')
        req = urllib.request.Request(url, data=data, headers={
            'Content-Type': 'application/json', 'User-Agent': UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            res = json.loads(r.read().decode('utf-8'))
        return self._clean_llm(res['candidates'][0]['content']['parts'][0]['text'])

    # -- DeepL --
    def _deepl(self, text):
        key = self.key or self.cfg.get('deepl_key', '')
        if not key:
            raise RuntimeError('未填写 DeepL ApiKey')
        # Base 若填的是 https://api-free.deepl.com/v2 这类域名, 需补 /translate 端点;
        # 留空则用官方默认地址
        url = (self.base or 'https://api-free.deepl.com/v2').rstrip('/')
        if not url.endswith('/translate'):
            url += '/translate'
        params = {
            'auth_key': key,
            'text': text,
            'target_lang': deepl_lang(self.dst).upper(),
        }
        # src=auto 时省略 source_lang, DeepL 服务端自动检测
        if self.src != 'auto':
            params['source_lang'] = deepl_lang(self.src).upper()
        data = urllib.parse.urlencode(params).encode('utf-8')
        req = urllib.request.Request(url, data=data, headers={'User-Agent': UA})
        with urllib.request.urlopen(req, timeout=20) as r:
            res = json.loads(r.read().decode('utf-8'))
        return res['translations'][0]['text']

    # -- 百度 --
    def _baidu(self, text):
        appid = self.appid or self.cfg.get('baidu_id', '')
        secret = self.secret or self.cfg.get('baidu_secret', '')
        if not (appid and secret):
            raise RuntimeError('未填写 百度 AppId / Secret')
        import hashlib
        import random
        salt = str(random.randint(10000, 999999))
        sign = hashlib.md5((appid + text + salt + secret).encode('utf-8')).hexdigest()
        params = {
            'q': text, 'from': 'auto', 'to': baidu_lang(self.dst),
            'appid': appid, 'salt': salt, 'sign': sign,
        }
        url = "https://fanyi-api.baidu.com/api/trans/vip/translate?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={'User-Agent': UA})
        with urllib.request.urlopen(req, timeout=20) as r:
            res = json.loads(r.read().decode('utf-8'))
        if 'trans_result' not in res:
            raise RuntimeError('百度翻译错误: ' + str(res))
        return ''.join(t['dst'] for t in res['trans_result'])

    @staticmethod
    def _clean_llm(s):
        if not s:
            return ''
        s = s.strip()
        # 去掉整体包裹的代码围栏 / 引号
        if s.startswith('```') and s.endswith('```'):
            s = s[3:-3].strip()
        if len(s) >= 2 and ((s[0] == '"' and s[-1] == '"') or (s[0] == "'" and s[-1] == "'")):
            s = s[1:-1].strip()
        return s


# ----------------------------------------------------------------------------
# CSV 导入 / 导出
# ----------------------------------------------------------------------------
def export_csv(store, path):
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(['original', 'translation', 'status'])
        for e in store.entries:
            w.writerow([e['original'], e['translation'], e['status']])


def import_csv(store, path, mode='merge'):
    rows = []
    with open(path, encoding='utf-8-sig', errors='replace', newline='') as f:
        r = csv.DictReader(f)
        for row in r:
            o = (row.get('original') or '').replace('\r', '')
            t = (row.get('translation') or '').replace('\r', '')
            if o == '':
                continue
            rows.append((o, t))
    if mode == 'replace':
        store.entries = []
        seen = set()
        for o, t in rows:
            if o in seen:
                continue
            seen.add(o)
            store.entries.append({'original': o, 'translation': t,
                                  'status': classify(o, t)})
        store.dirty = True
        return len(store.entries)
    index = {e['original']: e for e in store.entries}
    updated = 0
    for o, t in rows:
        if o in index:
            if index[o]['translation'] != t:
                index[o]['translation'] = t
                store.update_status(index[o])
                updated += 1
        else:
            store.entries.append({'original': o, 'translation': t,
                                  'status': classify(o, t)})
            updated += 1
    if updated:
        store.dirty = True
    return updated


# ----------------------------------------------------------------------------
# 本地配置 (提供方 / API / 模型)
# ----------------------------------------------------------------------------
def load_config():
    cfg = {
        'provider': '免费Google', 'base': '', 'key': '', 'model': '',
        'appid': '', 'secret': '', 'src': 'auto', 'dst': 'zh-CN',
        'concurrency': '3', 'delay': '0.3', 'prompt': '',
        'provider_mem': {},
        # v3.18: 游戏目录记忆 —— game_dir 为上次使用的目录,
        # recent_dirs 为最近 5 个(持久化为 | 分隔字符串)
        'game_dir': '',
        'recent_dirs': [],
        # v3.28: 保存时是否同步把译文写到「注入工具认的位置」（默认开）。
        #       关掉的方法：config.ini 里 [translate] sync_kit = 0
        'sync_kit': '1',
        # v4.0 (FR-37): 七步流水线状态持久化 —— 启动时回到上次所在步骤。
        #       空串 = 从未走过流程（首次启动落第 0 步）
        'flow.current_step': '',
        'flow.max_step': '',
    }
    cp = configparser.RawConfigParser()  # RawConfigParser: % 不触发插值(prompt 含 %s)
    if os.path.isfile(CONFIG_PATH):
        try:
            cp.read(CONFIG_PATH, encoding='utf-8')
            if cp.has_section('translate'):
                for k in cfg:
                    # provider_mem/recent_dirs 为复合类型, 不走字符串直读
                    if k in ('provider_mem', 'recent_dirs'):
                        continue
                    if cp.has_option('translate', k):
                        cfg[k] = cp.get('translate', k)
            # 最近目录: 持久化为 '|' 分隔(Windows 路径不含该字符), 读回为 list
            if cp.has_option('translate', 'recent_dirs'):
                raw = cp.get('translate', 'recent_dirs') or ''
                cfg['recent_dirs'] = [p.strip() for p in raw.split('|') if p.strip()]
            # 读取「每提供方自定义记忆」段 [provider:xxx] (base/model/key)
            mem = {}
            for sec in cp.sections():
                if sec.startswith('provider:'):
                    nm = sec[len('provider:'):]
                    if nm not in PROVIDERS:
                        continue
                    m = {}
                    for k in ('base', 'model', 'key'):
                        if cp.has_option(sec, k):
                            v = cp.get(sec, k).strip()
                            if v:
                                m[k] = v
                    if m:
                        mem[nm] = m
            cfg['provider_mem'] = mem
        except Exception:
            pass
    return cfg


def save_config(cfg):
    cp = configparser.RawConfigParser()  # RawConfigParser: 原样保存 % 等字符
    cp['translate'] = {k: cfg[k] for k in
                       ('provider', 'base', 'key', 'model', 'appid', 'secret',
                        'src', 'dst', 'concurrency', 'delay', 'prompt',
                        'sync_kit')}
    # v3.18: 游戏目录记忆(简单字符串键, 单独追加)
    cp['translate']['game_dir'] = str(cfg.get('game_dir', '') or '')
    cp['translate']['recent_dirs'] = '|'.join(cfg.get('recent_dirs') or [])
    # v4.0 (FR-37): 步骤状态（键名带点，RawConfigParser 原样存取）
    cp['translate']['flow.current_step'] = str(cfg.get('flow.current_step', '') or '')
    cp['translate']['flow.max_step'] = str(cfg.get('flow.max_step', '') or '')
    # 每提供方自定义记忆段 [provider:xxx]: 仅写非空且有差异的自定义值
    for nm, m in (cfg.get('provider_mem') or {}).items():
        if nm not in PROVIDERS:
            continue
        cp['provider:' + nm] = {k: v for k, v in m.items() if v}
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        cp.write(f)


# ----------------------------------------------------------------------------
# GUI
# ----------------------------------------------------------------------------
