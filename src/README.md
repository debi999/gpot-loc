# G-POT Loc · 应用源码（C 路线，v0.4.x 实测迭代）

> 技术栈：**Python 内核 + WebView2（Fluent 观感）**，2026-10-09 老板拍板。
> M2 源码迁移已完成（2026-10-10）：内核为旧库真实业务逻辑，非 stub。

## 分层与解耦

这是本原型最重要的设计约束——**三层之间只通过契约耦合，不通过代码直连**：

```
gpot/core/   业务内核：纯 Python 逻辑，零 UI / 零 HTTP 依赖
   │  （只 export 数据 dict，被 import）
   ▼
gpot/api/    HTTP 桥：唯一把前端接到内核的地方（REST + JSON）
   │  （前端只 fetch 这个，不碰 core）
   ▼
gpot/ui/     WebView2 宿主 + 纯静态前端（HTML/JS/CSS）
```

三条硬规则（违反即算耦合回归）：

1. **`core/` 永不 import `api` 或 `ui`**。内核可在无浏览器、无网络下独立运行
   （见 `tests/test_pipeline.py`，只 import core）。
2. **`api/` 只 import `core`，只出口 JSON**。所有业务逻辑都在 core；api 只是
   序列化 + 路由。前端换技术栈（WebView2 / 真 WinUI3 壳 / tkinter）都不用动内核。
3. **`ui/assets/` 是纯静态文件**，只通过 `fetch('http://localhost:PORT/api/...')`
   与后端对话，自身不含任何 Python。

> 历史注记：M2 之前原型用 stub 跑通流程、`TODO(M2)` 标接缝；M2 已把旧库 `gui/`
> 真实逻辑迁入并替换全部接缝（API 契约不变）。当前 `core/` 即真实内核：
> `kernel.py`（旧主程序业务段）+ engine_detector / lang_detector / ui_terms /
> batch_fast / kit_catalog / kit_installer / rpgmaker_engine / check_assets。

## 本地运行

```bash
cd src
pip install -r requirements.txt      # 只需 pywebview（Windows 自带 WebView2 运行时）
python main.py                       # 开 WebView2 无边框窗口
python main.py --no-gui              # 只起 API（无界面，调试用；保留控制台）
python main.py --open-browser        # 用系统浏览器代替 WebView2
python -m pytest tests/ -q           # 跑内核测试（13 项）
```

默认 API 端口 `8731`，首页即 `http://127.0.0.1:8731/`。
GUI 模式下若进程自带控制台（假 pythonw / 控制台直跑），`main.py` 会以
`CREATE_NO_WINDOW` 无窗重启自身后退出父进程——交付形态全程无黑窗（FR-50）；
`--no-gui` / `--open-browser` 保留控制台。

## API 契约（前端消费的全部端点）

| 方法 | 路径 | 作用 |
|---|---|---|
| GET  | `/api/state`            | 全量流水线状态（步骤 / 配置 / 引擎 / 进度 / `app_version` / `prompt_default` / `external_changed` …） |
| GET  | `/api/providers`        | 翻译后端目录 |
| GET  | `/api/models`           | 获取模型列表（OpenAI /models + Ollama /api/tags 兜底，FR-54） |
| POST | `/api/config`           | 保存并测试翻译服务配置（含 src/dst/prompt/并发间隔；本地 Ollama 族连通后自动同步 server_config.ini，FR-53/55/58/59） |
| POST | `/api/game`             | 选定游戏目录（含 BepInEx 下钻 `resolve_game_root`） |
| POST | `/api/detect`           | 识别引擎 + 准备工具清单 |
| POST | `/api/deploy`           | 部署注入工具 |
| POST | `/api/extract`          | 提取待翻译文本 |
| POST | `/api/translate/start`  | 启动翻译任务 → 返回 `job_id`（scope 含 selected 勾选行，FR-61） |
| GET  | `/api/jobs/{id}`        | 轮询翻译任务进度 |
| POST | `/api/jobs/{id}/cancel` | 取消翻译任务 |
| GET  | `/api/rows`             | 第 4 步表格真数据（`limit` / `offset` / `status` / `q` / `sort` / `rev`，返回 `total` / `matched`） |
| POST | `/api/row/edit`         | 双击行内编辑译文（立即原子落盘 + 状态重判） |
| POST | `/api/row/delete`       | 删除条目（indices 去重越界忽略，FR-57） |
| GET  | `/api/sink?engine=`     | 取某引擎的「落盘形态」视图（三态） |
| POST | `/api/sink/apply`       | 保存并应用到游戏（按引擎分流；引擎不符 400） |
| GET  | `/api/verify`           | 取验证指引 + 写入自检 |
| POST | `/api/launch`           | 启动游戏主 exe（`_find_game_exe`） |
| POST | `/api/open-dir`         | 资源管理器打开译文目录 |
| GET  | `/api/pick-folder`      | 原生目录选择对话框（IFileOpenDialog，SHBrowse 兜底） |
| POST | `/api/restore`          | 还原原文（RPG Maker 备份点） |
| POST | `/api/nav`              | 导航跳转（**双闸门**：数字 max_step + 前置事实 `prereq_ok`；被拦回 400 + `blocked_reason` 说清缺哪步，FR-63） |
| POST | `/api/reset`            | 重置流程状态（回到第 0 步，译文词典不删） |
| GET  | `/api/kit/check`        | 齿轮「校验注入工具」——只读，不写盘（FR-62） |
| GET  | `/api/logs`             | 齿轮「运行日志」——只读诊断文本（FR-62） |
| POST | `/api/export-csv`       | 导出 CSV（UTF-8-sig） |
| POST | `/api/import-csv`       | 导入 CSV（merge 合并） |
| POST | `/api/import-txt`       | 导入 TXT（等号/Tab/纯原文三形态，FR-56） |
| POST | `/api/replace`          | 全局查找替换（field=translation/original/both） |
| POST | `/api/dedup`            | 清理重复（normalize 键） |

## 目录

```
src/
├── main.py                入口（无窗自重启 + 版本感知复用 + 起服务 + 开窗口）
├── requirements.txt       pywebview
├── gpot/
│   ├── core/              ← 内核（纯逻辑，唯一真源）
│   │   ├── kernel.py      业务内核（旧库真实逻辑迁移）
│   │   ├── store.py       运行时状态 + 导航锁
│   │   ├── detection.py   引擎识别（15 类真实启发式）
│   │   ├── providers.py   翻译后端（8 后端真实预设 + 连通测试）
│   │   ├── extract.py     文本提取（按引擎分流 + 护栏）
│   │   ├── translate.py   翻译任务（真实线程 + batch_fast）
│   │   ├── sink.py        落盘三形态（runtime/rewrite/none）
│   │   ├── pipeline.py    七步状态机（完成→解锁规则）
│   │   └── …              engine_detector / kit_catalog / kit_installer / rpgmaker_engine 等
│   ├── api/
│   │   └── server.py      HTTP 桥（唯一 UI↔内核耦合点；APP_VERSION 真源）
│   └── ui/
│       ├── host.py        WebView2 宿主（frameless + WinCtl 窗口三键）
│       └── assets/        纯静态前端（index.html / app.js / styles.css）
└── tests/
    └── test_pipeline.py   内核测试（13 项，真实链路）
```
