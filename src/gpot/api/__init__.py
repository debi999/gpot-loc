"""API 层（api）— UI 与内核之间唯一的桥。

解耦契约：
  * 只允许 import gpot.core（绝不 import gpot.ui）
  * 通过 HTTP + JSON 与前端对话；前端用 fetch() 调它
  * 自身不含业务逻辑，全部委托给 core.* 并序列化
所有端点路径集中在 do_* 方法，便于文档化与测试。
"""
