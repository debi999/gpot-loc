#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
独游翻译器 · 注入工具安装器 (Kit Installer)
================================================================
配合 `kit_catalog.py` 完成两件事：

  ① **部署注入工具**：<｜hy_place▁holder▁no▁813｜>下载 → 缓存 → 校验 → 解压 → 铺到游戏目录
  ② **落地译文**：按 sink 定义把翻译结果写进「注入工具认的那个位置」

     engine_detector ──► kit_catalog ──► kit_installer ──► 游戏目录
     （识别引擎）        （要装什么/往哪放）  （真的去装/真的写）

三条不变的前提
--------------
* **零第三方依赖**：只用标准库（urllib / zipfile / hashlib / shutil）。
* **默认不覆盖**：游戏目录里已存在的文件一律 skip —— 老板手上调好的配置
  （BepInEx.cfg / AutoTranslatorConfig.ini 等）比「最新版」值钱得多。要覆盖
  必须显式 `force=True`。
* **离线优先**：本地缓存里有就直接装，不联网。缺了才下载，且自动选最快的源。

用法:
    python kit_installer.py <游戏目录> --plan              # 只列计划，不动手
    python kit_installer.py <游戏目录> --install           # 真的安装
    python kit_installer.py <游戏目录> --install --optional
    python kit_installer.py <游戏目录> --install --force   # 覆盖已有文件
