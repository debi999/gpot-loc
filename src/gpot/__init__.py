"""G-POT Loc — 应用包根。

分层（详见 src/README.md）：
  gpot.core  业务内核，零 UI / 零 HTTP 依赖（纯逻辑 + 数据）
  gpot.api   HTTP 桥，唯一把 UI 接到内核的地方
  gpot.ui    WebView2 宿主 + 纯静态前端
"""
