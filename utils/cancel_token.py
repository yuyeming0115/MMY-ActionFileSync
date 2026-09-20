from __future__ import annotations

import threading


class CancellationToken:
    """线程安全的取消令牌，用于在后台任务中协作式取消。

    用法：
        token = CancellationToken()
        # 在后台线程循环中：
        if token.is_cancelled():
            return
        # 在 UI 线程中：
        token.cancel()
    """

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        """请求取消。线程安全。"""
        self._event.set()

    def is_cancelled(self) -> bool:
        """检查是否已请求取消。线程安全。"""
        return self._event.is_set()

    def reset(self) -> None:
        """重置令牌为未取消状态，用于复用。"""
        self._event.clear()