"""

import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile

# M2 迁移适配（唯一改动）：包内相对导入（原为 `import kit_catalog as catalog`）
from . import kit_catalog as catalog

# --- UTF-8 输出引导 ---------------------------------------------------------
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass


class KitError(RuntimeError):
    """安装器可预期的失败（下载失败 / 校验不过 / 目标不可写）。"""


class LowSpeed(KitError):
    """下载速度长期低于阈值 —— 触发切换到下一个候选源。"""


# ----------------------------------------------------------------------------
# 默认路径
# ----------------------------------------------------------------------------
# 缓存跟着**源码库**走（I 盘），不进游戏目录 —— 按项目的盘位铁律：
#   开发过程产物 → I 盘代码库；交付产物 → F 盘游戏目录。
# ----------------------------------------------------------------------------
# ⚠️ PyInstaller 从 PYZ **内存加载**模块时 `__file__` 不存在（不是 None，是直接
# NameError）。打包成 exe 后若这里不设防，`import kit_installer` 会在**模块级**
# 抛异常 → GUI 顶部的 try/except ImportError **接不住**（NameError 不是 ImportError）
# → 整个 GUI 起不来。2026-10-08 验包时发现，必须这么写。
try:
    _HERE = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _HERE = os.getcwd()          # exe 双击启动时 cwd 通常就是 exe 所在目录
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, '..'))


def default_cache_dir():
    """工具包下载缓存根目录。"""
    env = os.environ.get('ST_TOOL_CACHE', '').strip()
    if env:
        return os.path.abspath(env)
    return os.path.join(_REPO_ROOT, 'toolcache')


def default_tool_dir():
    """解包类工具的落脚目录（不进游戏目录）。"""
    env = os.environ.get('ST_TOOL_DIR', '').strip()
    if env:
        return os.path.abspath(env)
    return os.path.join(default_cache_dir(), 'tools')


# ----------------------------------------------------------------------------
# 下载：多候选源 + 低速自动切换
# ----------------------------------------------------------------------------
# 本机实测（2026-10-08）：GitHub 直连 ~25KB/s，ghfast.top 镜像 ~1.5MB/s。
# 差 60 倍，所以宁可早点发现慢、早点换源，也别干等。
# ----------------------------------------------------------------------------
MIN_SPEED_BPS = 20 * 1024        # 低于 20KB/s 判定为「活着但太慢」
SPEED_WINDOW = 6.0               # 每 6 秒做一次速度体检
CONNECT_TIMEOUT = 20             # 连接超时（秒）
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) indie-game-translator/kit'


def _download_once(url, dest, log=None, expect_size=None,
                   min_speed=MIN_SPEED_BPS, window=SPEED_WINDOW):
    """单次流式下载。低速太久抛 LowSpeed。返回 (bytes, elapsed)。

    边下边写临时文件 .part，成功才 rename —— 避免 Ctrl-C 留下半个坏 zip
    被下一次当成「缓存已命中」。
    """
    log = log or (lambda *a, **k: None)
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    tmp = dest + '.part'
    got = 0
    t0 = time.time()
    last_check = t0
    last_got = 0
    try:
        resp = urllib.request.urlopen(req, timeout=CONNECT_TIMEOUT)
        try:
            total = int(resp.headers.get('Content-Length') or 0) or expect_size or 0
            with open(tmp, 'wb') as f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    got += len(chunk)
                    now = time.time()
                    if now - last_check >= window:
                        speed = (got - last_got) / max(now - last_check, 1e-6)
                        if speed < min_speed and (now - t0) > window:
                            raise LowSpeed(
                                '%.0f B/s 太慢（阈值 %d B/s）' % (speed, min_speed))
                        last_check = now
                        last_got = got
                        if total:
                            log('      ...%d/%d (%d%%)' %
                                (got, total, min(100, got * 100 // total)))
        finally:
            resp.close()
    except Exception:
        try:
            if os.path.isfile(tmp):
                os.remove(tmp)
        except Exception:
            pass
        raise
    os.replace(tmp, dest)
    return got, time.time() - t0


def sha256_file(path):
    """算文件 sha256。大文件也没事，分块读。"""
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for blk in iter(lambda: f.read(1 << 20), b''):
            h.update(blk)
    return h.hexdigest()


def download_pack(pack, dest, log=None, prefer='mirror'):
    """按候选源顺序尝试下载，成功返回 (bytes, elapsed, used_url)。

    低速（LowSpeed）/ 网络错误都会自动换下一个源；全挂了抛 KitError。
    """
    log = log or (lambda *a, **k: None)
    urls = catalog.build_urls(pack, prefer=prefer)
    errors = []
    for i, url in enumerate(urls, 1):
        log('   [%d/%d] %s' % (i, len(urls), url))
        try:
            n, el = _download_once(url, dest, log=log, expect_size=pack.get('size'))
            log('       %d 字节，%.1fs（%.0f KB/s）' %
                (n, el, (n / el / 1024) if el > 0 else 0))
            return n, el, url
        except LowSpeed as e:
            errors.append('%s → %s' % (url, e))
            log('       速度不达标，换下一个源')
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
            errors.append('%s → %s' % (url, e))
            log('       失败：%s' % e)
    raise KitError('全部候选源都失败:\n  ' + '\n  '.join(errors))


# ----------------------------------------------------------------------------
# 缓存：命中就不联网
# ----------------------------------------------------------------------------

def cache_path_for(pack, cache_dir=None):
    """某个包在缓存里该待的位置。"""
    d = cache_dir or default_cache_dir()
    return os.path.join(d, pack['filename'])


def _cache_is_good(path, pack):
    """缓存文件能不能直接用。

    有 sha256 就严格校验内容；没有 sha256 的包（比如 IL2CPP 版，还没实拉过）
    退而求其次只比对体积 —— 校验强度弱是**故意降级**并对外说明，
    不假装做到了内容级校验。
    """
    if not os.path.isfile(path):
        return False
    try:
        size = os.path.getsize(path)
    except Exception:
        return False
    if pack.get('sha256'):
        try:
            if sha256_file(path) != pack['sha256']:
                return False
        except Exception:
            return False
        return True
    exp = pack.get('size')
    if exp and size != exp:
        return False
    return True


def ensure_cached(pack, cache_dir=None, log=None, prefer='mirror', force=False):
    """保证包在本地可用。返回 (path, source)；source ∈ {'cache','download'}。"""
    log = log or (lambda *a, **k: None)
    d = cache_dir or default_cache_dir()
    os.makedirs(d, exist_ok=True)
    path = cache_path_for(pack, d)
    if not force and _cache_is_good(path, pack):
        log('   缓存命中: %s' % path)
        return path, 'cache'
    if os.path.isfile(path):
        log('   缓存文件不可用（大小/哈希不匹配），重新下载')
    log('   下载: %s' % pack['title'])
    download_pack(pack, path, log=log, prefer=prefer)
    # 下完立刻校验，坏包不要留进缓存喂下一次
    if pack.get('sha256'):
        actual = sha256_file(path)
        if actual != pack['sha256']:
            try:
                os.remove(path)
            except Exception:
                pass
            raise KitError('sha256 校验失败\n  期望 %s\n  实际 %s' %
                           (pack['sha256'], actual))
        log('   sha256 校验通过')
    else:
        log('   ⚠️ 该包未登记 sha256，只做了体积比对（校验强度弱）')
    return path, 'download'


# ----------------------------------------------------------------------------
# 部署：把包铺到该去的地方
# ----------------------------------------------------------------------------

def _safe_join(root, rel):
    """拼接路径并防目录穿越（../../etc/passwd 这种）。

    zip 里的条目名来自第三方，不能信。
    """
    rel = rel.replace('\\', '/')
    parts = [p for p in rel.split('/') if p not in ('', '.', '..')]
    if not parts:
        return None
    target = os.path.abspath(os.path.join(root, *parts))
    root_abs = os.path.abspath(root)
    if target != root_abs and not target.startswith(root_abs + os.sep):
        return None
    return target


def _strip(rel, n):
    """剥掉 zip 条目名前 n 层目录。层数不够返回 None（该条目跳过）。"""
    rel = rel.replace('\\', '/')
    if n <= 0:
        return rel
    parts = rel.split('/')
    if len(parts) <= n:
        return None
    return '/'.join(parts[n:])


def _should_write(dst, force):
    """目标已存在时该怎么办。默认保护：skip。"""
    if force or not os.path.exists(dst):
        return True
    return False


def deploy_zip(zpath, dst_root, strip_root=0, force=False, log=None):
    """解压 zip 到 dst_root。返回 {'copied': n, 'skipped': n}。

    strip_root=1 表示包内有一层版本目录要剥掉。
    """
    log = log or (lambda *a, **k: None)
    stats = {'copied': 0, 'skipped': 0}
    os.makedirs(dst_root, exist_ok=True)
    with zipfile.ZipFile(zpath) as z:
        for info in z.infolist():
            rel = _strip(info.filename, strip_root or 0)
            if not rel:
                continue
            target = _safe_join(dst_root, rel)
            if target is None:
                log('     跳过异常条目: %s' % info.filename)
                continue
            if info.is_dir():
                os.makedirs(target, exist_ok=True)
                continue
            if not _should_write(target, force):
                stats['skipped'] += 1
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with z.open(info) as src, open(target, 'wb') as out:
                shutil.copyfileobj(src, out, length=1 << 20)
            stats['copied'] += 1
    return stats


def deploy_file(src, dst, force=False, log=None):
    """单个文件（如 version.dll / WolfDec.exe）复制。返回 'copied' / 'skipped'。"""
    log = log or (lambda *a, **k: None)
    if not _should_write(dst, force):
        return 'skipped'
    os.makedirs(os.path.dirname(dst) or '.', exist_ok=True)
    shutil.copy2(src, dst)
    return 'copied'


def _dest_for(pack, game_dir, tool_dir=None):
    """算出某个包的落点。返回 (kind, target_root_or_file)。

    kind: 'game_root' | 'game_file' | 'tool_dir'
    """
    dest = pack.get('dest', 'game_root')
    if dest == 'tool_dir':
        return dest, tool_dir or default_tool_dir()
    if dest == 'game_file':
        return dest, _safe_join(game_dir, pack.get('target', pack['filename']))
    return 'game_root', game_dir


# ----------------------------------------------------------------------------
# 计划 / 安装
# ----------------------------------------------------------------------------

def already_installed(pack, game_dir, tool_dir=None):
    """这个包是不是已经装过了。

    ⚠️ `dest='game_root'` 的包不能拿「游戏根目录存在」来判断 —— 那永远为真，
    结果就是**所有包都被误判成已安装**。正确做法是用 `marker`
    （该包装好后必然存在的特征文件）来判。

    tool_dir 类：已经有同名目录或文件就算装过。
    """
    kind, target = _dest_for(pack, game_dir, tool_dir)
    if kind == 'game_root':
        m = pack.get('marker')
        return bool(m) and os.path.isfile(os.path.join(game_dir, m))
    if kind == 'game_file':
        return os.path.isfile(target)
    if os.path.isdir(os.path.join(target, pack['id'])):
        return True
    return os.path.isfile(os.path.join(target, pack['filename']))


def plan_install(engine, game_dir, cache_dir=None, tool_dir=None,
                 include_optional=False, lang=None):
    """列出「会装什么、往哪放、是否已存在」——**不做任何写操作**。

    返回 dict:
        engine / display / sink_path / cache_dir / tool_dir /
        packs: [{id, title, kind, dest, cached, action, reason}]
               action ∈ 'install' | 'skip_exists' | 'skip_optional' | 'no-pack'
    """
    kit = catalog.get_kit(engine)
    if kit is None:
        raise KitError('未知引擎: %s' % engine)
    lang = lang or catalog.language_from_ini(game_dir) or catalog.DEFAULT_LANG
    packs = []
    for p in catalog.required_tools(engine, include_optional=include_optional):
        kind, target = _dest_for(p, game_dir, tool_dir)
        cached = _cache_is_good(cache_path_for(p, cache_dir), p)
        if already_installed(p, game_dir, tool_dir):
            action = 'skip_exists'
            reason = '已安装（%s 已存在；加 --force 覆盖）' % (p.get('marker') or '目标文件')
        else:
            action = 'install'
            reason = ''
        packs.append({
            'id': p['id'], 'title': p['title'], 'kind': kind,
            'dest': target, 'cached': cached, 'action': action, 'reason': reason,
            'size': p.get('size'), 'verified': p.get('verified', False),
            'optional': p.get('optional', False),
        })
    optional_skipped = len(catalog.required_tools(engine, True)) - len(packs)
    return {
        'engine': engine,
        'display': kit.get('display', engine),
        'game_dir': os.path.abspath(game_dir),
        'cache_dir': os.path.abspath(cache_dir or default_cache_dir()),
        'tool_dir': os.path.abspath(tool_dir or default_tool_dir()),
        'lang': lang,
        'sink_path': catalog.sink_path(engine, game_dir, lang),
        'sink_fmt': catalog.get_sink(engine).get('fmt'),
        'sink_desc': catalog.get_sink(engine).get('desc'),
        'packs': packs,
        'optional_skipped': optional_skipped,
        'notes': kit.get('notes', ''),
        'reason': kit.get('reason', ''),
    }


def install_kit(engine, game_dir, cache_dir=None, tool_dir=None, log=None,
                force=False, include_optional=False, prefer='mirror'):
    """真的安装。返回 dict 汇总（含每步结果，便于 GUI 展示）。"""
    log = log or (lambda *a, **k: None)
    if not os.path.isdir(game_dir):
        raise KitError('游戏目录不存在: %s' % game_dir)
    game_dir = os.path.abspath(game_dir)
    cache_dir = cache_dir or default_cache_dir()
    tool_dir = tool_dir or default_tool_dir()

    plan = plan_install(engine, game_dir, cache_dir, tool_dir, include_optional)
    results = []
    counts = {'installed': 0, 'skipped': 0, 'failed': 0}
    log('引擎: %s' % plan['display'])
    for item in plan['packs']:
        pack = catalog.get_pack(item['id'])
        if item['action'] == 'skip_exists' and not force:
            log('  [跳过] %s — %s' % (pack['title'], item['reason']))
            results.append(dict(item, result='skipped'))
            counts['skipped'] += 1
            continue
        log('  [安装] %s' % pack['title'])
        try:
            src, how = ensure_cached(pack, cache_dir, log=log, prefer=prefer)
            kind, target = _dest_for(pack, game_dir, tool_dir)
            if kind == 'game_root':
                os.makedirs(target, exist_ok=True)
                st = deploy_zip(src, target, strip_root=pack.get('strip_root', 0),
                                force=force, log=log)
                log('       %s: 新增 %d，跳过 %d' %
                    (how, st['copied'], st['skipped']))
            elif kind == 'game_file':
                act = deploy_file(src, target, force=force, log=log)
                log('       %s → %s: %s' % (how, target, act))
            else:  # tool_dir
                os.makedirs(target, exist_ok=True)
                if pack['filename'].lower().endswith('.zip'):
                    st = deploy_zip(src, os.path.join(target, pack['id']),
                                    strip_root=pack.get('strip_root', 0),
                                    force=force, log=log)
                    log('       %s → %s: 新增 %d' % (how, target, st['copied']))
                else:
                    act = deploy_file(src, os.path.join(target, pack['filename']),
                                      force=force, log=log)
                    log('       %s → %s: %s' % (how, target, act))
            results.append(dict(item, result='installed', source=how))
            counts['installed'] += 1
        except Exception as e:
            log('       失败: %s' % e)
            results.append(dict(item, result='failed', error=str(e)))
            counts['failed'] += 1
    plan.update({'results': results, 'counts': counts})
    return plan


# ----------------------------------------------------------------------------
# 译文落地
# ----------------------------------------------------------------------------

def _escape(s):
    """XUnity 行格式转义：字段内部换行写成字面 \\n。

    与 GUI `TranslationStore._escape_line` 保持一致 —— 如果不转义，一条多行
    译文会被切成两行，重载时后半句变成一篇全新的「原文」，资产直接损坏。
    """
    return (s or '').replace('\r\n', '\\n').replace('\n', '\\n').replace('\r', '\\n')


def _normalize_entries(entries):
    """接受 dict 或 (原文, 译文) 元组，统一成 [(o, t), ...]。

    空原文一律丢掉 —— XUnity 里空原文是不可用的 key。
    """
    out = []
    for e in entries:
        if isinstance(e, dict):
            o, t = e.get('original', ''), e.get('translation', '')
        else:
            o, t = (list(e) + ['', ''])[:2]
        if o:
            out.append((o, t or ''))
    return out


def _rpy_quote(s):
    """Ren'Py 字符串转义：反斜杠与双引号。"""
    return (s or '').replace('\\', '\\\\').replace('"', '\\"')


