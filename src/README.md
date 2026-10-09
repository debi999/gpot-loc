# G-POT Loc · 应用源码（C 路线原型）

> 技术栈：**Python 内核 + WebView2（Fluent 观感）**，2026-10-09 老板拍板。

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

> 接缝留痕：core 里所有 `TODO(M2)` 标注处，都是旧库 `gui/` 真实逻辑迁入的位置
> （`engine_detector` / `Translator`+`batch_fast` / `kit_catalog`+`kit_installer`
> / `rpgmaker_engine`）。原型用 stub 复用真实数字把流程跑通，M2 只换函数体、不动契约。

## 本地运行

```bash
cd src
pip install -r requirements.txt      # 只需 pywebview（Windows 自带 WebView2 运行时）
python main.py                       # 开 WebView2 窗口
python main.py --no-gui              # 只起 API（无界面，调试用）
python main.py --open-browser        # 用系统浏览器代替 WebView2
python tests/test_pipeline.py        # 跑内核解耦测试
```

默认 API 端口 `8731`，首页即 `http://127.0.0.1:8731/`。

## API 契约（前端消费的全部端点）

| 方法 | 路径 | 作用 |
|---|---|---|
| GET  | `/api/state`            | 全量流水线状态（步骤 / 配置 / 引擎 / 进度 …） |
| GET  | `/api/providers`        | 翻译后端目录 |
| POST | `/api/config`           | 保存并测试翻译服务配置 |
| POST | `/api/game`             | 选定游戏目录 |
| POST | `/api/detect`           | 识别引擎 + 准备工具清单 |
| POST | `/api/deploy`           | 部署注入工具 |
| POST | `/api/extract`          | 提取待翻译文本 |
| POST | `/api/translate/start`  | 启动翻译任务 → 返回 `job_id` |
| GET  | `/api/jobs/{id}`        | 轮询翻译任务进度 |
| POST | `/api/jobs/{id}/cancel` | 取消翻译任务 |
| GET  | `/api/sink?engine=`     | 取某引擎的「落盘形态」视图（三态） |
| POST | `/api/sink/apply`       | 保存并应用到游戏（按引擎分流） |
| GET  | `/api/verify`           | 取验证指引 + 写入自检 |
| POST | `/api/nav`              | 导航跳转（受 max_step 锁约束） |
| POST | `/api/reset`            | 重置演示状态 |

## 目录

```
src/
├── main.py                入口（参数解析 + 起服务 + 开窗口）
├── requirements.txt       pywebview
├── gpot/
│   ├── core/              ← 内核（纯逻辑）
│   │   ├── store.py       运行时状态 + 导航锁（唯一真源）
│   │   ├── detection.py   引擎识别（stub）
│   │   ├── providers.py   翻译后端目录（stub）
│   │   ├── extract.py     文本提取（stub）
│   │   ├── translate.py   翻译任务（真实流式形状）
│   │   ├── sink.py        落盘三形态（runtime/rewrite/none）
│   │   └── pipeline.py    七步状态机（完成→解锁规则）
│   ├── api/
│   │   └── server.py      HTTP 桥（唯一 UI↔内核耦合点）
│   └── ui/
│       ├── host.py        WebView2 宿主（懒加载 pywebview）
│       └── assets/        纯静态前端（index.html / app.js / styles.css）
└── tests/
    └── test_pipeline.py   内核解耦测试（只 import core）
```
