"""内核层（core）— 业务逻辑的单一真源。

铁律：本目录下的任何模块都**不得** import gpot.api 或 gpot.ui。
它只产出/消费纯 Python 数据（dict / dataclass），由 api 层负责序列化。
这样内核可以在没有浏览器、没有网络的情况下被单独测试（见 tests/）。
"""
