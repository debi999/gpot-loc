"""UI 层（ui）— WebView2 宿主 + 纯静态前端。

本目录与内核完全解耦：宿主只负责「开一个指向本地 API 的窗口」，
前端只是纯 HTML/JS/CSS，通过 fetch() 调 API。换任何前端技术都不动 core。
"""
