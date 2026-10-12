# G-POT Loc · Codegraph 开发纪律

> **最高优先级开发规则**（老板 2026-10-10 拍板）：本仓库的一切开发活动
> （改代码、修 bug、迁逻辑、写测试、改文档锚点）都必须在 codegraph 的约束下进行。
> 适用对象：所有 AI 会话与人类贡献者。违反 = 不许合入。

## 八条铁律

1. **改动前先查爆炸半径**。任何修改前，先用 codegraph_explore 查目标符号
   及其**全部调用方与测试**（blast radius），禁止盲改。codegraph 未覆盖的
   符号，先读源码确认调用链再动手。

2. **改后复查爆炸半径**。被改符号列出的每个调用方、每份测试都必须同步
   更新并全绿。只改函数体不改调用方契约 = 事故。

3. **死代码不许合入**。新增的公共函数必须有调用方或有测试
   （codegraph 报「no tests found within 3 caller hops」且无调用方的符号
   不许存在）。发现孤儿符号，删除或补测试。

4. **分层铁律（codegraph 评估口径）**：
   - `core/` 纯逻辑，零 UI/HTTP 依赖（唯一真源）；
   - `api/` 只做 HTTP 映射（薄委托 + 错误码转换），**禁止新增业务逻辑**；
   - `ui/` 纯静态前端，只 fetch API，无 Python。
   评估时发现业务逻辑落在 api 层，一律下沉 core。

5. **单源纪律**。同一规则/映射/实现只许存在一份——映射表（如 SMAP）、
   筛选逻辑、去重键、状态判定，全部在 core 单源化，其他层引用。
   发现双份实现 = 立即单源化（历史教训：状态筛选键没过映射表 → 永远 0 命中）。

6. **文档锚点可验证**。《需求说明书》§5 的每个代码锚点必须能用
   codegraph 符号验证存在且语义一致；新增 FR 必须三同步：
   §5 映射表 + 测试用例 + 代码内 `# FR-xx:` 锚点注释。

7. **回归锁必须反向验红**（2026-10-13 立，老板亲定）。
   凡"为了防止某个 bug 复发"而写的断言（下称**锁**），交付前必须造出该 bug
   形态跑一次，**断言必须 FAIL**；改回修复态再跑一次，**必须 PASS**。
   两态都验过，锁才算成立。
   - 只验绿不验红 = **假锁**。前科两次：v0.6.4 FR-85 冒烟读 `.hidden` 属性判
     可见性，按钮从未显示却 86/86 全绿（跨 3 版才由老板截图发现）；
     v0.6.7 首版锁用 `\bhidden\b` 搜标签文本，被 class 值里的 hidden 词骗过，
     反向验证 4 项全绿。
   - 反向验红记录写进该测试文件的 docstring：造了什么 bug 形态、哪一项变红。
   - **无反向验红记录的锁不许合入。**
   - 模板：`tools/lock_template.py`（三件套：正向锁 + 反向验红说明 + 判据口径）。

8. **验证判据分层 + 单一入口 + 自动判档**（2026-10-13 立）。
   - **单一入口**：一律 `python tools/verify.py`，**不加参数**——它自动注入
     `PYTHONPATH=src` / `ST_NO_LOCAL_LLM=1` / `NODE_PATH` / `NO_PROXY=*` +
     自动起收服务 + 统一端口 18771，并按改动自动判档（见下节）。禁止手工拼命令。
   - **规则检查先跑、失败即止**：规则不过再跑 50 秒测试是纯浪费，脚本已串行化。
   - **判据分层**：① 可见性 / 布局 / 字体类断言，判据必须是
     `getComputedStyle().display` 或 `getBoundingClientRect()`，
     **禁止**用 class / 属性 / `STATE` 内部变量代理——代理判据正是假绿的来源
     （91 条冒烟里 67 条是代理，FR-85 因此全绿漏 bug）。
     ② 文本 / 数值类断言取渲染后 `innerText`，不取 `STATE` 字段。
     ③ 每个 FR 至少一条**路径级断言**（走完整交互），不能只验元素属性——
     FR-85 就是漏了"工具全就位→点主按钮→进第 3 步"这条路径才潜伏 3 个版本。

## 验证分级（T1/T2/T3）—— 让脚本判档，别让人判

改一行文档和改 core 分层跑同一套验证 = 每轮白烧 50 秒，还会诱导「合规表演」。
分级由 `tools/tier.py` **按改动路径自动判定**（单一真源，`rule_check.py` 也用它），
人/AI 不必自己选档——选错就是白跑或漏跑。

| 档 | 触发（改动路径） | 跑什么 | 实测 |
|----|------------------|--------|------|
| T1 | `docs/` · `*.md` · `tools/rule_baseline.txt` | 只跑规则检查 | **1.7s** |
| T2 | `src/gpot/ui/` · `src/tests/` · `tools/smoke_ui.js` | 规则 + 单测 + 真浏览器冒烟 | ≈50s |
| T3 | `src/gpot/core/` · `api/` · `src/main.py` · `hooks/` | 全套（+ 端到端） | ≈56s |

```bash
python tools/verify.py            # 自动判档（日常就用这条，别加参数）
python tools/verify.py --tier 3   # 强制全套（提交前）
python tools/verify.py --only unit  # 手动覆盖（调试）
```

> ⚠️ **解释器**：本机 pytest 只装在托管 venv，用
> `C:/Users/Administrator/.workbuddy/binaries/python/envs/default/Scripts/python.exe`。
> 系统 python 跑会报 `No module named pytest`（已实测踩到）。

## R5 UI 改动验收形态签核（硬门禁）

触及 `src/gpot/ui/` 前，在 `docs/ui-signoff.md` 的「## 签核记录」下写一行：

```
2026-10-13 · styles.css · 留白 —— 老板截图反馈：不要臃肿说明段
```

判据：记录区里须有某**行**同时含 ①今天日期 ②本次改动的文件名。缺则 `rule_check`
报 FAIL、提交被拒。这是六条规则里唯一直接砍返工轮次的（FR-84 一天内反转），
所以做成硬门禁，**且故意不设 baseline key——不许被基线豁免**。

## 提交门禁

- [ ] `python tools/verify.py` 自动判档全绿（T2/T3 改动必须真跑，`--only unit` 不达标）
- [ ] 触及 UI → `docs/ui-signoff.md` 已签核（日期为今天 + 点名改动文件）
- [ ] 本次新增的每条**回归锁**都做了反向验红（bug 形态 FAIL + 修复态 PASS），
      且记录已写进测试文件 docstring
- [ ] 新增断言若为可见性/布局/字体类，判据是 `getComputedStyle` /
      `getBoundingClientRect`，非 class / 属性 / STATE
- [ ] `node --check app.js` + `py_compile` 通过
- [ ] 改过的每个符号：爆炸半径内调用方/测试已同步
- [ ] 文档锚点与 codegraph 符号一致（改了符号名/位置必须改 §5）

## 2026-10-10 评估轮实证

本轮按此纪律执行：codegraph 两轮探索定位 8 项问题（P1×2 / P2×3 / P3×3），
全部修复并下沉 5 个业务函数到 core（`store.replace_rows/dedup_rows/edit_row/
recent_games`、`detection.find_game_exe`），`SMAP`/筛选逻辑单源化到
`core/translate.py`，测试 22→29 全绿。
