# G-POT Loc · G-POT 翻译器

**把生肉熬成蜜语。** · *Localize the desire.*

**Hook · Extract · Translate.**

---

G-POT Loc 是一条面向独立游戏的七步汉化流水线：识别引擎 → 部署注入工具 →
提取文本 → 翻译校对 → 按引擎把译文真正落到游戏里 → 验证生效 → 可一键还原。
名字里的 **Pot（锅）** 就是这条流水线本身 —— 生肉下锅，火候到了，出锅的就是蜜语。

> 命名方案由项目所有者于 2026-10-09 确定并生效（中文名 / 英文名 / repo 名 / 双语 slogan / 流程标语）。

## 当前状态

| 阶段 | 状态 |
|---|---|
| UI 版面（七步流水线） | ✅ 已定稿（原型 `prototype/ui-prototype.html`，v0.2 密度收窄版） |
| **C 路线最小原型**（Python 内核 + WebView2） | ✅ 三层解耦架构跑通，见 [`src/`](src/) 与 [docs/开发计划.md](docs/开发计划.md) |
| 业务功能按新版迁移（真实内核接入） | ⏳ M2（见 [docs/开发计划.md](docs/开发计划.md)） |
| 可用稳定版本 | v3.x（旧界面），代码与回归测试在旧库继续可用 |

## 七步流程

```
0 配置翻译服务      （一次性）
1 选择游戏目录      （一次性）
2 识别引擎 + 部署注入工具（一次性，换游戏重来）
3 提取待翻译文本    （游戏更新后）
4 翻译与人工校对    （每轮迭代）
5 保存并应用到游戏  （每轮迭代，按引擎自动变脸）
6 启动验证 / 一键还原（每次应用后）
```

## 特性一览

- **15 类游戏引擎识别**：Unity (Mono/IL2CPP)、Ren'Py、RPG Maker MV/MZ/Legacy、
  Kirikiri、WolfRPG、Godot、GameMaker、Flash、TyranoScript、NScripter、Unreal、SRPG Studio
- **8 种翻译后端**：本地 Ollama（离线）/ OpenAI 兼容 / Google 免费 / Claude / Gemini / DeepL / 百度等
- **注入工具自动部署**：清单化管理（缓存优先 → 镜像下载 → sha256 校验 → 部署），没有可靠方案的引擎如实留白
- **按引擎分流落地**：Unity 保存即生效（不改游戏本体）；RPG Maker 备份原文后字段白名单回写；
  无自动方案的引擎不伪装，给出真实缺失原因
- **提取护栏**：截断残片过滤（实测拦截 35.4%、0 误伤）与污染词条过滤（0 误伤）
- **诚实性约束**：未执行的步骤不编造状态；已验证 / 仅查过 API 的工具包状态分开显示
- **翻译为可选项（FR-49）**：第 3 步（提取）完成后，第 4 步（翻译）与第 5 步（保存）**同时解锁**；老条目已译、或仅想验证「提取 → 写入」链路时，可跳过翻译直接保存，未译条目照常落盘
- **保存步骤锁死当前引擎（FR-48）**：第 5 步锁定在第 2 步识别出的引擎；切到非当前引擎时保存按钮禁用并提示锁定原因，后端 `/api/sink/apply` 二次校验拦截越权写入（返回 `400 engine_mismatch`）

## 源码（C 路线最小原型）

`src/` 是 v4.0 的应用真源，采用 **core / api / ui 三层解耦**（详见 [`src/README.md`](src/README.md)）：
内核纯 Python 零依赖 UI、HTTP 桥唯一连接、前端纯静态。**仓库根已放好两个启动 bat**
（`启动 G-POT 翻译器(浏览器版).bat` 推荐首选，最稳；`启动 G-POT 翻译器.bat` 为 WebView2 原生窗口），
双击即可运行。手动运行：

```bash
cd src
pip install -r requirements.txt      # 只需 pywebview（Windows 自带 WebView2 运行时）
python main.py                       # 开 WebView2 窗口；或 --no-gui 只起 API
python tests/test_pipeline.py        # 内核解耦测试（只 import core）
```

## 文档索引

| 文档 | 内容 |
|---|---|
| [docs/项目说明书.md](docs/项目说明书.md) | 定位、架构、数据流、设计决策记录 |
| [docs/UI规格说明书.md](docs/UI规格说明书.md) | 七步版面 FR-35~FR-49、能力归位映射、验收清单 |
| [docs/使用手册.md](docs/使用手册.md) | 面向玩家的分步操作说明与 FAQ |
| [docs/测试用例.md](docs/测试用例.md) | TC 用例（按 FR 编号）、旧回归资产继承映射 |
| [docs/开发计划.md](docs/开发计划.md) | 里程碑、技术栈决策矩阵、源码迁移清单 |
| [docs/本地测试指南.md](docs/本地测试指南.md) | 双击即测：启动方式、七步走查、已知限制 |
| [prototype/ui-prototype.html](prototype/ui-prototype.html) | 可点击的高保真原型（浏览器直接打开） |

## 与旧项目的关系

- 旧库 `debi999/indie-game-translator`（v3.x 及更早）：**冻结为历史**，保留全部开发过程产物，
  不再迭代；其中 `gui/` 的共享模块与测试体系是本项目的直接血缘。
- 本库 `debi999/gpot-loc`：**唯一活跃仓库**。v4.0 起的全部新代码、文档、测试都在这里。
- 源码迁移按 [docs/开发计划.md](docs/开发计划.md) 的清单执行，迁移时只搬家不改逻辑。
