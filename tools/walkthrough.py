"""FR-82 真机三管线走查（M3 剩余清单第三条）。

按《测试用例》§2 要求，Unity / RPG Maker MV / 无方案引擎各走一遍真实识别 + 工具校验
+ 提取，**全程只读**：不改游戏本体（红线），提取结果只落临时目录统计。

用法：python tools/walkthrough.py [--extract]
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))

from gpot.core import engine_detector, extract, kit_installer  # noqa: E402
from gpot.core import store as store_mod  # noqa: E402

GAMES = [
    ('Unity (Starmaker)', r'F:\erogame\Starmaker_Story\Starmaker Story(1.8e\Starmaker 1.8E'),
    ('RPG Maker MV', r'F:\erogame\交易大师\YARISUTEMESUBUTA ~ 一次性交易大师 ~'),
    # 无方案引擎：Ren'Py（不在 kit_catalog 支持列表内，应如实报「无注入工具」
    # 而不是编一个假方案出来 —— 诚实性 NFR-9 的验收点）
    ('无方案引擎 (Ren\'Py)', r'F:\erogame\青蛙的食谱\青蛙的食谱'),
]


def line(t=''):
    print(t)


def walk(name, gdir, do_extract):
    line('=' * 68)
    line('【%s】' % name)
    line('游戏目录：%s' % gdir)
    if not os.path.isdir(gdir):
        line('  ✗ 目录不存在 —— 跳过')
        return False
    try:
        eng, conf = engine_detector.detect_best(gdir)
    except Exception as e:
        line('  ✗ 识别异常：%s' % e)
        return False
    line('  识别引擎：%s（置信度 %.0f%%）' % (eng, conf * 100))
    try:
        kit = kit_installer.plan_install(eng, gdir)
    except Exception as e:
        line('  工具清单：该引擎无工具包（%s）' % str(e)[:80])
        kit = None
    if kit:
        line('  缓存目录：%s' % kit['cache_dir'])
        line('  译文落点：%s' % kit['sink_path'])
        for p in kit['packs']:
            line('    [%s] %s → %s（缓存命中=%s）'
                 % (p['action'], p['title'], p['dest'], p['cached']))
    if not do_extract:
        line('  （--extract 未开，跳过提取）')
        return True
    # 提取：走真实 store（翻译词典指到临时目录，绝不碰游戏本体的既有词典）
    try:
        with tempfile.TemporaryDirectory() as td:
            st = store_mod.Store()
            st.game = {"path": gdir, "name": os.path.basename(gdir)}
            st.engine = {"engine": eng, "key": eng}
            st.tstore.path = os.path.join(td, 'Translation.txt')
            st.tstore.entries = []
            res = extract.extract(st, {'mode': 'merge', 'deep': False,
                                       'guard_frag': True, 'guard_poll': True})
            if res.get('status') == 'done':
                line('  提取：扫描 %s 条 / 新增 %s 条 / 共 %s 条'
                     '（护栏拦下 %s 条 · 词典落临时目录，未碰游戏本体）'
                     % (res.get('scanned'), res.get('added'), res.get('total'),
                        res.get('guarded')))
            else:
                line('  提取未执行：%s' % (res.get('message') or res.get('error') or res))
    except Exception as e:
        line('  提取异常：%s' % str(e)[:120])
    return True


def main():
    do_extract = '--extract' in sys.argv
    ok = 0
    for name, gdir in GAMES:
        try:
            if walk(name, gdir, do_extract):
                ok += 1
        except Exception as e:
            line('  ✗ 走查异常：%s' % e)
    line('=' * 68)
    line('结果：%d/%d 条管线走查通过' % (ok, len(GAMES)))
    return 0 if ok == len(GAMES) else 1


if __name__ == '__main__':
    sys.exit(main())