def _write_atomic(path, text, bom=False, backup=True, log=None):
    """原子写 + .bak 备份。与 GUI save() 同一套策略（写了 Fsync，异常留原文件）。"""
    log = log or (lambda *a, **k: None)
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    if backup and os.path.isfile(path):
        try:
            sb = path + '.bak'
            shutil.copy2(path, sb)
        except Exception as e:
            log('      ⚠️ 备份失败（继续写主文件）: %s' % e)
    tmp = path + '.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8', newline='') as f:
            if bom:
                f.write('\ufeff')
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            if os.path.isfile(tmp):
                os.remove(tmp)
        except Exception:
            pass
        raise


def write_translations(engine, game_dir, entries, lang=None, backup=True,
                       log=None, min_sync=None):
    """把译文写进「注入工具认的位置」。

    entries: [{'original','translation'}] 或 [(原文, 译文)]
    min_sync: 少于这个条数就拒绝写入（GUI 防误清空的护栏，默认 None=不限制）

    返回 dict(path, fmt, count, note)。
    """
    log = log or (lambda *a, **k: None)
    if not os.path.isdir(game_dir):
        raise KitError('游戏目录不存在: %s' % game_dir)
    if lang and ('/' in lang or '\\' in lang or lang in ('.', '..')):
        raise KitError('非法的语言标识: %r' % lang)
    game_dir = os.path.abspath(game_dir)
    lang = lang or catalog.language_from_ini(game_dir) or catalog.DEFAULT_LANG
    rows = _normalize_entries(entries)
    if min_sync and len(rows) < min_sync:
        raise KitError('只有 %d 条，少于安全阈值 %d —— 疑似误操作，已拒绝写入'
                       % (len(rows), min_sync))

    sink = catalog.get_sink(engine)
    fmt = sink.get('fmt', 'manual')
    note = ''

    # ---- Ren'Py：原生 tl 机制 ----
    if fmt == 'rpy':
        d = catalog.sink_dir(engine, game_dir, lang)
        if not d:
            raise KitError('引擎 %s 未定义译文目录' % engine)
        path = os.path.join(d, 'strings.rpy')
        body = ['translate %s strings:\n' % lang, '']
        for o, t in rows:
            body.append('    old "%s"' % _rpy_quote(o))
            body.append('    new "%s"' % _rpy_quote(t))
            body.append('')
        _write_atomic(path, '\n'.join(body), backup=backup, log=log)
        note = ("生成 Ren'Py translate 块。⚠️ 该格式**未在实际游戏里跑过**，"
                '拿一个备份存档的游戏先试。')
        return {'path': path, 'fmt': fmt, 'count': len(rows), 'note': note}

    # ---- 其余：统一下 kv 落点 ----
    # kv / builtin / manual 的目标都是「一个 txt 词典」，区别只在后续由谁消费：
    #   kv      → XUnity 运行时直接读，写完即生效
    #   builtin → 翻译器工作副本，还需各自的 apply（RPG Maker 的 apply 尚未实现）
    #   manual  → 工作副本 + 人工按引擎流程回填
    path = catalog.sink_path(engine, game_dir, lang)
    if not path:
        raise KitError('引擎 %s 没有单文件落点，需人工处理' % engine)
    text = ''.join('%s=%s\n' % (_escape(o), _escape(t)) for o, t in rows)
    _write_atomic(path, text, bom=True, backup=backup, log=log)
    if fmt == 'kv':
        note = '注入工具运行时直接读这个文件 —— 重开游戏即生效。'
    elif fmt == 'builtin':
        note = ('工作副本已写。**真正生效还需要 apply 步骤**（回写引擎数据文件），'
                '该步骤当前未实现。')
    else:
        note = ('工作副本已写。该引擎没有通用注入器，'
                '需按引擎各自的流程回填到游戏数据。')
    return {'path': path, 'fmt': fmt, 'count': len(rows), 'note': note}


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------

