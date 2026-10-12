"""G-POT Loc 规则合规检查器 —— 把《修复时间成本诊断》P0~P2 变成可跑的命令。

背景（2026-10-13 老板亲定）：时间黑洞是「假绿 → 返工」，不是跑得慢。
诊断里的整改项凡是能机械判定的，全部落到本脚本，避免规则只写在文档里靠记性。

用法（仓库根）：
    python tools/rule_check.py            # 全项检查（秒级，不跑浏览器）
    python tools/rule_check.py --deep     # 额外跑一次单测，用于核对文档里的测试计数
    python tools/rule_check.py --strict   # WARN 也当 FAIL（提交门禁用）

检查项 → 对应诊断根因：

| 项 | 规则 | 诊断编号 |
|----|------|----------|
| R1 | 冒烟断言不得用 class/属性/STATE 当可见性判据（必须 getComputedStyle） | P0-1 根因 1 |
| R2 | 回归测试文件必须写「反向验红记录」 | P0-2 根因 2 |
| R3 | 版本号三处一致（APP_VERSION / docs / tests） | P2-1 根因 4 |
| R4 | 文档里的测试计数不得与实测漂移（--deep 才核） | P2-1 根因 4 |
| R5 | **硬门禁**：改动触及 UI 资源 → 必须先签核验收形态（写一行 docs/ui-signoff.md） | P1-2 根因 3 |
| R6 | 冒烟硬 sleep 总预算（当前基线 25.4s，超 40s 报 WARN） | 根因 4 |

R5 为什么从「只提示」升为「硬门禁」（2026-10-13 老板亲定）：
它是六条里**唯一直接砍返工轮次**的（FR-84 按「填内容」实现 17 段说明，
老板复看否决「臃肿」→ 一天内全部撤销）。之前它是 P1 提醒项，最容易被跳过，
而成本高的 R5（版本/计数）反倒是机械检查 —— 严格度和收益倒挂。

退出码：0=无 FAIL，1=有 FAIL（--strict 时 WARN 也算）。
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import tier  # noqa: E402  （单一真源：改动文件清单与分级，verify.py 也用它）
SRC = ROOT / "src"
TESTS = SRC / "tests"
DOCS = ROOT / "docs"
SMOKE = ROOT / "tools" / "smoke_ui.js"
SERVER = SRC / "gpot" / "api" / "server.py"

# 冒烟硬 sleep 基线（2026-10-13 实测 25420ms）
SLEEP_BUDGET_MS = 40_000


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


class Report:
    """检查报告。

    level 说明：
      FAIL  真违规，阻塞
      WARN  提示（--strict 时也阻塞）
      BASE  **已知欠账**（命中基线）—— 记在账上但不阻塞，防止老账把人卡死
      PASS / SKIP
    """

    def __init__(self, strict: bool = False, baseline: set | None = None):
        self.rows: list[tuple[str, str, str, str]] = []  # (level, rule, msg, key)
        self.strict = strict
        self.baseline = baseline or set()

    def add(self, level: str, rule: str, msg: str, key: str = ""):
        if level == "FAIL" and key and key in self.baseline:
            level = "BASE"
        self.rows.append((level, rule, msg, key))

    def fail(self, r, m, key=""): self.add("FAIL", r, m, key)
    def warn(self, r, m, key=""): self.add("WARN", r, m, key)
    def ok(self, r, m, key=""): self.add("PASS", r, m, key)
    def skip(self, r, m, key=""): self.add("SKIP", r, m, key)

    @property
    def failed(self) -> bool:
        lv = {"FAIL", "WARN"} if self.strict else {"FAIL"}
        return any(l in lv for l, _, _, _ in self.rows)

    def render(self) -> str:
        out = []
        for lvl, rule, msg, _ in self.rows:
            out.append(f"{lvl:<4} [{rule}] {msg}")
        return "\n".join(out)

    def current_keys(self) -> set:
        """当前所有违规项的 key（用于 --update-baseline）。"""
        return {k for lvl, _, _, k in self.rows if lvl in ("FAIL", "WARN") and k}


# ---------------------------------------------------------------------------
# R1 判据分层：可见性断言不得用 class / 属性 / STATE 代理
# ---------------------------------------------------------------------------
# 判据口径（前科）：v0.6.4 的 FR-85 冒烟读 `.hidden` 属性判可见性，
# 而实现用的是 hidden **类** —— 按钮从未显示，冒烟照样全绿。
# 所以：凡是「可见/隐藏/显示」语义的断言，判据必须是计算样式。
_VIS_PROXY_PATTERNS = [
    (r"classList\.contains\(\s*['\"]hidden['\"]", "classList.contains('hidden') 当可见性判据"),
    (r"\.hidden\s*\)", "读 .hidden 属性当可见性判据"),
    (r"classList\.contains\(\s*['\"]expanded['\"]", "classList.contains('expanded') 当展开态判据"),
]


def check_r1(rep: Report):
    src = _read(SMOKE)
    if not src:
        rep.warn("R1", f"读不到 {SMOKE.name}")
        return
    lines = src.splitlines()
    hits = []
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("//") or stripped.startswith("*"):
            continue                                  # 注释里讲事故不算违规
        for pat, why in _VIS_PROXY_PATTERNS:
            if re.search(pat, line):
                # 同一条断言若已用 getComputedStyle 兜底，从宽放行
                ctx = "\n".join(lines[max(0, i - 6): i + 3])
                if "getComputedStyle" in ctx:
                    continue
                # key 用「归一化代码片段」而非行号：行号会随编辑漂移，
                # 基线一漂就全变成新违规、误阻塞。
                norm = re.sub(r"\s+", "", stripped)[:60]
                hits.append((i, why, stripped, f"R1|smoke_ui.js|{norm}"))
                break
    if hits:
        for i, why, stripped, key in hits:
            rep.fail("R1", f"L{i}: {why}  → {stripped[:90]}", key)
        # 汇总提示只在「有真 FAIL」时才报 WARN：老账全进基线后不该再刷存在感，
        # 否则 --strict 会永远卡在这一条（基线机制就失去意义）。
        real = any(l == "FAIL" and r == "R1" for l, r, _, _ in rep.rows)
        if real:
            rep.warn("R1", f"共 {len(hits)} 处代理判据（其中 {real and sum(1 for l, r, _, _ in rep.rows if l == 'FAIL' and r == 'R1')} 处为新违规）；"
                           f"可见性断言改用 getComputedStyle().display 或 getBoundingClientRect()")
    else:
        rep.ok("R1", "冒烟无 class/属性代理可见性判据")


# ---------------------------------------------------------------------------
# R2 回归测试必须写反向验红记录
# ---------------------------------------------------------------------------
_MUTATION_KEYS = ("反向验红", "反向验证", "造 bug 形态", "验红")


def check_r2(rep: Report):
    if not TESTS.is_dir():
        rep.warn("R2", f"找不到 {TESTS}")
        return
    missing = []
    for f in sorted(TESTS.glob("test_*.py")):
        src = _read(f)
        # docstring = 文件开头第一个三引号块
        m = re.search(r'"""(.*?)"""', src, re.S)
        doc = m.group(1) if m else ""
        # 只针对「锁」类测试：文件名或 docstring 表明是回归锁
        is_lock = bool(re.search(r"review|回归|锁|regression", f.name, re.I)) \
            or "锁" in doc or "回归" in doc
        if not is_lock:
            continue
        if not any(k in doc for k in _MUTATION_KEYS):
            missing.append(f.name)
    if missing:
        for n in missing:
            rep.fail("R2", f"{n} 缺「反向验红记录」（铁律 7：造 bug 形态必须 FAIL，再交付）",
                     f"R2|{n}")
    else:
        rep.ok("R2", "所有回归锁测试均已记录反向验红")


# ---------------------------------------------------------------------------
# R3 版本号三处一致
# ---------------------------------------------------------------------------
def _ver_tuple(s: str):
    try:
        return tuple(int(x) for x in s.split("."))
    except Exception:
        return None


def _max_version(texts: list[str], major: str = "0"):
    """取文本里最大的版本号。

    ⚠️ 两道收紧，都是首跑实测踩出来的误报：
      ① 必须带 `v` 前缀 —— 否则 `127.0.0.1` 里的 `127.0.0` 被当版本号；
      ② 主版本必须与真源一致 —— 否则文档里引用的第三方版本（如 `v3.21.1`）
         被当成本项目版本。主版本从 APP_VERSION 取，升到 1.x 自动跟随。
    """
    best, raw = None, None
    pat = r"\bv" + re.escape(major) + r"\.(\d+)\.(\d+)\b"
    for t in texts:
        for m in re.findall(pat, t):
            full = f"{major}.{m[0]}.{m[1]}"
            tv = _ver_tuple(full)
            if tv and (best is None or tv > best):
                best, raw = tv, full
    return raw


def check_r3(rep: Report):
    srv = _read(SERVER)
    m = re.search(r'APP_VERSION\s*=\s*["\']([\d.]+)["\']', srv)
    if not m:
        rep.fail("R3", f"{SERVER.name} 里找不到 APP_VERSION（版本号唯一真源）")
        return
    truth = m.group(1)
    major = truth.split(".")[0]

    doc_texts = [_read(p) for p in DOCS.glob("*.md")] if DOCS.is_dir() else []
    test_texts = [_read(p) for p in TESTS.glob("test_*.py")] if TESTS.is_dir() else []
    v_doc = _max_version(doc_texts, major)
    v_test = _max_version(test_texts, major)

    rep.ok("R3", f"真源 APP_VERSION = {truth}")
    if v_doc and _ver_tuple(v_doc) > _ver_tuple(truth):
        rep.fail("R3", f"docs 最高版本 {v_doc} > 真源 {truth}（版本漂了，升版要改 APP_VERSION）",
                 "R3|docs-ahead")
    if v_test and _ver_tuple(v_test) > _ver_tuple(truth):
        rep.fail("R3", f"tests 最高版本 {v_test} > 真源 {truth}", "R3|tests-ahead")

    # <title> 写死版本号的历史坑（v0.6.6 之前 <title> 写 v4.0）
    idx = SRC / "gpot" / "ui" / "assets" / "index.html"
    html = _read(idx)
    t = re.search(r"<title>(.*?)</title>", html, re.S)
    if t and re.search(r"\d+\.\d+\.\d+", t.group(1)):
        rep.warn("R3", f"index.html <title> 写死了版本号「{t.group(1).strip()}」，"
                       f"升版必漂 —— 建议由后端 /api/state 注入")
    if not (v_doc and _ver_tuple(v_doc) > _ver_tuple(truth)) \
       and not (v_test and _ver_tuple(v_test) > _ver_tuple(truth)):
        rep.ok("R3", "docs / tests 版本号未超前于真源")


# ---------------------------------------------------------------------------
# R4 文档测试计数漂移（--deep 才核，需要真跑单测）
# ---------------------------------------------------------------------------
def check_r4(rep: Report, deep: bool):
    if not deep:
        rep.add("SKIP", "R4", "文档计数核对需 --deep（会跑一次单测）")
        return
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC)
    env["ST_NO_LOCAL_LLM"] = "1"
    p = subprocess.run([sys.executable, "-m", "pytest", str(TESTS), "-q"],
                       cwd=str(ROOT), env=env, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    m = re.search(r"(\d+) passed", p.stdout + p.stderr)
    if not m:
        rep.warn("R4", "没能解析出单测通过数")
        return
    actual = int(m.group(1))
    # 文档里形如「单测 127/127」「130 项」
    drift = []
    for f in DOCS.glob("*.md"):
        txt = _read(f)
        for mm in re.finditer(r"单测\s*(\d+)\s*/\s*(\d+)", txt):
            if int(mm.group(2)) != actual:
                drift.append(f"{f.name}: 「{mm.group(0)}」vs 实测 {actual}")
    if drift:
        for d in drift:
            rep.fail("R4", f"{d}（手写计数必然漂，改由脚本回填）",
                     f"R4|{d.split(':')[0]}")
    else:
        rep.ok("R4", f"文档单测计数与实测一致（{actual}）")


# ---------------------------------------------------------------------------
# R5 硬门禁：改动触及 UI 资源 → 必须先签核验收形态
# ---------------------------------------------------------------------------
# 判据口径：docs/ui-signoff.md 正文里须同时含 ①今天日期 ②本次改动的某个 UI 文件名。
# 为什么要求「今天 + 点名」：只要求文件存在 = 写一次永久豁免，规则立刻失效。
# 为什么不用交互提问：pre-commit 在非交互/AI 环境会挂死；写一行反而更快（≈10 秒）。
#
# ⚠️ 本项**故意不设 key**：不许被 rule_baseline.txt 豁免。
#    它是流程动作不是历史欠账，一旦进基线就永远绿灯，等于废除。
SIGNOFF = DOCS / "ui-signoff.md"
SIGNOFF_MARKER = "## 签核记录"


def _signoff_hits(today: str, names: list[str]) -> list[str]:
    """在「## 签核记录」之后找：某正文行同时含今天日期与某个改动文件名。

    ⚠️ 反向验红实测（2026-10-13）：首版判据是「全文含今天日期 + 含文件名」，
    结果被文件顶部**模板示例行**骗过 —— 示例里写了 `2026-10-13 · styles.css`，
    而本次改动正好有 styles.css，改回 bug 形态（日期退成昨天）仍然 PASS = 假绿锁。
    所以必须锚定到记录区，且**行级**匹配（同一行同时满足两个条件）。
    """
    raw = _read(SIGNOFF)
    if SIGNOFF_MARKER not in raw:
        return []
    body = raw.split(SIGNOFF_MARKER, 1)[1]
    lines = [l for l in body.splitlines()
             if l.strip() and not l.lstrip().startswith(("#", ">", "`"))]
    return [n for n in names
            if any((today in l) and (n in l) for l in lines)]


def check_r5(rep: Report):
    hits = tier.ui_hits(tier.changed_files())
    if not hits:
        rep.ok("R5", "本次无 UI 资源改动")
        return

    today = date.today().isoformat()
    names = [Path(f).name for f in hits]
    named = _signoff_hits(today, names)

    if named:
        rep.ok("R5", f"UI 改动已签核（{today} · 点名 {named[0]}）")
        return

    rep.fail("R5", f"UI 改动 {len(hits)} 个文件（{', '.join(names[:3])}…）未签核。"
                   f"在 docs/{SIGNOFF.name} 补一行再跑：")
    rep.fail("R5", f"    {today} · {names[0]} · 加密度|留白 —— 谁确认的、要什么形态")
    rep.fail("R5", "「加密度还是留白」先问清再写（FR-84 一天内反转的教训）")


# ---------------------------------------------------------------------------
# R6 冒烟硬 sleep 预算
# ---------------------------------------------------------------------------
def check_r6(rep: Report):
    src = _read(SMOKE)
    total = sum(int(x) for x in re.findall(r"waitForTimeout\((\d+)\)", src))
    if total > SLEEP_BUDGET_MS:
        rep.warn("R6", f"冒烟硬 sleep 合计 {total}ms > 预算 {SLEEP_BUDGET_MS}ms"
                       f"（基线 25420ms；优先换 waitForSelector，别再加 sleep）")
    else:
        rep.ok("R6", f"冒烟硬 sleep {total}ms，在预算内")


BASELINE_FILE = ROOT / "tools" / "rule_baseline.txt"


def _load_baseline() -> set:
    """已知欠账清单：命中即降级为 BASE（记账但不阻塞）。

    为什么不直接全阻塞：立规则当天仓库里已有 8 条真实欠账，全阻塞 = 老板没法提交。
    所以老账进基线、只卡新账。清一条就从基线里删一条。
    """
    if not BASELINE_FILE.is_file():
        return set()
    out = set()
    for line in _read(BASELINE_FILE).splitlines():
        line = line.strip()
        # ⚠️ 只认「整行以 # 开头」的注释，绝不按行内 # 切：
        # key 里可能含 `#p4tbody` 这类 CSS 选择器，一切就被截半截、永远匹配不上。
        if line and not line.startswith("#"):
            out.add(line)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deep", action="store_true", help="额外跑单测核对文档计数")
    ap.add_argument("--strict", action="store_true", help="WARN 也算失败")
    ap.add_argument("--update-baseline", action="store_true",
                    help="把当前全部违规写入基线文件（清账后重跑以收紧）")
    ap.add_argument("--no-baseline", action="store_true",
                    help="忽略基线，全部按真违规算（看全貌用）")
    args = ap.parse_args()

    base = set() if args.no_baseline else _load_baseline()
    rep = Report(strict=args.strict, baseline=base)
    check_r1(rep)
    check_r2(rep)
    check_r3(rep)
    check_r4(rep, args.deep)
    check_r5(rep)
    check_r6(rep)

    if args.update_baseline:
        keys = rep.current_keys()
        BASELINE_FILE.write_text(
            "# 已知欠账基线（tools/rule_check.py）\n"
            "# 命中即降级为 BASE：记账但不阻塞提交。清掉一条就删一行。\n"
            "# 生成：python tools/rule_check.py --update-baseline\n\n"
            + "\n".join(sorted(keys)) + "\n", encoding="utf-8")
        print(f"已写入 {len(keys)} 条基线 → {BASELINE_FILE}")
        return 0

    print("=" * 70)
    print(rep.render())
    print("=" * 70)
    n = {lv: sum(1 for l, _, _, _ in rep.rows if l == lv)
         for lv in ("FAIL", "WARN", "BASE")}
    print(f"FAIL {n['FAIL']} · WARN {n['WARN']} · 已知欠账 BASE {n['BASE']} · "
          f"RESULT: {'HAS FAILURE' if rep.failed else 'OK'}")
    return 1 if rep.failed else 0


if __name__ == "__main__":
    sys.exit(main())
