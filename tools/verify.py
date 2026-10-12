"""G-POT Loc 一键回归 —— 按改动自动判档，一条命令跑完该跑的。

背景（2026-10-13）：改完一次要手工拼 4 段命令、记 4 个环境变量、起 2 个端口不同的
服务，每次开工都重踩一遍。本脚本把「规则检查 → 单测 → 冒烟 → 端到端」收成一条命令。

**默认自动判档**（`--tier auto`，由 `tools/tier.py` 按改动路径判定）：

| 档 | 触发 | 跑什么 | 耗时 |
|----|------|--------|------|
| T1 | 文档 / 注释 / 基线 / 规则文件 | 只跑规则检查 | ≈3s |
| T2 | UI 资源 / 测试 / 冒烟脚本 | 规则 + 单测 + 真浏览器冒烟 | ≈50s |
| T3 | core / api / 入口 / 端到端脚本 | 全套（再 + 端到端） | ≈55s |

改一行文档不该等 50 秒，改 core 分层不该只跑单测 —— 让脚本判，别让人判。

用法（仓库根目录）：
    python tools/verify.py              # 自动判档（日常就用这条，别加参数）
    python tools/verify.py --tier 3     # 强制全套（提交前 / 改了 core 时）
    python tools/verify.py --only unit  # 手动覆盖档位（调试用）
    python tools/verify.py --no-rules   # 跳过规则检查，只跑测试
    python tools/verify.py --port 18999 # 指定端口

约定：
- 单测固定注入 ST_NO_LOCAL_LLM=1（老板纪律：日常回归禁止真跑本地 LLM 占显存）。
- 冒烟与端到端共用**同一个服务实例**（端到端脚本硬编码 18771，故默认就用它，
  避免起两个服务）。
- **规则检查先跑、失败即止**：规则不过再跑 50 秒测试是纯浪费。
- 退出码 0=全绿，1=有失败。
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import tier  # noqa: E402  （单一真源：改动分级，rule_check.py 也用它）

# 端到端硬编码 18771，统一端口 = 只起一次服务
DEFAULT_PORT = 18771
PY = sys.executable
NODE = r"C:/Users/Administrator/.workbuddy/binaries/node/versions/22.22.2-6/node.exe"
NODE_MODULES = r"C:/Users/Administrator/.workbuddy/binaries/node/workspace/node_modules"


def _env(port: int) -> dict:
    e = dict(os.environ)
    e["PYTHONPATH"] = str(SRC)
    e["ST_NO_LOCAL_LLM"] = "1"          # 纪律：日常回归不真跑本地 LLM
    e["GPOT_PORT"] = str(port)
    e["NODE_PATH"] = NODE_MODULES
    e["NO_PROXY"] = "*"                 # 绕本机代理，避免 127.0.0.1 被劫
    e["no_proxy"] = "*"
    return e


def _wait_up(port: int, timeout: float = 25.0) -> bool:
    deadline = time.time() + timeout
    url = f"http://127.0.0.1:{port}/"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.4)
    return False


def _tail(text: str, n: int = 12) -> str:
    lines = [l for l in text.splitlines() if l.strip()]
    return "\n".join(lines[-n:])


def run_rules(env: dict) -> tuple[bool, str]:
    """规则合规检查（秒级）。先跑它、失败即止，比先跑 50 秒测试划算。"""
    p = subprocess.run(
        [PY, str(TOOLS / "rule_check.py")],
        cwd=str(ROOT), env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    return p.returncode == 0, (p.stdout or "") + (p.stderr or "")


def run_unit(env: dict) -> tuple[bool, str]:
    p = subprocess.run(
        [PY, "-m", "pytest", str(SRC / "tests"), "-q"],
        cwd=str(ROOT), env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return p.returncode == 0, _tail(p.stdout + p.stderr)


def run_smoke(env: dict) -> tuple[bool, str]:
    if not Path(NODE).exists():
        return False, f"找不到 node: {NODE}"
    p = subprocess.run(
        [NODE, str(TOOLS / "smoke_ui.js")],
        cwd=str(ROOT), env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    out = p.stdout + p.stderr
    ok = ("ALL PASS" in out) and ("FAIL" not in out)
    return ok, _tail(out)


def run_e2e(env: dict) -> tuple[bool, str]:
    p = subprocess.run(
        [PY, str(TOOLS / "e2e_check.py")],
        cwd=str(ROOT), env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    out = p.stdout + p.stderr
    ok = p.returncode == 0 and "FAIL" not in out
    return ok, _tail(out)


def _plan_for_tier(t: int) -> list[str]:
    """档位 → 要跑的测试。"""
    return {1: [], 2: ["unit", "smoke"], 3: ["unit", "smoke", "e2e"]}[t]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", choices=["auto", "1", "2", "3"], default="auto",
                    help="验证档位；auto=按改动路径自动判（默认）")
    ap.add_argument("--only", choices=["unit", "ui", "e2e", "all", "none"], default=None,
                    help="手动覆盖档位（调试用；none=只跑规则检查）")
    ap.add_argument("--no-rules", action="store_true", help="跳过规则检查")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--keep-server", action="store_true", help="跑完不关服务（调试用）")
    args = ap.parse_args()

    env = _env(args.port)
    files = tier.changed_files()
    auto_t, t_hits = tier.classify(files)
    t = auto_t if args.tier == "auto" else int(args.tier)

    print("=" * 60)
    print(f"[verify] 改动 {len(files)} 个文件 → {tier.describe(t)}")
    if t_hits and args.tier == "auto":
        print(f"[verify] 判档依据：{', '.join(t_hits[:4])}"
              f"{' …' if len(t_hits) > 4 else ''}")
    if not files:
        print("[verify] 无改动（git 干净），按 T1 处理。")
    print("=" * 60)

    # ---- 1) 规则检查（秒级，先跑；不过就别烧后面 50 秒） ----
    if not args.no_rules:
        print("[verify] 1/2 规则合规检查 ...")
        ok_rules, out_rules = run_rules(env)
        for line in out_rules.splitlines():
            if line.strip() and not line.startswith("="):
                print("   " + line)
        if not ok_rules:
            print("[verify] 规则检查未过，已中止（先修规则再跑测试，别浪费机器时间）。")
            return 1
    else:
        print("[verify] 规则检查已跳过（--no-rules）。")

    # ---- 2) 按档位跑测试 ----
    if args.only is not None:
        plan = {"none": [], "unit": ["unit"], "ui": ["unit", "smoke"],
                "e2e": ["e2e"], "all": ["unit", "smoke", "e2e"]}[args.only]
        if args.only != "none":
            print(f"[verify] 手动覆盖档位 --only {args.only}")
    else:
        plan = _plan_for_tier(t)

    results: list[tuple[str, bool, str]] = []
    if not plan:
        print("[verify] 2/2 本档无需跑测试（T1：纯文档/规则改动）。")
    else:
        need_server = ("smoke" in plan) or ("e2e" in plan)
        srv = None
        try:
            if need_server:
                print(f"[verify] 2/2 起服务 127.0.0.1:{args.port} ...")
                srv = subprocess.Popen(
                    [PY, str(SRC / "main.py"), "--port", str(args.port), "--no-gui"],
                    cwd=str(SRC), env=env,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                if not _wait_up(args.port):
                    print("[verify] 服务未就绪，中止。")
                    return 1
                print("[verify] 服务就绪。\n")
            if "unit" in plan:
                ok, out = run_unit(env)
                results.append(("单元 pytest", ok, out))
            if "smoke" in plan:
                ok, out = run_smoke(env)
                results.append(("真浏览器冒烟", ok, out))
            if "e2e" in plan:
                ok, out = run_e2e(env)
                results.append(("端到端", ok, out))
        finally:
            if srv is not None and not args.keep_server:
                srv.terminate()
                try:
                    srv.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    srv.kill()

    print("=" * 60)
    all_ok = True
    for name, ok, out in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
        if not ok:
            all_ok = False
            print("-" * 60)
            print(out)
            print("-" * 60)
    if not results:
        print("PASS  本档无需测试")
    print("=" * 60)
    print(f"RESULT: {'ALL PASS' if all_ok else 'HAS FAILURE'}   (档位 T{t})")
    if t < 3 and args.only is None:
        print("提示：提交前跑一次 `python tools/verify.py --tier 3`（全套 ≈55s）。")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