def _detect_engine(game_dir):
    """调 engine_detector 自动识别。识别不出来抛 KitError。"""
    try:
        import engine_detector
    except ImportError:
        raise KitError('找不到 engine_detector.py（需与 kit_installer 同目录）')
    eng, conf = engine_detector.detect_best(game_dir)
    if not eng:
        raise KitError('识别不出引擎：硬特征和软特征都没有命中')
    return eng, conf


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description='独游翻译器 · 注入工具安装器')
    ap.add_argument('game_dir', help='游戏根目录')
    ap.add_argument('--plan', action='store_true', help='只列计划不动手')
    ap.add_argument('--install', action='store_true', help='执行安装')
    ap.add_argument('--force', action='store_true', help='覆盖已存在的文件')
    ap.add_argument('--optional', action='store_true', help='连可选包一起装')
    ap.add_argument('--engine', help='指定引擎（默认自动识别）')
    ap.add_argument('--cache-dir', help='下载缓存目录')
    ap.add_argument('--json', action='store_true', help='JSON 输出')
    args = ap.parse_args(argv)

    game_dir = os.path.abspath(args.game_dir)
    if not os.path.isdir(game_dir):
        print('游戏目录不存在: %s' % game_dir)
        return 1
    try:
        if args.engine:
            engine, conf = args.engine, 1.0
        else:
            engine, conf = _detect_engine(game_dir)
    except KitError as e:
        print(str(e))
        return 1

    if args.json:
        plan = plan_install(engine, game_dir, args.cache_dir,
                            include_optional=args.optional)
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0

    print('=' * 62)
    print(' 游戏目录: %s' % game_dir)
    print(' 引擎: %s%s' % (engine, '' if args.engine else '（自动识别，置信度 %.0f%%）'
                        % (conf * 100)))
    print('=' * 62)

    if not args.install:
        plan = plan_install(engine, game_dir, args.cache_dir,
                            include_optional=args.optional)
        kit = catalog.get_kit(engine)
        print(' 方案: %s' % plan['display'])
        if kit.get('reason'):
            print('   %s' % kit['reason'])
        print(' 工具包:')
        for p in plan['packs']:
            flag = '✓核实过' if p['verified'] else '⚠未核实'
            mark = '已缓存' if p['cached'] else '需下载'
            print('   - %s  [%s/%s/%s]' %
                  (p['title'], flag, mark,
                   '%.1fMB' % (p['size'] / 1048576.0) if p['size'] else '?'))
            print('     落点 %s' % p['dest'])
            if p['action'] == 'skip_exists':
                print('     → %s' % p['reason'])
        if plan['optional_skipped']:
            print('   （另有 %d 个可选包未列入，加 --optional 包含）'
                  % plan['optional_skipped'])
        print(' 译文落点: %s' % plan['sink_path'])
        print('     格式: %s' % plan['sink_fmt'])
        print(' 提示: 加 --install 真正执行')
        return 0

    # install_kit 默认把日志吃掉（log=None → 内部 no-op），CLI 这里要真打出来
    _log = lambda m, *a: print(m)  # noqa: E731  （内部调用一律单参数格式串）
    try:
        res = install_kit(engine, game_dir, cache_dir=args.cache_dir,
                          force=args.force, include_optional=args.optional,
                          log=_log)
    except KitError as e:
        print(str(e))
        return 1
    print('-' * 62)
    print(' 安装完成: 新增 %d / 跳过 %d / 失败 %d' %
          (res['counts']['installed'], res['counts']['skipped'],
           res['counts']['failed']))
    print(' 译文落点: %s' % res['sink_path'])
    return 0 if res['counts']['failed'] == 0 else 2


if __name__ == '__main__':
    sys.exit(main())
